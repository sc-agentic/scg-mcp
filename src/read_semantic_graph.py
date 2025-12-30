import sys
from pathlib import Path
from typing import List
from src.models.semantic_graph_pb2 import SemanticGraphFile


def read_all_semantic_graphs(directory: str) -> List[SemanticGraphFile]:
    semantic_graphs_dir = Path(directory) / ".semanticgraphs"
    if not semantic_graphs_dir.exists():
        raise FileNotFoundError(f"Directory {semantic_graphs_dir} does not exist")

    graphs = []
    for db_file in semantic_graphs_dir.rglob("*.semanticgraphdb"):
        try:
            with open(db_file, "rb") as f:
                g = SemanticGraphFile()
                g.ParseFromString(f.read())
                graphs.append(g)
        except Exception as e:
            print(f"Error reading {db_file}: {e}")
    return graphs


def print_graph_summary(graph: SemanticGraphFile):
    print(f"\nGraph: {graph.uri}")
    print(f"Nodes: {len(graph.nodes)}")

    node_kinds = {}
    total_edges = 0
    edge_types = {}

    for node in graph.nodes:
        kind = node.kind or "unknown"
        node_kinds[kind] = node_kinds.get(kind, 0) + 1
        for edge in node.edges:
            etype = edge.type or "unknown"
            edge_types[etype] = edge_types.get(etype, 0) + 1
            total_edges += 1

    print(f"Edges: {total_edges}")

    if node_kinds:
        print(
            "Kinds: "
            + ", ".join(
                f"{k}:{v}"
                for k, v in sorted(node_kinds.items(), key=lambda x: -x[1])[:5]
            )
        )
    if edge_types:
        print(
            "Edges: "
            + ", ".join(
                f"{k}:{v}"
                for k, v in sorted(edge_types.items(), key=lambda x: -x[1])[:5]
            )
        )


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else "data/glide"
    print(f"Reading graphs from: {directory}")

    try:
        graphs = read_all_semantic_graphs(directory)
        print(f"Found {len(graphs)} files")
        for g in graphs[:5]:
            print_graph_summary(g)
        if len(graphs) > 5:
            print(f"... and {len(graphs) - 5} more")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
