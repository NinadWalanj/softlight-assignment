from planner.vector_db import get_relevant_chunks

query = "how to create a page in notion"
chunks = get_relevant_chunks("notion", query, top_k=3)

print("\nQuery:", query)
print("\nRetrieved Context:")
for i, c in enumerate(chunks, start=1):
    print(f"\n--- Chunk {i} ---\n{c}\n")
