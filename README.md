# Semantic Graph RAG

## Project Selection

All commands below accept a `--project <name>` flag to choose which codebase to analyze.  
Available projects are defined in [`src/config.py`](src/config.py).

| Project        | Data dir             | Code dir              |
| -------------- | -------------------- | --------------------- |
| `glide`        | `data/glide`         | `code/glide-4.5.0`    |
| `private_repo` | `data/private_repo`  | `code/private_repo`   |

The default project is **`private_repo`**. You can override it in three ways:

```bash
# 1. CLI flag (highest priority)
uv run python -m src.bootstrap --project glide

# 2. Environment variable
export SCG_PROJECT=glide
uv run python -m src.bootstrap

# 3. Change DEFAULT_PROJECT in src/config.py
```

### Adding a new project

1. Place semantic-graph data in `data/<name>/`
2. Place the source code in `code/<name>/`
3. Add an entry to the `PROJECTS` dict in `src/config.py`

## Quick start

```bash
docker-compose up -d                                # Start Neo4j
uv run python -m src.bootstrap --project glide      # Build embeddings & upload to Neo4j

npx @modelcontextprotocol/inspector uv run python -m src.mcp_server --project glide  # Start MCP Inspector
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