import sys
import uvicorn
import logging
import contextlib
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.config import get_project_config
from src.rag_engine import GraphRAG

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

rag: GraphRAG | None = None


@contextlib.contextmanager
def redirect_stdout_to_stderr():
    old_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old_stdout


def init_rag() -> None:
    global rag
    cfg = get_project_config()
    log.info("Initializing GraphRAG engine for project '%s'...", cfg.name)
    with redirect_stdout_to_stderr():
        rag = GraphRAG(data_dir=cfg.data_dir, code_dir=cfg.code_dir)
    log.info("GraphRAG engine initialized.")


def get_rag() -> GraphRAG:
    if rag is None:
        raise RuntimeError("RAG engine not initialized. Call init_rag() first.")
    return rag


server = Server(
    "semantic-graph-rag",
    instructions="A powerful Semantic Code Graph (SCG) tool for deep codebase understanding. "
                 "It enables semantic search, relationship exploration (inheritance, usage, etc.), and retrieval of source code. "
                 "Accessing graph statistics and exploring deep code relationships is essential for understanding "
                 "complex architectural patterns, identifying core components, and navigating large-scale projects "
                 "efficiently. Use this to get a structural overview or drill down into specific implementations."
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_code",
            description="Search for code entities (classes, methods, fields) in the codebase using semantic search. "
                        "This is the entry point for finding relevant code when you don't know the exact names. "
                        "Returns the most relevant nodes matching your query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query to search for code entities (e.g., 'image loading', 'cache management', 'bitmap decoder')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_node_context",
            description="Get the context subgraph around specific code nodes. "
                        "Use this to explore graph relations (like who calls this, or what this inherits from). "
                        "Understanding these relations is crucial for tracing data flow and architectural dependencies.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of node IDs to get context for (obtained from search_code)",
                    },
                    "hops": {
                        "type": "integer",
                        "description": "Number of relationship hops to traverse (default: 1)",
                        "default": 1,
                    },
                    "include_source": {
                        "type": "boolean",
                        "description": "Whether to include source code snippets (default: true)",
                        "default": True,
                    },
                },
                "required": ["node_ids"],
            },
        ),
        Tool(
            name="get_node_source",
            description="Get the source code for a specific node. Returns the actual code implementation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "The ID of the node to get source code for",
                    },
                    "context_padding": {
                        "type": "integer",
                        "description": "Number of lines of context to include before and after (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["node_id"],
            },
        ),
        Tool(
            name="get_graph_stats",
            description="Get statistics about the loaded code graph, including node and edge counts. "
                        "These statistics provide a high-level overview of the project's complexity and "
                        "the distribution of code entities (classes, methods, etc.).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    engine = get_rag()
    results = engine.find_nodes(query, limit=limit)
    
    if not results:
        return f"No results found for query: '{query}'"
    
    output = [f"Found {len(results)} results for '{query}':\n"]
    for i, node in enumerate(results, 1):
        score = node.get("score", "N/A")
        kind = node.get("kind", "Unknown")
        name = node.get("display_name") or node["id"]
        output.append(f"{i}. [{kind}] {name}")
        output.append(f"   ID: {node['id']}")
        if isinstance(score, float):
            output.append(f"   Score: {score:.4f}")
        output.append("")
    
    return "\n".join(output)


@mcp.tool()
def get_node_context(node_ids: list[str], hops: int = 1, include_source: bool = True) -> str:
    """Get the context subgraph around specific code nodes, including related entities and their relationships.
    
    Args:
        node_ids: List of node IDs to get context for (obtained from search_code)
        hops: Number of relationship hops to traverse (default: 1)
        include_source: Whether to include source code snippets (default: true)
    """
    engine = get_rag()
    subgraph = engine.get_context_subgraph(node_ids, hops=hops)
    
    if include_source:
        return engine.format_context_for_llm(subgraph, code_context_padding=3)
    
    output = [
        f"Context subgraph ({len(subgraph['nodes'])} nodes, {len(subgraph['edges'])} edges):\n"
    ]
    output.append("Nodes:")
    for node in subgraph["nodes"]:
        kind = node.get("kind", "Unknown")
        name = node.get("display_name") or node["id"]
        output.append(f"  - [{kind}] {name} (ID: {node['id']})")
    
    output.append("\nRelationships:")
    for edge in subgraph["edges"]:
        s = engine.node_metadata.get(edge["source"], {}).get("display_name", edge["source"])
        t = engine.node_metadata.get(edge["target"], {}).get("display_name", edge["target"])
        output.append(f"  - {s} --[{edge['type']}]--> {t}")
    
    return "\n".join(output)


@mcp.tool()
def get_node_source(node_id: str, context_padding: int = 5) -> str:
    """Get the source code for a specific node. Returns the actual code implementation.
    
    Args:
        node_id: The ID of the node to get source code for
        context_padding: Number of lines of context to include before and after (default: 5)
    """
    engine = get_rag()
    source = engine.get_node_source(node_id, context_padding=context_padding)
    
    if source is None:
        meta = engine.node_metadata.get(node_id)
        if meta is None:
            return f"Node '{node_id}' not found in the graph."
        return f"Source code not available for node '{node_id}'."
    
    meta = engine.node_metadata.get(node_id, {})
    name = meta.get("display_name") or node_id
    kind = meta.get("kind", "Unknown")
    
    output = [
        f"Source code for [{kind}] {name}:",
        f"Node ID: {node_id}",
        "-" * 60,
        source,
        "-" * 60,
    ]
    return "\n".join(output)


@mcp.tool()
def get_graph_stats() -> str:
    """Get statistics about the loaded code graph, including node and edge counts."""
    engine = get_rag()
    graph = engine.graph
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    
    kind_counts: dict[str, int] = {}
    for _, meta in engine.node_metadata.items():
        kind = meta.get("kind", "Unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    
    output = [
        "Graph Statistics:",
        f"  Total Nodes: {node_count:,}",
        f"  Total Edges: {edge_count:,}",
        f"  Embeddings: {'Yes' if engine.embeddings is not None else 'No'}",
        "",
        "Nodes by Kind:",
    ]
    
    for kind, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
        output.append(f"  {kind}: {count:,}")
    
    return "\n".join(output)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    init_rag()
    async with mcp.session_manager.run():
        yield


def create_app():
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
