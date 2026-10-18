import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Literal
from pydantic import (
    BaseModel, ConfigDict, Field, StrictInt, StrictStr,
    field_validator, model_validator,
)

class OwnerSchema(BaseModel):
    document_number: str

    @field_validator("document_number")
    @classmethod
    def clean_document(cls, v: str) -> str:
        # Limpa tudo o que não for número (pontos, traços, barras)
        # Assim 123.456.789-09 vira 12345678909
        document = re.sub(r"[^\d]", "", v)
        if len(document) not in (11, 14):
            raise ValueError("document_number must contain 11 or 14 digits")
        return document

class SourceAccountSchema(BaseModel):
    branch: str
    account_number: str
    opening_date: Optional[datetime] = None
    owner: OwnerSchema

class DestinationAccountSchema(BaseModel):
    participant: str
    branch: str
    account_number: str
    opening_date: Optional[datetime] = None
    owner: OwnerSchema

class GeolocationSchema(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

class SourceSchema(BaseModel):
    device_id: str
    channel: str
    ip: str
    geolocation: Optional[GeolocationSchema] = None


class OperationalApprovalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partner_id: StrictStr = Field(..., min_length=1)
    approved_at: datetime

    @field_validator("approved_at")
    @classmethod
    def approval_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operational profile approval timestamps must include a timezone")
        return value.astimezone(timezone.utc)


class OperationalProfileSchema(BaseModel):
    """Immutable EPP snapshot; each approved change increments ``version``."""

    model_config = ConfigDict(extra="forbid")

    profile_id: StrictStr = Field(..., min_length=1)
    version: StrictInt = Field(..., ge=1)
    operation_type: Literal["payroll"]
    status: Literal["active", "inactive", "revoked"]
    company_id: StrictStr = Field(..., min_length=1)
    responsibility_id: StrictStr = Field(..., min_length=1)
    max_payment_cents: StrictInt = Field(..., gt=0)
    max_batch_cents: StrictInt = Field(..., gt=0)
    approvals: list[OperationalApprovalSchema] = Field(..., min_length=1)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def profile_expiration_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("operational profile expiration must include a timezone")
        return value.astimezone(timezone.utc)


class OperationalProfileReferenceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: StrictStr = Field(..., min_length=1)
    version: StrictInt = Field(..., ge=1)
    status: Literal["active", "inactive", "revoked"]

# Este é o Schema que recebe a requisição (O payload de Entrada do PDF)
class PixTransactionInput(BaseModel):
    id: str
    amount: int = Field(..., gt=0, description="Valor em centavos deve ser maior que zero")
    transaction_date: datetime
    source_account: SourceAccountSchema
    destination_account: DestinationAccountSchema
    source: SourceSchema
    context: Optional[Dict[str, Any]] = None

    @field_validator("transaction_date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("transaction_date must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_context(self):
        if self.context is None:
            return self

        event = self.context.get("event")
        if event not in ("request", "vote", "execution"):
            raise ValueError("context.event must be request, vote, or execution")
        if not self.context.get("author_id"):
            raise ValueError("context.author_id is required")
        if event in ("vote", "execution") and (
            not self.context.get("request_id") or not self.context.get("request_hash")
        ):
            raise ValueError("context.request_id and context.request_hash are required")
        if "operational_profile" in self.context:
            if event != "request" or self.context.get("origin") != "scheduled":
                raise ValueError("context.operational_profile is only valid on scheduled requests")
            operational_profile = OperationalProfileSchema.model_validate(self.context["operational_profile"])
            if (
                operational_profile.company_id != self.context.get("company_id")
                or operational_profile.responsibility_id != self.context.get("responsibility_id")
            ):
                raise ValueError("operational profile company and responsibility must match context")
            if not self.context.get("batch_id"):
                raise ValueError("context.batch_id is required for an operational profile")
            batch_total = self.context.get("batch_total_cents")
            if type(batch_total) is not int or batch_total <= 0:
                raise ValueError("context.batch_total_cents must be a positive integer")
            if type(self.context.get("beneficiary_authorized")) is not bool:
                raise ValueError("context.beneficiary_authorized must be a boolean")
        if "operational_profile_ref" in self.context:
            if event != "execution" or self.context.get("origin") != "scheduled":
                raise ValueError("context.operational_profile_ref is only valid on scheduled executions")
            OperationalProfileReferenceSchema.model_validate(self.context["operational_profile_ref"])
            if not self.context.get("batch_id"):
                raise ValueError("context.batch_id is required for a profiled payroll execution")
            batch_total = self.context.get("batch_total_cents")
            if type(batch_total) is not int or batch_total <= 0:
                raise ValueError("context.batch_total_cents must be a positive integer")
        return self

# Este é o Schema que devolvemos como resposta (O payload de Saída do PDF)
class PixTransactionOutput(BaseModel):
    key: str
    status: str
    metadata: Dict[str, Any] = {}
