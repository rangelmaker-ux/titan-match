"""Atualizações do Titan Match por GitHub Releases (mesmo modelo do Titan Titles Studio).

Fluxo: consulta a última release pública → baixa só de hosts do GitHub → confere o sha256 do
pacote (campo `digest` da API) e de cada arquivo (manifest.json) → aceita só arquivos do app
→ faz backup → instala → em qualquer erro, restaura o backup.

O Python embutido e as bibliotecas NÃO são trocados por aqui: se uma versão precisar de um
instalador novo, o manifesto traz `min_installer` e o plugin pede para baixar o instalador.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .net import ssl_context
from .paths import app_root, user_data_dir

REPO = "rangelmaker-ux/titan-match"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "Titan-Match-Update.zip"
PRODUCT = "Titan Match"
MAX_BYTES = 64 * 1024 * 1024
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                 "objects.githubusercontent.com"}
ALLOWED_FILE = re.compile(
    r"(?:VERSION|titan_match/(?:[a-z_]+/)?[a-z_]+\.py|templates/[A-Za-z0-9_.-]+\.(?:drx|json)"
    r"|assets/[A-Za-z0-9_.-]+\.(?:png|ico))")
INSTALLER_VERSION_FILE = "INSTALLER_VERSION"


class UpdateError(RuntimeError):
    pass


def version(value: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value).strip())
    if not m:
        raise UpdateError(f"Versão inválida: {value!r}")
    return tuple(map(int, m.groups()))  # type: ignore[return-value]


def allowed_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password or p.port not in (None, 443):
        raise UpdateError("Endereço de atualização não permitido.")
    if p.hostname == "api.github.com" and not p.path.startswith(f"/repos/{REPO}/"):
        raise UpdateError("Repositório de atualização inválido.")
    if p.hostname == "github.com" and not p.path.startswith(f"/{REPO}/releases/"):
        raise UpdateError("Repositório de atualização inválido.")
    return url


def _ssl_context() -> ssl.SSLContext:
    return ssl_context()


def _open(url: str, accept: str = "application/vnd.github+json"):
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            allowed_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(Redirect(), urllib.request.HTTPSHandler(context=_ssl_context()))
    req = urllib.request.Request(allowed_url(url), headers={"User-Agent": "Titan-Match-Updater", "Accept": accept})
    return opener.open(req, timeout=15)


@dataclass
class Release:
    version: str
    url: str
    sha256: str
    notes: str = ""


def installed_layout() -> bool:
    """True quando roda da pasta instalada (não do repositório de desenvolvimento)."""
    return not (app_root() / ".git").exists() and not (app_root() / "src").exists()


def check(current: str = __version__, fetch=None) -> tuple[str, Release | None]:
    """('current'|'available'|'unavailable'|'error', Release)."""
    try:
        if fetch is None:
            with _open(API) as r:
                raw = r.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return "error", None
            rel = json.loads(raw)
        else:
            rel = fetch()
        if rel.get("draft") or rel.get("prerelease"):
            return "error", None
        tag = rel.get("tag_name", "")
        if version(tag) <= version(current):
            return "current", None
        asset = {a.get("name"): a for a in rel.get("assets", [])}.get(ASSET)
        digest = (asset or {}).get("digest") or ""
        if not asset or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            return "unavailable", None
        return "available", Release(tag.lstrip("v"), allowed_url(asset["browser_download_url"]), digest[7:],
                                    (rel.get("body") or "")[:2000])
    except Exception:  # noqa: BLE001
        return "error", None


def download(rel: Release, dest_dir: Path | None = None) -> Path:
    dest_dir = Path(dest_dir or tempfile.mkdtemp(prefix="titanmatch_up_"))
    path = dest_dir / ASSET
    h = hashlib.sha256()
    size = 0
    with _open(rel.url, accept="application/octet-stream") as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise UpdateError("Pacote grande demais.")
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != rel.sha256:
        raise UpdateError("Falha de integridade: o pacote baixado não confere com o GitHub.")
    return path


def validate_package(path: Path, expected_version: str) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise UpdateError("Pacote inválido ou muito grande.")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("product") != PRODUCT or manifest.get("version") != expected_version:
            raise UpdateError("Este pacote não corresponde à atualização esperada.")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files or set(names) != set(files) | {"manifest.json"}:
            raise UpdateError("Conteúdo do pacote inválido.")
        if not {"VERSION", "titan_match/__init__.py", "titan_match/ui.py"} <= set(files):
            raise UpdateError("Pacote incompleto.")
        data: dict[str, bytes] = {}
        for name, digest in files.items():
            if not ALLOWED_FILE.fullmatch(name) or ".." in name:
                raise UpdateError(f"Arquivo não permitido na atualização: {name}")
            content = z.read(name)
            if hashlib.sha256(content).hexdigest() != digest:
                raise UpdateError(f"Falha de integridade em {name}.")
            if name.endswith(".py"):
                ast.parse(content.decode("utf-8-sig"))  # só valida sintaxe; não executa
            data[name] = content
        if data["VERSION"].decode().strip() != expected_version:
            raise UpdateError("VERSION do pacote não confere.")
    return manifest, data


def needs_installer(manifest: dict, root: Path | None = None) -> bool:
    root = root or app_root()
    need = manifest.get("min_installer")
    if not need:
        return False
    try:
        have = (root / INSTALLER_VERSION_FILE).read_text().strip()
    except OSError:
        have = "0.0.0"
    return version(have) < version(need)


def install_package(path: Path, expected_version: str, root: Path | None = None,
                    backups: Path | None = None) -> Path:
    """Instala o pacote na pasta do app. Retorna a pasta de backup. Em erro, restaura e relança."""
    root = Path(root or app_root())
    manifest, data = validate_package(path, expected_version)
    if needs_installer(manifest, root):
        raise UpdateError("Esta versão precisa do instalador novo. Baixe o instalador na Titan Loja.")
    backups = Path(backups or (user_data_dir() / "backups"))
    backup = backups / f"{time.strftime('%Y%m%d-%H%M%S')}-antes-de-{expected_version}"
    backup.mkdir(parents=True, exist_ok=True)
    for part in ("titan_match", "templates", "assets", "VERSION"):
        src = root / part
        if src.is_dir():
            shutil.copytree(src, backup / part)
        elif src.is_file():
            shutil.copy2(src, backup / part)
    try:
        for name, content in data.items():
            dest = (root / name).resolve()
            if root.resolve() not in dest.parents:
                raise UpdateError("Destino inesperado.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".novo")
            tmp.write_bytes(content)
            tmp.replace(dest)
    except Exception:
        restore(backup, root)
        raise
    return backup


def restore(backup: Path, root: Path | None = None) -> None:
    root = Path(root or app_root())
    for part in ("titan_match", "templates", "assets"):
        if (backup / part).is_dir():
            shutil.copytree(backup / part, root / part, dirs_exist_ok=True)
    if (backup / "VERSION").is_file():
        shutil.copy2(backup / "VERSION", root / "VERSION")


def build_package(src_root: Path, out_path: Path, ver: str, min_installer: str | None = None) -> Path:
    """Monta o Titan-Match-Update.zip a partir do repositório (usado pelo script de release)."""
    files: dict[str, bytes] = {"VERSION": (ver + "\n").encode()}
    pkg = src_root / "src" / "titan_match"
    for p in sorted(pkg.rglob("*.py")):
        files["titan_match/" + p.relative_to(pkg).as_posix()] = p.read_bytes()
    for p in sorted((src_root / "templates").glob("*")):
        if p.suffix in (".drx", ".json"):
            files["templates/" + p.name] = p.read_bytes()
    for p in sorted((src_root / "assets").glob("*")):
        if p.suffix in (".png", ".ico") and not p.name.startswith("_"):
            files["assets/" + p.name] = p.read_bytes()
    manifest = {"product": PRODUCT, "version": ver,
                "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
    if min_installer:
        manifest["min_installer"] = min_installer
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return out_path


if __name__ == "__main__":  # python -m titan_match.update <versão>  → gera dist/Titan-Match-Update.zip
    root = Path(__file__).resolve().parents[2]
    v = sys.argv[1] if len(sys.argv) > 1 else __version__
    out = build_package(root, root / "dist" / ASSET, v)
    print(out, hashlib.sha256(out.read_bytes()).hexdigest())
