from typing import Optional

from fastapi import Header
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

# Os headers que várias rotas leem. O `alias` é o nome que o cliente escreve.
PESSOA_HEADER = Header(default=None, alias="X-Pessoa-Id")
IDEMPOTENCY_HEADER = Header(default=None, alias="Idempotency-Key")


def respond(content, status_code: int = http_status.HTTP_200_OK) -> JSONResponse:
    """O resource decide o status; o `jsonable_encoder` garante que data/uuid
    virem texto mesmo que um DTO esqueça de converter."""
    return JSONResponse(content=jsonable_encoder(content), status_code=status_code)


def created_or_replayed(content, created: bool) -> JSONResponse:
    """201 para o que foi criado agora; 200 para a retentativa idêntica de uma
    chave de idempotência (a mesma resposta, nada mudou)."""
    return respond(content, http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK)


__all__ = ["Optional", "PESSOA_HEADER", "IDEMPOTENCY_HEADER", "respond", "created_or_replayed", "http_status"]
