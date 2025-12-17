import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

import networkx as nx
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from sentence_transformers import SentenceTransformer, util

    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False
    print("Warning: sentence-transformers not found. Using simple string matching.")

try:
    from src.models.semantic_graph_pb2 import SemanticGraphFile, GraphNode, Edge
except ImportError:
    try:
        from semantic_graph_pb2 import SemanticGraphFile, GraphNode, Edge
    except ImportError:
        raise ImportError(
            "Could not import semantic_graph_pb2. Ensure protobuf bindings are generated."
        )


class GraphRAG:
    def __init__(self, data_dir: Union[str, Path]):
        self.data_dir = Path(data_dir)
        self.graph = nx.DiGraph()
        self.node_metadata: Dict[str, Dict[str, Any]] = {}
        self.node_ids_list: List[str] = []
        self.embeddings: Optional[torch.Tensor] = None
        self.model: Optional[SentenceTransformer] = None

        if HAS_SENTENCE_TRANSFORMERS:
            print("Initializing sentence-transformer model (all-MiniLM-L6-v2)...")
            self.model = SentenceTransformer("all-MiniLM-L6-v2")

        self._load_graph()
        if self.model:
            self._build_index()

    def _load_graph(self):
        print(f"Loading graphs from {self.data_dir}...")
        files = list(self.data_dir.rglob("*.semanticgraphdb"))
        for file_path in files:
            try:
                with open(file_path, "rb") as f:
                    sgf = SemanticGraphFile()
                    sgf.ParseFromString(f.read())
                    self._process_file(sgf)
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
        print(
            f"Graph loaded: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges"
        )

    def _process_file(self, sgf: SemanticGraphFile):
        file_uri = sgf.uri
        for node in sgf.nodes:
            if not self.graph.has_node(node.id):
                self.graph.add_node(
                    node.id, kind=node.kind, display_name=node.displayName
                )
                self.node_metadata[node.id] = {
                    "kind": node.kind,
                    "display_name": node.displayName,
                    "location": node.location,
                    "properties": dict(node.properties),
                    "file_uri": file_uri,
                }
            for edge in node.edges:
                self.graph.add_edge(node.id, edge.to, type=edge.type)

    def _build_index(self):
        print(f"Computing embeddings for {len(self.node_metadata)} nodes...")
        texts = []
        self.node_ids_list = []
        for node_id, data in self.node_metadata.items():
            display = data.get("display_name") or node_id
            kind = data.get("kind", "UNKNOWN")
            texts.append(f"{kind}: {display}")
            self.node_ids_list.append(node_id)

        if texts and self.model:
            self.embeddings = self.model.encode(
                texts, convert_to_tensor=True, show_progress_bar=True
            )
            print("Embeddings computed.")

    def find_nodes(self, query: str, limit: int = 5) -> List[Dict]:
        if HAS_SENTENCE_TRANSFORMERS and self.embeddings is not None and self.model:
            return self._find_nodes_semantic(query, limit)
        return self._find_nodes_keyword(query, limit)

    def _find_nodes_semantic(self, query: str, limit: int = 5) -> List[Dict]:
        query_embedding = self.model.encode(query, convert_to_tensor=True)
        cos_scores = util.cos_sim(query_embedding, self.embeddings)[0]
        top_results = torch.topk(cos_scores, k=min(limit, len(self.node_ids_list)))

        results = []
        for score, idx in zip(top_results.values, top_results.indices):
            node_id = self.node_ids_list[idx]
            results.append(
                {"id": node_id, "score": float(score), **self.node_metadata[node_id]}
            )
        return results

    def _find_nodes_keyword(self, query: str, limit: int = 5) -> List[Dict]:
        query_lower = query.lower()
        matches = []
        for node_id, data in self.node_metadata.items():
            score = 0
            if query_lower in (data.get("display_name") or "").lower():
                score += 2
            if query_lower in node_id.lower():
                score += 1
            if score > 0:
                matches.append((score, node_id, data))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [{"id": m[1], **m[2]} for m in matches[:limit]]

    def get_context_subgraph(
        self, node_ids: List[str], hops: int = 1
    ) -> Dict[str, Any]:
        subgraph_nodes = set(node_ids)
        current_level = set(node_ids)

        for _ in range(hops):
            next_level = set()
            for node_id in current_level:
                if node_id not in self.graph:
                    continue
                next_level.update(self.graph.successors(node_id))
                next_level.update(self.graph.predecessors(node_id))
            subgraph_nodes.update(next_level)
            current_level = next_level

        result = {
            "nodes": [
                {"id": nid, **self.node_metadata[nid]}
                for nid in subgraph_nodes
                if nid in self.node_metadata
            ],
            "edges": [
                {"source": u, "target": v, "type": data.get("type", "unknown")}
                for u, v, data in self.graph.subgraph(subgraph_nodes).edges(data=True)
            ],
        }
        return result

    def format_context_for_llm(self, subgraph: Dict[str, Any]) -> str:
        output = ["CODEBASE CONTEXT:\n\nEntities:"]

        nodes_by_kind = {}
        for node in subgraph["nodes"]:
            nodes_by_kind.setdefault(node["kind"], []).append(node)

        for kind, nodes in nodes_by_kind.items():
            output.append(f"  [{kind}]")
            for node in nodes:
                name = node["display_name"] or node["id"]
                output.append(f"    - {name} (ID: {node['id']})")

        output.append("\nRelationships:")
        for edge in subgraph["edges"]:
            s_name = self.node_metadata.get(edge["source"], {}).get(
                "display_name", edge["source"]
            )
            t_name = self.node_metadata.get(edge["target"], {}).get(
                "display_name", edge["target"]
            )
            output.append(f"  - {s_name} --[{edge['type']}]--> {t_name}")

        return "\n".join(output)


def demo():
    data_path = Path("data/glide/.semanticgraphs")
    if not data_path.exists():
        print(f"Data path {data_path} not found.")
        return

    rag = GraphRAG("data/glide")

    print("\n--- Demo Query: 'Cache' ---")
    nodes = rag.find_nodes("Cache", limit=3)
    if not nodes:
        print("No nodes found for 'Cache'")
        return

    print(f"Found {len(nodes)} starting nodes.")
    subgraph = rag.get_context_subgraph([n["id"] for n in nodes], hops=1)

    print(
        f"Subgraph has {len(subgraph['nodes'])} nodes and {len(subgraph['edges'])} edges."
    )
    print("\nGenerated LLM Context:")
    print("-" * 40)
    print(rag.format_context_for_llm(subgraph))
    print("-" * 40)


if __name__ == "__main__":
    demo()
