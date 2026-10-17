from sqlalchemy.exc import IntegrityError


def violated_constraint(error: IntegrityError) -> str:
    """O nome da restrição que o banco recusou (uq_empresa_cnpj, por exemplo).

    É por esse nome que o controller sabe QUAL regra de negócio a corrida
    violou e responde 409 — em vez de um 500 genérico. Daí todas as UNIQUE
    do database.sql terem nome.
    """
    diag = getattr(error.orig, "diag", None)

    return getattr(diag, "constraint_name", None) or ""
