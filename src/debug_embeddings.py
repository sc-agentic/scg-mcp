from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password")


def check_embeddings():
    print("=== Checking Database State ===")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        driver.verify_connectivity()
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    with driver.session() as session:
        # Check Total Nodes
        result = session.run("MATCH (n:CodeNode) RETURN count(n) as count")
        total = result.single()["count"]
        print(f"Total Nodes: {total}")

        # Check Nodes with Embeddings
        result = session.run(
            "MATCH (n:CodeNode) WHERE n.embedding IS NOT NULL RETURN count(n) as count"
        )
        with_emb = result.single()["count"]
        print(f"Nodes with Embeddings: {with_emb}")

        if with_emb > 0:
            # Check embedding dimension
            result = session.run(
                "MATCH (n:CodeNode) WHERE n.embedding IS NOT NULL RETURN size(n.embedding) as dim LIMIT 1"
            )
            dim = result.single()["dim"]
            print(f"Embedding Dimension: {dim}")

    driver.close()


if __name__ == "__main__":
    check_embeddings()
