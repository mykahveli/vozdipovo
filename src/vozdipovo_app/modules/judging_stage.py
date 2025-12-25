#!src/vozdipovo_app/modules/judging_stage.py
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from vozdipovo_app.judge import evaluate_article_significance
from vozdipovo_app.llm.errors import classify_llm_error
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass
class JudgingStage:
    ctx: Any
    limit: int
    throttle_seconds: float = 0.0
    significance_threshold: float = 0.0
    commit_every: int = 5

    def run(self) -> int:
        conn = self.ctx.conn

        q = """
        SELECT
          ld.id AS legal_doc_id,
          ld.site_name,
          COALESCE(ld.title, '') AS title,
          COALESCE(ld.url, '') AS url,
          COALESCE(ld.raw_payload_json, ld.content_text, ld.summary, ld.raw_html, '') AS snippet
        FROM legal_docs ld
        LEFT JOIN news_articles na ON na.legal_doc_id = ld.id
        WHERE na.id IS NULL
           OR na.review_status IN ('RETRY')
        ORDER BY ld.id DESC
        LIMIT ?;
        """
        rows = conn.execute(q, (int(self.limit),)).fetchall()
        if not rows:
            logger.info("Nenhum documento novo para julgar")
            return 0

        processed = 0
        commit_every = max(1, int(self.commit_every))

        for i, r in enumerate(rows, start=1):
            legal_doc_id = int(r["legal_doc_id"])
            title = str(r["title"] or "")
            url = str(r["url"] or "")
            snippet = str(r["snippet"] or "")
            site_name = str(r["site_name"] or "")

            logger.info(
                f"Julgando, i={i}, total={len(rows)}, legal_doc_id={legal_doc_id}"
            )

            try:
                res = evaluate_article_significance(
                    title=title,
                    text_snippet=snippet[:4000],
                    source_name=site_name,
                    url=url,
                )

                final_score = float(res.get("final_score") or 0.0)
                threshold = float(self.significance_threshold or 0.0)
                decision = "WRITE" if final_score >= threshold else "SKIP"

                conn.execute(
                    """
                    INSERT INTO news_articles (
                      legal_doc_id,
                      titulo,
                      final_score,
                      score_editorial,
                      judge_justification,
                      reviewed_by_model,
                      reviewed_at,
                      decision,
                      review_status,
                      review_attempts,
                      updated_at,
                      created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'JUDGED', 1, datetime('now'), datetime('now'))
                    ON CONFLICT(legal_doc_id) DO UPDATE SET
                      titulo=excluded.titulo,
                      final_score=excluded.final_score,
                      score_editorial=excluded.score_editorial,
                      judge_justification=excluded.judge_justification,
                      reviewed_by_model=excluded.reviewed_by_model,
                      reviewed_at=excluded.reviewed_at,
                      decision=excluded.decision,
                      review_status='JUDGED',
                      review_error=NULL,
                      review_error_kind=NULL,
                      review_http_status=NULL,
                      review_next_retry_at=NULL,
                      updated_at=datetime('now');
                    """,
                    (
                        legal_doc_id,
                        title,
                        final_score,
                        float(res.get("score_editorial") or 0.0),
                        str(res.get("judge_justification") or ""),
                        str(res.get("reviewed_by_model") or ""),
                        str(res.get("reviewed_at") or _iso(_utc_now())),
                        decision,
                    ),
                )

                processed += 1

            except Exception as e:
                cls = classify_llm_error(e)

                kind: Optional[str] = None
                if hasattr(cls, "kind") and cls.kind is not None:
                    kind = (
                        cls.kind.value if hasattr(cls.kind, "value") else str(cls.kind)
                    )
                elif hasattr(cls, "reason"):
                    kind = str(cls.reason)

                retry_after = getattr(cls, "retry_after_seconds", None)
                if retry_after is None:
                    retry_after = 90

                next_retry = _iso(_utc_now() + timedelta(seconds=int(retry_after)))

                conn.execute(
                    """
                    INSERT INTO news_articles (
                      legal_doc_id,
                      titulo,
                      review_status,
                      review_error,
                      review_error_kind,
                      review_http_status,
                      review_attempts,
                      review_next_retry_at,
                      updated_at,
                      created_at
                    )
                    VALUES (?, ?, 'RETRY', ?, ?, ?, 1, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(legal_doc_id) DO UPDATE SET
                      review_status='RETRY',
                      review_error=excluded.review_error,
                      review_error_kind=excluded.review_error_kind,
                      review_http_status=excluded.review_http_status,
                      review_attempts=COALESCE(news_articles.review_attempts, 0) + 1,
                      review_next_retry_at=excluded.review_next_retry_at,
                      updated_at=datetime('now');
                    """,
                    (
                        legal_doc_id,
                        title,
                        str(e),
                        kind,
                        getattr(cls, "http_status", None),
                        next_retry,
                    ),
                )

            if processed > 0 and (processed % commit_every) == 0:
                conn.commit()
                logger.info(f"Commit parcial, processed={processed}")

            if self.throttle_seconds:
                time.sleep(float(self.throttle_seconds))

        conn.commit()
        return processed


if __name__ == "__main__":
    from vozdipovo_app.db.migrate import ensure_schema
    from vozdipovo_app.modules.base import StageContext
    from vozdipovo_app.settings import get_settings

    s = get_settings()
    conn = ensure_schema(str(s.db_path))
    try:
        ctx = StageContext(conn=conn, app_cfg=s.app_cfg, editorial=s.editorial)
        stage = JudgingStage(
            ctx=ctx,
            limit=20,
            throttle_seconds=0.0,
            significance_threshold=0.0,
            commit_every=5,
        )
        print(stage.run())
    finally:
        conn.close()
