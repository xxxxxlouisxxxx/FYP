"""Structured output schemas enforced by the model gateway for product agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Literal["PRIMARY_RECOMMENDATION", "SUPPORTING_RECOMMENDATION", "MENTION", "EXCLUSION"]


class GerpAnswerOutput(BaseModel):
    """gerp_answer_v1"""

    model_config = ConfigDict(extra="ignore")
    answer_text: str = Field(min_length=1, max_length=8000)
    citations: list[str] = Field(default_factory=list, max_length=20)


class ExtractedMention(BaseModel):
    model_config = ConfigDict(extra="ignore")
    surface: str
    alias: str
    label: Label
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _span(self) -> ExtractedMention:
        if self.end <= self.start:
            raise ValueError("span end must be after start")
        return self


class GerpExtractionOutput(BaseModel):
    """gerp_extraction_v1"""

    model_config = ConfigDict(extra="ignore")
    mentions: list[ExtractedMention] = Field(default_factory=list, max_length=200)
    skipped_segments: list[dict] = Field(default_factory=list)


class ExplanationOutput(BaseModel):
    """explanation_v1"""

    model_config = ConfigDict(extra="ignore")
    summary: str = Field(min_length=10, max_length=2000)
    cited_evidence_ids: list[str] = Field(default_factory=list)
