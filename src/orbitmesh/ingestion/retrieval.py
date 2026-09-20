"""Evidence retrieval: filter-then-rank against the vector store's own metadata.

Filtering by product line and document status happens before ranking, so an
embedding-similar chunk from the wrong product line or a superseded document
cannot outrank the correct one (see design note: "generic similarity" failure mode).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .vectorstore import get_collection


@dataclass
class Evidence:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    subsection: str
    text: str
    product_line: str
    status: str
    version: str
    distance: float

    @property
    def locator(self) -> str:
        return self.subsection or self.section


def _build_where(product_line: Optional[str], include_archived: bool) -> Optional[dict]:
    clauses: List[dict] = []
    if product_line and product_line != "unknown":
        clauses.append({"product_line": {"$in": [product_line, "all"]}})
    if not include_archived:
        clauses.append({"status": "current"})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def retrieve(
    query: str,
    product_line: Optional[str] = None,
    include_archived: bool = False,
    k: int = 5,
) -> List[Evidence]:
    """Query the corpus collection, filtered by product line and archival status.

    Falls back to an unfiltered query if the filtered query returns nothing, so a
    misclassified or unanticipated product line doesn't leave the customer with no
    evidence at all (the caller/LLM is still responsible for flagging low-confidence
    results rather than presenting a wrong-product chunk as if it matched).
    """
    collection = get_collection()
    where = _build_where(product_line, include_archived)
    result = collection.query(query_texts=[query], n_results=k, where=where)
    evidence = _to_evidence(result)
    if not evidence and where is not None:
        result = collection.query(query_texts=[query], n_results=k)
        evidence = _to_evidence(result)
    return evidence


def _to_evidence(result: dict) -> List[Evidence]:
    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    out = []
    for cid, text, meta, dist in zip(ids, docs, metas, dists):
        out.append(
            Evidence(
                chunk_id=cid,
                doc_id=meta.get("doc_id", ""),
                title=meta.get("title", ""),
                section=meta.get("section", ""),
                subsection=meta.get("subsection", ""),
                text=text,
                product_line=meta.get("product_line", ""),
                status=meta.get("status", ""),
                version=meta.get("version", ""),
                distance=dist,
            )
        )
    return out
