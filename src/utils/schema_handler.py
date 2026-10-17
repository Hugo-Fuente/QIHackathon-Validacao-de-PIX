import functools
import json
import os

from jsonschema import RefResolver, ValidationError, validate

from constants import SCHEMA_PATH
from errors import InvalidSchema


class SchemaCache:
    """Cache em memória dos schemas lidos do disco (um por processo)."""

    schemas = {}

    @staticmethod
    def get_schema(schema_file_name: str) -> dict:
        schema_path = os.path.join(SCHEMA_PATH, schema_file_name)

        if schema_path in SchemaCache.schemas:
            return SchemaCache.schemas[schema_path]

        if not os.path.isfile(schema_path):
            raise Exception(
                f"Nao encontrei o schema '{schema_file_name}' em {SCHEMA_PATH}. "
                + "Ou o arquivo nao existe, ou o nome escrito na rota esta diferente."
            )

        with open(schema_path, "r", encoding="utf-8") as arquivo:
            schema = json.loads(arquivo.read())

        SchemaCache.schemas[schema_path] = schema

        return schema


class SchemaHandler:
    """Valida corpo e query string contra arquivos JSON Schema em src/schemas/.

    O contrato fica em um arquivo JSON Schema, legível por quem integra com
    a API. Em troca, o corpo chega como dict e não como objeto tipado.
    """

    @staticmethod
    def validate(schema_file_name: str):
        """Decorator: valida o parâmetro `payload` antes de executar o método.

        Uso:
            @SchemaHandler.validate("post_empresa.json")
            def on_post(self, payload: dict, ...): ...
        """

        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                if "payload" not in kwargs:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o SchemaHandler, mas nao "
                        + "tem um parametro chamado 'payload'. E de la que sai o corpo a validar."
                    )

                schema = SchemaCache.get_schema(schema_file_name)
                resolver = RefResolver(f"file://{SCHEMA_PATH}/", None)

                try:
                    validate(kwargs["payload"], schema, resolver=resolver)
                except ValidationError as error:
                    raise InvalidSchema(describe_schema_error(error))

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate

    @staticmethod
    def validate_query_params(schema_file_name: str):
        """Decorator: valida a query string do parâmetro `request`.

        Lê a query crua (e não os parâmetros declarados no FastAPI) para que
        `additionalProperties: false` rejeite parâmetros desconhecidos. Campos
        declarados como "array" no schema são lidos com `getlist`.

        Uso:
            @SchemaHandler.validate_query_params("get_extrato.json")
            def on_get(self, request: Request, ...): ...
        """

        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                request = kwargs.get("request")
                if request is None:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o validate_query_params, mas "
                        + "nao tem um parametro chamado 'request'. E de la que sai a query string."
                    )

                schema = SchemaCache.get_schema(schema_file_name)
                resolver = RefResolver(f"file://{SCHEMA_PATH}/", None)
                query_params = query_params_to_dict(request.query_params, schema)

                try:
                    validate(query_params, schema, resolver=resolver)
                except ValidationError as error:
                    raise InvalidSchema(describe_schema_error(error))

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate


def query_params_to_dict(query_params, schema: dict) -> dict:
    """Converte a query string em dict, lendo como lista os campos "array" do schema.

    Campos ausentes são omitidos, para não falharem a validação de tipo.
    """
    properties = schema.get("properties", {})
    parsed_params = {}

    for param_name in query_params.keys():
        declared = properties.get(param_name, {})

        if declared.get("type") == "array":
            parsed_params[param_name] = query_params.getlist(param_name)
        else:
            parsed_params[param_name] = query_params[param_name]

    return parsed_params


def describe_schema_error(error: ValidationError) -> str:
    """Mensagem do erro de schema, com o caminho do campo quando aninhado."""
    location = []
    for part in error.absolute_path:
        location.append(str(part))

    if location:
        return f"{error.message} in {'.'.join(location)}"

    return error.message
