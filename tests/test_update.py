"""Atualizador: verificação de release, integridade, arquivos permitidos, backup e rollback."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from titan_match import update


def _release(tag="v9.9.9", digest="sha256:" + "a" * 64, name=update.ASSET,
             url="https://github.com/rangelmaker-ux/titan-match/releases/download/v9.9.9/Titan-Match-Update.zip"):
    return {"tag_name": tag, "draft": False, "prerelease": False,
            "assets": [{"name": name, "digest": digest, "browser_download_url": url}]}


def test_check_states():
    assert update.check("1.0.0", fetch=lambda: _release("v1.0.0"))[0] == "current"
    st, rel = update.check("1.0.0", fetch=lambda: _release())
    assert st == "available" and rel.version == "9.9.9" and len(rel.sha256) == 64
    assert update.check("1.0.0", fetch=lambda: _release(digest=""))[0] == "unavailable"
    assert update.check("1.0.0", fetch=lambda: _release(url="https://evil.example/x.zip"))[0] == "error"


def test_allowed_url_rejects_other_repos_and_hosts():
    update.allowed_url("https://api.github.com/repos/rangelmaker-ux/titan-match/releases/latest")
    for bad in ("http://github.com/rangelmaker-ux/titan-match/releases/x",
                "https://github.com/outro/repo/releases/x",
                "https://evil.com/rangelmaker-ux/titan-match/releases/x"):
        with pytest.raises(update.UpdateError):
            update.allowed_url(bad)


def _make_app(root: Path, ver="0.1.0"):
    (root / "titan_match").mkdir(parents=True)
    (root / "titan_match" / "__init__.py").write_text(f'__version__ = "{ver}"\n')
    (root / "titan_match" / "ui.py").write_text("x = 1\n")
    (root / "templates").mkdir()
    (root / "templates" / "a.json").write_text("{}")
    (root / "VERSION").write_text(ver + "\n")
    (root / update.INSTALLER_VERSION_FILE).write_text("0.1.0\n")


def test_build_validate_install_and_backup(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    pkg = update.build_package(repo, tmp_path / "up.zip", "9.9.9")
    manifest, data = update.validate_package(pkg, "9.9.9")
    assert "titan_match/ui.py" in data and "templates/TitanMatch_cinema.drx" in data
    app = tmp_path / "app"
    _make_app(app)
    backup = update.install_package(pkg, "9.9.9", root=app, backups=tmp_path / "bk")
    assert (app / "VERSION").read_text().strip() == "9.9.9"
    assert (backup / "VERSION").read_text().strip() == "0.1.0"  # backup da versão anterior
    with pytest.raises(update.UpdateError):
        update.validate_package(pkg, "9.9.8")  # versão diferente da anunciada


def _tamper(src: Path, dst: Path, name: str, content: bytes, fix_hash: bool):
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    m = json.loads(items["manifest.json"])
    items[name] = content
    if fix_hash:
        m["files"][name] = hashlib.sha256(content).hexdigest()
    items["manifest.json"] = json.dumps(m).encode()
    with zipfile.ZipFile(dst, "w") as z:
        for k, v in items.items():
            z.writestr(k, v)
    return dst


def test_rejects_tampered_and_forbidden_files(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    pkg = update.build_package(repo, tmp_path / "up.zip", "9.9.9")
    bad_hash = _tamper(pkg, tmp_path / "b1.zip", "titan_match/ui.py", b"x = 2\n", fix_hash=False)
    with pytest.raises(update.UpdateError, match="integridade"):
        update.validate_package(bad_hash, "9.9.9")
    forbidden = _tamper(pkg, tmp_path / "b2.zip", "../../malware.py", b"x=1\n", fix_hash=True)
    with pytest.raises(update.UpdateError):
        update.validate_package(forbidden, "9.9.9")
    bad_py = _tamper(pkg, tmp_path / "b3.zip", "titan_match/ui.py", b"def (\n", fix_hash=True)
    with pytest.raises(SyntaxError):
        update.validate_package(bad_py, "9.9.9")


def test_installer_requirement_blocks_update(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    pkg = update.build_package(repo, tmp_path / "up.zip", "9.9.9", min_installer="2.0.0")
    app = tmp_path / "app"
    _make_app(app)
    with pytest.raises(update.UpdateError, match="instalador"):
        update.install_package(pkg, "9.9.9", root=app, backups=tmp_path / "bk")
    assert (app / "VERSION").read_text().strip() == "0.1.0"  # nada mudou
