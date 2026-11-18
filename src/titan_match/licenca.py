"""Licença do Titan Match pela Titan Loja (mesmo padrão do Titan Color).

O plugin envia {chave, dispositivo, produto, versao} para a loja. O dispositivo é o ID da
máquina (Windows: MachineGuid; macOS: IOPlatformUUID), com prefixo do produto/sistema.
A resposta esperada está em docs/LOJA_ENDPOINT.md.

Uso offline: depois de ativado, o plugin revalida a cada VERIFY_EVERY; se a loja não responder,
continua funcionando até GRACE sem verificação bem-sucedida.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .paths import IS_MAC, IS_WIN, user_data_dir

API = "https://titan-loja.pages.dev/api/match-licenca"
PRODUCT_ID = "titan-match"
VERIFY_EVERY = 3 * 24 * 3600
GRACE = 14 * 24 * 3600

# Enquanto o endpoint /api/match-licenca não existir na loja, a licença não é exigida.
# Ligar (True) só depois que a loja responder conforme docs/LOJA_ENDPOINT.md.
ENFORCE_LICENSE = False


class LicenseError(RuntimeError):
    pass


@dataclass
class LicenseState:
    valid: bool
    reason: str
    nome: str = ""
    expira_em: float | None = None
    enforced: bool = ENFORCE_LICENSE


def license_path() -> Path:
    return user_data_dir() / "licenca.json"


def device_id() -> str:
    """ID estável da máquina, com prefixo do produto (como o Titan Color usa 'color-win-')."""
    try:
        if IS_WIN:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return "match-win-" + winreg.QueryValueEx(k, "MachineGuid")[0]
        if IS_MAC:
            out = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return "match-mac-" + line.split("=")[-1].strip().strip('"')
    except Exception:  # noqa: BLE001
        pass
    import uuid

    return "match-other-" + hex(uuid.getnode())[2:]


def _load() -> dict:
    try:
        return json.loads(license_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    p = license_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _post(payload: dict, poster=None) -> dict:
    if poster is not None:
        return poster(payload)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8", "User-Agent": f"Titan-Match/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read(64 * 1024))
    except urllib.error.HTTPError as e:  # a loja responde {"erro": "..."} com status 4xx
        try:
            return json.loads(e.read(64 * 1024))
        except Exception:  # noqa: BLE001
            raise LicenseError(f"Loja respondeu {e.code}.") from e


def activate(chave: str, poster=None, now: float | None = None) -> LicenseState:
    """Ativa a chave neste computador (precisa de internet)."""
    chave = (chave or "").strip()
    if not chave:
        raise LicenseError("Digite a chave da Titan Loja.")
    now = time.time() if now is None else now
    resp = _post({"acao": "ativar", "chave": chave, "dispositivo": device_id(), "produto": PRODUCT_ID,
                  "versao": __version__}, poster)
    if not resp.get("ok"):
        raise LicenseError(resp.get("erro") or "Chave inválida.")
    d = {"chave": chave, "dispositivo": device_id(), "nome": resp.get("nome", ""), "ativado_em": now,
         "verificado_em": now, "expira_em": resp.get("expira_em")}
    _save(d)
    return LicenseState(True, "Licença ativada.", d["nome"], d["expira_em"])


def status(poster=None, now: float | None = None, online: bool = True) -> LicenseState:
    """Estado atual; revalida na loja quando passou VERIFY_EVERY."""
    now = time.time() if now is None else now
    d = _load()
    if not d.get("chave"):
        return LicenseState(not ENFORCE_LICENSE, "Licença não ativada.")
    if d.get("expira_em") and now > float(d["expira_em"]):
        return LicenseState(not ENFORCE_LICENSE, "Licença expirada.", d.get("nome", ""), d.get("expira_em"))
    last = float(d.get("verificado_em") or 0)
    if online and now - last >= VERIFY_EVERY:
        try:
            resp = _post({"acao": "verificar", "chave": d["chave"], "dispositivo": device_id(),
                          "produto": PRODUCT_ID, "versao": __version__}, poster)
            if resp.get("ok"):
                d["verificado_em"] = now
                d["expira_em"] = resp.get("expira_em", d.get("expira_em"))
                d["nome"] = resp.get("nome", d.get("nome", ""))
                _save(d)
                last = now
            else:
                return LicenseState(not ENFORCE_LICENSE, resp.get("erro") or "Licença recusada pela loja.",
                                    d.get("nome", ""))
        except Exception:  # noqa: BLE001  (sem internet / loja fora: usa a carência)
            pass
    if now - last > GRACE:
        return LicenseState(not ENFORCE_LICENSE, "Conecte à internet para revalidar a licença.", d.get("nome", ""))
    return LicenseState(True, "Licença ativa.", d.get("nome", ""), d.get("expira_em"))


def deactivate() -> None:
    try:
        license_path().unlink()
    except OSError:
        pass
