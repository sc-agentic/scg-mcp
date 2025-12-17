import sys
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from src.models.semantic_graph_pb2 import SemanticGraphFile
except ImportError:
    try:
        from semantic_graph_pb2 import SemanticGraphFile
    except ImportError:
        print("Warning: Could not import semantic_graph protobuf modules.")
        print(
            "Please generate the bindings using: protoc --python_out=. semantic_graph.proto"
        )
        sys.exit(1)


def read_semantic_graph_file(file_path: str) -> SemanticGraphFile:
    with open(file_path, "rb") as f:
        graph_file = SemanticGraphFile()
        graph_file.ParseFromString(f.read())
        return graph_file


def read_all_semantic_graphs(directory: str) -> List[SemanticGraphFile]:
    graphs = []
    semantic_graphs_dir = Path(directory) / ".semanticgraphs"

    if not semantic_graphs_dir.exists():
        raise FileNotFoundError(f"Directory {semantic_graphs_dir} does not exist")

    for db_file in semantic_graphs_dir.rglob("*.semanticgraphdb"):
        try:
            graph = read_semantic_graph_file(str(db_file))
            graphs.append(graph)
        except Exception as e:
            print(f"Error reading {db_file}: {e}")
            continue

    return graphs


def analyze_graph(graph: SemanticGraphFile) -> Dict[str, Any]:
    node_kinds = {}
    edge_types = {}
    total_edges = 0

    for node in graph.nodes:
        kind = node.kind if node.kind else "unknown"
        node_kinds[kind] = node_kinds.get(kind, 0) + 1

        for edge in node.edges:
            edge_type = edge.type if edge.type else "unknown"
            edge_types[edge_type] = edge_types.get(edge_type, 0) + 1
            total_edges += 1

    return {
        "uri": graph.uri,
        "total_nodes": len(graph.nodes),
        "total_edges": total_edges,
        "node_kinds": node_kinds,
        "edge_types": edge_types,
    }


def print_graph_summary(graph: SemanticGraphFile):
    print(f"\n{'=' * 60}")
    print(f"Semantic Graph File: {graph.uri}")
    print(f"{'=' * 60}")
    print(f"Total Nodes: {len(graph.nodes)}")

    total_edges = sum(len(node.edges) for node in graph.nodes)
    print(f"Total Edges: {total_edges}")

    node_kinds = {}
    for node in graph.nodes:
        kind = node.kind if node.kind else "unknown"
        node_kinds[kind] = node_kinds.get(kind, 0) + 1

    if node_kinds:
        print("\nNode Kinds:")
        for kind, count in sorted(node_kinds.items(), key=lambda x: -x[1]):
            print(f"  {kind}: {count}")

    edge_types = {}
    for node in graph.nodes:
        for edge in node.edges:
            edge_type = edge.type if edge.type else "unknown"
            edge_types[edge_type] = edge_types.get(edge_type, 0) + 1

    if edge_types:
        print("\nEdge Types:")
        for edge_type, count in sorted(edge_types.items(), key=lambda x: -x[1]):
            print(f"  {edge_type}: {count}")

    print("\nFirst 5 Nodes:")
    for i, node in enumerate(graph.nodes[:5]):
        print(f"  {i + 1}. {node.id} ({node.kind})")
        if node.displayName:
            print(f"     Display Name: {node.displayName}")
        if node.location:
            loc = node.location
            print(f"     Location: {loc.uri}:{loc.startLine}:{loc.startCharacter}")


def main():
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = "data/glide"

    print(f"Reading semantic graphs from: {directory}")

    try:
        graphs = read_all_semantic_graphs(directory)
        print(f"\nFound {len(graphs)} semantic graph files")

        for graph in graphs[:5]:
            print_graph_summary(graph)

        if len(graphs) > 5:
            print(f"\n... and {len(graphs) - 5} more files")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
