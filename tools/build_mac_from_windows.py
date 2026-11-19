"""Monta o instalador macOS do Titan Match SEM precisar de um Mac (roda no Windows/Linux).

    python tools/build_mac_from_windows.py            (Apple Silicon e Intel)
    python tools/build_mac_from_windows.py aarch64    (só um)

O que faz, para cada arquitetura:
  1. baixa o Python portátil para macOS (python-build-standalone, com Tkinter) e confere o SHA-256 oficial;
  2. baixa as bibliotecas (numpy, Pillow, opencv) já compiladas para macOS (wheels) com o pip;
  3. grava o ZIP direto, com permissões Unix (executáveis) e links simbólicos preservados,
     no mesmo formato que tools/build_mac.sh gera num Mac.
Saída: dist/Titan-Match-macOS-<arch>-<versão>.zip
"""
from __future__ import annotations

import hashlib
import io
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY_VERSION, PBS_DATE = "3.12.8", "20241219"
BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_DATE}"
CACHE = REPO / "build" / "mac-cache"
ROOT = "Titan-Match-macOS"
MACOS = [f"{v}_0" for v in range(11, 16)]  # macosx_11_0 … macosx_15_0
SKIP_PY = ("/lib/python3.12/test/", "/lib/python3.12/idlelib/", "/lib/python3.12/turtledemo/", "/__pycache__/")


def version() -> str:
    sys.path.insert(0, str(REPO / "src"))
    import titan_match

    return titan_match.__version__


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        print("baixando", url.rsplit("/", 1)[-1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.replace(dest)
    return dest


def python_tarball(arch: str) -> Path:
    name = f"cpython-{PY_VERSION}+{PBS_DATE}-{arch}-apple-darwin-install_only.tar.gz"
    tgz = fetch(f"{BASE}/{name}", CACHE / name)
    sums = fetch(f"{BASE}/SHA256SUMS", CACHE / f"SHA256SUMS-{PBS_DATE}").read_text()
    want = next(line.split()[0] for line in sums.splitlines() if line.strip().endswith(name))
    got = hashlib.sha256(tgz.read_bytes()).hexdigest()
    if got != want:
        tgz.unlink()
        raise SystemExit(f"SHA-256 do Python para Mac não confere ({name}).")
    return tgz


def wheels(arch: str) -> Path:
    plat = "arm64" if arch == "aarch64" else "x86_64"
    req = hashlib.sha256((REPO / "requirements.txt").read_bytes()).hexdigest()[:8]
    target = CACHE / f"site-packages-{arch}-{req}"
    if not target.exists():
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--target", str(target),
               "--only-binary=:all:", "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312",
               "-r", str(REPO / "requirements.txt")]
        for m in MACOS:
            cmd += ["--platform", f"macosx_{m}_{plat}", "--platform", f"macosx_{m}_universal2"]
        subprocess.run(cmd, check=True)
    return target


class Zip:
    def __init__(self, path: Path):
        self.z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6)

    def _info(self, name: str, mode: int) -> zipfile.ZipInfo:
        zi = zipfile.ZipInfo(name, date_time=(2026, 11, 18, 12, 0, 0))
        zi.create_system = 3  # Unix: o macOS respeita as permissões
        zi.external_attr = mode << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        return zi

    def file(self, name: str, data: bytes, executable: bool = False):
        self.z.writestr(self._info(name, stat.S_IFREG | (0o755 if executable else 0o644)), data)

    def link(self, name: str, target: str):
        zi = self._info(name, stat.S_IFLNK | 0o777)
        zi.compress_type = zipfile.ZIP_STORED
        self.z.writestr(zi, target)

    def tree(self, src: Path, dest: str):
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                self.file(f"{dest}/{p.relative_to(src).as_posix()}", p.read_bytes())

    def close(self):
        self.z.close()


def lf(p: Path) -> bytes:
    return p.read_bytes().replace(b"\r\n", b"\n")


def build(arch: str, ver: str) -> Path:
    tgz, site = python_tarball(arch), wheels(arch)
    out = REPO / "dist" / f"Titan-Match-macOS-{arch}-{ver}.zip"
    out.parent.mkdir(exist_ok=True)
    z = Zip(out)
    A = f"{ROOT}/Arquivos"
    # 1) Python portátil, com permissões e links do tar
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            name = m.name.lstrip("./")
            if not name.startswith("python/") or any(s in "/" + name + "/" for s in SKIP_PY):
                continue
            if m.issym():
                z.link(f"{A}/{name}", m.linkname)
            elif m.isfile():
                z.file(f"{A}/{name}", t.extractfile(m).read(), executable=bool(m.mode & 0o111))
    # 2) Bibliotecas para macOS
    z.tree(site, f"{A}/python/lib/python3.12/site-packages")
    # 3) App
    z.tree(REPO / "src" / "titan_match", f"{A}/app/titan_match")
    for p in sorted((REPO / "templates").glob("*")):
        if p.suffix in (".drx", ".json"):
            z.file(f"{A}/app/templates/{p.name}", p.read_bytes())
    for p in sorted((REPO / "assets").glob("*")):
        if p.is_file() and not p.name.startswith("_"):
            z.file(f"{A}/app/assets/{p.name}", p.read_bytes())
    z.file(f"{A}/app/VERSION", f"{ver}\n".encode())
    z.file(f"{A}/app/INSTALLER_VERSION", f"{ver}\n".encode())
    # 4) Instalador
    mac = REPO / "installer" / "mac"
    z.file(f"{A}/Titan Match.py", lf(mac / "Titan Match.py"))
    z.file(f"{ROOT}/Instalar_Titan_Match.command", lf(mac / "Instalar_Titan_Match.command"), executable=True)
    z.file(f"{ROOT}/LEIA-ME.txt", lf(mac / "LEIA-ME.txt"))
    z.close()
    print(f"OK: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    archs = sys.argv[1:] or ["aarch64", "x86_64"]
    v = version()
    for a in archs:
        build(a, v)
