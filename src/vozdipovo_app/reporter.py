#!src/vozdipovo_app/reporter.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from pydantic import BaseModel, Field, root_validator, validator

from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.llm.rotator import LLMRotator
from vozdipovo_app.news_pipeline import strict_json_extract
from vozdipovo_app.utils.backoff import (
    call_with_exponential_backoff,
    is_retryable_llm_error,
)
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReporterInput:
    titulo: str
    corpo: str
    keywords: List[str]
    site_name: str
    act_type: str


class ReporterOutput(BaseModel):
    titulo: str
    texto_completo_md: str
    factos_nucleares: List[str] = Field(default_factory=list)
    fontes_mencionadas: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    categoria_tematica: str
    subcategoria: str

    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    @validator("keywords", "factos_nucleares", "fontes_mencionadas", pre=True)
    def _coerce_list(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts
        return [str(v).strip()] if str(v).strip() else []

    @root_validator
    def _basic_sanity(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        titulo = str(values.get("titulo") or "").strip()
        texto = str(values.get("texto_completo_md") or "").strip()
        if not titulo:
            raise ValueError("titulo vazio no output do Reporter")
        if len(texto) < 60:
            raise ValueError("texto_completo_md demasiado curto no output do Reporter")
        return values


class ReporterService:
    def __init__(self, prompt_path: str = "configs/prompts/reporter.md") -> None:
        self._prompt_path = prompt_path

    @property
    def prompt_path(self) -> str:
        return self._prompt_path

    def report(self, data: ReporterInput) -> Dict[str, Any]:
        cfg = get_editorial_config()
        pools = cfg.llm.reporter or cfg.llm.reviser
        rotator = LLMRotator(pools)

        template = _read_text(self._prompt_path)
        prompt = (
            template.replace("{{TITULO}}", data.titulo.strip())
            .replace("{{CORPO}}", data.corpo.strip())
            .replace(
                "{{KEYWORDS}}",
                ", ".join([k.strip() for k in data.keywords if k.strip()]),
            )
            .replace("{{SITE_NAME}}", data.site_name.strip())
            .replace("{{ACT_TYPE}}", data.act_type.strip())
        )

        def _call() -> Dict[str, Any]:
            text, meta = rotator.ask(
                prompt=prompt,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1300,
            )
            payload = strict_json_extract(text)
            payload["reporter_model_used"] = str(meta.get("model") or "")
            return payload

        payload = call_with_exponential_backoff(
            _call,
            is_retryable=is_retryable_llm_error,
            max_attempts=4,
            base_delay_seconds=1.0,
        )

        fields = set(getattr(ReporterOutput, "model_fields", {}).keys()) or set(
            getattr(ReporterOutput, "__fields__", {}).keys()
        )
        extra_keys = sorted(
            [
                k
                for k in payload.keys()
                if k not in fields and k != "reporter_model_used"
            ]
        )
        if extra_keys:
            logger.warning(f"Reporter devolveu campos extra, campos={extra_keys}")

        out = ReporterOutput.model_validate(payload)
        return {
            "titulo": out.titulo,
            "texto_completo_md": out.texto_completo_md,
            "factos_nucleares": out.factos_nucleares,
            "fontes_mencionadas": out.fontes_mencionadas,
            "keywords": out.keywords,
            "categoria_tematica": out.categoria_tematica,
            "subcategoria": out.subcategoria,
            "reporter_model_used": str(payload.get("reporter_model_used") or ""),
            "raw": payload,
        }


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf_8") as f:
        return f.read()
