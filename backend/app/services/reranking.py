"""Cross-encoder reranking of fused retrieval candidates by relevance to the query."""

import re
from typing import Protocol

import httpx

from app.config import Settings


class Reranker(Protocol):
    model_id: str

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """Relevance score per text, in input order. Higher is more relevant."""
        ...


class LocalReranker:
    """ONNX cross-encoder via fastembed, run in-process. The default jina-reranker-v1-turbo-en
    reads 8K tokens, so 900-token chunks are scored whole."""

    def __init__(self, model: str, cache_dir: str | None) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model_id = f"fastembed:{model}"
        self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        # Small batches: long passages make cross-encoder activations memory-hungry.
        return [float(score) for score in self._model.rerank(query, texts, batch_size=2)]


class VoyageReranker:
    """Voyage AI hosted reranking. Sends evidence text to a third party (see spec §12)."""

    URL = "https://api.voyageai.com/v1/rerank"

    def __init__(self, model: str, api_key: str, client: httpx.Client | None = None) -> None:
        self.model_id = f"voyage:{model}"
        self._model = model
        self._client = client or httpx.Client(timeout=60)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        response = self._client.post(
            self.URL,
            headers=self._headers,
            json={"query": query, "documents": texts, "model": self._model},
        )
        response.raise_for_status()
        scores = [0.0] * len(texts)
        for item in response.json()["data"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores


class OverlapReranker:
    """Fraction of query words present in the text. For tests only."""

    model_id = "fake:overlap"

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        words = set(re.findall(r"\w{3,}", query.lower()))
        return [
            len(words & set(re.findall(r"\w{3,}", text.lower()))) / (len(words) or 1)
            for text in texts
        ]


def get_reranker(settings: Settings) -> Reranker | None:
    provider = settings.reranker_provider
    if provider == "none":
        return None
    if provider == "local":
        cache = str(settings.model_cache_dir) if settings.model_cache_dir else None
        return LocalReranker(settings.reranker_model, cache)
    if provider == "voyage":
        if settings.voyage_api_key is None:
            raise ValueError("VOYAGE_API_KEY is required for RERANKER_PROVIDER=voyage")
        return VoyageReranker(settings.reranker_model, settings.voyage_api_key.get_secret_value())
    if provider == "fake":
        if settings.environment == "production":
            raise ValueError("the fake reranker is not allowed in production")
        return OverlapReranker()
    raise ValueError(f"unknown reranker provider {provider!r}")
