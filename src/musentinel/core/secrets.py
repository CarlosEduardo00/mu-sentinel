"""Segredos (chaves de API, tokens) no Gerenciador de Credenciais do Windows via keyring.

Nada daqui vai para YAML, log, export de perfil ou mensagem de erro.
"""

from __future__ import annotations

import logging

SERVICE = "MUSentinel"
log = logging.getLogger(__name__)


def get_secret(key: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE, key)
    except Exception as exc:  # backend do keyring indisponível
        log.warning("keyring indisponível ao ler %s: %s", key, type(exc).__name__)
        return None


def set_secret(key: str, value: str) -> None:
    import keyring

    keyring.set_password(SERVICE, key, value)


def delete_secret(key: str) -> None:
    try:
        import keyring

        keyring.delete_password(SERVICE, key)
    except Exception:
        pass


def has_secret(key: str) -> bool:
    return bool(get_secret(key))
