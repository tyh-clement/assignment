#!/usr/bin/env python3
"""Run paid-API-free ingestion and retrieval checks in CI mode."""
from __future__ import annotations

import os

os.environ.setdefault("ORBITMESH_CI_MODE", "1")

from orbitmesh import config
from orbitmesh.ingestion.ingest import ingest
from orbitmesh.ingestion.retrieval import retrieve
from orbitmesh.ingestion.vectorstore import get_collection


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"CI check failed: {message}")


def main() -> None:
    ingest(force=True)
    collection = get_collection()
    initial_count = collection.count()
    require(initial_count > 0, "ingestion produced no chunks")

    pro_results = retrieve("N5 Pro node flashing amber", product_line="pro", k=3)
    require(pro_results, "Pro retrieval returned no results")
    require(pro_results[0].doc_id == "pro-led-reference", "Pro retrieval selected the wrong document")
    require(
        all(result.product_line in {"pro", "all"} for result in pro_results),
        "Pro retrieval returned a home-only document",
    )

    home_results = retrieve("N1 node flashing amber", product_line="home", k=3)
    require(home_results, "home retrieval returned no results")
    require(
        all(result.product_line in {"home", "all"} for result in home_results),
        "home retrieval returned a Pro-only document",
    )

    current_results = retrieve("band steering roaming workaround", k=5)
    require(
        all(result.status == "current" for result in current_results),
        "archived evidence was returned by default",
    )

    ingest(force=False)
    require(collection.count() == initial_count, "re-ingestion accumulated duplicate chunks")

    print(f"CI retrieval checks passed: {initial_count} chunks, filtered retrieval, idempotency")


if __name__ == "__main__":
    main()
