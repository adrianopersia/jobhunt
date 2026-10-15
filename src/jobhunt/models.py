"""Contratos de datos. `JobAnalysis` es lo que devuelve el agente scout: se valida acá
antes de tocar la base, así un JSON mal formado nunca entra como análisis."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JobStub(BaseModel):
    source: str
    external_id: str
    url: str
    title: str
    company: str
    location: str = ""

    @property
    def id(self) -> str:
        return f"{self.source}:{self.external_id}"


class JobDetail(BaseModel):
    description: str
    apply_url: str = ""
    posted_at: str | None = None
    employment_type: str | None = None
    modality_raw: str | None = None
    location_raw: str | None = None
    location_requirements: list[str] = []


class RoleFamily(StrEnum):
    APPLIED_AI = "applied_ai"
    AI_AUTOMATION = "ai_automation"
    FULLSTACK_AI_NATIVE = "fullstack_ai_native"
    FORWARD_DEPLOYED = "forward_deployed"
    SOFTWARE_GENERAL = "software_general"
    ML_ENGINEER = "ml_engineer"
    ML_RESEARCH = "ml_research"
    DATA = "data"
    NON_ENGINEERING = "non_engineering"


class Seniority(StrEnum):
    JUNIOR = "junior"
    SEMI_SENIOR = "semi_senior"
    SENIOR = "senior"
    STAFF_PLUS = "staff_plus"
    UNSPECIFIED = "unspecified"


class Modality(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNSPECIFIED = "unspecified"


Tri = Literal["yes", "no", "unclear"]


class Salary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float | None = None
    max: float | None = None
    currency: str = Field(description="ISO 4217, ej. USD, ARS")
    period: Literal["hour", "month", "year"]


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(description="Requisito tal como lo pide el aviso, resumido")
    kind: Literal["must", "nice"]
    covered: Literal["yes", "partial", "no"]
    evidence: list[str] = Field(
        default=[], description="IDs de logros o skills del perfil que lo cubren"
    )


class JobAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_family: RoleFamily
    seniority: Seniority
    years_required_min: int | None = Field(ge=0, le=30)
    modality: Modality
    work_location: str = Field(description="Ciudad/país si es híbrido o presencial; vacío si es remoto")
    remote_accepts_argentina: Tri
    salary: Salary | None
    posting_language: Literal["es", "en"]
    english_required: Tri
    requirements: list[Requirement]
    stack: list[str]
    blockers: list[str] = Field(description="Motivos concretos por los que no conviene postularse")
    fit_score: int = Field(ge=0, le=100)
    rationale: str = Field(description="2 a 4 oraciones: por qué ese puntaje")


class Preferences(BaseModel):
    """Lo que busca el candidato. El ejemplo versionado está en examples/."""

    model_config = ConfigDict(extra="forbid")
    home_city_keywords: list[str] = Field(
        description="Híbrido o presencial solo se acepta si la ubicación menciona alguna"
    )
    remote_ok: bool = True
    salary_floor_usd_month: float | None = None
    fx_to_usd: dict[str, float] = Field(
        default={}, description="Unidades de moneda por 1 USD, ej. {'ARS': 1400}"
    )
    max_years_required: int = 5
    excluded_role_families: list[RoleFamily] = []
    apply_threshold: int = 70
    maybe_threshold: int = 50
    title_include: list[str] = Field(description="Regex: el título tiene que matchear alguna")
    title_exclude: list[str] = Field(description="Regex: si matchea alguna, se descarta")
