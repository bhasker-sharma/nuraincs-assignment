from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9_.:-]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class WBC(_Strict):
    value: float = Field(ge=0, le=500, allow_inf_nan=False)
    unit: Literal["10^3/uL"]


class RBC(_Strict):
    value: float = Field(ge=0, le=20, allow_inf_nan=False)
    unit: Literal["10^6/uL"]


class Hb(_Strict):
    value: float = Field(ge=0, le=30, allow_inf_nan=False)
    unit: Literal["g/dL"]

class Measurements(_Strict):
    wbc: WBC
    rbc: RBC
    hb: Hb


class RecordIn(_Strict):
    event_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    device_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    sample_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    sequence: int = Field(ge=0)
    measured_at: datetime
    measurements: Measurements

    @field_validator("measured_at")
    @classmethod
    def must_be_utc_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("measured_at must include a timezone")
        return v.astimezone(timezone.utc)
    
class ItemResult(BaseModel):
    event_id: str
    status: Literal["created", "duplicate", "conflict"]


class IngestResponse(BaseModel):
    received_at: datetime
    results: list[ItemResult]


class RecordOut(BaseModel):
    event_id: str
    device_id: str
    sample_id: str
    sequence: int
    measured_at: datetime
    received_at: datetime
    measurements: Measurements