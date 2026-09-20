"""Load the corpus manifest and derive routing metadata (product line, status) from each document's own text.

Classification is pattern-based, not hardcoded per document, so it stays correct if the
corpus is edited or new documents are added with the same conventions (an "Applies to:"
line, and "Archived"/"Superseded" wording for retired material).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

APPLIES_TO_RE = re.compile(r"\*\*Applies to:\*\*\s*(.+)", re.IGNORECASE)
ARCHIVED_RE = re.compile(r"\barchived\b|\bsuperseded\b", re.IGNORECASE)
PRO_RE = re.compile(r"\b(R5 Pro|N5 Pro|Pro Console|Pro Series)\b", re.IGNORECASE)
HOME_RE = re.compile(r"\b(R1|N1)\b")


@dataclass
class DocumentMeta:
    doc_id: str
    title: str
    path: Path
    version: str
    effective_date: str
    product_line: str  # "home", "pro", or "all"
    status: str  # "current" or "archived"
    applies_to: str
    body: str


def load_manifest(corpus_dir: Path) -> List[dict]:
    with open(corpus_dir / "manifest.json", encoding="utf-8") as f:
        return json.load(f)["documents"]


def extract_applies_to(body: str) -> str:
    match = APPLIES_TO_RE.search(body)
    return match.group(1).strip() if match else ""


def classify_product_line(applies_to_text: str, body: str) -> str:
    if applies_to_text:
        # An "Applies to" line may add a "Do not apply this document to <other line>"
        # exclusion clause; only the leading positive clause states what the doc covers.
        haystack = re.split(r"\.\s+Do not apply", applies_to_text, maxsplit=1, flags=re.IGNORECASE)[0]
    else:
        haystack = body[:2000]
    has_pro = bool(PRO_RE.search(haystack))
    has_home = bool(HOME_RE.search(haystack))
    if has_pro and not has_home:
        return "pro"
    if has_home and not has_pro:
        return "home"
    return "all"


def classify_status(body: str) -> str:
    # Only inspect the preamble (before the first "## " section) so that a later section
    # discussing history (e.g. a withdrawn workaround) doesn't mislabel a current document.
    preamble = body.split("\n## ", 1)[0]
    return "archived" if ARCHIVED_RE.search(preamble) else "current"


def build_document_meta(entry: dict, corpus_dir: Path) -> DocumentMeta:
    path = corpus_dir / entry["path"]
    body = path.read_text(encoding="utf-8")
    applies_to = extract_applies_to(body)
    return DocumentMeta(
        doc_id=entry["id"],
        title=entry["title"],
        path=path,
        version=str(entry.get("version", "")),
        effective_date=str(entry.get("effective_date", "")),
        product_line=classify_product_line(applies_to, body),
        status=classify_status(body),
        applies_to=applies_to,
        body=body,
    )


def load_documents(corpus_dir: Path) -> List[DocumentMeta]:
    return [build_document_meta(entry, corpus_dir) for entry in load_manifest(corpus_dir)]
