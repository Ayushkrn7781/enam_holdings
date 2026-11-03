"""PDF ingestion: text blocks -> paragraphs -> section/speaker-aware chunks that never cross a boundary."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import Chunk, Document

MAX_CHARS = 1100
MIN_CHARS = 40
WATERMARK = "ILLUSTRATIVE DEMO DOCUMENT - NOT A REAL COMPANY FILING - FIGURES ARE SYNTHETIC"

KNOWN_SECTIONS = re.compile(
    r"^(management discussion and analysis|md&a|management'?s discussion|directors'? report|board'?s report|"
    r"independent auditor'?s report|auditor'?s report|notes to (the )?(consolidated |standalone )?financial statements|"
    r"contingent liabilities|related party (transactions|disclosures)|key (financial )?ratios|risks?( and concerns)?|"
    r"outlook|segment (information|reporting)|business overview|financial performance|q\s*&\s*a session|"
    r"question[- ]and[- ]answer session|opening remarks|report on corporate governance|corporate governance)\b", re.I)
SPEAKER = re.compile(r"^([A-Z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+){0,4}):\s+(.*)$", re.S)
_FURNITURE = re.compile(r"^(page\s+\d+(\s+of\s+\d+)?|\d+\s*/\s*\d+|\d{1,3})$", re.I)
_NUMTOK = re.compile(r"^[\(\-]?[\d,]+(\.\d+)?%?\)?$")


def _is_heading(par: str) -> bool:
    if "\n" in par.strip():
        return False
    line = par.strip()
    if not line or len(line) > 90:
        return False
    if KNOWN_SECTIONS.match(line):
        return True
    if line[-1] in ".,;:!?":
        return False
    words = line.split()
    if not 1 <= len(words) <= 9:
        return False
    if re.search(r"\d{3,}", line):
        return False
    titled = all(w[0].isupper() or w.lower() in {"and", "of", "the", "to", "in", "for", "on", "&", "vs"} for w in words
                 if w[0].isalpha())
    return line.isupper() or titled


def _numeric_share(text: str) -> float:
    toks = text.split()
    if not toks:
        return 0.0
    return sum(1 for t in toks if _NUMTOK.match(t)) / len(toks)


def _split_long(par: str, limit: int = MAX_CHARS) -> list[str]:
    from .retrieval import split_sentences
    if len(par) <= limit:
        return [par]
    out, cur = [], ""
    for s in split_sentences(par):
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def read_pages(path: str | Path) -> list[str]:
    import pymupdf
    doc = pymupdf.open(str(path))
    pages = []
    for p in doc:
        blocks = [b[4].strip() for b in p.get_text("blocks") if b[6] == 0 and b[4].strip()]
        pages.append("\n\n".join(blocks))
    doc.close()
    return pages


def paragraphs(pages: list[str]) -> list[tuple[int, list[str]]]:
    """Per page: blank-line paragraphs with running headers and furniture removed."""
    line_pages: Counter = Counter()
    for txt in pages:
        for ln in {ln.strip() for ln in txt.splitlines() if ln.strip()}:
            if len(ln) <= 120:
                line_pages[ln] += 1
    running = {ln for ln, c in line_pages.items() if len(pages) >= 3 and c >= 0.6 * len(pages)}
    out = []
    for i, txt in enumerate(pages):
        pars = []
        for raw in re.split(r"\n\s*\n", txt):
            lines = [ln.strip() for ln in raw.splitlines()
                     if ln.strip() and ln.strip() not in running and WATERMARK not in ln and not _FURNITURE.match(ln.strip())]
            if lines:
                pars.append("\n".join(lines))
        out.append((i + 1, pars))
    return out


def chunk_pages(pages: list[str], transcript: bool = False) -> list[dict]:
    chunks: list[dict] = []
    section: Optional[str] = None
    speaker: Optional[str] = None
    for page_no, pars in paragraphs(pages):
        buf: list[str] = []
        buf_kind = "text"

        def flush():
            nonlocal buf
            text = " ".join(" ".join(b.split()) for b in buf).strip()
            if len(text) >= MIN_CHARS:
                chunks.append({"page": page_no, "section": section, "speaker": speaker, "text": text,
                               "kind": buf_kind})
            buf = []

        for par in pars:
            if _is_heading(par):
                flush()
                section = par.strip()
                continue
            if transcript:
                m = SPEAKER.match(par.strip())
                if m and len(m.group(1).split()) <= 5 and " - " not in m.group(1) and "–" not in m.group(1):
                    flush()
                    speaker = m.group(1).strip()
                    par = m.group(2)
            kind = "table" if _numeric_share(par) > 0.35 else "text"
            for piece in _split_long(" ".join(par.split())):
                if buf and (kind != buf_kind or len(" ".join(buf)) + len(piece) + 1 > MAX_CHARS):
                    flush()
                buf_kind = kind
                buf.append(piece)
        flush()
    return chunks


def ingest_document(s: Session, doc: Document) -> int:
    from . import retrieval
    try:
        pages = read_pages(doc.local_path)
    except Exception as e:
        doc.status, doc.error = "failed", f"could not read PDF: {e}"
        return 0
    s.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    chunks = chunk_pages(pages, transcript=doc.doc_type == "transcript")
    for c in chunks:
        s.add(Chunk(document_id=doc.id, ticker=doc.ticker, **c))
    doc.pages = len(pages)
    doc.status = "indexed" if chunks else "failed"
    doc.error = None if chunks else "no text extracted (scanned PDF?)"
    s.flush()
    retrieval.invalidate(doc.ticker)
    return len(chunks)
