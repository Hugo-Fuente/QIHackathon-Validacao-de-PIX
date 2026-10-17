import re
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator

class OwnerSchema(BaseModel):
    document_number: str

    @field_validator("document_number")
    @classmethod
    def clean_document(cls, v: str) -> str:
        # Limpa tudo o que não for número (pontos, traços, barras)
        # Assim 123.456.789-09 vira 12345678909
        return re.sub(r"[^\d]", "", v)

class SourceAccountSchema(BaseModel):
    branch: str
    account_number: str
    opening_date: datetime
    owner: OwnerSchema

class DestinationAccountSchema(BaseModel):
    participant: str
    branch: str
    account_number: str
    opening_date: datetime
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

# Este é o Schema que devolvemos como resposta (O payload de Saída do PDF)
class PixTransactionOutput(BaseModel):
    key: str
    status: str
    metadata: Dict[str, Any] = {}