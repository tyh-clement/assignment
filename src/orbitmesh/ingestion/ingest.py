"""Ingest the OrbitMesh corpus into a persistent Chroma collection.

Idempotent by design: each document's existing chunks are deleted and re-inserted whenever
its content hash changes, so re-running ingestion (e.g. after a corpus update) never
accumulates duplicate or stale chunks. Documents whose hash is unchanged are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Dict, List

from .. import config
from .chunking import chunk_markdown
from .documents import DocumentMeta, load_documents
from .vectorstore import get_client, get_collection


def log(*args: object) -> None:
    print(*args, file=sys.stderr)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def chunk_id(doc_id: str, order: int, section: str, subsection: str | None) -> str:
    slug = slugify(subsection or section)
    return f"{doc_id}::{order:02d}::{slug}"


def load_state(path) -> Dict[str, dict]:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(path, state: Dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def build_chunk_records(doc: DocumentMeta) -> tuple[List[str], List[str], List[dict]]:
    ids: List[str] = []
    texts: List[str] = []
    metadatas: List[dict] = []
    for chunk in chunk_markdown(doc.body):
        cid = chunk_id(doc.doc_id, chunk.order, chunk.section, chunk.subsection)
        ids.append(cid)
        texts.append(chunk.text)
        metadatas.append(
            {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "section": chunk.section,
                "subsection": chunk.subsection or "",
                "product_line": doc.product_line,
                "status": doc.status,
                "version": doc.version,
                "effective_date": doc.effective_date,
                "source_path": str(doc.path.name),
            }
        )
    return ids, texts, metadatas


def ingest(force: bool = False) -> None:
    client = get_client()
    collection = get_collection(client)

    state = load_state(config.INGEST_STATE_PATH)
    docs = load_documents(config.CORPUS_DIR)
    seen_doc_ids = set()

    if collection.count() == 0 and state:
        log("collection is empty; rebuilding all documents")
        force = True

    added_docs = 0
    skipped_docs = 0
    total_chunks = 0

    for doc in docs:
        seen_doc_ids.add(doc.doc_id)
        content_hash = sha256(doc.body)
        previous = state.get(doc.doc_id)
        if (
            not force
            and previous
            and previous.get("hash") == content_hash
            and previous.get("embedding_model") == config.EMBEDDING_MODEL
        ):
            log(f"skip  {doc.doc_id}: unchanged (hash matches last ingest)")
            skipped_docs += 1
            continue

        # Replace-on-write: drop any chunks from a prior version of this document first.
        collection.delete(where={"doc_id": doc.doc_id})

        ids, texts, metadatas = build_chunk_records(doc)
        if ids:
            collection.upsert(ids=ids, documents=texts, metadatas=metadatas)

        state[doc.doc_id] = {
            "hash": content_hash,
            "chunk_ids": ids,
            "version": doc.version,
            "product_line": doc.product_line,
            "status": doc.status,
            "embedding_model": config.EMBEDDING_MODEL,
        }
        added_docs += 1
        total_chunks += len(ids)
        log(
            f"index {doc.doc_id}: {len(ids)} chunk(s) "
            f"(product_line={doc.product_line}, status={doc.status}, version={doc.version})"
        )

    # Clean up documents that were removed from the manifest since the last ingest.
    stale_doc_ids = set(state.keys()) - seen_doc_ids
    for doc_id in stale_doc_ids:
        log(f"remove {doc_id}: no longer present in manifest")
        collection.delete(where={"doc_id": doc_id})
        del state[doc_id]

    save_state(config.INGEST_STATE_PATH, state)

    log(
        f"done: {added_docs} document(s) (re)indexed, {skipped_docs} unchanged, "
        f"{len(stale_doc_ids)} removed, {total_chunks} chunk(s) written, "
        f"collection size={collection.count()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the OrbitMesh corpus into Chroma.")
    parser.add_argument(
        "--force", action="store_true", help="Re-embed every document even if its hash is unchanged."
    )
    args = parser.parse_args()
    ingest(force=args.force)


if __name__ == "__main__":
    main()
