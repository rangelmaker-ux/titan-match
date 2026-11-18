"""Geração de LUTs .cube para os nós de CST (Input e Output)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import numpy as np

from . import profiles as pf

LUT_SIZE = 33
LUT_SUBFOLDER = "Titan Match"


def lut_grid(size: int = LUT_SIZE) -> np.ndarray:
    """Grade em ordem .cube (R varia mais rápido)."""
    v = np.linspace(0.0, 1.0, size)
    b, g, r = np.meshgrid(v, v, v, indexing="ij")
    return np.stack([r, g, b], axis=-1).reshape(-1, 3)


def write_cube(path: str | os.PathLike, fn: Callable[[np.ndarray], np.ndarray], title: str, size: int = LUT_SIZE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.clip(fn(lut_grid(size)), 0.0, 1.0)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(f'TITLE "{title}"\n# Gerado por Titan Match\nLUT_3D_SIZE {size}\n')
        f.write("DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n")
        for r, g, b in out:
            f.write(f"{r:.6f} {g:.6f} {b:.6f}\n")
    return path


def read_cube(path: str | os.PathLike) -> tuple[int, np.ndarray]:
    size, rows = 0, []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line[0] == "#" or line.startswith(("TITLE", "DOMAIN")):
            continue
        if line.startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
            continue
        rows.append([float(x) for x in line.split()])
    return size, np.asarray(rows)


def apply_cube(table: np.ndarray, size: int, rgb: np.ndarray) -> np.ndarray:
    """Interpolação trilinear (para testes/preview)."""
    lut = table.reshape(size, size, size, 3)  # [b, g, r]
    x = np.clip(rgb, 0, 1) * (size - 1)
    i0 = np.floor(x).astype(int).clip(0, size - 2)
    f = x - i0
    out = np.zeros_like(rgb, dtype=np.float64)
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = (
                    (f[..., 0] if dr else 1 - f[..., 0])
                    * (f[..., 1] if dg else 1 - f[..., 1])
                    * (f[..., 2] if db else 1 - f[..., 2])
                )
                out += w[..., None] * lut[i0[..., 2] + db, i0[..., 1] + dg, i0[..., 0] + dr]
    return out


MASTER_LUT_ROOT_WIN = Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT")


def default_lut_root() -> Path:
    """Pasta mestre de LUTs do Resolve no Windows.

    Medido no Resolve 21.1.2: SetLUT falha com LUTs em %APPDATA%\\...\\Support\\LUT
    (a pasta não é varrida por padrão), mas funciona na pasta mestre em ProgramData
    depois de RefreshLUTList(). Se ela não for gravável, cai para %APPDATA%.
    """
    if MASTER_LUT_ROOT_WIN.is_dir() and os.access(MASTER_LUT_ROOT_WIN, os.W_OK):
        return MASTER_LUT_ROOT_WIN
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT"


def build_cst_luts(profile_key: str, out_dir: str | os.PathLike) -> dict[str, Path]:
    prof = pf.get_profile(profile_key)
    out_dir = Path(out_dir)
    inp = write_cube(out_dir / f"TitanMatch_Input_{profile_key}_to_DWG-DI.cube",
                     lambda x: pf.input_cst(x, prof), f"Titan Match Input CST {prof.brand} {prof.label} -> DWG/DI")
    outp = write_cube(out_dir / "TitanMatch_Output_DWG-DI_to_Rec709-G24.cube",
                      pf.output_cst, "Titan Match Output CST DWG/DI -> Rec.709 G2.4")
    return {"input_cst": inp, "output_cst": outp}
