import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator

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
        return self

# Este é o Schema que devolvemos como resposta (O payload de Saída do PDF)
class PixTransactionOutput(BaseModel):
    key: str
    status: str
    metadata: Dict[str, Any] = {}
