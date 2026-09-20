"""Split a markdown document into retrievable chunks aligned with its own section headings.

Each chunk carries its section (and subsection) heading text inline, so the embedded text
is self-describing even before any metadata filtering runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")


@dataclass
class Chunk:
    section: str
    subsection: Optional[str]
    text: str
    order: int


def chunk_markdown(body: str) -> List[Chunk]:
    lines = body.splitlines()
    chunks: List[Chunk] = []

    title = ""
    current_h2 = ""
    current_h2_lines: List[str] = []
    current_h3: Optional[str] = None
    current_h3_lines: List[str] = []
    preamble_lines: List[str] = []
    started_sections = False

    def flush_h3() -> None:
        nonlocal current_h3, current_h3_lines
        text = "\n".join(current_h3_lines).strip()
        if current_h3 and text:
            chunks.append(
                Chunk(
                    section=current_h2,
                    subsection=current_h3,
                    text=f"## {current_h2}\n### {current_h3}\n\n{text}",
                    order=0,
                )
            )
        current_h3 = None
        current_h3_lines = []

    def flush_h2_intro() -> None:
        # Text directly under an "##" heading, before its first "###" subsection (if any).
        # Flushed as soon as we know it's complete, so it appears before its subsections.
        nonlocal current_h2_lines
        text = "\n".join(current_h2_lines).strip()
        if current_h2 and text:
            chunks.append(
                Chunk(section=current_h2, subsection=None, text=f"## {current_h2}\n\n{text}", order=0)
            )
        current_h2_lines = []

    def flush_h2() -> None:
        nonlocal current_h2, current_h2_lines
        if current_h3 is None:
            flush_h2_intro()
        else:
            flush_h3()
        current_h2_lines = []

    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading = match.group(2).strip()
            if level == 1:
                title = heading
                continue
            if level == 2:
                flush_h2()
                current_h2 = heading
                started_sections = True
                continue
            if level == 3:
                if current_h3 is None:
                    flush_h2_intro()
                else:
                    flush_h3()
                current_h3 = heading
                continue
        elif not started_sections:
            preamble_lines.append(line)
        elif current_h3 is not None:
            current_h3_lines.append(line)
        else:
            current_h2_lines.append(line)
    flush_h2()

    overview_text = "\n".join(preamble_lines).strip()
    meaningful = [
        ln for ln in overview_text.splitlines() if ln.strip() and not ln.strip().startswith("**")
    ]
    if meaningful:
        chunks.insert(
            0,
            Chunk(section="Overview", subsection=None, text=f"# {title}\n\n{overview_text}", order=0),
        )

    for idx, chunk in enumerate(chunks):
        chunk.order = idx
    return chunks
