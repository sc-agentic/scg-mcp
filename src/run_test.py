import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Set, List, Any

import matplotlib.pyplot as plt
import networkx as nx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from src.models.semantic_graph_pb2 import SemanticGraphFile
except ImportError:
    try:
        from semantic_graph_pb2 import SemanticGraphFile
    except ImportError:
        sys.exit(
            "Error: Could not import semantic_graph_pb2. Run generate_proto.py first."
        )

HAS_VIS = True


def generate_graph_image(all_graphs: List[SemanticGraphFile], filename: str):
    G = nx.DiGraph()

    node_data: Dict[str, Dict[str, Any]] = {}
    all_node_ids: Set[str] = set()

    for graph in all_graphs:
        file_uri = graph.uri
        for node in graph.nodes:
            node_id = node.id
            if node_id not in node_data:
                node_data[node_id] = {
                    "kind": node.kind or "unknown",
                    "display_name": node.displayName or node.id,
                    "file_uris": {file_uri},
                }
                all_node_ids.add(node_id)
            else:
                node_data[node_id]["file_uris"].add(file_uri)
                if node.displayName and not node_data[node_id]["display_name"]:
                    node_data[node_id]["display_name"] = node.displayName

    for node_id, data in node_data.items():
        file_count = len(data["file_uris"])
        file_label = (
            f" ({file_count} file{'s' if file_count > 1 else ''})"
            if file_count > 1
            else ""
        )

        G.add_node(
            node_id,
            kind=data["kind"],
            display_name=data["display_name"] + file_label,
            file_count=file_count,
        )

    for graph in all_graphs:
        for node in graph.nodes:
            source_id = node.id
            for edge in node.edges:
                target_id = edge.to
                if source_id in all_node_ids and target_id in all_node_ids:
                    if not G.has_edge(source_id, target_id):
                        G.add_edge(
                            source_id, target_id, edge_type=edge.type or "unknown"
                        )

    if len(G.nodes) == 0:
        print("   ✗ No nodes to visualize")
        return

    print(f"   Creating layout for {len(G.nodes)} nodes, {len(G.edges)} edges...")
    try:
        pos = nx.spring_layout(G, k=1, iterations=50, seed=42)
    except Exception:
        pos = nx.circular_layout(G)

    node_kinds = [G.nodes[node].get("kind", "unknown") for node in G.nodes()]
    unique_kinds = list(set(node_kinds))
    color_map = plt.cm.Set3(range(len(unique_kinds)))
    kind_to_color = {kind: color_map[i] for i, kind in enumerate(unique_kinds)}
    node_colors = [kind_to_color[kind] for kind in node_kinds]

    plt.figure(figsize=(16, 12))
    nx.draw_networkx_edges(
        G, pos, alpha=0.2, edge_color="gray", arrows=True, arrowsize=10, width=0.5
    )
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=50, alpha=0.8)

    if len(G.nodes) <= 100:
        labels = {
            node: G.nodes[node].get("display_name", node)[:20] for node in G.nodes()
        }
        nx.draw_networkx_labels(G, pos, labels, font_size=6, alpha=0.7)

    from matplotlib.patches import Patch

    legend_elements = [
        Patch(facecolor=kind_to_color[kind], label=kind) for kind in unique_kinds[:10]
    ]
    plt.legend(handles=legend_elements, loc="upper left", fontsize=8, ncol=2)

    unique_files = len(
        set(G.nodes[node].get("file_uri", "unknown") for node in G.nodes())
    )
    plt.title(
        f"Complete Database Semantic Graph\n{len(G.nodes)} nodes, {len(G.edges)} edges across {unique_files} files",
        fontsize=12,
    )
    plt.axis("off")
    plt.tight_layout()

    output_path = f"graph_{filename}.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"   ✓ Graph saved to: {output_path}")
    plt.close()


def main():
    print("=" * 70)
    print("Semantic Graph Reader - Setup Test")
    print("=" * 70)

    print(f"\n1. Python: {sys.version.split()[0]}")

    try:
        import google.protobuf

        print(f"2. protobuf: ✓ Installed (v{google.protobuf.__version__})")
    except ImportError:
        print("2. protobuf: ✗ NOT INSTALLED")
        sys.exit(1)

    proto_file = "src/models/semantic_graph.proto"
    if os.path.exists(proto_file):
        print("3. Proto file: ✓ Found")
    else:
        print("3. Proto file: ✗ Missing")
        sys.exit(1)

    print("\n4. Generating protobuf bindings...")
    output_file = "src/models/semantic_graph_pb2.py"
    if os.path.exists(output_file):
        os.remove(output_file)
        print("   Removed old binding file")

    try:
        result = subprocess.run(
            [
                "protoc",
                "--proto_path=src/models",
                "--python_out=src/models",
                proto_file,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and os.path.exists(output_file):
            print("   ✓ Generated using protoc")
        else:
            print(f"   protoc error: {result.stderr.strip()}")
            sys.exit(1)
    except Exception as e:
        print(f"   protoc exception: {e}")
        sys.exit(1)

    print("\n5. Testing import...")
    try:
        if "src.models.semantic_graph_pb2" in sys.modules:
            del sys.modules["src.models.semantic_graph_pb2"]

        from src.models.semantic_graph_pb2 import SemanticGraphFile

        print("   ✓ Successfully imported all classes")
    except ImportError as e:
        print(f"   ✗ Import failed: {e}")
        sys.exit(1)

    print("\n6. Reading all database files...")
    test_dir = Path("data/glide/.semanticgraphs")
    if not test_dir.exists():
        print(f"   ✗ Directory not found: {test_dir}")
        sys.exit(1)

    db_files = list(test_dir.rglob("*.semanticgraphdb"))
    if not db_files:
        print("   ✗ No .semanticgraphdb files found")
        sys.exit(1)

    print(f"   Found {len(db_files)} file(s)")

    all_graphs = []
    total_nodes = 0
    total_edges = 0
    node_kinds: Dict[str, int] = {}
    edge_types: Dict[str, int] = {}

    print("   Reading and parsing files...")
    for db_file in db_files:
        try:
            with open(db_file, "rb") as f:
                graph = SemanticGraphFile()
                graph.ParseFromString(f.read())
                all_graphs.append(graph)
                total_nodes += len(graph.nodes)

                for node in graph.nodes:
                    kind = node.kind or "unknown"
                    node_kinds[kind] = node_kinds.get(kind, 0) + 1
                    for edge in node.edges:
                        etype = edge.type or "unknown"
                        edge_types[etype] = edge_types.get(etype, 0) + 1
                        total_edges += 1
        except Exception as e:
            print(f"   ⚠ Warning: Failed to read {db_file.name}: {e}")
            continue

    if not all_graphs:
        print("   ✗ No valid graph files could be read")
        sys.exit(1)

    print(f"   ✓ Successfully parsed {len(all_graphs)} file(s)")
    print(f"   - Total nodes: {total_nodes}")
    print(f"   - Total edges: {total_edges}")

    if node_kinds:
        print("   - Node kinds (top 5):")
        for kind, count in sorted(node_kinds.items(), key=lambda x: -x[1])[:5]:
            print(f"     {kind}: {count}")

    if HAS_VIS:
        print("\n7. Generating graph visualization for entire database...")
        generate_graph_image(all_graphs, "complete_database")
    else:
        print("\n7. Graph visualization: ✗ Skipped (matplotlib/networkx not installed)")

    print("\n" + "=" * 70)
    print("✓ SETUP COMPLETE AND WORKING!")
    print("=" * 70)


if __name__ == "__main__":
    main()
