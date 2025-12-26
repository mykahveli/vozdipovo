#!src/vozdipovo_app/editorial/models.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QualityConfig(BaseModel):
    """Configuração de qualidade para controlo de fidelidade.

    Attributes:
        min_source_chars: Tamanho mínimo (chars) do texto fonte.
        min_overlap_tokens: Nº mínimo de tokens partilhados (4+ chars).
        min_overlap_ratio: Rácio mínimo de interseção (0..1) entre tokens.
    """

    model_config = ConfigDict(extra="ignore")

    min_source_chars: int = Field(default=400, ge=0)
    min_overlap_tokens: int = Field(default=6, ge=0)
    min_overlap_ratio: float = Field(default=0.08, ge=0.0, le=1.0)


class ScoringConfig(BaseModel):
    """Configuração de normalização de scores.

    Attributes:
        significance_power: Expoente para normalização do score final.
        editorial_power: Expoente para normalização do score editorial.
    """

    model_config = ConfigDict(extra="ignore")

    significance_power: float = Field(default=1.0, ge=0.1, le=5.0)
    editorial_power: float = Field(default=1.0, ge=0.1, le=5.0)


class ModelPool(BaseModel):
    """Pool de modelos para uma etapa.

    Attributes:
        primary: Lista de modelos preferidos.
        fallback: Lista de modelos de fallback.
    """

    model_config = ConfigDict(extra="allow")

    primary: list[str] = Field(default_factory=list)
    fallback: list[str] = Field(default_factory=list)
    env_override: str | None = None


class LlmTuning(BaseModel):
    """Configuração de modelos por etapa.

    Attributes:
        reporter: Modelos para redação.
        judge: Modelos para julgamento.
        reviser: Modelos para revisão editorial.
        generator: Modelos para geração, mantido por compatibilidade.
    """

    model_config = ConfigDict(extra="allow")

    reporter: ModelPool | None = None
    judge: ModelPool | None = None
    reviser: ModelPool | None = None
    generator: ModelPool | None = None


class EditorialConfig(BaseModel):
    """Configuração editorial.

    Attributes:
        llm: Afinamento de modelos por etapa.
        significance_threshold: Threshold default de relevância.
    """

    model_config = ConfigDict(extra="allow")

    llm: LlmTuning = Field(default_factory=LlmTuning)
    significance_threshold: float = 3.0
    quality: QualityConfig = Field(default_factory=QualityConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


if __name__ == "__main__":
    cfg = EditorialConfig(
        llm=LlmTuning(
            judge=ModelPool(primary=["meta-llama/llama-4-scout-17b-16e-instruct"]),
            reporter=ModelPool(primary=["meta-llama/llama-4-scout-17b-16e-instruct"]),
            reviser=ModelPool(primary=["meta-llama/llama-4-scout-17b-16e-instruct"]),
        ),
        significance_threshold=3.0,
    )
    print(cfg.model_dump())
