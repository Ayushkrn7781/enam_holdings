"""Hybrid retrieval: BM25 (always) + optional dense (fastembed), fused with Reciprocal Rank Fusion."""
from __future__ import annotations

import re
import threading
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Chunk, Document

STOP = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is it its
of on or our over so such that the their them then there these they this to was we were what when where which who why
will with would you your about any also than more most much very just per vs""".split())

EXPANSIONS = {
    "revenue": ["sales", "turnover", "topline", "income from operations"],
    "debt": ["borrowings", "leverage", "loans", "debentures"],
    "margin": ["ebitda", "operating profit", "opm"],
    "guidance": ["outlook", "expect", "target", "guide", "aim"],
    "cash": ["cash flow", "operating activities", "free cash"],
    "risk": ["risks", "threats", "concerns", "headwinds"],
    "capex": ["capital expenditure", "capacity", "investment", "plant"],
    "profit": ["pat", "net profit", "earnings"],
    "business": ["operates", "segments", "products", "overview", "revenue mix"],
    "does": ["operates", "segments", "products", "overview", "revenue mix"],
}
_SUFFIXES = ["ments", "ment", "ings", "ing", "ions", "ion", "ies", "ed", "es", "s"]


def stem(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) > len(suf) + 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z0-9%]+", (text or "").lower()) if t not in STOP]


def expand_query(q: str) -> str:
    low = q.lower()
    extra = []
    for k, vs in EXPANSIONS.items():
        if re.search(rf"\b{k}", low):
            extra += vs
    return q + (" " + " ".join(extra) if extra else "")


_ABBR = "".join(rf"(?<!\b{a}\.)" for a in ("Rs", "Mr", "Ms", "Mrs", "Dr", "No", "Co", "Ltd", "vs", "approx", r"e\.g", r"i\.e"))
_SPLIT = re.compile(_ABBR + r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(" ".join((text or "").split())) if p.strip()]


class _Index:
    def __init__(self, chunks: list[Chunk], docs: dict[int, Document]):
        self.chunks = chunks
        self.docs = docs
        corpus = [tokenize(f"{c.section or ''} {c.text}") for c in chunks]
        self.bm25 = BM25Okapi(corpus) if corpus else None
        self.emb: Optional[np.ndarray] = None
        if settings.enable_dense and chunks:
            self.emb = _embed([c.text for c in chunks])


_cache: dict[str, _Index] = {}
_lock = threading.Lock()
_embedder = None


def _embed(texts: list[str]) -> Optional[np.ndarray]:
    global _embedder
    try:
        if _embedder is None:
            from fastembed import TextEmbedding  # optional dependency
            _embedder = TextEmbedding(settings.embed_model)
        v = np.array(list(_embedder.embed(texts)), dtype=np.float32)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    except Exception:
        return None


def mode() -> str:
    return "hybrid (BM25 + dense, RRF)" if settings.enable_dense else "BM25 with query expansion"


def invalidate(ticker: Optional[str] = None) -> None:
    with _lock:
        if ticker is None:
            _cache.clear()
        else:
            _cache.pop(ticker, None)


def _index(s: Session, ticker: str) -> _Index:
    with _lock:
        if ticker in _cache:
            return _cache[ticker]
    docs = {d.id: d for d in s.scalars(select(Document).where(Document.ticker == ticker, Document.status == "indexed"))}
    chunks = s.scalars(select(Chunk).where(Chunk.ticker == ticker, Chunk.document_id.in_(list(docs) or [-1]))
                       .order_by(Chunk.id)).all()
    for c in chunks:
        s.expunge(c)
    for d in docs.values():
        s.expunge(d)
    idx = _Index(list(chunks), docs)
    with _lock:
        _cache[ticker] = idx
    return idx


def search(s: Session, ticker: str, query: str, k: int = 6, doc_types: Optional[list[str]] = None,
           periods: Optional[list[str]] = None) -> list[dict]:
    idx = _index(s, ticker)
    if not idx.chunks or idx.bm25 is None:
        return []
    allowed = [i for i, c in enumerate(idx.chunks)
               if (not doc_types or idx.docs[c.document_id].doc_type in doc_types)
               and (not periods or idx.docs[c.document_id].period_label in periods)]
    if not allowed:
        return []
    own = set(tokenize(ticker.replace("&", " ")))  # the company's own name carries no signal inside its own index
    qt = [t for t in tokenize(expand_query(query)) if t not in own] or tokenize(query)
    scores = idx.bm25.get_scores(qt)
    bm_rank = sorted(allowed, key=lambda i: -scores[i])
    bm_rank = [i for i in bm_rank if scores[i] > 0]
    fused: dict[int, float] = {}
    for r, i in enumerate(bm_rank):
        fused[i] = fused.get(i, 0) + 1 / (60 + r)
    if idx.emb is not None:
        qv = _embed([query])
        if qv is not None:
            sims = idx.emb @ qv[0]
            for r, i in enumerate(sorted(allowed, key=lambda i: -sims[i])[: max(20, k * 3)]):
                fused[i] = fused.get(i, 0) + 1 / (60 + r)
    top = sorted(fused, key=lambda i: -fused[i])[:k]
    max_bm = max((scores[i] for i in allowed), default=0) or 1
    out = []
    for i in top:
        c = idx.chunks[i]
        d = idx.docs[c.document_id]
        out.append({"chunk_id": c.id, "document_id": d.id, "document": d.title, "doc_type": d.doc_type,
                    "period": d.period_label, "page": c.page, "section": c.section, "speaker": c.speaker,
                    "text": c.text, "kind": c.kind, "url": d.url, "source": d.source,
                    "score": round(float(fused[i]), 5), "bm25": round(float(scores[i]), 3),
                    "relevance": round(float(scores[i]) / max_bm, 3)})
    return out
