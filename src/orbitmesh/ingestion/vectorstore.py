"""Shared Chroma client/collection accessors so ingestion and retrieval always agree
on embedding function and collection name.
"""
from __future__ import annotations

import chromadb
from dotenv import load_dotenv
from chromadb.utils import embedding_functions

from .. import config


def get_embedder():
    load_dotenv()
    if config.CI_MODE:
        return embedding_functions.DefaultEmbeddingFunction()
    return embedding_functions.OpenAIEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL,
        api_base=config.EMBEDDING_API_BASE,
        api_key_env_var="OPENROUTER_API_KEY",
    )


def get_client() -> chromadb.ClientAPI:
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(config.CHROMA_DIR))


def get_collection(client: chromadb.ClientAPI | None = None):
    client = client or get_client()
    return client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        embedding_function=get_embedder(),
        metadata={"hnsw:space": "cosine"},
    )
