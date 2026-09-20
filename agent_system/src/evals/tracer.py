"""Granular observability and execution trajectory tracer.

Tracks model provider (Groq vs OpenAI), model name, tokens, TTFT, step latency,
and precise cost tracking per step, with OpenTelemetry-compatible export.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.schemas import TraceRecord


class TrajectoryTracer:
    """Thread-safe telemetry and trajectory recorder."""

    _instance: Optional[TrajectoryTracer] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> TrajectoryTracer:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TrajectoryTracer, cls).__new__(cls)
                cls._instance.traces = {}
                cls._instance.all_records = []
            return cls._instance

    def reset(self) -> None:
        """Clears stored traces for isolated test runs."""
        with self._lock:
            self.traces = {}
            self.all_records = []

    def log_step(
        self,
        trace_id: str,
        step_name: str,
        provider: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        ttft_ms: float = 0.0,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceRecord:
        """Appends a new trace record for an execution step."""
        record = TraceRecord(
            trace_id=trace_id,
            step_name=step_name,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            ttft_ms=round(ttft_ms, 2),
            latency_ms=round(latency_ms, 2),
            cost_usd=round(cost_usd, 7),
            status=status,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata or {},
        )

        with self._lock:
            if trace_id not in self.traces:
                self.traces[trace_id] = []
            self.traces[trace_id].append(record)
            self.all_records.append(record)

        return record

    def get_trace_records(self, trace_id: str) -> List[TraceRecord]:
        """Fetches all records belonging to a trace ID."""
        with self._lock:
            return list(self.traces.get(trace_id, []))

    def export_otel_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        """Exports trace records formatted as OpenTelemetry / Phoenix span structures."""
        with self._lock:
            records = self.traces.get(trace_id, [])

        spans = []
        for idx, rec in enumerate(records):
            spans.append({
                "trace_id": rec.trace_id,
                "span_id": f"span-{idx + 1:03d}",
                "name": rec.step_name,
                "attributes": {
                    "llm.provider": rec.provider,
                    "llm.model": rec.model,
                    "llm.tokens.prompt": rec.tokens_in,
                    "llm.tokens.completion": rec.tokens_out,
                    "llm.tokens.total": rec.tokens_in + rec.tokens_out,
                    "llm.ttft_ms": rec.ttft_ms,
                    "duration_ms": rec.latency_ms,
                    "cost_usd": rec.cost_usd,
                    "status": rec.status,
                },
                "timestamp": rec.timestamp,
            })
        return spans

    def export_jsonl(self, filepath: str) -> None:
        """Persists all logged traces to a structured JSONL audit file."""
        with self._lock:
            records = list(self.all_records)

        with open(filepath, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(rec.model_dump_json() + "\n")
