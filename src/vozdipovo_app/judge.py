#!src/vozdipovo_app/judge.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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

    scores = (
        res.scores.model_dump()
        if hasattr(res.scores, "model_dump")
        else res.scores.dict()
    )

    reviewed_at = datetime.now(timezone.utc).isoformat()

    payload: dict[str, Any] = {
        **scores,
        "final_score": float(res.final_score),
        "score_editorial": float(res.editorial_score),
        "judge_justification": str(getattr(res.scores, "justification", "") or ""),
        "reviewed_by_model": f"{res.provider_used}:{res.model_used}",
        "reviewed_at": reviewed_at,
    }
    return payload


if __name__ == "__main__":
    out = evaluate_article_significance(
        title="Teste",
        text_snippet="Um texto curto de teste.",
        source_name="teste",
        keywords="teste",
        url="https://example.com",
    )
    print(out.keys())
