"""OpenTelemetry tracing with a database span exporter, plus cost records."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from sqlalchemy import func, select

from hop.platform.storage.db import CostRow, SpanRow, Store

SENSITIVE_KEYS = re.compile(r"(prompt_text|payload|answer_text|password|secret|token_value|api_key)", re.I)
SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|Basic\s+[A-Za-z0-9=+/]{8,})")
_PROPAGATOR = TraceContextTextMapPropagator()


def safe_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Telemetry never carries protected payloads or secrets; they are referenced by id instead."""
    clean: dict[str, Any] = {}
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        if SENSITIVE_KEYS.search(key):
            clean[key] = "[redacted]"
            continue
        if isinstance(value, list | tuple):
            value = [str(v) for v in value][:50]
        elif not isinstance(value, str | bool | int | float):
            value = str(value)
        if isinstance(value, str):
            value = SECRET_VALUE.sub("[redacted]", value)[:1000]
        clean[key] = value
    return clean


def _ts(ns: int | None) -> datetime:
    return datetime.fromtimestamp((ns or 0) / 1e9, tz=UTC)


class DatabaseSpanExporter(SpanExporter):
    def __init__(self, store: Store) -> None:
        self.store = store

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.store.session() as s:
            for span in spans:
                ctx = span.get_span_context()
                parent = span.parent.span_id if span.parent else None
                s.merge(
                    SpanRow(
                        span_id=format(ctx.span_id, "016x"),
                        trace_id=format(ctx.trace_id, "032x"),
                        parent_span_id=format(parent, "016x") if parent else None,
                        name=span.name,
                        start_time=_ts(span.start_time),
                        end_time=_ts(span.end_time),
                        duration_ms=((span.end_time or 0) - (span.start_time or 0)) / 1e6,
                        status=span.status.status_code.name,
                        attributes=dict(span.attributes or {}),
                    )
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # pragma: no cover
        return None


class Telemetry:
    def __init__(
        self,
        store: Store,
        *,
        service_name: str = "hop-platform",
        tenant_id: str = "hktdc",
        console: bool = False,
        extra_exporters: Sequence[SpanExporter] = (),
    ) -> None:
        self.store = store
        self.tenant_id = tenant_id
        self.provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        self.provider.add_span_processor(SimpleSpanProcessor(DatabaseSpanExporter(store)))
        for exporter in extra_exporters:
            self.provider.add_span_processor(SimpleSpanProcessor(exporter))
        if console:
            self.provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        self.tracer = self.provider.get_tracer("hop")

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Span]:
        attrs = {"tenant.id": self.tenant_id, **(attributes or {})}
        with self.tracer.start_as_current_span(name, attributes=safe_attributes(attrs)) as span:
            try:
                yield span
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                span.set_attribute("error.class", type(exc).__name__)
                span.set_attribute("error.message", SECRET_VALUE.sub("[redacted]", str(exc))[:500])
                raise

    @contextmanager
    def continue_trace(self, traceparent: str | None) -> Iterator[None]:
        """Attach a remote parent (W3C traceparent) so API calls and runs share one trace."""
        if not traceparent:
            yield
            return
        token = otel_context.attach(_PROPAGATOR.extract({"traceparent": traceparent}))
        try:
            yield
        finally:
            otel_context.detach(token)

    # queries ------------------------------------------------------------------------------
    def spans_for_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self.store.session() as s:
            rows = s.execute(select(SpanRow).where(SpanRow.trace_id == trace_id).order_by(SpanRow.start_time))
            return [
                {
                    "span_id": r.span_id,
                    "parent_span_id": r.parent_span_id,
                    "name": r.name,
                    "start_time": r.start_time.isoformat(),
                    "duration_ms": round(r.duration_ms, 2),
                    "status": r.status,
                    "attributes": r.attributes,
                }
                for r in rows.scalars()
            ]


def span_tree(spans: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Depth-first ordering of spans as (depth, span)."""
    children: dict[str | None, list[dict[str, Any]]] = {}
    ids = {s["span_id"] for s in spans}
    for s in spans:
        parent = s["parent_span_id"] if s["parent_span_id"] in ids else None
        children.setdefault(parent, []).append(s)
    out: list[tuple[int, dict[str, Any]]] = []

    def walk(parent: str | None, depth: int) -> None:
        for s in sorted(children.get(parent, []), key=lambda x: x["start_time"]):
            out.append((depth, s))
            walk(s["span_id"], depth + 1)

    walk(None, 0)
    return out


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def current_span_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.span_id, "016x") if ctx.is_valid else None


def outbound_trace_headers() -> dict[str, str]:
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier


class CostRecorder:
    def __init__(self, store: Store) -> None:
        self.store = store

    def record(
        self,
        *,
        run_id: str | None,
        category: str,
        provider: str,
        capability_id: str,
        units: float,
        unit: str,
        usd: float,
        simulated: bool,
    ) -> None:
        with self.store.session() as s:
            s.add(
                CostRow(
                    run_id=run_id,
                    category=category,
                    provider=provider,
                    capability_id=capability_id,
                    units=units,
                    unit=unit,
                    usd=usd,
                    simulated=int(simulated),
                    trace_id=current_trace_id(),
                    span_id=current_span_id(),
                )
            )

    def total_for_run(self, run_id: str) -> float:
        """Rounded to micro-dollars so totals agree across backends that sum floats in different orders."""
        with self.store.session() as s:
            total = s.execute(
                select(func.coalesce(func.sum(CostRow.usd), 0.0)).where(CostRow.run_id == run_id)
            ).scalar()
            return round(float(total or 0.0), 6)

    def breakdown(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with self.store.session() as s:
            q = select(
                CostRow.category,
                CostRow.provider,
                CostRow.capability_id,
                CostRow.unit,
                func.sum(CostRow.units),
                func.sum(CostRow.usd),
                func.max(CostRow.simulated),
            ).group_by(CostRow.category, CostRow.provider, CostRow.capability_id, CostRow.unit)
            if run_id:
                q = q.where(CostRow.run_id == run_id)
            return [
                {
                    "category": c,
                    "provider": p,
                    "capability_id": cap,
                    "unit": unit,
                    "units": float(u or 0),
                    "usd": round(float(usd or 0), 6),
                    "simulated": bool(sim),
                }
                for c, p, cap, unit, u, usd, sim in s.execute(q)
            ]
