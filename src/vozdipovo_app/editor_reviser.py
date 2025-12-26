#!src/vozdipovo_app/editor_reviser.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

from pydantic import BaseModel, Field, ValidationError

from vozdipovo_app.llm.stage_client import get_stage_client_editor


class EditorChecklist(BaseModel):
    """Checklist do editor.

    Attributes:
        mencionou_indice_ou_estudo: Se mencionou índice/estudo.
        manteve_numeros_chave: Se manteve números-chave.
        incluiu_plataformas: Se incluiu plataformas (quando aplicável).
        incluiu_citacao: Se incluiu citação (quando aplicável).
        evitou_sensacionalismo: Se evitou sensacionalismo.
        tamanho_adequado: Se o texto está no intervalo alvo.
        preservou_factos_nucleares: Se preservou factos nucleares.
    """

    model_config = {"extra": "ignore"}

    mencionou_indice_ou_estudo: bool = False
    manteve_numeros_chave: bool = False
    incluiu_plataformas: bool = False
    incluiu_citacao: bool = False
    evitou_sensacionalismo: bool = True
    tamanho_adequado: bool = False
    preservou_factos_nucleares: bool = False


class EditorOutput(BaseModel):
    """Output validado do prompt do editor."""

    model_config = {"extra": "ignore"}

    titulo_revisto: str = Field(..., min_length=1, max_length=240)
    texto_completo_md_revisto: str = Field(..., min_length=1)
    keywords_revistas: List[str] = Field(default_factory=list)
    categoria_tematica: str = Field(default="", max_length=80)
    subcategoria: str = Field(default="", max_length=120)
    comentarios_edicao: str = Field(default="", max_length=1500)
    checklist: EditorChecklist = Field(default_factory=EditorChecklist)


@dataclass(frozen=True, slots=True)
class RevisionResult:
    """Resultado normalizado da revisão editorial."""

    revision_status: str
    revision_error: str
    revision_model_used: str
    titulo_revisto: str
    texto_completo_md_revisto: str
    keywords_revistas: List[str]
    categoria_tematica: str
    subcategoria: str
    comentarios_edicao: str
    checklist_json: str


def revise_article(
    *,
    title: str,
    text_md: str,
    keywords: str,
    site_name: str,
    act_type: str,
    categoria_tematica: str,
    subcategoria: str,
    factos_nucleares: List[str],
) -> RevisionResult:
    """Revisa e melhora um artigo usando o prompt do editor.

    Args:
        title: Título do writer.
        text_md: Corpo em markdown do writer.
        keywords: Keywords (string).
        site_name: Nome da fonte/site.
        act_type: Tipo de ato.
        categoria_tematica: Categoria temática do writer.
        subcategoria: Subcategoria do writer.
        factos_nucleares: Lista de factos nucleares do writer.

    Returns:
        RevisionResult: Resultado estruturado.
    """
    payload_text = "\n\n".join(
        [
            f"TITULO: {str(title or '').strip()}",
            f"TEXTO_COMPLETO:\n{str(text_md or '').strip()}",
        ]
    ).strip()

    if not payload_text:
        return RevisionResult(
            revision_status="ERROR",
            revision_error="Texto vazio",
            revision_model_used="",
            titulo_revisto="",
            texto_completo_md_revisto="",
            keywords_revistas=[],
            categoria_tematica=str(categoria_tematica or "").strip(),
            subcategoria=str(subcategoria or "").strip(),
            comentarios_edicao="",
            checklist_json="{}",
        )

    client = get_stage_client_editor()
    res = client.run_json(
        template_vars={
            "TITULO": str(title or "").strip(),
            "TEXTO_COMPLETO": str(text_md or "").strip(),
            "KEYWORDS": str(keywords or "").strip(),
            "SITE_NAME": str(site_name or "").strip(),
            "ACT_TYPE": str(act_type or "").strip(),
            "CATEGORIA_TEMATICA": str(categoria_tematica or "").strip(),
            "SUBCATEGORIA": str(subcategoria or "").strip(),
            "FACTOS_NUCLEARES": json.dumps(
                [str(x).strip() for x in (factos_nucleares or []) if str(x).strip()],
                ensure_ascii=False,
            ),
        },
        allowed_keys=[
            "titulo_revisto",
            "texto_completo_md_revisto",
            "keywords_revistas",
            "categoria_tematica",
            "subcategoria",
            "comentarios_edicao",
            "checklist",
        ],
        corr_id=f"editor:{(title or '')[:40]}",
    )

    if not res.ok or not isinstance(res.parsed_json, dict):
        return RevisionResult(
            revision_status="ERROR",
            revision_error=str(res.error or "Falha no editor")[:900],
            revision_model_used=f"{res.provider}:{res.model}".strip(":"),
            titulo_revisto="",
            texto_completo_md_revisto="",
            keywords_revistas=[],
            categoria_tematica=str(categoria_tematica or "").strip(),
            subcategoria=str(subcategoria or "").strip(),
            comentarios_edicao="",
            checklist_json="{}",
        )

    try:
        out = EditorOutput.model_validate(res.parsed_json)
    except ValidationError as e:
        return RevisionResult(
            revision_status="ERROR",
            revision_error=f"JSON inválido: {e}"[:900],
            revision_model_used=f"{res.provider}:{res.model}".strip(":"),
            titulo_revisto="",
            texto_completo_md_revisto="",
            keywords_revistas=[],
            categoria_tematica=str(categoria_tematica or "").strip(),
            subcategoria=str(subcategoria or "").strip(),
            comentarios_edicao="",
            checklist_json=json.dumps(res.parsed_json, ensure_ascii=False)[:2000],
        )

    checklist_json = (
        json.dumps(out.checklist.model_dump(), ensure_ascii=False)
        if hasattr(out.checklist, "model_dump")
        else json.dumps(out.checklist.dict(), ensure_ascii=False)
    )

    return RevisionResult(
        revision_status="OK",
        revision_error="",
        revision_model_used=f"{res.provider}:{res.model}".strip(":"),
        titulo_revisto=out.titulo_revisto.strip(),
        texto_completo_md_revisto=out.texto_completo_md_revisto.strip(),
        keywords_revistas=[
            str(k).strip() for k in (out.keywords_revistas or []) if str(k).strip()
        ],
        categoria_tematica=str(out.categoria_tematica or "").strip(),
        subcategoria=str(out.subcategoria or "").strip(),
        comentarios_edicao=str(out.comentarios_edicao or "").strip(),
        checklist_json=checklist_json,
    )


if __name__ == "__main__":
    demo = revise_article(
        title="Teste",
        text_md="Praia, Cabo Verde — Texto de teste.",
        keywords="teste, cabo verde",
        site_name="governo_cv",
        act_type="Comunicado",
        categoria_tematica="Geral",
        subcategoria="",
        factos_nucleares=["Facto 1", "Facto 2"],
    )
    print(demo.revision_status, demo.revision_model_used)
