#!src/vozdipovo_app/editorial/models.py
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    confloat,
    conint,
    root_validator,
    validator,
)


class StrictBaseModel(BaseModel):
    """Base Pydantic com validação estrita e sem chaves silenciosas."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        validate_by_name=True,
    )


class ThrottleSeconds(StrictBaseModel):
    judge: confloat(ge=0.0) = 0.2
    wordpress: confloat(ge=0.0) = 0.6


class PipelineTuning(StrictBaseModel):
    scrape_limit_per_run: conint(ge=1) = 300
    judge_limit_per_run: conint(ge=1) = 120
    generate_limit_per_run: conint(ge=1) = 30
    revision_limit_per_run: conint(ge=1) = 30
    publish_limit_per_run: conint(ge=1) = 25
    rss_max_age_hours: conint(ge=1) = 72
    rss_drop_if_no_pub_date: bool = True
    throttle_seconds: ThrottleSeconds = Field(default_factory=ThrottleSeconds)


class ScoringTuning(StrictBaseModel):
    significance_threshold: confloat(ge=0.0, le=10.0) = 1.2
    significance_power: confloat(gt=0.0, le=10.0) = 1.7
    editorial_power: confloat(gt=0.0, le=10.0) = 2.0


class QualityTuning(StrictBaseModel):
    min_source_chars: conint(ge=0) = 800
    min_overlap_tokens: conint(ge=0) = 18
    min_overlap_ratio: confloat(ge=0.0, le=1.0) = 0.14
    rss_min_text_chars: conint(ge=0) = 600
    rss_fetch_full_article: bool = True


class ModelPool(StrictBaseModel):
    models: List[str] = Field(default_factory=list)
    env_override: Optional[str] = None

    @validator("models", pre=True)
    def _coerce_models(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts
        return [str(v)]

    @validator("models")
    def _sanitize_models(cls, v: List[str]) -> List[str]:
        cleaned = [str(m).strip() for m in v if str(m).strip()]
        seen: set[str] = set()
        out: List[str] = []
        for m in cleaned:
            k = m.casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append(m)
        return out


class StageModels(StrictBaseModel):
    groq: ModelPool
    openrouter: Optional[ModelPool] = None

    @root_validator(skip_on_failure=True)
    def _require_groq_models(cls, values: Dict[str, object]) -> Dict[str, object]:
        groq = values.get("groq")
        if isinstance(groq, ModelPool) and not groq.models:
            raise ValueError("llm stage groq.models must not be empty")
        return values


class LlmTuning(StrictBaseModel):
    judge: StageModels
    reviser: StageModels


class HighlightRule(StrictBaseModel):
    category_id: conint(ge=1)
    limit: conint(ge=1)
    editorial_threshold: confloat(ge=0.0, le=10.0)


class HomepageTuning(StrictBaseModel):
    time_window_hours: conint(ge=1) = 24
    breaking: HighlightRule
    featured: HighlightRule


class AudioTuning(StrictBaseModel):
    enabled: bool = True
    only_for_highlights: bool = True
    highlights: List[str] = Field(default_factory=lambda: ["BREAKING", "FEATURED"])
    output_subdir: str = "audio"

    @validator("highlights", pre=True)
    def _normalize_highlights(cls, v: object) -> object:
        if isinstance(v, list):
            return [str(x).strip().upper() for x in v if str(x).strip()]
        return v


class WordPressTuning(StrictBaseModel):
    default_status: str = "publish"
    category_ids: Dict[str, int] = Field(default_factory=dict)
    allowed_editorial_categories: List[str] = Field(default_factory=list)

    @validator("default_status")
    def _validate_status(cls, v: str) -> str:
        s = str(v or "").strip().lower()
        allowed = {"publish", "draft", "pending", "private"}
        if s not in allowed:
            raise ValueError(f"default_status must be one of {sorted(allowed)}")
        return s

    @validator("category_ids")
    def _validate_category_ids(cls, v: Dict[str, int]) -> Dict[str, int]:
        if "Geral" not in v:
            raise ValueError("category_ids must contain Geral")
        out: Dict[str, int] = {}
        for k, raw in v.items():
            name = str(k).strip()
            if not name:
                continue
            cid = int(raw)
            if cid < 1:
                raise ValueError(f"category id must be >= 1 for {name}")
            out[name] = cid
        return out

    @validator("allowed_editorial_categories", pre=True)
    def _normalize_allowed(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        s = str(v).strip()
        return [s] if s else []

    @root_validator(skip_on_failure=True)
    def _ensure_allowed_in_categories(
        cls, values: Dict[str, object]
    ) -> Dict[str, object]:
        category_ids = values.get("category_ids") or {}
        allowed = values.get("allowed_editorial_categories") or []
        if not isinstance(category_ids, dict) or not isinstance(allowed, list):
            return values
        missing = [c for c in allowed if c not in category_ids]
        if missing:
            raise ValueError(
                f"allowed_editorial_categories contains unknown categories: {missing}"
            )
        return values


class JudgeTuning(StrictBaseModel):
    suspend_mode: str = "skip"

    @validator("suspend_mode", pre=True)
    def _normalize_suspend_mode(cls, v: object) -> str:
        s = str(v or "skip").strip().lower()
        return s if s in {"skip", "interactive", "abort"} else "skip"


class EditorialConfig(StrictBaseModel):
    version: conint(ge=1) = 1
    pipeline: PipelineTuning
    scoring: ScoringTuning
    quality: QualityTuning = Field(default_factory=QualityTuning)
    llm: LlmTuning
    homepage: HomepageTuning
    wordpress: WordPressTuning
    audio: AudioTuning = Field(default_factory=AudioTuning)
    judge: JudgeTuning = Field(default_factory=JudgeTuning)
    comment: Optional[str] = Field(default=None, alias="_comment")
