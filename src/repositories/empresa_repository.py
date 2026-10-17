from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import Empresa, EmpresaSocio, Pessoa, PermissaoSocio
from models.base import new_uuid
from repositories.base_repository import BaseRepository, is_uuid


class EmpresaRepository(BaseRepository):
    """Pessoa, empresa, sócios e permissões."""

    # ── pessoa ──────────────────────────────────────────────────────

    def get_pessoa(self, pessoa_id: str):
        return self.get_by_id(Pessoa, Pessoa.pessoa_id, pessoa_id)

    def upsert_pessoa(self, cpf: str, nome: str, email: str, data_nascimento: date) -> Pessoa:
        """Cria a pessoa ou reaproveita a que já tem este CPF.

        O ON CONFLICT DO NOTHING resolve a corrida de dois cadastros que
        trazem o mesmo sócio novo ao mesmo tempo: o segundo espera o primeiro
        e simplesmente reaproveita a linha. (O e-mail repetido com CPF
        diferente continua violando uq_pessoa_email, e vira 409.)
        """
        statement = (
            pg_insert(Pessoa)
            .values(pessoa_id=new_uuid(), cpf=cpf, nome=nome, email=email, data_nascimento=data_nascimento)
            .on_conflict_do_nothing(index_elements=["cpf"])
        )
        self.session.execute(statement)

        return self.session.query(Pessoa).filter(Pessoa.cpf == cpf).populate_existing().one()

    # ── empresa ─────────────────────────────────────────────────────

    def get_empresa(self, empresa_id: str, lock: bool = False):
        return self.get_by_id(Empresa, Empresa.empresa_id, empresa_id, lock=lock)

    def exists_cnpj_or_razao_social(self, cnpj: str, razao_social_key: str) -> bool:
        normalized = func.lower(func.regexp_replace(func.btrim(Empresa.razao_social), r"\s+", " ", "g"))
        query = self.session.query(Empresa.empresa_id).filter((Empresa.cnpj == cnpj) | (normalized == razao_social_key))

        return query.first() is not None

    def add_empresa(self, cnpj: str, razao_social: str) -> Empresa:
        return self.add(Empresa(cnpj=cnpj, razao_social=razao_social))

    # ── sócios ──────────────────────────────────────────────────────

    def add_socio(self, empresa_id: str, pessoa_id: str, papel: str, participacao_bp: int) -> EmpresaSocio:
        socio = EmpresaSocio(empresa_id=empresa_id, pessoa_id=pessoa_id, papel=papel, participacao_bp=participacao_bp)

        return self.add(socio)

    def get_socio(self, empresa_socio_id: str):
        return self.get_by_id(EmpresaSocio, EmpresaSocio.empresa_socio_id, empresa_socio_id)

    def get_socio_da_empresa(self, empresa_id: str, empresa_socio_id: str):
        socio = self.get_socio(empresa_socio_id)

        if socio is None or socio.empresa_id != str(empresa_id):
            return None

        return socio

    def get_socio_by_pessoa(self, empresa_id: str, pessoa_id: str):
        return (
            self.session.query(EmpresaSocio)
            .filter(EmpresaSocio.empresa_id == empresa_id, EmpresaSocio.pessoa_id == pessoa_id)
            .one_or_none()
        )

    def list_socios(self, empresa_id: str) -> list:
        """Os sócios da empresa com a pessoa de cada um: [(EmpresaSocio, Pessoa)]."""
        return (
            self.session.query(EmpresaSocio, Pessoa)
            .join(Pessoa, Pessoa.pessoa_id == EmpresaSocio.pessoa_id)
            .filter(EmpresaSocio.empresa_id == empresa_id)
            .order_by(Pessoa.nome, EmpresaSocio.empresa_socio_id)
            .all()
        )

    def get_nome_do_socio(self, empresa_socio_id):
        if empresa_socio_id is None or not is_uuid(empresa_socio_id):
            return None

        return (
            self.session.query(Pessoa.nome)
            .join(EmpresaSocio, EmpresaSocio.pessoa_id == Pessoa.pessoa_id)
            .filter(EmpresaSocio.empresa_socio_id == empresa_socio_id)
            .scalar()
        )

    # ── permissões ──────────────────────────────────────────────────

    def add_permissao(self, empresa_socio_id: str, acao: str, escopo: str, limite) -> PermissaoSocio:
        permissao = PermissaoSocio(
            empresa_socio_id=empresa_socio_id, acao=acao, escopo=escopo, limite_transacao_centavos=limite
        )

        return self.add(permissao)

    def get_permissao(self, empresa_socio_id: str, acao: str):
        return (
            self.session.query(PermissaoSocio)
            .filter(PermissaoSocio.empresa_socio_id == empresa_socio_id, PermissaoSocio.acao == acao)
            .populate_existing()
            .one_or_none()
        )

    def list_permissoes(self, empresa_socio_id: str) -> list:
        return (
            self.session.query(PermissaoSocio)
            .filter(PermissaoSocio.empresa_socio_id == empresa_socio_id)
            .order_by(PermissaoSocio.acao)
            .all()
        )

    def delete_permissao(self, permissao: PermissaoSocio) -> None:
        self.session.delete(permissao)
        self.session.flush()

    def count_com_permissao(self, empresa_id: str, acao: str) -> int:
        """Quantos sócios da empresa têm a ação (usado para não deixar a
        empresa sem nenhum gestor de governança)."""
        return (
            self.session.query(PermissaoSocio.permissao_id)
            .join(EmpresaSocio, EmpresaSocio.empresa_socio_id == PermissaoSocio.empresa_socio_id)
            .filter(EmpresaSocio.empresa_id == empresa_id, PermissaoSocio.acao == acao)
            .count()
        )

    def list_aprovadores(self, empresa_id: str) -> list:
        """Os sócios com a permissão APROVAR: [(EmpresaSocio, PermissaoSocio)]."""
        return (
            self.session.query(EmpresaSocio, PermissaoSocio)
            .join(PermissaoSocio, PermissaoSocio.empresa_socio_id == EmpresaSocio.empresa_socio_id)
            .filter(EmpresaSocio.empresa_id == empresa_id, PermissaoSocio.acao == PermissaoSocio.APROVAR)
            .populate_existing()
            .all()
        )
