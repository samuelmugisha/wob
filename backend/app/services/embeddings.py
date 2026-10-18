"""Embedding providers (spec §3: configurable, with recorded model ID and dimensionality)."""

import hashlib
import math
import re
from typing import Protocol

import httpx

from app.config import Settings


class Embedder(Protocol):
    model_id: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """ONNX model run in-process via fastembed; evidence never leaves the server.

    nomic-embed-text-v1.5 accepts 8192-token inputs, so 900-token chunks are embedded whole,
    and expects task prefixes on every input.
    """

    PREFIXES = {
        "nomic-ai/nomic-embed-text-v1.5": ("search_document: ", "search_query: "),
        "nomic-ai/nomic-embed-text-v1": ("search_document: ", "search_query: "),
    }

    def __init__(self, model: str, dimensions: int, cache_dir: str | None) -> None:
        from fastembed import TextEmbedding

        self.model_id = f"fastembed:{model}"
        self.dimensions = dimensions
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self._doc_prefix, self._query_prefix = self.PREFIXES.get(model, ("", ""))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [v.tolist() for v in self._model.embed(texts, batch_size=16)]
        if vectors and len(vectors[0]) != self.dimensions:
            raise ValueError(
                f"{self.model_id} returns {len(vectors[0])} dimensions; "
                f"EMBEDDING_DIM is {self.dimensions}"
            )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._query_prefix + text])[0]


class VoyageEmbedder:
    """Voyage AI hosted embeddings. Sends evidence text to a third party: check the data
    protection position (spec §12) before enabling."""

    URL = "https://api.voyageai.com/v1/embeddings"
    BATCH = 64

    def __init__(
        self, model: str, dimensions: int, api_key: str, client: httpx.Client | None = None
    ) -> None:
        self.model_id = f"voyage:{model}"
        self.dimensions = dimensions
        self._model = model
        self._client = client or httpx.Client(timeout=60)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            response = self._client.post(
                self.URL,
                headers=self._headers,
                json={
                    "input": texts[start : start + self.BATCH],
                    "model": self._model,
                    "input_type": input_type,
                    "output_dimension": self.dimensions,
                },
            )
            response.raise_for_status()
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in data)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


class HashingEmbedder:
    """Deterministic bag-of-words hashing. For tests and offline development only: it has no
    semantic understanding and must never be used to assess real finalists."""

    def __init__(self, dimensions: int) -> None:
        self.model_id = "fake:hashing"
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def get_embedder(settings: Settings) -> Embedder:
    provider = settings.embedding_provider
    if provider == "local":
        return LocalEmbedder(
            settings.embedding_model,
            settings.embedding_dim,
            str(settings.model_cache_dir) if settings.model_cache_dir else None,
        )
    if provider == "voyage":
        if settings.voyage_api_key is None:
            raise ValueError("VOYAGE_API_KEY is required for EMBEDDING_PROVIDER=voyage")
        return VoyageEmbedder(
            settings.embedding_model,
            settings.embedding_dim,
            settings.voyage_api_key.get_secret_value(),
        )
    if provider == "fake":
        if settings.environment == "production":
            raise ValueError("the fake embedding provider is not allowed in production")
        return HashingEmbedder(settings.embedding_dim)
    raise ValueError(f"unknown embedding provider {provider!r}")
