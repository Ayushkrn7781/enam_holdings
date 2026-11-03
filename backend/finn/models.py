"""SQLAlchemy 2 models. Every table carries a `source` column for provenance."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# source values: nse | bse | screener | yfinance | pdf | llm | demo


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "company"
    ticker: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[Optional[str]] = mapped_column(String(80))
    is_financial: Mapped[bool] = mapped_column(Boolean, default=False)
    about: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="demo")


class Holding(Base):
    __tablename__ = "holding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("company.ticker"), unique=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(16), default="demo")


class Price(Base):
    __tablename__ = "price"
    __table_args__ = (UniqueConstraint("ticker", "date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Optional[float]] = mapped_column(Float)
    high: Mapped[Optional[float]] = mapped_column(Float)
    low: Mapped[Optional[float]] = mapped_column(Float)
    close: Mapped[Optional[float]] = mapped_column(Float)
    adj_close: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="demo")


class Announcement(Base):
    __tablename__ = "announcement"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[Optional[str]] = mapped_column(Text)
    exchange_category: Mapped[Optional[str]] = mapped_column(String(200))
    attachment_url: Mapped[Optional[str]] = mapped_column(Text)
    attachment_text: Mapped[Optional[str]] = mapped_column(Text)  # pages joined by \f
    source: Mapped[str] = mapped_column(String(16), default="demo")
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    # derived
    category: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    subtype: Mapped[Optional[str]] = mapped_column(String(40))
    category_method: Mapped[Optional[str]] = mapped_column(String(16))
    score: Mapped[Optional[float]] = mapped_column(Float, index=True)
    priority: Mapped[Optional[str]] = mapped_column(String(12))
    score_breakdown: Mapped[Optional[Any]] = mapped_column(JSON)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    enrichment: Mapped[Optional[Any]] = mapped_column(JSON)
    is_duplicate_of: Mapped[Optional[int]] = mapped_column(Integer)


class FinancialPeriod(Base):
    __tablename__ = "financial_period"
    __table_args__ = (UniqueConstraint("ticker", "period_type", "period_end", "basis"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    period_type: Mapped[str] = mapped_column(String(1))  # Q | Y
    period_end: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(20))
    basis: Mapped[str] = mapped_column(String(16), default="consolidated")
    unit: Mapped[str] = mapped_column(String(16), default="INR crore")
    metrics: Mapped[Any] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(16), default="demo")
    source_url: Mapped[Optional[str]] = mapped_column(Text)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("ticker", "url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    doc_type: Mapped[str] = mapped_column(String(20))  # annual_report | transcript | results | presentation
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(Text)
    period_label: Mapped[Optional[str]] = mapped_column(String(20))
    period_end: Mapped[Optional[date]] = mapped_column(Date)
    local_path: Mapped[Optional[str]] = mapped_column(Text)
    pages: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="discovered")
    error: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="demo")


class Chunk(Base):
    __tablename__ = "chunk"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(8), default="text")
    speaker: Mapped[Optional[str]] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary)


class Guidance(Base):
    __tablename__ = "guidance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"))
    chunk_id: Mapped[Optional[int]] = mapped_column(Integer)
    page: Mapped[Optional[int]] = mapped_column(Integer)
    said_in: Mapped[str] = mapped_column(String(20))
    statement: Mapped[str] = mapped_column(Text)
    speaker: Mapped[Optional[str]] = mapped_column(String(80))
    metric: Mapped[str] = mapped_column(String(24))
    target_low: Mapped[Optional[float]] = mapped_column(Float)
    target_high: Mapped[Optional[float]] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String(10))
    horizon: Mapped[Optional[str]] = mapped_column(String(20))
    commitment: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(16), default="pdf")


class AlertRule(Base):
    __tablename__ = "alert_rule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[Optional[str]] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(16))  # price_up | price_down | volume | category
    threshold: Mapped[Optional[float]] = mapped_column(Float)
    category: Mapped[Optional[str]] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(12), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(16), default="user")


class AlertEvent(Base):
    __tablename__ = "alert_event"
    __table_args__ = (UniqueConstraint("rule_id", "ticker", "ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rule.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(24))
    ref: Mapped[str] = mapped_column(String(40))
    triggered_at: Mapped[datetime] = mapped_column(DateTime)
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[Optional[float]] = mapped_column(Float)
    announcement_id: Mapped[Optional[int]] = mapped_column(Integer)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="demo")


class ResearchLog(Base):
    __tablename__ = "research_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(24))
    question: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(16))
    answer: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(16), default="llm")


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
