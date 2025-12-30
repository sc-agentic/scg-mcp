docker-compose up -d 

# Queries
MATCH (n:CodeNode)-[r:CALL|TYPE]->(m:CodeNode)
WHERE n.id CONTAINS "DiskCache"
RETURN n, r, m LIMIT 50

# Explicit nodes
MATCH (n:CodeNode) WHERE n.kind IS NOT NULL RETURN n LIMIT 5

# Implicit nodes
MATCH (n:Node) WHERE n.kind IS NULL RETURN n LIMIT 5