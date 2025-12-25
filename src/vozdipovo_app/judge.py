#!src/vozdipovo_app/judge.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vozdipovo_app.director import (
    calculate_editorial_score as _calculate_editorial_score,
)
from vozdipovo_app.director import (
    calculate_significance_score as _calculate_significance_score,
)
from vozdipovo_app.director import director_assess


@dataclass(frozen=True, slots=True)
class JudgeResult:
    payload: dict[str, Any]


def calculate_significance_score(scores: dict[str, Any]) -> float:
    return _calculate_significance_score(scores)


def calculate_editorial_score(scores: dict[str, Any]) -> float:
    return _calculate_editorial_score(scores)


def evaluate_article_significance(
    title: str,
    text_snippet: str,
    source_name: str,
    keywords: str = "",
    url: str | None = None,
) -> dict[str, Any]:
    _ = url

    res = director_assess(
        title=title or "",
        body=text_snippet or "",
        keywords=keywords or "",
        source_name=source_name or "",
    )

    scores_obj = getattr(res, "scores", None)
    if scores_obj is None:
        scores: dict[str, Any] = {}
    elif hasattr(scores_obj, "model_dump"):
        scores = scores_obj.model_dump()
    elif hasattr(scores_obj, "dict"):
        scores = scores_obj.dict()
    else:
        scores = dict(scores_obj) if isinstance(scores_obj, dict) else {}

    justification = getattr(res, "justification", "") or ""
    provider_used = getattr(res, "provider_used", "") or ""
    model_used = getattr(res, "model_used", "") or ""
    reviewed_at = getattr(res, "reviewed_at", None)

    payload: dict[str, Any] = {
        **scores,
        "final_score": float(getattr(res, "final_score", 0.0) or 0.0),
        "score_editorial": float(getattr(res, "editorial_score", 0.0) or 0.0),
        "judge_justification": str(justification),
        "reviewed_by_model": f"{provider_used}:{model_used}".strip(":"),
        "reviewed_at": reviewed_at,
    }
    return payload


if __name__ == "__main__":
    out = evaluate_article_significance(
        title="Teste",
        text_snippet="Texto curto para teste",
        source_name="governo_cv",
    )
    print(out)
