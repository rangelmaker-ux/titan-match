"""Contexto HTTPS comum (loja e GitHub).

O Python portátil do Mac não usa o Keychain: sem um arquivo de certificados ele não
valida HTTPS. Ordem: certifi (vai junto no instalador) → padrão do sistema →
/private/etc/ssl/cert.pem (raízes do macOS).
"""
from __future__ import annotations

import os
import ssl

_MAC_PEM = "/private/etc/ssl/cert.pem"


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        ctx.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001
        pass
    if os.path.isfile(_MAC_PEM):
        try:
            ctx.load_verify_locations(_MAC_PEM)
        except (OSError, ssl.SSLError):
            pass
    return ctx
