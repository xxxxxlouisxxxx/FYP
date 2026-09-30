"""Untrusted-content handling: prompt-injection detection and instruction/data separation.

All provider and model content is untrusted data. It is labelled, delimited when placed in prompts,
scanned for injection patterns, and never interpreted as instructions by deterministic code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions?|rules|prompts?)\b", re.I),
    ),
    ("role_hijack", re.compile(r"\b(you are now|act as|new instructions|system prompt)\b", re.I)),
    ("fake_delimiter", re.compile(r"<\s*/?\s*(system|assistant|untrusted_content|instructions)\s*>", re.I)),
    ("exfiltration", re.compile(r"\b(send|post|upload|forward|exfiltrate)\b.{0,60}\b(to|at)\b.{0,20}https?://", re.I)),
    ("tool_coercion", re.compile(r"\b(call|invoke|execute|run)\b.{0,20}\b(tool|function|command|shell)\b", re.I)),
    ("label_coercion", re.compile(r"\b(label|classify|mark|rank)\b.{0,60}\bas (the )?(primary|top|#1|best)\b", re.I)),
    ("zh_override", re.compile(r"(忽略|無視|忽视).{0,10}(指示|指令|規則)")),
)


@dataclass(frozen=True)
class InjectionFinding:
    pattern: str
    start: int
    end: int
    excerpt: str


def detect_injection(text: str) -> list[InjectionFinding]:
    findings: list[InjectionFinding] = []
    for name, pattern in INJECTION_PATTERNS:
        for m in pattern.finditer(text or ""):
            findings.append(InjectionFinding(name, m.start(), m.end(), text[m.start() : m.end()][:120]))
    return sorted(findings, key=lambda f: f.start)


def wrap_untrusted(text: str, source: str) -> str:
    """Delimit untrusted data so the model is instructed to treat it as data only."""
    safe = re.sub(r"<\s*/?\s*untrusted_content[^>]*>", "[removed-delimiter]", text or "", flags=re.I)
    return f'<untrusted_content source="{source}">\n{safe}\n</untrusted_content>'


SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text
