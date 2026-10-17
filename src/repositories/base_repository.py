from uuid import UUID

from sqlalchemy.orm import Session

from database import Context


def is_uuid(value) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class BaseRepository:
    """O que todo repository tem em comum: a sessão do contexto e três atalhos.

    Nenhuma regra de negócio mora aqui nem nas filhas — elas buscam, guardam
    e travam; quem decide o que fazer com isso é o controller.
    """

    def __init__(self, context: Context) -> None:
        self.session: Session = context.db_session

    def flush(self) -> None:
        self.session.flush()

    def add(self, obj):
        """Grava já (flush, ainda sem commit): o id uuid fica disponível para
        a linha seguinte, e uma violação de UNIQUE/CHECK aparece AQUI — na
        linha que a causou — em vez de estourar só no commit."""
        self.session.add(obj)
        self.session.flush()
        return obj

    def get_by_id(self, model, pk_column, value, lock: bool = False):
        """Uma linha pela chave primária — ou None, inclusive quando o id nem é
        um uuid (um path /conta/abc vira 404, não 500).

        `lock=True` é o SELECT ... FOR UPDATE: trava a linha até o commit e,
        com `populate_existing`, SEMPRE relê o valor do banco — mesmo que o
        objeto já estivesse na sessão com um saldo de antes da espera pela
        trava. Ler depois de travar é a regra da RFC.
        """
        if not is_uuid(value):
            return None

        query = self.session.query(model).filter(pk_column == str(value))

        if lock:
            query = query.with_for_update().populate_existing()

        return query.one_or_none()
