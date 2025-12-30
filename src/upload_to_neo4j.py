import sys
from typing import List, Dict, Any
from tqdm import tqdm
from src.rag_engine import GraphRAG
from neo4j import GraphDatabase


def batch_data(data: List[Any], batch_size: int = 500):
    for i in range(0, len(data), batch_size):
        yield data[i : i + batch_size]


class Neo4jUploader:
    def __init__(self, uri, auth):
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self.driver.verify_connectivity()
        print(f"Connected to Neo4j at {uri}")

    def close(self):
        self.driver.close()

    def clear_database(self):
        print("Clearing database...")
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("Database cleared.")

    def create_indexes(self):
        print("Creating indexes...")
        with self.driver.session() as session:
            try:
                session.run("CREATE CONSTRAINT FOR (n:Node) REQUIRE n.id IS UNIQUE")
            except Exception as e:
                print(f"Note: {e}")

    def upload_nodes(self, nodes_data: List[Dict]):
        print(f"Uploading {len(nodes_data)} nodes...")
        query = """
        UNWIND $batch AS row
        MERGE (n:CodeNode {id: row.id})
        SET n.kind = row.kind,
            n.displayName = row.displayName,
            n.uri = row.uri,
            n.source = row.source,
            n.embedding = row.embedding
        """
        with self.driver.session() as session:
            with tqdm(total=len(nodes_data), desc="Nodes") as pbar:
                for batch in batch_data(nodes_data):
                    try:
                        session.run(query, batch=batch)
                    except Exception as e:
                        print(f"Error: {e}")
                    pbar.update(len(batch))

    def upload_edges(self, edges_by_type: Dict[str, List[Dict]]):
        print("Uploading edges...")
        total_edges = sum(len(e) for e in edges_by_type.values())

        with tqdm(total=total_edges, desc="Edges") as pbar:
            for edge_type, edges in edges_by_type.items():
                safe_type = (
                    "".join(x for x in edge_type if x.isalnum() or x == "_").upper()
                    or "RELATED_TO"
                )

                query = f"""
                UNWIND $batch AS row
                MERGE (s:CodeNode {{id: row.source}})
                MERGE (t:CodeNode {{id: row.target}})
                MERGE (s)-[:{safe_type}]->(t)
                """

                with self.driver.session() as session:
                    for batch in batch_data(edges):
                        session.run(query, batch=batch)
                        pbar.update(len(batch))
        print("Finished uploading edges.")


def main():
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_AUTH = ("neo4j", "password")

    print("--- Neo4j SCG Uploader ---")
    print("Initializing GraphRAG engine...")
    rag = GraphRAG(data_dir="data/glide", code_dir="code/glide-4.5.0")

    print("Preparing data...")
    embedding_map = {}
    if rag.embeddings is not None:
        print("Extracting embeddings...")
        vecs = rag.embeddings.cpu().numpy()
        for idx, node_id in enumerate(rag.node_ids_list):
            embedding_map[node_id] = vecs[idx].tolist()

    nodes_payload = []
    print(f"Processing {len(rag.node_metadata)} nodes...")
    for node_id, meta in rag.node_metadata.items():
        src = rag.get_node_source(node_id, context_padding=2)
        nodes_payload.append(
            {
                "id": node_id,
                "kind": meta.get("kind", "Unknown"),
                "displayName": meta.get("display_name", "") or node_id,
                "uri": str(meta.get("location", {}).uri)
                if meta.get("location")
                else "",
                "source": src if src else "",
                "embedding": embedding_map.get(node_id, []),
            }
        )

    edges_by_type = {}
    print(f"Processing {rag.graph.number_of_edges()} edges...")
    for u, v, data in rag.graph.edges(data=True):
        etype = data.get("type", "RELATED_TO")
        edges_by_type.setdefault(etype, []).append({"source": u, "target": v})

    try:
        uploader = Neo4jUploader(NEO4J_URI, NEO4J_AUTH)
        uploader.clear_database()
        uploader.upload_nodes(nodes_payload)
        uploader.upload_edges(edges_by_type)
        print("\nUpload Complete! Check http://localhost:7474")
        uploader.close()
    except Exception as e:
        print(f"\nError: {e}")
        print("Ensure Docker is running: docker-compose up -d")
        sys.exit(1)


if __name__ == "__main__":
    main()
