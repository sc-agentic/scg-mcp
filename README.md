# Semantic Graph RAG

### Adding a new project

1. Place semantic-graph data in `data/<name>/`
2. Place the source code in `code/<name>/`
3. Add an entry to the `PROJECTS` dict in `src/config.py`

## Quick start

Generate SCG (windows)
```bash
.\scg-cli\bin\scg-cli.bat generate -p .\code\glide-5.0.5 -o .\data\glide\glide_cg.semanticgraphdb
```

Upload to Neo4j
```bash
docker-compose up -d

uv run python -m src.upload_to_neo4j --project glide -g CG
```

Run MCP server
```bash
uv run python -m src.mcp_server --project glide 

npx @modelcontextprotocol/inspector uv run python -m src.mcp_server --project glide
```

## Queries

```sql
MATCH (n:CodeNode)-[r:CALL|TYPE]->(m:CodeNode)
WHERE n.id CONTAINS "DiskCache"
RETURN n, r, m LIMIT 50
```

#### Explicit nodes

```sql
MATCH (n:CodeNode) WHERE n.kind IS NOT NULL RETURN n LIMIT 5
```

#### Implicit nodes

```sql
MATCH (n:Node) WHERE n.kind IS NULL RETURN n LIMIT 5
```

#### Count nodes

```sql
MATCH (n) RETURN count(n)
```

#### Show nodes and direct relationships

```sql
MATCH (n)
WITH n LIMIT 200
MATCH (n)-[r]-(m)
RETURN n, r, m
```

## MCP Inspector
```bash
npx @modelcontextprotocol/inspector uv run python -m src.mcp_server --project glide
```