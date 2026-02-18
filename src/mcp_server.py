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
    "efficiently. Use this to get a structural overview or drill down into specific implementations.",
)


# ── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def search_code(query: str, limit: int = 5) -> str:
    """Search for code entities (classes, methods, fields) in the codebase using semantic vector search.
    This is the entry point for finding relevant code when you don't know the exact names.
    Returns the most relevant nodes matching your query.

    Args:
        query: Natural language query to search for code entities (e.g., 'image loading', 'cache management', 'bitmap decoder')
        limit: Maximum number of results to return (default: 5)
    """
    driver = _get_driver()

    if embed_model is None:
        return "Error: Embedding model not loaded."

    query_embedding = embed_model.encode(query).tolist()

    cypher = """
    CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
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
                        limit=limit,
                        embedding=query_embedding,
                    )
                )
            )
    except Exception as e:
        return f"Search error: {e}"

    if not results:
        return f"No results found for query: '{query}'"

    output = [f"Found {len(results)} results for '{query}':\n"]
    for i, record in enumerate(results, 1):
        output.append(f"{i}. [{record['kind']}] {record['displayName']}")
        output.append(f"   ID: {record['id']}")
        output.append(f"   Score: {record['score']:.4f}")
        output.append("")

    return "\n".join(output)


@mcp.tool()
def get_node_context(
    node_ids: list[str], hops: int = 1, include_source: bool = True
) -> str:
    """Get the context subgraph around specific code nodes, including related entities and their relationships.
    Use this to explore graph relations (like who calls this, or what this inherits from).
    Understanding these relations is crucial for tracing data flow and architectural dependencies.

    Args:
        node_ids: List of node IDs to get context for (obtained from search_code)
        hops: Number of relationship hops to traverse (default: 1, max: 3)
        include_source: Whether to include source code snippets (default: true)
    """
    driver = _get_driver()
    hops = max(1, min(int(hops), 3))

    source_field = ", n.source AS source" if include_source else ""

    nodes_cypher = f"""
    MATCH (start:CodeNode) WHERE start.id IN $node_ids
    MATCH path = (start)-[*0..{hops}]-(n:CodeNode)
    RETURN DISTINCT n.id AS id, n.kind AS kind, n.displayName AS displayName{source_field}
    """

    rels_cypher = f"""
    MATCH (start:CodeNode) WHERE start.id IN $node_ids
    MATCH (start)-[*0..{hops}]-(n:CodeNode)
    WITH collect(DISTINCT n) AS nodes
    UNWIND nodes AS a
    MATCH (a)-[r]->(b:CodeNode) WHERE b IN nodes
    RETURN DISTINCT a.displayName AS source, type(r) AS relType, b.displayName AS target,
                    a.id AS sourceId, b.id AS targetId
    """

    try:
        with driver.session() as session:
            nodes = session.execute_read(
                lambda tx: list(tx.run(nodes_cypher, node_ids=node_ids))
            )
            rels = session.execute_read(
                lambda tx: list(tx.run(rels_cypher, node_ids=node_ids))
            )
    except Exception as e:
        return f"Error getting node context: {e}"

    if not nodes:
        return f"No nodes found for IDs: {node_ids}"

    output = [f"Context subgraph ({len(nodes)} nodes, {len(rels)} relationships):\n"]

    output.append("Nodes:")
    for n in nodes:
        output.append(f"  - [{n['kind']}] {n['displayName']} (ID: {n['id']})")

    if include_source:
        output.append("\nSource Code:")
        for n in nodes:
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
    counts only, NO source code. Use this to get an overview before deciding what
    to drill into with get_node_source or get_node_context.

    Much cheaper in tokens than get_node_context. Returns for each node:
    kind, displayName, file location, and a breakdown of relationship counts
    by type (both incoming and outgoing).

    Args:
        node_ids: List of node IDs to summarize
    """
    driver = _get_driver()

    cypher = """
    UNWIND $node_ids AS nid
    MATCH (n:CodeNode {id: nid})
    OPTIONAL MATCH (n)-[out]->()
    WITH n, type(out) AS outType, count(out) AS outCount
    WITH n, collect(CASE WHEN outType IS NOT NULL THEN {type: outType, count: outCount} END) AS outgoing
    OPTIONAL MATCH (n)<-[inc]-()
    WITH n, outgoing, type(inc) AS incType, count(inc) AS incCount
    WITH n, outgoing, collect(CASE WHEN incType IS NOT NULL THEN {type: incType, count: incCount} END) AS incoming
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
            out_parts = ", ".join(f"{e['type']}: {e['count']}" for e in outgoing)
            output.append(f"  Outgoing: {out_parts}")
        else:
            output.append("  Outgoing: (none)")

        if incoming:
            inc_parts = ", ".join(f"{e['type']}: {e['count']}" for e in incoming)
            output.append(f"  Incoming: {inc_parts}")
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
                MATCH path = (start)-[:INHERITS|IMPLEMENTS*1..10]->(ancestor:CodeNode)
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
                MATCH path = (start)<-[:INHERITS|IMPLEMENTS*1..10]-(descendant:CodeNode)
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
def query_neo4j(cypher: str, params: dict | None = None) -> str:
    """Execute a read-only Cypher query against the Neo4j code graph database.
    Use this for advanced queries that the other tools don't cover, such as
    complex pattern matching, path finding, or aggregations.

    The graph schema consists of :CodeNode nodes with properties:
      id, kind, displayName, source, uri, startLine, endLine, embedding, prop_*
    Relationships are typed by their edge kind (e.g. CALLS, INHERITS, OVERRIDES,
    HAS_MEMBER, USES_TYPE, etc.) and may have locUri, locLine properties.

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

        output = [f"Returned {len(result)} record(s):\n"]
        for i, record in enumerate(result, 1):
            output.append(f"Record {i}:")
            for key in record.keys():
                value = record[key]
                output.append(f"  {key}: {value}")
            output.append("")

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
