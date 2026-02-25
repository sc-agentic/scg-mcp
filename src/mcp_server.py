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


NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "password"))
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_INDEX_NAME = "code_embeddings"
VECTOR_DIMENSIONS = 384


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



mcp = FastMCP(
    "semantic-graph-rag",
    instructions="Semantic Code Graph (SCG) for codebase exploration.\n\n"
    "SCHEMA: Nodes are :CodeNode with properties: id, kind, displayName, uri, startLine, endLine.\n"
    "kind values: CLASS, TRAIT, METHOD, CONSTRUCTOR, FILE, VALUE, VARIABLE, PARAMETER, TYPE_PARAMETER.\n"
    "Edges: CALL, EXTEND, OVERRIDE, CONTAINS, TYPE, DECLARATION, PARAMETER, RETURN_TYPE, "
    "TYPE_ARGUMENT, EXTEND_TYPE_ARGUMENT, RETURN_TYPE_ARGUMENT, TYPE_PARAMETER.\n\n"
    "WORKFLOW: search_code → get_node_summary → get_class_hierarchy → get_node_context.\n"
    "AVOID: hops=2 on large classes (fan-out explosion), query_neo4j without LIMIT.",
)


DEFAULT_SEARCH_KINDS = ["CLASS", "TRAIT", "ENUM", "METHOD", "CONSTRUCTOR", "FILE"]
MAX_CONTEXT_NODES = 50
CONTEXT_NOISE_KINDS = {"PARAMETER", "VARIABLE", "TYPE_PARAMETER"}


@mcp.tool()
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
    kinds: list[str] | None = None,
) -> str:
    """Get the context subgraph around code nodes — related entities and relationships.

    Args:
        node_ids: Node IDs to explore (from search_code)
        hops: Relationship hops (default: 1, max: 3). Avoid hops=2 on large classes.
        kinds: Node kinds to include. Default filters out PARAMETER, VARIABLE, TYPE_PARAMETER. Pass ['ALL'] for all.
    """
    driver = _get_driver()
    hops = max(1, min(int(hops), 3))

    include_all = kinds is not None and len(kinds) == 1 and kinds[0].upper() == "ALL"
    filter_kinds = None if include_all else (set(k.upper() for k in kinds) if kinds else None)
    use_noise_filter = not include_all and filter_kinds is None

    nodes_cypher = f"""
    MATCH (start:CodeNode) WHERE start.id IN $node_ids
    MATCH path = (start)-[*0..{hops}]-(n:CodeNode)
    RETURN DISTINCT n.id AS id, n.kind AS kind, n.displayName AS displayName
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
                    a.id AS sourceId, b.id AS targetId
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
        # Deduplicate
        seen_rels = set()
        unique_rels = []
        for r in rels:
            key = (r['source'], r['relType'], r['target'])
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





@mcp.tool()
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


@mcp.tool()
def find_path(from_id: str, to_id: str, max_depth: int = 5) -> str:
    """Find shortest path between two code entities.

    Args:
        from_id: Starting node ID
        to_id: Target node ID
        max_depth: Max hops (default: 5, max: 10)
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
    """Compact summary of nodes: metadata + relationship counts with sample neighbors.

    Args:
        node_ids: Node IDs to summarize
    """
    driver = _get_driver()


    cypher = """
    UNWIND $node_ids AS nid
    MATCH (n:CodeNode {id: nid})
    

    OPTIONAL MATCH (n)-[out]->(target)
    WITH n, type(out) AS outType, count(out) AS outCount, collect(target.displayName)[..5] AS outExamples
    WITH n, collect(CASE WHEN outType IS NOT NULL THEN {type: outType, count: outCount, examples: outExamples} END) AS outgoing
    

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


@mcp.tool()
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
    """Execute a read-only Cypher query. Always use LIMIT and kind filters.

    Args:
        cypher: Cypher query string (read-only)
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
            output.append(f"\n⚠️  {total_count - MAX_QUERY_RESULTS} additional records were truncated.")
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
    global neo4j_driver, embed_model


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
