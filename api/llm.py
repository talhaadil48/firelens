"""The single gateway for model calls (CLAUDE.md rule 6), so the provider can be swapped.

Providers (FIRELENS_LLM_PROVIDER):
    mock    offline, deterministic; used by tests and CI (never calls a network)
    azure   Azure OpenAI; API key if AZURE_OPENAI_API_KEY is set, else managed identity
    openai  any OpenAI-compatible endpoint (OPENAI_BASE_URL, OPENAI_API_KEY)
Secrets only come from environment variables.
"""

import hashlib
import math
import os
from collections.abc import Iterator
from functools import lru_cache
from typing import Protocol

EMBED_DIM = 1536  # text-embedding-3-small


class LLM(Protocol):
    name: str

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str: ...

    def stream(self, messages: list[dict]) -> Iterator[str]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockLLM:
    """Offline stand-in. Embeddings are stable hashes, so retrieval tests are reproducible."""

    name = "mock"

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        return "{}" if json_mode else "Mock model: no language model was called."

    def stream(self, messages: list[dict]) -> Iterator[str]:
        yield self.chat(messages)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBED_DIM
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                vector[int.from_bytes(digest[:4], "big") % EMBED_DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors


class OpenAICompatible:
    """Azure OpenAI or any OpenAI-compatible API through the official `openai` SDK."""

    def __init__(self, client, chat_model: str, embed_model: str, name: str):
        self.client, self.chat_model, self.embed_model, self.name = (
            client,
            chat_model,
            embed_model,
            name,
        )

    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = self.client.chat.completions.create(
            model=self.chat_model, messages=messages, temperature=0, **kwargs
        )
        return response.choices[0].message.content or ""

    def stream(self, messages: list[dict]) -> Iterator[str]:
        response = self.client.chat.completions.create(
            model=self.chat_model, messages=messages, temperature=0, stream=True
        )
        for event in response:
            if event.choices and event.choices[0].delta.content:
                yield event.choices[0].delta.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = texts[start : start + 64]
            response = self.client.embeddings.create(model=self.embed_model, input=batch)
            vectors.extend(item.embedding for item in response.data)
        return vectors


def _azure() -> OpenAICompatible:
    from openai import AzureOpenAI

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    if key:
        client = AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=version)
    else:  # managed identity on Azure Container Apps; az login locally
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        client = AzureOpenAI(
            azure_endpoint=endpoint, azure_ad_token_provider=token, api_version=version
        )
    return OpenAICompatible(
        client,
        os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"],
        os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        "azure",
    )


def _openai() -> OpenAICompatible:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ.get("OPENAI_BASE_URL") or None
    )
    return OpenAICompatible(
        client,
        os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        "openai",
    )


@lru_cache(maxsize=1)
def get_llm() -> LLM:
    provider = os.environ.get("FIRELENS_LLM_PROVIDER", "mock").lower()
    if provider == "azure":
        return _azure()
    if provider == "openai":
        return _openai()
    if provider == "mock":
        return MockLLM()
    raise ValueError(f"Unknown FIRELENS_LLM_PROVIDER: {provider}")
