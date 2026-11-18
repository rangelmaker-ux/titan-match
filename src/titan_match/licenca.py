"""Licença do Titan Match pela Titan Loja — o mesmo sistema de chaves dos outros apps Titan.

* Ativar:   POST {SITE}/api/ativar   {chave, produto: "match", dispositivo}
            -> {ok, valida_ate, atualizacoes, perfil_pendente}  |  4xx {erro}
            (1 chave = 1 computador; 409 = já ativada em outro computador)
* Revalidar: POST {SITE}/api/licenca {hash: sha256(CHAVE), produto: "match", dispositivo}
            -> {ok, valida_ate}  |  403 chave bloqueada/inválida, 409 não ativa neste computador

A chave em texto não fica guardada no computador: só o hash (é o que /api/licenca usa).
Como nos outros apps anuais da loja, licença vencida NÃO bloqueia o uso: o que está instalado
continua funcionando; só as atualizações param (vencimento + GRACE_DIAS da loja).
Sem internet, o plugin segue funcionando até GRACE desde a última revalidação.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .paths import IS_MAC, IS_WIN, user_data_dir

SITE = "https://titan-loja.pages.dev"
PRODUTO = "match"
VERIFY_EVERY = 3 * 24 * 3600
GRACE = 14 * 24 * 3600          # sem conseguir revalidar (offline)
UPDATE_GRACE_DIAS = 7           # igual a GRACE_DIAS da loja

# Liga a exigência da chave. Fica False até o produto "match" estar à venda na loja.
ENFORCE_LICENSE = False


class LicenseError(RuntimeError):
    pass


@dataclass
class LicenseState:
    valid: bool
    reason: str
    nome: str = ""
    expira_em: float | None = None      # vencimento da licença (unix), vindo da loja
    atualizacoes: bool = True           # licença em dia (com a espera da loja) -> pode atualizar
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


def normaliza(chave: str) -> str:
    return str(chave or "").strip().upper()


def key_hash(chave: str) -> str:
    return hashlib.sha256(normaliza(chave).encode("utf-8")).hexdigest()


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


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


def _post(rota: str, payload: dict, poster=None) -> tuple[int, dict]:
    """(status HTTP, corpo). `poster(rota, payload)` substitui a rede nos testes."""
    if poster is not None:
        return poster(rota, payload)
    req = urllib.request.Request(f"{SITE}/api/{rota}", data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": f"Titan-Match/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read(64 * 1024) or b"{}")
    except urllib.error.HTTPError as e:  # a loja responde {"erro": "..."} com 4xx
        try:
            return e.code, json.loads(e.read(64 * 1024) or b"{}")
        except ValueError:
            return e.code, {"erro": f"A loja respondeu {e.code}."}


def _updates_ok(expira: float | None, now: float) -> bool:
    return expira is None or now < expira + UPDATE_GRACE_DIAS * 86400


def activate(chave: str, poster=None, now: float | None = None) -> LicenseState:
    """Ativa a chave neste computador (precisa de internet)."""
    chave = normaliza(chave)
    if not chave:
        raise LicenseError("Digite a chave da Titan Loja.")
    now = time.time() if now is None else now
    try:
        code, resp = _post("ativar", {"chave": chave, "produto": PRODUTO, "dispositivo": device_id()}, poster)
    except OSError as e:
        raise LicenseError("Sem conexão com a Titan Loja. Confira a internet e tente de novo.") from e
    if code != 200 or not resp.get("ok"):
        raise LicenseError(resp.get("erro") or "Chave inválida.")
    expira = _ts(resp.get("valida_ate"))
    d = {"hash": key_hash(chave), "final": chave[-4:], "dispositivo": device_id(), "ativado_em": now,
         "verificado_em": now, "expira_em": expira}
    _save(d)
    return LicenseState(True, "Licença ativa.", f"chave final {d['final']}", expira, _updates_ok(expira, now))


def status(poster=None, now: float | None = None, online: bool = True) -> LicenseState:
    """Estado atual; revalida na loja quando passou VERIFY_EVERY."""
    now = time.time() if now is None else now
    d = _load()
    if not d.get("hash"):
        return LicenseState(not ENFORCE_LICENSE, "Licença não ativada.", atualizacoes=not ENFORCE_LICENSE)
    nome = f"chave final {d.get('final', '')}"
    last = float(d.get("verificado_em") or 0)
    if online and now - last >= VERIFY_EVERY:
        try:
            code, resp = _post("licenca", {"hash": d["hash"], "produto": PRODUTO, "dispositivo": device_id()}, poster)
        except Exception:  # noqa: BLE001  (sem internet / loja fora: usa a carência)
            code, resp = 0, {}
        if code == 200 and resp.get("ok"):
            d["verificado_em"] = now
            d["expira_em"] = _ts(resp.get("valida_ate")) or d.get("expira_em")
            _save(d)
            last = now
        elif code in (403, 409):  # chave bloqueada / liberada deste computador pela loja
            return LicenseState(not ENFORCE_LICENSE, resp.get("erro") or "Licença recusada pela loja.", nome,
                                atualizacoes=False)
    expira = d.get("expira_em")
    upd = _updates_ok(expira, now)
    if now - last > GRACE:
        return LicenseState(not ENFORCE_LICENSE, "Conecte à internet para revalidar a licença.", nome, expira, False)
    if expira and now > expira:
        return LicenseState(True, "Licença vencida: o plugin continua funcionando, sem novas versões.", nome,
                            expira, upd)
    return LicenseState(True, "Licença ativa.", nome, expira, upd)


def deactivate() -> None:
    try:
        license_path().unlink()
    except OSError:
        pass
