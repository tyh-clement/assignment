"""Central paths and settings, overridable via environment variables."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CORPUS_DIR = Path(os.environ.get("CORPUS_DIR", REPO_ROOT / "corpus"))
DATA_DIR = Path(os.environ.get("ORBITMESH_DATA_DIR", REPO_ROOT / "data"))
CHROMA_DIR = Path(os.environ.get("CHROMA_DIR", DATA_DIR / "chroma"))
COLLECTION_NAME = os.environ.get("CHROMA_COLLECTION", "orbitmesh_corpus_openrouter")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_API_BASE = os.environ.get("EMBEDDING_API_BASE", "https://openrouter.ai/api/v1")
CI_MODE = os.environ.get("ORBITMESH_CI_MODE", "0") == "1"
INGEST_STATE_PATH = Path(
    os.environ.get("INGEST_STATE_PATH", DATA_DIR / "ingest_state.json")
)
