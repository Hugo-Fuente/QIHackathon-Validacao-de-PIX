from uuid import uuid4

from sqlalchemy import Column, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


def new_uuid() -> str:
    return str(uuid4())


def uuid_pk() -> Column:
    """Chave primária uuid. O id nasce no Python (str), então o objeto já
    tem identidade antes mesmo do flush — e o banco ainda tem o DEFAULT
    gen_random_uuid() para quem inserir direto por SQL."""
    return Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)


def uuid_fk(target: str, **kwargs) -> Column:
    return Column(UUID(as_uuid=False), ForeignKey(target), **kwargs)


def now_default():
    """criado_em é clock_timestamp(), e não now(): now() congela no começo
    da transação, e o extrato precisa da hora em que a linha foi mesmo
    gravada — já sob a trava da conta, na ordem em que o saldo mudou."""
    return func.clock_timestamp()
