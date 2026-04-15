import os
import sys
import uvicorn
import logging
import contextlib
from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from starlette.applications import Starlette
from starlette.routing import Mount
from src.config import get_project_config

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "password"))
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_INDEX_NAME = "code_embeddings"
VECTOR_DIMENSIONS = 384


neo4j_driver = None
embed_model: SentenceTransformer | None = None
stop_node_ids: set[str] | None = None
STOP_NODE_COUNT = int(os.environ.get("SCG_STOP_NODE_COUNT", "200"))
_project_code_dir: str | None = None


def _get_stop_nodes() -> set[str]:
    """Calculate highly connected nodes (super-nodes) to avoid exploding traversals."""
    global stop_node_ids
    if stop_node_ids is not None:
        return stop_node_ids

    driver = _get_driver()
    cypher = """
    MATCH (n:CodeNode)<-[r]-()
    WITH n, count(r) AS inDegree
    ORDER BY inDegree DESC
    LIMIT $limit
    RETURN n.id AS id, inDegree
    """
    try:
        with driver.session() as session:
            results = session.execute_read(
                lambda tx: list(tx.run(cypher, limit=STOP_NODE_COUNT))
            )
            stop_node_ids = {r["id"] for r in results}
            log.info("Identified %d stop-nodes to filter out.", len(stop_node_ids))
    except Exception as e:
        log.warning("Failed to identify stop-nodes: %s", e)
        stop_node_ids = set()

    return stop_node_ids


@contextlib.contextmanager
def redirect_stdout_to_stderr():
    old_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old_stdout


def _get_driver():
    if neo4j_driver is None:
        raise RuntimeError("Neo4j driver not initialized. Is the database running?")
    return neo4j_driver


mcp = FastMCP(
    "semantic-graph-rag",
    instructions="Semantic Code Graph (SCG) MCP server for codebase exploration.\n"
    "Use `investigate` for ALL codebase queries — it searches, summarizes, and returns code in one call.\n"
    "Use `query_neo4j` ONLY when investigate is insufficient and you need a specific Cypher query.\n"
    "Node kinds: CLASS, TRAIT, METHOD, CONSTRUCTOR, FILE, VALUE, VARIABLE, PARAMETER.\n"
    "Edge types: CALL, EXTEND, OVERRIDE, CONTAINS, TYPE, DECLARATION, PARAMETER, RETURN_TYPE.\n"
    "WARNING: Do NOT use 'EXTENDS' or 'IMPLEMENTS' in Cypher. The relationship is EXACTLY 'EXTEND'.",
)


DEFAULT_SEARCH_KINDS = ["CLASS", "TRAIT", "ENUM", "METHOD", "CONSTRUCTOR", "FILE"]
MAX_CONTEXT_NODES = 50
CONTEXT_NOISE_KINDS = {"PARAMETER", "VARIABLE", "TYPE_PARAMETER"}


def search_code(query: str, limit: int = 5, kinds: list[str] | None = None) -> str:
    """Semantic search for code entities. Entry point for finding relevant code.

    Args:
        query: Natural language query (e.g., 'image loading', 'cache management')
        limit: Max results (default: 5)
        kinds: Node kinds to include (default: CLASS, TRAIT, METHOD, CONSTRUCTOR, FILE). Pass ['ALL'] for all.
    """
    driver = _get_driver()

    if embed_model is None:
        return "Error: Embedding model not loaded."

    query_embedding = embed_model.encode(query).tolist()

    include_all = kinds is not None and len(kinds) == 1 and kinds[0].upper() == "ALL"
    filter_kinds = None if include_all else (kinds if kinds else DEFAULT_SEARCH_KINDS)

    raw_limit = limit * 5 if filter_kinds else limit

    cypher = """
    CALL db.index.vector.queryNodes($index_name, $raw_limit, $embedding)
    YIELD node, score
    RETURN node.id AS id, node.kind AS kind, node.displayName AS displayName, score
    ORDER BY score DESC
    """

    try:
        with driver.session() as session:
            results = session.execute_read(
                lambda tx: list(
                    tx.run(
                        cypher,
                        index_name=VECTOR_INDEX_NAME,
                        raw_limit=raw_limit,
                        embedding=query_embedding,
                    )
                )
            )
    except Exception as e:
        return f"Search error: {e}"

    if filter_kinds:
        results = [r for r in results if r["kind"] in filter_kinds][:limit]
    else:
        results = results[:limit]

    if not results:
        kind_note = f" (filtered to kinds: {filter_kinds})" if filter_kinds else ""
        return f"No results found for query: '{query}'{kind_note}"

    kind_note = (
        f" (kinds: {', '.join(filter_kinds)})" if filter_kinds else " (all kinds)"
    )
    output = [f"Found {len(results)} results for '{query}'{kind_note}:\n"]
    for i, record in enumerate(results, 1):
        output.append(f"{i}. [{record['kind']}] {record['displayName']}")
        output.append(f"   ID: {record['id']}")
        output.append(f"   Score: {record['score']:.4f}")
        output.append("")

    return "\n".join(output)


def get_node_context(
    node_ids: list[str],
    hops: int = 1,
    kinds: list[str] | None = None,
    macro_topology: bool = True,
) -> str:
    """Get the context subgraph around code nodes — related entities and relationships.

    Args:
        node_ids: Node IDs to explore (from search_code)
        hops: Relationship hops (default: 1, max: 3). Avoid hops=2 on large classes.
        kinds: Node kinds to include. Default filters out PARAMETER, VARIABLE, TYPE_PARAMETER. Pass ['ALL'] for all.
        macro_topology: Aggregates method-level edges into file-level dependencies.
    """
    driver = _get_driver()
    hops = max(1, min(int(hops), 3))

    include_all = kinds is not None and len(kinds) == 1 and kinds[0].upper() == "ALL"
    filter_kinds = (
        None if include_all else (set(k.upper() for k in kinds) if kinds else None)
    )
    use_noise_filter = not include_all and filter_kinds is None

    stop_nodes = _get_stop_nodes()

    nodes_cypher = f"""
    MATCH (start:CodeNode) WHERE start.id IN $node_ids
    MATCH path = (start)-[*0..{hops}]-(n:CodeNode)
    WHERE NONE(x IN nodes(path) WHERE x.id IN $stop_node_ids AND NOT x.id IN $node_ids)
    RETURN DISTINCT n.id AS id, n.kind AS kind, n.displayName AS displayName
    """

    try:
        with driver.session() as session:
            raw_nodes = session.execute_read(
                lambda tx: list(
                    tx.run(
                        nodes_cypher, node_ids=node_ids, stop_node_ids=list(stop_nodes)
                    )
                )
            )
    except Exception as e:
        return f"Error getting node context: {e}"

    if not raw_nodes:
        return f"No nodes found for IDs: {node_ids}"

    if use_noise_filter:
        filtered_nodes = [n for n in raw_nodes if n["kind"] not in CONTEXT_NOISE_KINDS]
        noise_count = len(raw_nodes) - len(filtered_nodes)
    elif filter_kinds:
        filtered_nodes = [n for n in raw_nodes if n["kind"] in filter_kinds]
        noise_count = len(raw_nodes) - len(filtered_nodes)
    else:
        filtered_nodes = raw_nodes
        noise_count = 0

    truncated = False
    truncated_summary = ""
    if len(filtered_nodes) > MAX_CONTEXT_NODES:
        truncated = True
        shown_nodes = filtered_nodes[:MAX_CONTEXT_NODES]
        omitted = filtered_nodes[MAX_CONTEXT_NODES:]

        omitted_by_kind: dict[str, list[str]] = {}
        omitted_counts: dict[str, int] = {}
        max_ids_per_kind = 10
        for n in omitted:
            kind = n["kind"]
            omitted_counts[kind] = omitted_counts.get(kind, 0) + 1
            if kind not in omitted_by_kind:
                omitted_by_kind[kind] = []
            if len(omitted_by_kind[kind]) < max_ids_per_kind:
                omitted_by_kind[kind].append(n["id"])

        lines = [
            f"\n⚠️ Showing {MAX_CONTEXT_NODES} of {len(filtered_nodes)} nodes "
            f"({len(filtered_nodes) - MAX_CONTEXT_NODES} omitted)."
        ]
        lines.append("Omitted nodes by kind (use get_node_summary to inspect):")
        for kind, count in sorted(omitted_counts.items()):
            ids = omitted_by_kind[kind]
            ids_str = ", ".join(ids)
            if count > len(ids):
                ids_str += f", ... (+{count - len(ids)} more)"
            lines.append(f"  {kind} ({count}): {ids_str}")
        lines.append(
            "Tip: use hops=1 or filter with kinds parameter to narrow results."
        )
        truncated_summary = "\n".join(lines)
    else:
        shown_nodes = filtered_nodes

    shown_ids = {n["id"] for n in shown_nodes}
    all_traversed_ids = {n["id"] for n in raw_nodes}
    hidden_ids = all_traversed_ids - shown_ids

    rels_cypher = """
    MATCH (a:CodeNode)-[r]->(b:CodeNode)
    WHERE a.id IN $shown_ids AND b.id IN $shown_ids
    RETURN DISTINCT a.displayName AS source, type(r) AS relType, b.displayName AS target,
                    a.id AS sourceId, b.id AS targetId,
                    a.uri AS sourceUri, b.uri AS targetUri
    """

    try:
        with driver.session() as session:
            rels = session.execute_read(
                lambda tx: list(tx.run(rels_cypher, shown_ids=list(shown_ids)))
            )
    except Exception as e:
        return f"Error getting relationships: {e}"

    hidden_rel_summary = ""
    if hidden_ids:
        hidden_rels_cypher = """
        MATCH (a:CodeNode)-[r]->(b:CodeNode)
        WHERE (a.id IN $shown_ids AND b.id IN $hidden_ids)
           OR (a.id IN $hidden_ids AND b.id IN $shown_ids)
        RETURN type(r) AS relType, count(*) AS cnt
        """
        try:
            with driver.session() as session:
                hidden_rels = session.execute_read(
                    lambda tx: list(
                        tx.run(
                            hidden_rels_cypher,
                            shown_ids=list(shown_ids),
                            hidden_ids=list(hidden_ids),
                        )
                    )
                )
            if hidden_rels:
                parts = [f"{r['relType']} ({r['cnt']})" for r in hidden_rels]
                hidden_rel_summary = (
                    f"\n⚠️ {sum(r['cnt'] for r in hidden_rels)} relationships to/from "
                    f"omitted/filtered nodes not shown: {', '.join(parts)}. "
                    f"Use get_node_summary on omitted IDs to explore."
                )
        except Exception:
            pass

    header = f"Context subgraph ({len(shown_nodes)} nodes shown"
    if noise_count > 0:
        header += f", {noise_count} noise nodes filtered"
    header += f", {len(rels)} relationships):\n"
    output = [header]

    if truncated_summary:
        output.append(truncated_summary)

    output.append("\nNodes:")
    for n in shown_nodes:
        output.append(f"  - [{n['kind']}] {n['displayName']} (ID: {n['id']})")

    output.append("\nRelationships:")
    if rels:
        if macro_topology:
            file_deps = {}  # (sourceUri, targetUri) -> {relType: count}
            intra_file = set()

            for r in rels:
                sUri = r.get("sourceUri")
                tUri = r.get("targetUri")

                def get_container(uri, display):
                    if uri:
                        return uri.split("/")[-1]
                    return display

                sCont = get_container(sUri, r["source"])
                tCont = get_container(tUri, r["target"])

                if sCont != tCont:
                    key = (sCont, tCont)
                    if key not in file_deps:
                        file_deps[key] = {}
                    rt = r["relType"]
                    file_deps[key][rt] = file_deps[key].get(rt, 0) + 1
                else:
                    intra_file.add((r["source"], r["relType"], r["target"]))

            if file_deps:
                output.append("  [Macro-Topology] Inter-file Dependencies:")
                for (sc, tc), types in sorted(file_deps.items()):
                    types_str = ", ".join(f"{k} ({v})" for k, v in types.items())
                    total = sum(types.values())
                    output.append(f"    - {sc} => {tc} [weight: {total}] ({types_str})")

            if intra_file:
                output.append("  [Micro-Topology] Intra-file Relationships:")
                for src, rtype, tgt in sorted(intra_file):
                    output.append(f"    - {src} --[{rtype}]--> {tgt}")

            if not file_deps and not intra_file:
                output.append("  (none)")
        else:
            # Deduplicate
            seen_rels = set()
            unique_rels = []
            for r in rels:
                key = (r["source"], r["relType"], r["target"])
                if key not in seen_rels:
                    seen_rels.add(key)
                    unique_rels.append(r)
            for r in unique_rels:
                output.append(f"  - {r['source']} --[{r['relType']}]--> {r['target']}")
    else:
        output.append("  (none)")

    if hidden_rel_summary:
        output.append(hidden_rel_summary)

    return "\n".join(output)


def get_graph_stats() -> str:
    """Get node/edge counts and kind distribution for the code graph."""
    driver = _get_driver()

    cypher = """
    MATCH (n:CodeNode)
    WITH count(n) AS nodeCount,
         collect(n.kind) AS kinds
    OPTIONAL MATCH ()-[r]->()
    WITH nodeCount, kinds, count(DISTINCT r) AS edgeCount
    RETURN nodeCount, edgeCount, kinds
    """

    try:
        with driver.session() as session:
            result = session.execute_read(lambda tx: list(tx.run(cypher)))
    except Exception as e:
        return f"Error: {e}"

    if not result:
        return "No graph data found in Neo4j."

    record = result[0]
    node_count = record["nodeCount"]
    edge_count = record["edgeCount"]

    kind_counts: dict[str, int] = {}
    for kind in record["kinds"]:
        kind = kind or "Unknown"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    output = [
        "Graph Statistics:",
        f"  Total Nodes: {node_count:,}",
        f"  Total Edges: {edge_count:,}",
        "",
        "Nodes by Kind:",
    ]

    for kind, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
        output.append(f"  {kind}: {count:,}")

    return "\n".join(output)


def find_path(from_id: str, to_id: str, max_depth: int = 5) -> str:
    """Find shortest path between two code entities.

    Args:
        from_id: Starting node ID
        to_id: Target node ID
        max_depth: Max hops (default: 5, max: 10)
    """
    driver = _get_driver()
    max_depth = max(1, min(int(max_depth), 10))
    stop_nodes = _get_stop_nodes()

    cypher = f"""
    MATCH (start:CodeNode {{id: $from_id}}), (end:CodeNode {{id: $to_id}})
    MATCH path = shortestPath((start)-[*..{max_depth}]-(end))
    WHERE NONE(x IN nodes(path) WHERE x.id IN $stop_node_ids AND x.id <> $from_id AND x.id <> $to_id)
    RETURN [n IN nodes(path) | {{id: n.id, kind: n.kind, displayName: n.displayName}}] AS nodes,
           [r IN relationships(path) | {{source: startNode(r).id, target: endNode(r).id, type: type(r)}}] AS relationships,
           length(path) AS pathLength
    """

    try:
        with driver.session() as session:
            result = session.execute_read(
                lambda tx: list(
                    tx.run(
                        cypher,
                        from_id=from_id,
                        to_id=to_id,
                        stop_node_ids=list(stop_nodes),
                    )
                )
            )
    except Exception as e:
        return f"Error finding path: {e}"

    if not result:
        return (
            f"No path found between '{from_id}' and '{to_id}' within {max_depth} hops."
        )

    record = result[0]
    nodes = record["nodes"]
    rels = record["relationships"]
    path_len = record["pathLength"]

    output = [f"Shortest path ({path_len} hops):\n"]

    output.append("Path nodes (in order):")
    for i, node in enumerate(nodes):
        prefix = "  → " if i > 0 else "  ● "
        output.append(
            f"{prefix}[{node['kind']}] {node['displayName']} (ID: {node['id']})"
        )

    output.append("\nRelationships along path:")
    for r in rels:
        output.append(f"  {r['source']} --[{r['type']}]--> {r['target']}")

    return "\n".join(output)


def get_node_summary(node_ids: list[str]) -> str:
    """Compact summary of nodes: metadata + relationship counts with sample neighbors.

    Args:
        node_ids: Node IDs to summarize
    """
    driver = _get_driver()
    stop_nodes = _get_stop_nodes()

    cypher = """
    UNWIND $node_ids AS nid
    MATCH (n:CodeNode {id: nid})
    

    OPTIONAL MATCH (n)-[out]->(target)
    WHERE NOT target.id IN $stop_node_ids
    WITH n, type(out) AS outType, count(out) AS outCount, collect(target.displayName)[..5] AS outExamples
    WITH n, collect(CASE WHEN outType IS NOT NULL THEN {type: outType, count: outCount, examples: outExamples} END) AS outgoing
    

    OPTIONAL MATCH (n)<-[inc]-(source)
    WHERE NOT source.id IN $stop_node_ids
    WITH n, outgoing, type(inc) AS incType, count(inc) AS incCount, collect(source.displayName)[..5] AS incExamples
    WITH n, outgoing, collect(CASE WHEN incType IS NOT NULL THEN {type: incType, count: incCount, examples: incExamples} END) AS incoming
    
    RETURN n.id AS id, n.kind AS kind, n.displayName AS displayName,
           n.uri AS uri, n.startLine AS startLine, n.endLine AS endLine,
           outgoing, incoming
    """

    try:
        with driver.session() as session:
            results = session.execute_read(
                lambda tx: list(
                    tx.run(cypher, node_ids=node_ids, stop_node_ids=list(stop_nodes))
                )
            )
    except Exception as e:
        return f"Error: {e}"

    if not results:
        return f"No nodes found for IDs: {node_ids}"

    output = [f"Summary of {len(results)} node(s):\n"]
    for record in results:
        output.append(f"[{record['kind']}] {record['displayName']}")
        output.append(f"  ID: {record['id']}")
        uri = record.get("uri", "")
        if uri:
            output.append(
                f"  File: {uri} (lines {record.get('startLine', '?')}-{record.get('endLine', '?')})"
            )

        outgoing = [e for e in record["outgoing"] if e is not None]
        incoming = [e for e in record["incoming"] if e is not None]

        if outgoing:
            output.append("  Outgoing:")
            for e in outgoing:
                examples = ", ".join(e["examples"])
                if e["count"] > len(e["examples"]):
                    examples += f", ... (+{e['count'] - len(e['examples'])} more)"
                output.append(f"    - {e['type']} ({e['count']}): {examples}")
        else:
            output.append("  Outgoing: (none)")

        if incoming:
            output.append("  Incoming:")
            for e in incoming:
                examples = ", ".join(e["examples"])
                if e["count"] > len(e["examples"]):
                    examples += f", ... (+{e['count'] - len(e['examples'])} more)"
                output.append(f"    - {e['type']} ({e['count']}): {examples}")
        else:
            output.append("  Incoming: (none)")

        output.append("")

    return "\n".join(output)


def get_class_hierarchy(node_id: str, direction: str = "both") -> str:
    """Get inheritance hierarchy for a class/interface.

    Args:
        node_id: Class or interface node ID
        direction: 'up', 'down', or 'both' (default)
    """
    driver = _get_driver()
    direction = direction.lower()
    if direction not in ("up", "down", "both"):
        direction = "both"

    sections = []

    node_cypher = """
    MATCH (n:CodeNode {id: $node_id})
    RETURN n.id AS id, n.kind AS kind, n.displayName AS displayName
    """

    try:
        with driver.session() as session:
            node_result = session.execute_read(
                lambda tx: list(tx.run(node_cypher, node_id=node_id))
            )

            if not node_result:
                return f"Node '{node_id}' not found."

            node = node_result[0]
            sections.append(f"Hierarchy for [{node['kind']}] {node['displayName']}:\n")

            if direction in ("up", "both"):
                ancestors_cypher = """
                MATCH (start:CodeNode {id: $node_id})
                MATCH path = (start)-[:EXTEND*1..10]->(ancestor:CodeNode)
                WITH ancestor, relationships(path) AS rels, length(path) AS depth
                ORDER BY depth
                RETURN ancestor.id AS id, ancestor.kind AS kind,
                       ancestor.displayName AS displayName,
                       type(last(rels)) AS relType, depth
                """
                ancestors = session.execute_read(
                    lambda tx: list(tx.run(ancestors_cypher, node_id=node_id))
                )

                sections.append("Ancestors (superclasses / implemented interfaces):")
                if ancestors:
                    for a in ancestors:
                        indent = "  " * a["depth"]
                        sections.append(
                            f"  {indent}↑ [{a['kind']}] {a['displayName']} (via {a['relType']}, depth {a['depth']})"
                        )
                else:
                    sections.append("  (none — this is a root class/interface)")
                sections.append("")

            if direction in ("down", "both"):
                descendants_cypher = """
                MATCH (start:CodeNode {id: $node_id})
                MATCH path = (start)<-[:EXTEND*1..10]-(descendant:CodeNode)
                WITH descendant, relationships(path) AS rels, length(path) AS depth
                ORDER BY depth
                RETURN descendant.id AS id, descendant.kind AS kind,
                       descendant.displayName AS displayName,
                       type(last(rels)) AS relType, depth
                """
                descendants = session.execute_read(
                    lambda tx: list(tx.run(descendants_cypher, node_id=node_id))
                )

                sections.append("Descendants (subclasses / implementors):")
                if descendants:
                    for d in descendants:
                        indent = "  " * d["depth"]
                        sections.append(
                            f"  {indent}↓ [{d['kind']}] {d['displayName']} (via {d['relType']}, depth {d['depth']})"
                        )
                else:
                    sections.append("  (none — no known subclasses or implementors)")
                sections.append("")

    except Exception as e:
        return f"Error: {e}"

    return "\n".join(sections)


def list_package_classes(package_path: str, include_methods: bool = False) -> str:
    """List classes/interfaces in a package.

    Args:
        package_path: Path fragment to filter by (e.g., 'bitmap_recycle', 'load/engine')
        include_methods: Also list methods/constructors (default: false)
    """
    driver = _get_driver()

    kinds = ["CLASS", "TRAIT"]
    if include_methods:
        kinds.extend(["METHOD", "CONSTRUCTOR"])

    cypher = """
    MATCH (n:CodeNode)
    WHERE n.uri CONTAINS $path AND n.kind IN $kinds
    RETURN n.id AS id, n.kind AS kind, n.displayName AS displayName, n.uri AS uri
    ORDER BY n.uri, n.displayName
    """

    try:
        with driver.session() as session:
            results = session.execute_read(
                lambda tx: list(tx.run(cypher, path=package_path, kinds=kinds))
            )
    except Exception as e:
        return f"Error: {e}"

    if not results:
        return f"No classes or interfaces found matching path '{package_path}'."

    by_file: dict[str, list] = {}
    for r in results:
        uri = r.get("uri", "unknown")
        by_file.setdefault(uri, []).append(r)

    output = [
        f"Found {len(results)} entities in '{package_path}' ({len(by_file)} files):\n"
    ]
    for uri, nodes in sorted(by_file.items()):
        output.append(f"  {uri}:")
        for n in nodes:
            output.append(f"    [{n['kind']}] {n['displayName']} — ID: {n['id']}")
    output.append("")

    return "\n".join(output)


def _read_code_snippet(uri: str, start_line: int, end_line: int) -> str | None:
    """Read a snippet of code from a file."""
    base_dir = os.getcwd()
    if _project_code_dir:
        target_dir = os.path.join(base_dir, _project_code_dir)
    else:
        code_dir = os.path.join(base_dir, "code")
        project_name = os.environ.get("SCG_PROJECT", "private_repo")
        target_dir = os.path.join(code_dir, project_name)

    if not os.path.exists(target_dir):
        target_dir = base_dir

    file_path = os.path.join(target_dir, uri)

    # Try resolving if `uri` is absolute, or if it doesn't exist
    if not os.path.exists(file_path):
        if os.path.exists(uri):
            file_path = uri
        else:
            return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

            # 1-indexed lines
            s = max(0, start_line - 1)
            e = min(len(lines), end_line)

            snippet = "".join(lines[s:e])
            return snippet
    except Exception:
        return None


def semantic_grep(query: str, limit: int = 5) -> str:
    """Graph-Guided Semantic Grep.
    Searches for relevant nodes via semantic search, finds their immediate neighbors,
    and returns actual source code snippets formatting like grep.

    Args:
        query: Natural language query (e.g., 'image loading', 'cache')
        limit: Max initial nodes to search (default: 5)
    """
    driver = _get_driver()
    stop_nodes = _get_stop_nodes()

    if embed_model is None:
        return "Error: Embedding model not loaded."

    query_embedding = embed_model.encode(query).tolist()

    # Step 1: Semantic search to find top starting nodes
    search_cypher = """
    CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
    YIELD node, score
    RETURN node.id AS id, score
    ORDER BY score DESC
    """

    try:
        with driver.session() as session:
            initial_results = session.execute_read(
                lambda tx: list(
                    tx.run(
                        search_cypher,
                        index_name=VECTOR_INDEX_NAME,
                        limit=limit,
                        embedding=query_embedding,
                    )
                )
            )
    except Exception as e:
        return f"Semantic search error: {e}"

    if not initial_results:
        return f"No semantic matches found for '{query}'"

    start_node_ids = [r["id"] for r in initial_results]

    # Step 2: 1-hop expansion, fetching node metadata for snippets
    nodes_cypher = """
    MATCH (start:CodeNode) WHERE start.id IN $node_ids
    MATCH path = (start)-[*0..1]-(n:CodeNode)
    WHERE NONE(x IN nodes(path) WHERE x.id IN $stop_node_ids AND NOT x.id IN $node_ids)
    RETURN DISTINCT n.id AS id, n.kind AS kind, n.displayName AS displayName, 
           n.uri AS uri, n.startLine AS startLine, n.endLine AS endLine
    """

    try:
        with driver.session() as session:
            raw_nodes = session.execute_read(
                lambda tx: list(
                    tx.run(
                        nodes_cypher,
                        node_ids=start_node_ids,
                        stop_node_ids=list(stop_nodes),
                    )
                )
            )
    except Exception as e:
        return f"Error getting expanded context: {e}"

    # Filter out nodes without file locations
    valid_nodes = [
        n
        for n in raw_nodes
        if n.get("uri")
        and n.get("startLine") is not None
        and n.get("endLine") is not None
        and n["startLine"] > 0
        and n["endLine"] >= n["startLine"]
        # Exclude massive files/classes from flooding snippet output (limit to 100 lines)
        and (n["endLine"] - n["startLine"]) <= 100
    ]

    if not valid_nodes:
        return f"Found {len(raw_nodes)} nodes, but none had accessible source code locations or were small enough."

    output = [f"Found {len(valid_nodes)} relevant code snippets for '{query}':\n"]

    # Sort by uri then startLine
    valid_nodes.sort(key=lambda x: (x["uri"], x["startLine"]))

    for n in valid_nodes:
        uri = n["uri"]
        start = n["startLine"]
        end = n["endLine"]

        snippet = _read_code_snippet(uri, start, end)

        header = f"--- {uri}:{start}-{end} ({n['kind']} {n['displayName']}) ---"
        output.append(header)

        if snippet:
            output.append(f"```\n{snippet.rstrip()}\n```\n")
        else:
            output.append("`[Source code unavailable or could not be read]`\n")

    return "\n".join(output)


@mcp.tool()
def investigate(
    query: str,
    directions: str = "both",
    include_code: bool = False,
    include_file_deps: bool = False,
) -> str:
    """Primary codebase exploration tool. Finds relevant code entities and
    returns curated context (metadata, relationships, code) in one call.

    Args:
        query: Natural language query (e.g., 'cache management', 'image loading')
        directions: 'out', 'in', or 'both'. Which topological dependencies to include.
                    If you only want to know what a function calls, use 'out' to save context.
        include_code: If true, includes up to 15 lines of code snippet (method signature).
        include_file_deps: If true, includes inter-file topology. Leave false if searching for functions.
    """
    driver = _get_driver()
    stop_nodes = _get_stop_nodes()

    if embed_model is None:
        return "Error: Embedding model not loaded."

    directions = directions.lower()
    if directions not in ("out", "in", "both"):
        directions = "both"

    query_embedding = embed_model.encode(query).tolist()
    limit = 3

    # ── Step 1: Semantic search ──────────────────────────────────────────
    search_cypher = """
    CALL db.index.vector.queryNodes($index_name, $raw_limit, $embedding)
    YIELD node, score
    RETURN node.id AS id, node.kind AS kind, node.displayName AS displayName,
           node.uri AS uri, node.startLine AS startLine, node.endLine AS endLine,
           score
    ORDER BY score DESC
    """

    try:
        with driver.session() as session:
            search_results = session.execute_read(
                lambda tx: list(
                    tx.run(
                        search_cypher,
                        index_name=VECTOR_INDEX_NAME,
                        raw_limit=limit * 5,
                        embedding=query_embedding,
                    )
                )
            )
    except Exception as e:
        return f"Search error: {e}"

    # Filter to meaningful kinds
    search_results = [r for r in search_results if r["kind"] in DEFAULT_SEARCH_KINDS][
        :limit
    ]

    if not search_results:
        return f"No results found for '{query}'"

    node_ids = [r["id"] for r in search_results]

    # ── Step 2: Relationship summaries ───────────────────────────────────
    if directions == "out":
        rel_cypher = """
        UNWIND $node_ids AS nid MATCH (n:CodeNode {id: nid})
        OPTIONAL MATCH (n)-[out]->(target) WHERE target IS NOT NULL AND NOT target.id IN $stop_node_ids
        WITH n, type(out) AS outType, count(out) AS outCount, collect(DISTINCT target.displayName)[..2] AS outSamples
        WITH n, collect(CASE WHEN outType IS NOT NULL THEN {type: outType, count: outCount, samples: outSamples} END) AS outgoing
        RETURN n.id AS id, outgoing, [] AS incoming
        """
    elif directions == "in":
        rel_cypher = """
        UNWIND $node_ids AS nid MATCH (n:CodeNode {id: nid})
        OPTIONAL MATCH (n)<-[inc]-(source) WHERE source IS NOT NULL AND NOT source.id IN $stop_node_ids
        WITH n, type(inc) AS incType, count(inc) AS incCount, collect(DISTINCT source.displayName)[..2] AS incSamples
        WITH n, collect(CASE WHEN incType IS NOT NULL THEN {type: incType, count: incCount, samples: incSamples} END) AS incoming
        RETURN n.id AS id, [] AS outgoing, incoming
        """
    else:  # both
        rel_cypher = """
        UNWIND $node_ids AS nid MATCH (n:CodeNode {id: nid})
        OPTIONAL MATCH (n)-[out]->(target) WHERE target IS NOT NULL AND NOT target.id IN $stop_node_ids
        WITH n, type(out) AS outType, count(out) AS outCount, collect(DISTINCT target.displayName)[..2] AS outSamples
        WITH n, collect(CASE WHEN outType IS NOT NULL THEN {type: outType, count: outCount, samples: outSamples} END) AS outgoing
        OPTIONAL MATCH (n)<-[inc]-(source) WHERE source IS NOT NULL AND NOT source.id IN $stop_node_ids
        WITH n, outgoing, type(inc) AS incType, count(inc) AS incCount, collect(DISTINCT source.displayName)[..2] AS incSamples
        WITH n, outgoing, collect(CASE WHEN incType IS NOT NULL THEN {type: incType, count: incCount, samples: incSamples} END) AS incoming
        RETURN n.id AS id, outgoing, incoming
        """

    try:
        with driver.session() as session:
            rel_data = session.execute_read(
                lambda tx: list(
                    tx.run(
                        rel_cypher, node_ids=node_ids, stop_node_ids=list(stop_nodes)
                    )
                )
            )
    except Exception:
        rel_data = []

    rel_map = {r["id"]: r for r in rel_data}

    # ── Step 3 (optional): Inter-file dependencies ──────────────────────
    file_deps: dict[tuple[str, str], dict[str, int]] = {}
    if include_file_deps:
        deps_cypher = """
        MATCH (start:CodeNode) WHERE start.id IN $node_ids
        MATCH (start)-[*0..1]-(n:CodeNode)-[r]->(m:CodeNode)
        WHERE n.uri IS NOT NULL AND m.uri IS NOT NULL AND n.uri <> m.uri
          AND NOT n.id IN $stop_node_ids AND NOT m.id IN $stop_node_ids
        WITH split(n.uri, '/')[-1] AS srcFile, split(m.uri, '/')[-1] AS tgtFile,
             type(r) AS relType, count(*) AS cnt
        RETURN srcFile, tgtFile, collect({type: relType, count: cnt}) AS rels,
               sum(cnt) AS total
        ORDER BY total DESC
        LIMIT 5
        """
        try:
            with driver.session() as session:
                deps = session.execute_read(
                    lambda tx: list(
                        tx.run(
                            deps_cypher,
                            node_ids=node_ids,
                            stop_node_ids=list(stop_nodes),
                        )
                    )
                )
            for d in deps:
                key = (d["srcFile"], d["tgtFile"])
                file_deps[key] = {r["type"]: r["count"] for r in d["rels"]}
        except Exception:
            pass

    # ── Format output ────────────────────────────────────────────────────
    def _short_id(full_id: str) -> str:
        """Shorten 'com.bumptech.glide.load.engine.Engine#load' to 'Engine#load'."""
        parts = full_id.rsplit(".", 1)
        return parts[-1] if len(parts) > 1 else full_id

    output = []

    for i, r in enumerate(search_results, 1):
        short = _short_id(r["id"])
        line_info = ""
        if r.get("uri"):
            fname = r["uri"].rsplit("/", 1)[-1]
            line_info = f" ({fname}:{r.get('startLine', '?')}-{r.get('endLine', '?')})"
        output.append(f"{i}. [{r['kind']}] {r['displayName']}{line_info}")
        output.append(f"   ID: {r['id']}")

        # Compact relationship summary
        if r["id"] in rel_map:
            rd = rel_map[r["id"]]
            outgoing = [e for e in rd["outgoing"] if e is not None]
            incoming = [e for e in rd["incoming"] if e is not None]

            if outgoing:
                parts = [
                    f"{e['type']}({e['count']}): {', '.join(e['samples'][:2])}"
                    for e in outgoing
                ]
                output.append(f"   Out: {' | '.join(parts)}")

            if incoming:
                parts = [
                    f"{e['type']}({e['count']}): {', '.join(e['samples'][:2])}"
                    for e in incoming
                ]
                output.append(f"   In: {' | '.join(parts)}")

        # Code signature
        if include_code and r.get("uri") and r.get("startLine") and r.get("endLine"):
            line_count = r.get("endLine", r["startLine"]) - r["startLine"]
            if line_count >= 0:
                end_l = min(r["endLine"], r["startLine"] + 15)
                snippet = _read_code_snippet(r["uri"], r["startLine"], end_l)
                if snippet:
                    output.append(f"```\n{snippet.rstrip()}\n```")

    # Inter-file dependency map
    if include_file_deps and file_deps:
        output.append("\nFile deps:")
        for (sf, tf), types in sorted(
            file_deps.items(), key=lambda x: -sum(x[1].values())
        )[:5]:
            total = sum(types.values())
            types_str = ", ".join(f"{k}({v})" for k, v in types.items())
            output.append(f"  {sf} => {tf} [{total}] ({types_str})")

    return "\n".join(output)


MAX_QUERY_RESULTS = 50


@mcp.tool()
def query_neo4j(cypher: str, params: dict | None = None) -> str:
    """Execute a read-only Cypher query against the code graph.

    SCHEMA:
      Label: :CodeNode
      Properties: id (str, fully-qualified), kind (str), displayName (str),
                  uri (str, file path), startLine (int), endLine (int)
      Edge types: CALL, EXTEND, OVERRIDE, CONTAINS, TYPE, DECLARATION,
                  PARAMETER, RETURN_TYPE, TYPE_ARGUMENT, TYPE_PARAMETER
      WARNING: Do NOT use 'EXTENDS' or 'IMPLEMENTS'. The graph strictly uses 'EXTEND'.

    Example:
      MATCH (n:CodeNode)
      WHERE n.displayName CONTAINS 'Cache' AND n.kind = 'CLASS'
      RETURN n.id, n.displayName, n.uri LIMIT 10

    Args:
        cypher: Cypher query string (read-only, always include LIMIT)
        params: Optional query parameters
    """
    driver = _get_driver()

    if params is None:
        params = {}

    try:
        with driver.session() as session:
            result = session.execute_read(lambda tx: list(tx.run(cypher, **params)))

        if not result:
            return "Query returned no results."

        total_count = len(result)
        truncated = total_count > MAX_QUERY_RESULTS

        output = [f"Returned {total_count} record(s)"]
        if truncated:
            truncated_records = result[MAX_QUERY_RESULTS:]
            kind_counts: dict[str, int] = {}
            for r in truncated_records:
                k = None
                for col in ("kind", "n.kind"):
                    if col in r.keys():
                        k = r[col]
                        break
                k = k or "unknown"
                kind_counts[k] = kind_counts.get(k, 0) + 1

            output[0] += f", showing first {MAX_QUERY_RESULTS}"
            result = result[:MAX_QUERY_RESULTS]

        output[0] += ":\n"

        for i, record in enumerate(result, 1):
            output.append(f"Record {i}:")
            for key in record.keys():
                value = record[key]
                output.append(f"  {key}: {value}")
            output.append("")

        if truncated:
            output.append(
                f"\n⚠️  {total_count - MAX_QUERY_RESULTS} additional records were truncated."
            )
            output.append(f"Truncated kinds: {kind_counts}")
            output.append(
                "Tip: Add a LIMIT clause or filter with WHERE n.kind IN ['CLASS', 'TRAIT', 'METHOD'] "
                "to narrow results. Or use the list_package_classes tool for package exploration."
            )

        return "\n".join(output)

    except Exception as e:
        return f"Cypher query error: {e}"


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    global neo4j_driver, embed_model, _project_code_dir

    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        neo4j_driver.verify_connectivity()
        log.info("Connected to Neo4j at %s", NEO4J_URI)
    except Exception as e:
        log.error("Could not connect to Neo4j: %s", e)
        raise

    log.info("Loading embedding model '%s'...", EMBED_MODEL_NAME)
    with redirect_stdout_to_stderr():
        embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    log.info("Embedding model loaded.")

    cfg = get_project_config()
    _project_code_dir = str(cfg.code_dir)
    log.info("Project: %s, code_dir: %s", cfg.name, _project_code_dir)

    async with mcp.session_manager.run():
        yield

    if neo4j_driver is not None:
        neo4j_driver.close()
        log.info("Neo4j driver closed.")


def create_app() -> Starlette:
    app = Starlette(
        routes=[
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
    return app


def main():
    log.info("Starting SCG MCP Server...")
    log.info("Connect to: http://localhost:8080/mcp")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
