import hashlib
import json

MAX_KEY_LENGTH = 80


def request_hash(payload: dict) -> str:
    """O hash do corpo da requisição (sha256 em hexadecimal, 64 caracteres).

    É ele que separa uma RETENTATIVA legítima de um ABUSO da chave: a mesma
    chave com o mesmo corpo devolve o resultado já gravado (200); a mesma
    chave com corpo diferente é conflito (409).

    O JSON é canônico (chaves em ordem, sem espaços), então a ordem dos
    campos no corpo não muda o hash.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_valid_key(key) -> bool:
    return isinstance(key, str) and len(key.strip()) >= 1 and len(key) <= MAX_KEY_LENGTH
