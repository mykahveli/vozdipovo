#!src/vozdipovo_app/editor.py
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
class EditorInput:
    titulo: str
    texto_completo: str
    keywords: List[str]
    site_name: str
    act_type: str
    categoria_tematica: str
    subcategoria: str
    factos_nucleares: List[str]


class EditorChecklist(BaseModel):
    mencionou_indice_ou_estudo: bool = True
    manteve_numeros_chave: bool = True
    incluiu_plataformas: bool = True
    incluiu_citacao: bool = True
    evitou_sensacionalismo: bool = True
    tamanho_adequado: bool = True
    preservou_factos_nucleares: bool = True

    model_config = {"extra": "ignore"}


class EditorOutput(BaseModel):
    titulo_revisto: str
    texto_completo_md_revisto: str
    keywords_revistas: List[str] = Field(default_factory=list)
    categoria_tematica: str
    subcategoria: str
    comentarios_edicao: str = ""
    checklist: EditorChecklist = Field(default_factory=EditorChecklist)

    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    @validator("keywords_revistas", pre=True)
    def _coerce_keywords(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return [str(v).strip()] if str(v).strip() else []

    @root_validator
    def _sanity(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        titulo = str(values.get("titulo_revisto") or "").strip()
        texto = str(values.get("texto_completo_md_revisto") or "").strip()
        if not titulo:
            raise ValueError("titulo_revisto vazio no output do Editor")
        if len(texto) < 120:
            raise ValueError(
                "texto_completo_md_revisto demasiado curto no output do Editor"
            )
        return values


class EditorService:
    def __init__(self, prompt_path: str = "configs/prompts/editor.md") -> None:
        self._prompt_path = prompt_path

    @property
    def prompt_path(self) -> str:
        return self._prompt_path

    def edit(self, data: EditorInput) -> Dict[str, Any]:
        cfg = get_editorial_config()
        pools = cfg.llm.editor or cfg.llm.reviser
        rotator = LLMRotator(pools)

        template = _read_text(self._prompt_path)
        prompt = (
            template.replace("{{TITULO}}", data.titulo.strip())
            .replace("{{TEXTO_COMPLETO}}", data.texto_completo.strip())
            .replace(
                "{{KEYWORDS}}",
                ", ".join([k.strip() for k in data.keywords if k.strip()]),
            )
            .replace("{{SITE_NAME}}", data.site_name.strip())
            .replace("{{ACT_TYPE}}", data.act_type.strip())
            .replace("{{CATEGORIA}}", data.categoria_tematica.strip())
            .replace("{{SUBCATEGORIA}}", data.subcategoria.strip())
            .replace(
                "{{FACTOS_NUCLEARES}}",
                "\n".join(
                    [f"- {x.strip()}" for x in data.factos_nucleares if x.strip()]
                ),
            )
        )

        def _call() -> Dict[str, Any]:
            text, meta = rotator.ask(
                prompt=prompt,
                response_format={"type": "json_object"},
                temperature=0.15,
                max_tokens=1400,
            )
            payload = strict_json_extract(text)
            payload["editor_model_used"] = str(meta.get("model") or "")
            return payload

        payload = call_with_exponential_backoff(
            _call,
            is_retryable=is_retryable_llm_error,
            max_attempts=4,
            base_delay_seconds=1.0,
        )

        fields = set(getattr(EditorOutput, "model_fields", {}).keys()) or set(
            getattr(EditorOutput, "__fields__", {}).keys()
        )
        extra_keys = sorted(
            [k for k in payload.keys() if k not in fields and k != "editor_model_used"]
        )
        if extra_keys:
            logger.warning(f"Editor devolveu campos extra, campos={extra_keys}")

        out = EditorOutput.model_validate(payload)
        checklist_dict = (
            out.checklist.model_dump()
            if hasattr(out.checklist, "model_dump")
            else out.checklist.dict()
        )
        return {
            "titulo_revisto": out.titulo_revisto,
            "texto_completo_md_revisto": out.texto_completo_md_revisto,
            "keywords_revistas": out.keywords_revistas,
            "categoria_tematica": out.categoria_tematica,
            "subcategoria": out.subcategoria,
            "comentarios_edicao": out.comentarios_edicao,
            "checklist": checklist_dict,
            "editor_model_used": str(payload.get("editor_model_used") or ""),
            "raw": payload,
        }


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf_8") as f:
        return f.read()
