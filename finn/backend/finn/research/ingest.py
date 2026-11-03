"""Primary-document ingestion: PDF -> pages -> sections -> structure-aware chunks with provenance.

Chunks never cross a page boundary (so every citation has an exact page) and never cross a speaker turn in
transcripts (so "who said it" is preserved). Number-dense blocks are kept whole and tagged `table`.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Chunk, Document

log = logging.getLogger("finn.ingest")

SECTION_HINTS = re.compile(
    r"^(management discussion and analysis|management'?s? discussion|directors'? report|board'?s? report|"
    r"report on corporate governance|independent auditor'?s? report|notes to (the )?(standalone |consolidated )?financial statements|"
    r"contingent liabilit\w*|related party (transactions|disclosures)|key (financial )?ratios|risk(s| management)|outlook|"
    r"opportunities and threats|segment(-wise)? (performance|information)|business overview|financial performance|"
    r"question[- ]and[- ]answer session|opening remarks)\b",
    re.I,
)
SPEAKER = re.compile(r"^\s*([A-Z][A-Za-z.'\- ]{2,40}?)\s*:\s+(?=\S)")
MAX_CHARS = 1100
# Watermarks / page furniture that should never become retrievable evidence.
FURNITURE = re.compile(r"^(ILLUSTRATIVE DEMO DOCUMENT\b.*|page \d+ (of \d+)?|\d+\s*\|\s*page|this is a computer[- ]generated.*)$", re.I)


def read_pdf(path: str | Path) -> list[str]:
    import fitz  # PyMuPDF

    # Text blocks preserve paragraph boundaries far better than raw line dumps.
    with fitz.open(path) as doc:
        return ["\n\n".join(b[4].strip() for b in p.get_text("blocks") if b[6] == 0) for p in doc]


def _is_table(block: str) -> bool:
    toks = block.split()
    if len(toks) < 12:
        return False
    nums = sum(bool(re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?%?", t)) for t in toks)
    return nums / len(toks) > 0.35


def _running_headers(pages: list[str]) -> set[str]:
    """Short lines repeated on most pages (headers/footers/watermarks) — dropped before chunking."""
    if len(pages) < 3:
        return set()
    from collections import Counter

    cnt = Counter(ln.strip() for p in pages for ln in set(p.splitlines()) if 0 < len(ln.strip()) < 150)
    return {ln for ln, n in cnt.items() if n >= max(2, 0.6 * len(pages))}


def _is_heading(para: str) -> bool:
    """A heading is a whole paragraph: one short line, either a known section name or Title/UPPER case without a full stop."""
    if "\n" in para.strip() or len(para) > 90:
        return False
    t = para.strip()
    if SECTION_HINTS.match(t) and not t.endswith("."):
        return True
    words = t.split()
    return 1 <= len(words) <= 9 and not t.endswith((".", ":", ",")) and not re.search(r"\d{3,}", t) and (
        t.isupper() or sum(w[:1].isupper() for w in words) >= max(1, len(words) - 2))


def chunk_pages(pages: list[str], doc_type: str) -> list[dict]:
    out: list[dict] = []
    section = None
    noise = _running_headers(pages)
    speaker = None
    for pno, raw in enumerate(pages, start=1):
        text = raw.replace("\u00a0", " ")
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() not in noise and not FURNITURE.match(ln.strip())]
        # 1) paragraphs = blank-line separated groups of lines
        groups, buf = [], []
        for ln in lines:
            if ln.strip():
                buf.append(ln.strip())
            elif buf:
                groups.append("\n".join(buf))
                buf = []
        if buf:
            groups.append("\n".join(buf))
        # 2) headings set the section; transcripts split further on speaker turns
        paras: list[tuple[str | None, str, str | None]] = []
        for g in groups:
            if _is_heading(g):
                section = g.strip().title()[:200]
                continue
            if doc_type == "transcript":
                turn: list[str] = []
                for ln in g.split("\n"):
                    m = SPEAKER.match(ln)
                    if m and len(m.group(1).split()) <= 5:
                        if turn:
                            paras.append((speaker, " ".join(turn), section))
                            turn = []
                        speaker = m.group(1).strip()
                        ln = ln[m.end():]
                    turn.append(ln)
                if turn:
                    paras.append((speaker, " ".join(turn), section))
            else:
                paras.append((None, " ".join(g.split("\n")), section))

        # 3) merge small paragraphs up to MAX_CHARS (same speaker, same page); keep number-dense blocks whole
        cur, cur_sp, cur_sec = "", None, None

        def emit(kind="text", txt=None, sp=None, sec=None):
            out.append({"page": pno, "section": sec, "speaker": sp, "kind": kind, "text": txt})

        for sp, p, sec in paras:
            p = p.strip()
            if not p:
                continue
            if _is_table(p):
                if cur:
                    emit(txt=cur, sp=cur_sp, sec=cur_sec)
                    cur = ""
                emit("table", p[:3000], sp, sec)
                continue
            if cur and (sp != cur_sp or sec != cur_sec or len(cur) + len(p) > MAX_CHARS):
                emit(txt=cur, sp=cur_sp, sec=cur_sec)
                cur = ""
            cur_sp, cur_sec = sp, sec
            if len(p) > MAX_CHARS * 1.6:  # split long paragraphs on sentence boundaries
                for snt in re.split(r"(?<=[.!?])\s+", p):
                    if len(cur) + len(snt) > MAX_CHARS and cur:
                        emit(txt=cur, sp=sp, sec=sec)
                        cur = ""
                    cur = f"{cur} {snt}".strip()
                continue
            cur = f"{cur} {p}".strip() if cur else p
        if cur:
            emit(txt=cur, sp=cur_sp, sec=cur_sec)
    return [c for c in out if len(c["text"]) > 40]


def index_document(s: Session, doc: Document, pages: list[str]) -> int:
    doc.chunks.clear()
    s.flush()
    chunks = chunk_pages(pages, doc.doc_type)
    for c in chunks:
        doc.chunks.append(Chunk(ticker=doc.ticker, **c))
    doc.pages = len(pages)
    doc.status = "indexed"
    s.flush()
    from .retrieval import invalidate

    invalidate(doc.ticker)
    return len(chunks)


def index_pdf(s: Session, doc: Document) -> int:
    try:
        pages = read_pdf(doc.local_path)
        if sum(len(p) for p in pages) < 200:
            doc.status, doc.error = "failed", "no extractable text (scanned PDF?)"
            return 0
        return index_document(s, doc, pages)
    except Exception as e:
        log.exception("index failed for %s", doc.url)
        doc.status, doc.error = "failed", str(e)[:500]
        return 0
