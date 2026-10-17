from os import environ
from uuid import uuid4

from tests.utils.requisition import ClientRequisition

INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    """Uma chamada HTTP à API, devolvendo (status, json)."""

    @staticmethod
    def call(method, path, body=None, pessoa=None, key=None, params=None, token=True):
        headers = {}
        if token:
            headers["INTERNAL-TOKEN"] = INTERNAL_TOKEN
        if pessoa:
            headers["X-Pessoa-Id"] = pessoa
        if key:
            headers["Idempotency-Key"] = key
        r = ClientRequisition.send(method, path, payload=body, headers=headers, query_params=params)
        return r.response_status, r.response_json

    @staticmethod
    def new_key() -> str:
        return uuid4().hex
