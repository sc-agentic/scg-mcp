import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Any
import matplotlib.pyplot as plt
import networkx as nx
from src.models.semantic_graph_pb2 import SemanticGraphFile

HAS_VIS = True


def generate_graph_image(all_graphs: List[SemanticGraphFile], filename: str):
    G = nx.DiGraph()
    node_data: Dict[str, Dict[str, Any]] = {}

    for graph in all_graphs:
        for node in graph.nodes:
            if node.id not in node_data:
                node_data[node.id] = {
                    "kind": node.kind or "unknown",
                    "display_name": node.displayName or node.id,
                }
            for edge in node.edges:
                G.add_edge(node.id, edge.to, edge_type=edge.type or "unknown")

    for nid, data in node_data.items():
        G.add_node(nid, **data)

    if len(G.nodes) == 0:
        print("   ✗ No nodes to visualize")
        return

    print(f"   Layouting {len(G.nodes)} nodes...")
    pos = (
        nx.spring_layout(G, k=0.5, iterations=30)
        if len(G.nodes) < 500
        else nx.random_layout(G)
    )

    node_colors = [hash(G.nodes[n].get("kind", "")) % 20 for n in G.nodes]

    plt.figure(figsize=(12, 12))
    nx.draw(
        G,
        pos,
        node_color=node_colors,
        node_size=30,
        alpha=0.7,
        edge_color="gray",
        width=0.5,
        cmap=plt.cm.Pastel1,
    )

    if len(G.nodes) <= 100:
        nx.draw_networkx_labels(
            G, pos, {n: G.nodes[n]["display_name"][:15] for n in G.nodes}, font_size=6
        )

    plt.title(f"Graph: {len(G.nodes)} nodes, {len(G.edges)} edges")
    plt.axis("off")

    output_path = f"graph_{filename}.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"   ✓ Saved: {output_path}")
    plt.close()


def main():
    from src.config import get_project_config

    cfg = get_project_config()
    print(f"=== Semantic Graph Reader Setup Test [{cfg.name}] ===")
    print(f"1. Python: {sys.version.split()[0]}")

    # Check Protobuf
    import google.protobuf

    print(f"2. protobuf: ✓ (v{google.protobuf.__version__})")

    # Check Proto File
    proto_file = "src/models/semantic_graph.proto"
    if not os.path.exists(proto_file):
        sys.exit("3. Proto file: ✗ Missing")
    print("3. Proto file: ✓ Found")

    # Generate Bindings
    print("4. Generating bindings...")
    try:
        subprocess.run(
            [
                "protoc",
                "--proto_path=src/models",
                "--python_out=src/models",
                proto_file,
            ],
            check=True,
            capture_output=True,
        )
        print("   ✓ Generated")
    except:
        sys.exit("   ✗ Protoc failed")

    # Test Import
    from src.models.semantic_graph_pb2 import SemanticGraphFile

    print("5. Import: ✓ Success")

    # Read Files
    test_dir = cfg.data_dir / ".semanticgraphs"
    db_files = list(test_dir.rglob("*.semanticgraphdb"))
    if not db_files:
        sys.exit("6. Data: ✗ No .semanticgraphdb files found")

    print(f"6. Data: ✓ Found {len(db_files)} files")

    all_graphs = []
    node_count, edge_count = 0, 0

    for db_file in db_files:
        try:
            with open(db_file, "rb") as f:
                g = SemanticGraphFile()
                g.ParseFromString(f.read())
                all_graphs.append(g)
                node_count += len(g.nodes)
                edge_count += sum(len(n.edges) for n in g.nodes)
        except Exception as e:
            print(f"   Warn: {e}")

    print(f"   Stats: {node_count} nodes, {edge_count} edges")

    if HAS_VIS:
        print("7. Visualizing...")
        generate_graph_image(all_graphs, "complete_database")

    print("\n✓ SUCCESS")


if __name__ == "__main__":
    main()
