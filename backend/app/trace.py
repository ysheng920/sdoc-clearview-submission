"""Trace: the one record every engine emits.

The whole transparency story renders these. If an engine does something the UI
should be able to explain, it belongs in a Step -- not in a print() and not in a
separate logging path.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Step:
    """One observable thing an engine did."""
    name: str
    detail: str               # human sentence, shown verbatim in the UI
    data: dict = field(default_factory=dict)
    ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Span:
    """Where a value was found in the source text, so the UI can highlight it."""
    start: int
    end: int
    label: str | None = None   # the label text that matched, e.g. "Discharge Port"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Field:
    """One extracted field, with provenance and evidence."""
    name: str
    value: str | None = None       # normalised, used for comparison
    raw: str | None = None         # exactly as it appeared
    source: str = "missing"        # deterministic | llm | cloud | vlm | missing
    span: Span | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["span"] = self.span.to_dict() if self.span else None
        return d


@dataclass
class Trace:
    """What one engine did to one input."""
    engine: str
    inputs: dict = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    output: Any = None
    why: str = ""                  # one line, the headline reason
    model: str | None = None
    backend: str | None = None
    confidence: float | None = None
    escalated: bool = False
    tokens: dict = field(default_factory=dict)
    ms: float = 0.0
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "engine": self.engine,
            "inputs": self.inputs,
            "steps": [s.to_dict() for s in self.steps],
            "output": self.output,
            "why": self.why,
            "model": self.model,
            "backend": self.backend,
            "confidence": self.confidence,
            "escalated": self.escalated,
            "tokens": self.tokens,
            "ms": round(self.ms, 1),
        }


class Tracer:
    """Builds a Trace. Use as a context manager so timing is never forgotten."""

    def __init__(self, engine: str, **inputs):
        self.trace = Trace(engine=engine, inputs=inputs)
        self._t0 = time.perf_counter()

    def step(self, name: str, detail: str, **data) -> Step:
        s = Step(name=name, detail=detail, data=data,
                 ms=round((time.perf_counter() - self._t0) * 1000, 1))
        self.trace.steps.append(s)
        return s

    def finish(self, output: Any, why: str = "", **meta) -> Trace:
        t = self.trace
        t.output = output
        t.why = why
        t.ms = (time.perf_counter() - self._t0) * 1000
        for k, v in meta.items():
            setattr(t, k, v)
        return t

    def __enter__(self) -> "Tracer":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.step("error", f"{exc_type.__name__}: {exc}")
            self.finish(None, why=f"engine failed: {exc}")
        return False
