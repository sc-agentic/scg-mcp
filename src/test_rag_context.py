from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password")
USER_QUESTION = "How does the caching mechanism work in Glide?"


def main():
    print("=== Neo4j RAG Test (Vector Search) ===")
    print(f"Query: {USER_QUESTION}")

    print("Generating embedding...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    query_vector = model.encode(USER_QUESTION).tolist()

    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        driver.verify_connectivity()
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # Find top 5 relevant nodes using Cosine Similarity, then fetch 1-hop neighborhood
    cypher_query = """
    MATCH (n:CodeNode)
    WHERE n.embedding IS NOT NULL
    WITH n, vector.similarity.cosine(n.embedding, $embedding) AS score
    ORDER BY score DESC LIMIT 5
    OPTIONAL MATCH path = (n)-[r]-(neighbor)
    RETURN n, score, r, neighbor
    """

    results = []
    with driver.session() as session:
        try:
            result = session.run(cypher_query, embedding=query_vector)
            results = list(result)
        except Exception as e:
            print(f"Cypher execution error (ensure Neo4j 5.x+): {e}")
            return
    driver.close()

    if not results:
        print("No matches found.")
        return

    # Constructing RAG Context
    context_lines = ["RAG CONTEXT:\n"]

    nodes_info = {}
    edges_info = []

    for record in results:
        source = record["n"]
        target = record["neighbor"]
        rel = record["r"]
        score = record["score"]

        # Source Node
        if source["id"] not in nodes_info:
            nodes_info[source["id"]] = {
                "name": source.get("displayName", source["id"]),
                "kind": source.get("kind", "Unknown"),
                "score": score,
                "source": source.get("source", ""),
            }

        # Neighbor Node
        if target["id"] not in nodes_info:
            nodes_info[target["id"]] = {
                "name": target.get("displayName", target["id"]),
                "kind": target.get("kind", "Unknown"),
                "score": 0.0,
                "source": target.get("source", ""),
            }

        edges_info.append(
            f"{source.get('displayName', source['id'])} --[{rel.type}]--> {target.get('displayName', target['id'])}"
        )

    context_lines.append("Relevant Entities:")
    # Sort source nodes by score first
    sorted_ids = sorted(
        nodes_info.keys(), key=lambda k: nodes_info[k]["score"], reverse=True
    )

    for nid in sorted_ids:
        info = nodes_info[nid]
        prefix = f"[{info['score']:.4f}]" if info["score"] > 0 else "(Neighbor)"
        context_lines.append(f"  {prefix} {info['name']} ({info['kind']})")
        if info["score"] > 0:
            if info["source"]:
                context_lines.append("      Code:")
                for line in info["source"].splitlines():
                    context_lines.append(f"        {line}")
            else:
                context_lines.append("      Code: Not available")

    context_lines.append("\nRelationships:")
    # Deduplicate edges strings
    for edge_str in sorted(list(set(edges_info))):
        context_lines.append(f"  {edge_str}")

    print("\n" + "\n".join(context_lines))


if __name__ == "__main__":
    main()
