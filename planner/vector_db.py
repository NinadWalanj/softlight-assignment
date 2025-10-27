# planner/vector_db.py
import faiss
import numpy as np
import os, json
from openai import OpenAI
from tiktoken import get_encoding
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key)

INDEX_DIR = "planner/indexes"
os.makedirs(INDEX_DIR, exist_ok=True)


def embed_texts(texts):
    """Get embeddings for a list of texts using OpenAI embeddings model."""
    response = client.embeddings.create(model="text-embedding-3-large", input=texts)
    return [np.array(d.embedding, dtype=np.float32) for d in response.data]


def build_index(app_name, docs_path):
    """
    Build FAISS index from a local JSON or TXT file containing doc text chunks.
    Each chunk should be small (200–400 tokens).
    """
    with open(docs_path, "r", encoding="utf-8") as f:
        data = json.load(f) if docs_path.endswith(".json") else f.read().split("\n")

    texts = [d["text"] if isinstance(d, dict) else d for d in data]
    embeddings = embed_texts(texts)

    dim = len(embeddings[0])
    index = faiss.IndexFlatL2(dim)
    index.add(np.vstack(embeddings))
    faiss.write_index(index, os.path.join(INDEX_DIR, f"{app_name}.index"))

    with open(
        os.path.join(INDEX_DIR, f"{app_name}_texts.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(texts, f)
    print(f"FAISS index built for {app_name} with {len(texts)} chunks.")


def get_relevant_chunks(app_name, query, top_k=3):
    """Retrieve the top-K relevant doc chunks for a query."""
    index_path = os.path.join(INDEX_DIR, f"{app_name}.index")
    texts_path = os.path.join(INDEX_DIR, f"{app_name}_texts.json")
    if not os.path.exists(index_path) or not os.path.exists(texts_path):
        raise FileNotFoundError(
            f"No index found for {app_name}. Run build_index() first."
        )

    index = faiss.read_index(index_path)
    with open(texts_path, "r", encoding="utf-8") as f:
        texts = json.load(f)

    q_emb = embed_texts([query])[0].reshape(1, -1)
    D, I = index.search(q_emb, top_k)
    return [texts[i] for i in I[0]]
