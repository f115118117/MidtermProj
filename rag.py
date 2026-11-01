"""RAG for the library rules.

1. Cut every Markdown file in library_rules/ into sections (one section per "## " heading).
2. Turn every section into a vector with the embedding model, and keep the vectors in a cache file,
   so we only pay for embeddings once (the cache is rebuilt if a rule text changes).
3. For a question, embed the question and return the sections with the highest cosine similarity.
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np
from openai import OpenAI

BASE_DIR = Path(__file__).parent
RULES_DIR = BASE_DIR / "library_rules"
CACHE_PATH = BASE_DIR / ".cache" / "embeddings.json"


def load_chunks():
    """Return a list of {"source", "section", "text"} dicts, one per ## section."""
    chunks = []
    for path in sorted(RULES_DIR.glob("*.md")):
        doc_title, section, lines = path.stem, None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                if section and lines:
                    chunks.append(_make_chunk(path.name, doc_title, section, lines))
                section, lines = line[3:].strip(), []
            elif section and line.strip():
                lines.append(line.strip())
        if section and lines:
            chunks.append(_make_chunk(path.name, doc_title, section, lines))
    return chunks


def _make_chunk(file_name, doc_title, section, lines):
    # Put the document title and section name into the text: it helps the search a lot.
    text = f"{doc_title} > {section}\n" + "\n".join(lines)
    return {"source": file_name, "section": section, "text": text}


class RuleSearcher:
    def __init__(self, client=None, model=None, embed_fn=None):
        """embed_fn(list_of_texts) -> list of vectors. If not given, the embedding API is used."""
        if embed_fn is None:
            self.client = client or OpenAI(
                base_url=os.getenv("EMBEDDING_API_URL"),
                api_key=os.getenv("EMBEDDING_API_KEY") or "none",
            )
            self.model = model or os.getenv("EMBEDDING_MODEL_NAME")
            embed_fn = self._embed_api
        else:
            self.model = "custom"
        self.embed = embed_fn
        self.chunks = load_chunks()
        self.matrix = self._build_matrix()

    def _embed_api(self, texts):
        vectors = []
        for i in range(0, len(texts), 16):  # small batches work on every server
            resp = self.client.embeddings.create(model=self.model, input=texts[i:i + 16])
            vectors.extend(d.embedding for d in resp.data)
        return vectors

    def _build_matrix(self):
        cache = {}
        if CACHE_PATH.exists():
            try:
                cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cache = {}
        keys = [hashlib.sha256(f"{self.model}|{c['text']}".encode()).hexdigest() for c in self.chunks]
        missing = [i for i, k in enumerate(keys) if k not in cache]
        if missing:
            new_vectors = self.embed([self.chunks[i]["text"] for i in missing])
            for i, v in zip(missing, new_vectors):
                cache[keys[i]] = list(map(float, v))
            CACHE_PATH.parent.mkdir(exist_ok=True)
            CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
        m = np.array([cache[k] for k in keys], dtype=np.float32)
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def search(self, query, top_k=3):
        q = np.array(self.embed([query])[0], dtype=np.float32)
        q = q / np.linalg.norm(q)
        scores = self.matrix @ q
        best = np.argsort(-scores)[:top_k]
        return [{**self.chunks[i], "score": round(float(scores[i]), 3)} for i in best]


if __name__ == "__main__":
    for c in load_chunks():
        print(f"{c['source']:24} | {c['section']}")
