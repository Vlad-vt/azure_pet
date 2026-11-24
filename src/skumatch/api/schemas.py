"""Public API contracts (Pydantic v2)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from skumatch.retrieval import MatchMode


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=512, examples=["MILSA. Speisequark MAGERSTUFE 250g"])
    top_k: int = Field(default=5, ge=1, le=50)
    mode: MatchMode = MatchMode.HYBRID


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=512)


class BatchMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BatchItem] = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=20)
    mode: MatchMode = MatchMode.HYBRID


class SkuOut(BaseModel):
    id: int
    ean: str
    name: str
    brand: str
    quantity_raw: str
    quantity: str
    category: str
    category_path: str | None = None


class CandidateOut(BaseModel):
    sku: SkuOut
    score: float = Field(description="Weighted RRF score (higher is better)")
    ranks: dict[str, int] = Field(description="1-based rank per retriever that returned the SKU")
    unit_match: bool | None = Field(
        description="Pack size equals the quantity parsed from the line (null: none parsed)"
    )


class MatchResponse(BaseModel):
    query_normalized: str
    query_quantity: str | None
    mode: MatchMode
    candidates: list[CandidateOut]
    timings_ms: dict[str, float]


class BatchResultOut(BaseModel):
    id: str
    result: MatchResponse


class BatchMatchResponse(BaseModel):
    results: list[BatchResultOut]
    timings_ms: dict[str, float]


class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, str] = Field(default_factory=dict)
