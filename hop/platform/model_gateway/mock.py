"""Deterministic mock model adapter used by default (offline, no credentials).

* ``gerp_answer``      - replays recorded generative-engine answers from sandbox fixtures.
* ``gerp_extraction``  - lexicon + cue-phrase extractor that labels every entity hit as
                         PRIMARY_RECOMMENDATION / SUPPORTING_RECOMMENDATION / MENTION / EXCLUSION.
* ``explanation``      - composes a summary strictly from supplied facts (no new facts).

The same prompts and output schemas are used by the real OpenAI-compatible adapter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from hop.platform.model_gateway import ModelCall, RawCompletion, estimate_tokens
from hop.platform.policy_engine.content_safety import detect_injection

LABEL_PRECEDENCE = ("EXCLUSION", "PRIMARY_RECOMMENDATION", "SUPPORTING_RECOMMENDATION", "MENTION")

_SENTENCE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?")
_CLAUSE_SPLIT = re.compile(r"[;:，；]|,|\b(?:but|while|whereas|although|however|unlike)\b", re.I)


def _is_ascii(text: str) -> bool:
    return all(ord(c) < 128 for c in text)


def _cue_in(clause: str, cues: list[str]) -> bool:
    low = clause.lower()
    for cue in cues:
        c = cue.lower()
        if _is_ascii(c):
            if re.search(rf"(?<![\w]){re.escape(c)}(?![\w])", low):
                return True
        elif c in low:
            return True
    return False


def _clauses(sentence: str, offset: int) -> list[tuple[int, str]]:
    parts: list[tuple[int, str]] = []
    last = 0
    for m in _CLAUSE_SPLIT.finditer(sentence):
        parts.append((offset + last, sentence[last : m.start()]))
        last = m.start() if m.group(0).isalpha() else m.end()
    parts.append((offset + last, sentence[last:]))
    return [(o, c) for o, c in parts if c.strip()]


def extract_mentions(text: str, lexicon: list[dict[str, Any]], cues: dict[str, list[str]]) -> dict[str, Any]:
    entries = sorted(lexicon, key=lambda e: -len(e["alias"]))
    mentions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for sm in _SENTENCE.finditer(text):
        sentence = sm.group(0)
        if detect_injection(sentence):
            skipped.append({"start": sm.start(), "end": sm.end(), "reason": "suspected_prompt_injection"})
            continue
        pending: str | None = None
        for c_off, clause in _clauses(sentence, sm.start()):
            if _cue_in(clause, cues.get("exclusion", [])):
                label = "EXCLUSION"
            elif _cue_in(clause, cues.get("primary", [])):
                label = "PRIMARY_RECOMMENDATION"
            elif _cue_in(clause, cues.get("supporting", [])):
                label = "SUPPORTING_RECOMMENDATION"
            else:
                label = pending or "MENTION"
            before = len(mentions)
            taken: list[tuple[int, int]] = []
            for entry in entries:
                alias = entry["alias"]
                flags = 0 if entry.get("case_sensitive") else re.I
                pattern = rf"(?<![\w]){re.escape(alias)}(?![\w])" if _is_ascii(alias) else re.escape(alias)
                for m in re.finditer(pattern, clause, flags):
                    s, e = c_off + m.start(), c_off + m.end()
                    if any(s < te and e > ts for ts, te in taken):
                        continue
                    taken.append((s, e))
                    mentions.append({"surface": text[s:e], "alias": alias, "label": label, "start": s, "end": e})
            pending = label if len(mentions) == before and label != "MENTION" else None
    mentions.sort(key=lambda m: m["start"])
    return {"mentions": mentions, "skipped_segments": skipped}


class MockModelAdapter:
    provider = "mock"

    def __init__(self, fixture_lookup: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None) -> None:
        self.fixture_lookup = fixture_lookup

    def complete(self, call: ModelCall) -> RawCompletion:
        handler = {
            "gerp_answer": self._answer,
            "gerp_extraction": self._extract,
            "explanation": self._explain,
        }.get(call.task)
        output = handler(call) if handler else {"abstain": True, "reason": f"mock has no task {call.task}"}
        text = json.dumps(output, ensure_ascii=False)
        prompt_text = "".join(m["content"] for m in call.messages)
        return RawCompletion(text=text, tokens_in=estimate_tokens(prompt_text), tokens_out=estimate_tokens(text))

    def _answer(self, call: ModelCall) -> dict[str, Any]:
        fixture = self.fixture_lookup(call.variables) if self.fixture_lookup else None
        if fixture is None:
            return {"abstain": True, "reason": "no recorded generative-engine answer for this query"}
        if fixture.get("simulate") == "malformed":
            return {"answer": fixture.get("answer_text")}
        return {"answer_text": fixture["answer_text"], "citations": fixture.get("citations", [])}

    def _extract(self, call: ModelCall) -> dict[str, Any]:
        return extract_mentions(
            str(call.variables.get("answer_text", "")),
            list(call.variables.get("lexicon", [])),
            dict(call.parameters.get("cues", {})),
        )

    def _explain(self, call: ModelCall) -> dict[str, Any]:
        facts = call.variables.get("facts", {})
        statements = facts.get("observed", [])[:3]
        cited: list[str] = []
        parts = [f"{facts.get('title', 'Opportunity')}."]
        for st in statements:
            parts.append(st["text"])
            cited.extend(st.get("evidence_ids", [])[:3])
        parts.append("Counter-evidence and limitations are listed separately; human review is required.")
        return {"summary": " ".join(parts), "cited_evidence_ids": sorted(set(cited))}
