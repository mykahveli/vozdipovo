#!src/vozdipovo_app/director.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from pydantic import BaseModel, Field, conint

from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.llm.stage_client import get_stage_client_director
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, float(x)))


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class DirectorScores(BaseModel):
    """Scores do Director."""

    cv_relevance_score: conint(ge=0, le=10) = Field(...)
    scale_score: conint(ge=0, le=10) = Field(...)
    impact_score: conint(ge=0, le=10) = Field(...)
    novelty_score: conint(ge=0, le=10) = Field(...)
    potential_score: conint(ge=0, le=10) = Field(...)
    legacy_score: conint(ge=0, le=10) = Field(...)
    credibility_score: conint(ge=0, le=10) = Field(...)
    positivity_score: conint(ge=0, le=10) = Field(...)
    justification: str = Field(..., min_length=1, max_length=2000)

    model_config = {"extra": "ignore"}


@dataclass(frozen=True, slots=True)
class DirectorResult:
    """Resultado do Director com scores derivados."""

    scores: DirectorScores
    final_score: float
    editorial_score: float
    model_used: str
    provider_used: str


def calculate_significance_score(scores: Dict[str, Any]) -> float:
    cv_rel = _to_float(scores.get("cv_relevance_score", 0))
    if cv_rel < 2.0:
        return round(_clamp(cv_rel * 0.5), 2)

    scale = _to_float(scores.get("scale_score", 0))
    impact = _to_float(scores.get("impact_score", 0))
    legacy = _to_float(scores.get("legacy_score", 0))

    cred = _to_float(scores.get("credibility_score", 0))
    novelty = _to_float(scores.get("novelty_score", 0))

    raw = 0.40 * cv_rel + 0.25 * scale + 0.20 * impact + 0.10 * novelty + 0.05 * cred
    legacy_mult = 0.7 + 0.3 * (_clamp(legacy) / 10.0)
    raw_adj = raw * legacy_mult

    potential = _to_float(scores.get("potential_score", 0))
    potential_bonus = 1.0 + 0.1 * (_clamp(potential) / 10.0)
    final_raw = raw_adj * potential_bonus

    p = float(get_editorial_config().scoring.significance_power)
    norm = 10.0 * ((_clamp(final_raw) / 10.0) ** p)
    return round(_clamp(norm), 2)


def calculate_editorial_score(scores: Dict[str, Any]) -> float:
    cv_rel = _to_float(scores.get("cv_relevance_score", 0))
    if cv_rel < 1.5:
        penalty_factor = max(0.1, cv_rel / 15.0)
        base_score = cv_rel * 0.5
        return round(_clamp(base_score * penalty_factor), 2)

    positivity = _to_float(scores.get("positivity_score", 5.0))
    impact = _to_float(scores.get("impact_score", 0))
    novelty = _to_float(scores.get("novelty_score", 0))
    cred = _to_float(scores.get("credibility_score", 0))
    potential = _to_float(scores.get("potential_score", 0))

    raw = (
        0.30 * impact
        + 0.25 * novelty
        + 0.20 * cred
        + 0.15 * potential
        + 0.10 * positivity
    )
    p = float(get_editorial_config().scoring.editorial_power)
    norm = 10.0 * ((_clamp(raw) / 10.0) ** p)
    return round(_clamp(norm), 2)


def director_assess(
    title: str, body: str, keywords: str, source_name: str
) -> DirectorResult:
    client = get_stage_client_director()
    res = client.run_json(
        template_vars={
            "TITULO": title or "",
            "CORPO": body or "",
            "KEYWORDS": keywords or "",
            "FONTE": source_name or "",
        },
        allowed_keys=[
            "cv_relevance_score",
            "scale_score",
            "impact_score",
            "novelty_score",
            "potential_score",
            "legacy_score",
            "credibility_score",
            "positivity_score",
            "justification",
        ],
        corr_id=f"director:{(title or '')[:40]}",
    )

    if not res.ok or not isinstance(res.parsed_json, dict):
        raise RuntimeError(res.error or "Falha no Director")

    scores = DirectorScores.model_validate(res.parsed_json)
    scores_dict = (
        scores.model_dump() if hasattr(scores, "model_dump") else scores.dict()
    )
    final_score = calculate_significance_score(scores_dict)
    editorial_score = calculate_editorial_score(scores_dict)

    return DirectorResult(
        scores=scores,
        final_score=final_score,
        editorial_score=editorial_score,
        model_used=res.model,
        provider_used=res.provider,
    )
