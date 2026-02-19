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

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "password"))
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_INDEX_NAME = "code_embeddings"
VECTOR_DIMENSIONS = 384

# ── Module-level state ───────────────────────────────────────────────────────

neo4j_driver = None
embed_model: SentenceTransformer | None = None


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


# ── MCP Server ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    "semantic-graph-rag",
    instructions="A powerful Semantic Code Graph (SCG) tool for deep codebase understanding. "
    "It enables semantic search, relationship exploration (inheritance, usage, etc.), and retrieval of source code. "
    "Accessing graph statistics and exploring deep code relationships is essential for understanding "
    "complex architectural patterns, identifying core components, and navigating large-scale projects "
    "efficiently. Use this to get a structural overview or drill down into specific implementations.\n\n"
    "=== GRAPH SCHEMA ===\n"
    "Nodes: :CodeNode\n"
    "  Properties: id, kind, displayName, source, uri, startLine, endLine, embedding, prop_*\n"
    "  kind values: CLASS, TRAIT, METHOD, CONSTRUCTOR, FILE, VALUE, VARIABLE, PARAMETER, TYPE_PARAMETER, etc.\n\n"
    "Relationships (edge types):\n"
    "  - CALL: method/function calls\n"
    "  - EXTEND: class inheritance and interface implementation\n"
    "  - OVERRIDE: method overriding\n"
    "  - CONTAINS: file/class contains members\n"
    "  - TYPE: type usage/reference\n"
    "  - DECLARATION: variable/function declarations\n"
    "  - PARAMETER: method parameters\n"
    "  - RETURN_TYPE: method return types\n"
    "  - TYPE_ARGUMENT, EXTEND_TYPE_ARGUMENT, RETURN_TYPE_ARGUMENT, TYPE_PARAMETER: generics\n"
    "  Relationships may have locUri, locLine properties.\n\n"
    "=== RECOMMENDED WORKFLOW (token-efficient) ===\n"
    "1. START with search_code or list_package_classes to find relevant entities at class/interface level.\n"
    "2. USE get_node_summary (cheap, no source code) to understand relationships before diving deep.\n"
    "3. USE get_class_hierarchy to understand inheritance structure.\n"
    "4. ONLY THEN use get_node_source or get_node_context (with include_source=True) for specific nodes.\n\n"
    "AVOID:\n"
    "- query_neo4j without LIMIT or kind filters (always add WHERE n.kind IN ['CLASS', 'TRAIT', 'METHOD']).\n"
    "- get_node_context with include_source=True on broad queries — use get_node_summary first.\n"
    "- get_node_context with hops=2 on nodes inside large classes — this causes fan-out explosion. "
    "Use hops=1 first, then drill into specific neighbors.\n"
    "- Fetching all nodes in a package via raw Cypher — use list_package_classes instead.",
)


# ── Tools ────────────────────────────────────────────────────────────────────


# Default kinds for search — class-level entities that carry architectural meaning.
# The agent can override this to include finer-grained nodes when needed.
DEFAULT_SEARCH_KINDS = ["CLASS", "TRAIT", "ENUM", "METHOD", "CONSTRUCTOR", "FILE"]

# Maximum nodes returned by get_node_context before truncation.
MAX_CONTEXT_NODES = 50

# Node kinds that are filtered out of get_node_context results by default
# to avoid fan-out explosion from large classes.
CONTEXT_NOISE_KINDS = {"PARAMETER", "VARIABLE", "TYPE_PARAMETER"}


@mcp.tool()
def search_code(query: str, limit: int = 5, kinds: list[str] | None = None) -> str:
    """Search for code entities (classes, methods, fields) in the codebase using semantic vector search.
    This is the entry point for finding relevant code when you don't know the exact names.
    Returns the most relevant nodes matching your query.

    Args:
        query: Natural language query to search for code entities (e.g., 'image loading', 'cache management', 'bitmap decoder')
        limit: Maximum number of results to return (default: 5)
        kinds: Optional list of node kinds to include (e.g., ['CLASS', 'TRAIT', 'METHOD']).
               Defaults to CLASS, TRAIT, METHOD, CONSTRUCTOR, FILE.
               Pass ['ALL'] to include everything (parameters, variables, etc.).
    """
    driver = _get_driver()

    if embed_model is None:
        return "Error: Embedding model not loaded."

    query_embedding = embed_model.encode(query).tolist()

    # Determine kind filter
    include_all = kinds is not None and len(kinds) == 1 and kinds[0].upper() == "ALL"
    filter_kinds = None if include_all else (kinds if kinds else DEFAULT_SEARCH_KINDS)

    # Fetch more candidates so we have enough after kind-filtering
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

    # Apply kind filter
    if filter_kinds:
        results = [r for r in results if r["kind"] in filter_kinds][:limit]
    else:
        results = results[:limit]

    if not results:
        kind_note = f" (filtered to kinds: {filter_kinds})" if filter_kinds else ""
        return f"No results found for query: '{query}'{kind_note}"

    kind_note = f" (kinds: {', '.join(filter_kinds)})" if filter_kinds else " (all kinds)"
    output = [f"Found {len(results)} results for '{query}'{kind_note}:\n"]
    for i, record in enumerate(results, 1):
        output.append(f"{i}. [{record['kind']}] {record['displayName']}")
        output.append(f"   ID: {record['id']}")
        output.append(f"   Score: {record['score']:.4f}")
        output.append("")

    return "\n".join(output)


@mcp.tool()
def get_node_context(
    node_ids: list[str],
    hops: int = 1,
    include_source: bool = False,
    kinds: list[str] | None = None,
) -> str:
    """Get the context subgraph around specific code nodes, including related entities and their relationships.
    Use this to explore graph relations (like who calls this, or what this inherits from).
    Understanding these relations is crucial for tracing data flow and architectural dependencies.

    To save tokens, include_source defaults to false. Use get_node_source to fetch source
    for specific nodes after reviewing the relationship map.

    IMPORTANT: With hops=2 on nodes inside large classes, the results can explode to hundreds
    of nodes. Start with hops=1 and drill into specific neighbors instead.

    Args:
        node_ids: List of node IDs to get context for (obtained from search_code)
        hops: Number of relationship hops to traverse (default: 1, max: 3)
        include_source: Whether to include source code snippets (default: false)
        kinds: Optional list of node kinds to include in results.
               By default, PARAMETER, VARIABLE, and TYPE_PARAMETER are filtered out
               to reduce noise. Pass ['ALL'] to include everything.
    """
    driver = _get_driver()
    hops = max(1, min(int(hops), 3))

    # Determine kind filtering
    include_all = kinds is not None and len(kinds) == 1 and kinds[0].upper() == "ALL"
    filter_kinds = None if include_all else (set(k.upper() for k in kinds) if kinds else None)
    # If no explicit kinds given, use noise filter
    use_noise_filter = not include_all and filter_kinds is None

    source_field = ", n.source AS source" if include_source else ""

    nodes_cypher = f"""
    MATCH (start:CodeNode) WHERE start.id IN $node_ids
    MATCH path = (start)-[*0..{hops}]-(n:CodeNode)
    RETURN DISTINCT n.id AS id, n.kind AS kind, n.displayName AS displayName{source_field}
    """

    try:
        with driver.session() as session:
            raw_nodes = session.execute_read(
                lambda tx: list(tx.run(nodes_cypher, node_ids=node_ids))
            )
    except Exception as e:
        return f"Error getting node context: {e}"

    if not raw_nodes:
        return f"No nodes found for IDs: {node_ids}"

    # Apply kind filtering
    if use_noise_filter:
        filtered_nodes = [n for n in raw_nodes if n["kind"] not in CONTEXT_NOISE_KINDS]
        noise_count = len(raw_nodes) - len(filtered_nodes)
    elif filter_kinds:
        filtered_nodes = [n for n in raw_nodes if n["kind"] in filter_kinds]
        noise_count = len(raw_nodes) - len(filtered_nodes)
    else:
        filtered_nodes = raw_nodes
        noise_count = 0

    # Truncate if still too many
    truncated = False
    truncated_summary = ""
    if len(filtered_nodes) > MAX_CONTEXT_NODES:
        truncated = True
        shown_nodes = filtered_nodes[:MAX_CONTEXT_NODES]
        omitted = filtered_nodes[MAX_CONTEXT_NODES:]
        # Group omitted nodes by kind — collect IDs (capped per kind to avoid bloat)
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

        # Build summary with counts and recoverable IDs
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

    # Collect IDs of shown nodes for relationship filtering
    shown_ids = {n["id"] for n in shown_nodes}
    # Collect ALL traversed IDs (including omitted/filtered) to detect hidden relationships
    all_traversed_ids = {n["id"] for n in raw_nodes}
    hidden_ids = all_traversed_ids - shown_ids

    # Fetch relationships between shown nodes (full detail)
    rels_cypher = """
    MATCH (a:CodeNode)-[r]->(b:CodeNode)
    WHERE a.id IN $shown_ids AND b.id IN $shown_ids
    RETURN DISTINCT a.displayName AS source, type(r) AS relType, b.displayName AS target,
                    a.id AS sourceId, b.id AS targetId
    """

    try:
        with driver.session() as session:
            rels = session.execute_read(
                lambda tx: list(tx.run(rels_cypher, shown_ids=list(shown_ids)))
            )
    except Exception as e:
        return f"Error getting relationships: {e}"

    # If there are hidden nodes, count relationships crossing the boundary
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
                    lambda tx: list(tx.run(
                        hidden_rels_cypher,
                        shown_ids=list(shown_ids),
                        hidden_ids=list(hidden_ids),
                    ))
                )
            if hidden_rels:
                parts = [f"{r['relType']} ({r['cnt']})" for r in hidden_rels]
                hidden_rel_summary = (
                    f"\n⚠️ {sum(r['cnt'] for r in hidden_rels)} relationships to/from "
                    f"omitted/filtered nodes not shown: {', '.join(parts)}. "
                    f"Use get_node_summary on omitted IDs to explore."
                )
        except Exception:
            pass  # Non-critical — don't fail if summary query errors

    # Build output
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

    if include_source:
        output.append("\nSource Code:")
        for n in shown_nodes:
            source = n.get("source", "")
            if source:
                output.append(f"\n--- [{n['kind']}] {n['displayName']} ---")
                output.append(source)

    output.append("\nRelationships:")
    if rels:
        for r in rels:
            output.append(f"  - {r['source']} --[{r['relType']}]--> {r['target']}")
    else:
        output.append("  (none)")

    if hidden_rel_summary:
        output.append(hidden_rel_summary)

    return "\n".join(output)


@mcp.tool()
def get_node_source(node_id: str) -> str:
    """Get the source code for a specific node. Returns the actual code implementation
    along with file location information.

    Args:
        node_id: The ID of the node to get source code for
    """
    driver = _get_driver()

    cypher = """
    MATCH (n:CodeNode {id: $node_id})
    RETURN n.id AS id, n.kind AS kind, n.displayName AS displayName,
           n.source AS source, n.uri AS uri, n.startLine AS startLine, n.endLine AS endLine
    """

    try:
        with driver.session() as session:
            result = session.execute_read(
                lambda tx: list(tx.run(cypher, node_id=node_id))
            )
    except Exception as e:
        return f"Error: {e}"

    if not result:
        return f"Node '{node_id}' not found in the graph."

    record = result[0]
    source = record.get("source", "")
    if not source:
        return f"Source code not available for node '{node_id}'."

    name = record["displayName"] or node_id
    kind = record["kind"] or "Unknown"
    uri = record.get("uri", "N/A")
    start_line = record.get("startLine", "?")
    end_line = record.get("endLine", "?")

    output = [
        f"Source code for [{kind}] {name}:",
        f"Node ID: {node_id}",
        f"File: {uri} (lines {start_line}-{end_line})",
        "-" * 60,
        source,
        "-" * 60,
    ]
    return "\n".join(output)


@mcp.tool()
def get_graph_stats() -> str:
    """Get statistics about the loaded code graph, including node and edge counts.
    These statistics provide a high-level overview of the project's complexity and
    the distribution of code entities (classes, methods, etc.).
    """
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


@mcp.tool()
def find_path(from_id: str, to_id: str, max_depth: int = 5) -> str:
    """Find the shortest path between two code entities in the graph.
    Use this to trace execution flow, dependency chains, or understand how
    two components are connected through the codebase.

    Args:
        from_id: The node ID of the starting entity
        to_id: The node ID of the target entity
        max_depth: Maximum number of hops to search (default: 5, max: 10)
    """
    driver = _get_driver()
    max_depth = max(1, min(int(max_depth), 10))

    cypher = f"""
    MATCH (start:CodeNode {{id: $from_id}}), (end:CodeNode {{id: $to_id}})
    MATCH path = shortestPath((start)-[*..{max_depth}]-(end))
    RETURN [n IN nodes(path) | {{id: n.id, kind: n.kind, displayName: n.displayName}}] AS nodes,
           [r IN relationships(path) | {{source: startNode(r).id, target: endNode(r).id, type: type(r)}}] AS relationships,
           length(path) AS pathLength
    """

    try:
        with driver.session() as session:
            result = session.execute_read(
                lambda tx: list(tx.run(cypher, from_id=from_id, to_id=to_id))
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


@mcp.tool()
def get_node_summary(node_ids: list[str]) -> str:
    """Get a compact summary of one or more code nodes — metadata and relationship
    counts, PLUS a few sample neighbors. Use this to get an overview before deciding
    what to drill into.

    Returns for each node:
    - Metadata (kind, name, location)
    - Incoming/Outgoing relationship breakdown (counts + top 3 example nodes for each type)

    Args:
        node_ids: List of node IDs to summarize
    """
    driver = _get_driver()

    # Cypher: Collect neighbors by type, limited to 5 examples per type
    cypher = """
    UNWIND $node_ids AS nid
    MATCH (n:CodeNode {id: nid})
    
    // Outgoing relationships
    OPTIONAL MATCH (n)-[out]->(target)
    WITH n, type(out) AS outType, count(out) AS outCount, collect(target.displayName)[..5] AS outExamples
    WITH n, collect(CASE WHEN outType IS NOT NULL THEN {type: outType, count: outCount, examples: outExamples} END) AS outgoing
    
    // Incoming relationships
    OPTIONAL MATCH (n)<-[inc]-(source)
    WITH n, outgoing, type(inc) AS incType, count(inc) AS incCount, collect(source.displayName)[..5] AS incExamples
    WITH n, outgoing, collect(CASE WHEN incType IS NOT NULL THEN {type: incType, count: incCount, examples: incExamples} END) AS incoming
    
    RETURN n.id AS id, n.kind AS kind, n.displayName AS displayName,
           n.uri AS uri, n.startLine AS startLine, n.endLine AS endLine,
           outgoing, incoming
    """

    try:
        with driver.session() as session:
            results = session.execute_read(
                lambda tx: list(tx.run(cypher, node_ids=node_ids))
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
                examples = ", ".join(e['examples'])
                if e['count'] > len(e['examples']):
                    examples += f", ... (+{e['count'] - len(e['examples'])} more)"
                output.append(f"    - {e['type']} ({e['count']}): {examples}")
        else:
            output.append("  Outgoing: (none)")

        if incoming:
            output.append("  Incoming:")
            for e in incoming:
                examples = ", ".join(e['examples'])
                if e['count'] > len(e['examples']):
                    examples += f", ... (+{e['count'] - len(e['examples'])} more)"
                output.append(f"    - {e['type']} ({e['count']}): {examples}")
        else:
            output.append("  Incoming: (none)")

        output.append("")

    return "\n".join(output)


@mcp.tool()
def get_class_hierarchy(node_id: str, direction: str = "both") -> str:
    """Get the full inheritance/implementation hierarchy for a class or interface.
    Returns superclasses (parents), subclasses (children), and implemented interfaces.

    Args:
        node_id: The node ID of the class or interface to analyze
        direction: 'up' (ancestors only), 'down' (descendants only), or 'both' (default)
    """
    driver = _get_driver()
    direction = direction.lower()
    if direction not in ("up", "down", "both"):
        direction = "both"

    sections = []

    # Get the target node info
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

            # Ancestors: this node inherits/implements → parents → grandparents...
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

            # Descendants: children/implementors that inherit/implement this node
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


@mcp.tool()
def list_package_classes(package_path: str, include_methods: bool = False) -> str:
    """List all classes, interfaces, and traits in a specific package/directory.
    Returns only high-level entities (CLASS, TRAIT), not individual methods, fields, or variables.
    This is the recommended way to explore a package structure — much cheaper than a raw
    Cypher query which would return every AST node.

    Args:
        package_path: Part of the file path to filter by (e.g., 'bitmap_recycle', 'load/engine')
        include_methods: If true, also list METHOD and CONSTRUCTOR nodes (default: false)
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

    # Group by file
    by_file: dict[str, list] = {}
    for r in results:
        uri = r.get("uri", "unknown")
        by_file.setdefault(uri, []).append(r)

    output = [f"Found {len(results)} entities in '{package_path}' ({len(by_file)} files):\n"]
    for uri, nodes in sorted(by_file.items()):
        output.append(f"  {uri}:")
        for n in nodes:
            output.append(f"    [{n['kind']}] {n['displayName']} — ID: {n['id']}")
    output.append("")

    return "\n".join(output)


MAX_QUERY_RESULTS = 50


@mcp.tool()
def query_neo4j(cypher: str, params: dict | None = None) -> str:
    """Execute a read-only Cypher query against the Neo4j code graph database.
    Use this for advanced queries that the other tools don't cover, such as
    complex pattern matching, path finding, or aggregations.

    The graph schema consists of :CodeNode nodes with properties:
      id, kind, displayName, source, uri, startLine, endLine, embedding, prop_*
    Relationships are typed by their edge kind (e.g. CALL, EXTEND, OVERRIDE,
    CONTAINS, TYPE, DECLARATION, PARAMETER, RETURN_TYPE, etc.) and may have locUri, locLine properties.

    IMPORTANT: Always use LIMIT in your Cypher queries and filter by n.kind
    (e.g., WHERE n.kind IN ['CLASS', 'TRAIT', 'METHOD']) to avoid overwhelming
    results. Avoid returning PARAMETERs, VARIABLEs, or TYPE_PARAMETERs unless
    specifically needed.

    Args:
        cypher: A Cypher query string (read-only — MATCH, RETURN, WITH, etc.)
        params: Optional dictionary of query parameters to pass to the Cypher query
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
            # Build a summary of what was truncated
            truncated_records = result[MAX_QUERY_RESULTS:]
            kind_counts: dict[str, int] = {}
            for r in truncated_records:
                # Try common column names for kind
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
            output.append(f"\n⚠️  {total_count - MAX_QUERY_RESULTS} additional records were truncated.")
            output.append(f"Truncated kinds: {kind_counts}")
            output.append(
                "Tip: Add a LIMIT clause or filter with WHERE n.kind IN ['CLASS', 'TRAIT', 'METHOD'] "
                "to narrow results. Or use the list_package_classes tool for package exploration."
            )

        return "\n".join(output)

    except Exception as e:
        return f"Cypher query error: {e}"


# ── Server lifecycle ─────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    global neo4j_driver, embed_model

    # Initialize Neo4j
    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        neo4j_driver.verify_connectivity()
        log.info("Connected to Neo4j at %s", NEO4J_URI)
    except Exception as e:
        log.error("Could not connect to Neo4j: %s", e)
        raise

    # Load embedding model (lightweight — only used for encoding queries)
    log.info("Loading embedding model '%s'...", EMBED_MODEL_NAME)
    with redirect_stdout_to_stderr():
        embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    log.info("Embedding model loaded.")

    async with mcp.session_manager.run():
        yield

    # Cleanup
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
