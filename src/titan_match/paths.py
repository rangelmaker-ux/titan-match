"""Caminhos por sistema operacional (Windows e macOS).

Windows (medido no Resolve 21.1.2 desta máquina) e macOS (caminhos documentados pela
Blackmagic no README de scripting; NÃO verificados num Mac ainda).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
PRODUCT_DIR = "TitanMatch"


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def user_data_dir() -> Path:
    """Dados do usuário: licença, configuração, logs, backups de atualização."""
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")) / PRODUCT_DIR
    if IS_MAC:
        return _home() / "Library" / "Application Support" / PRODUCT_DIR
    return _home() / ".local" / "share" / PRODUCT_DIR


def install_dir() -> Path:
    """Onde o instalador coloca o produto (python embutido + app)."""
    return user_data_dir()


def log_dir() -> Path:
    if IS_MAC:
        return _home() / "Library" / "Logs" / PRODUCT_DIR
    return user_data_dir() / "Logs"


def resolve_scripts_dir(page: str = "Color") -> Path:
    """Pasta do menu Workspace > Scripts > <página> do DaVinci Resolve (por usuário)."""
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))
        return base / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / page
    if IS_MAC:
        return (_home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "Fusion"
                / "Scripts" / page)
    return _home() / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Scripts" / page


def lut_roots() -> list[Path]:
    """Pastas de LUT que o Resolve varre, na ordem de preferência.

    Medido no Windows: SetLUT só funcionou com LUTs na pasta mestre (ProgramData), não em %APPDATA%.
    """
    if IS_WIN:
        return [Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT"),
                Path(os.environ.get("APPDATA", "")) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT"]
    if IS_MAC:
        return [Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT"),
                _home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "LUT"]
    return [_home() / ".local" / "share" / "DaVinciResolve" / "LUT"]


def resolve_scripting() -> tuple[str, str]:
    """(RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB) padrão do sistema."""
    if IS_WIN:
        return (r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    if IS_MAC:
        return ("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
                "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so")
    return ("/opt/resolve/Developer/Scripting", "/opt/resolve/libs/Fusion/fusionscript.so")


def app_root() -> Path:
    """Raiz do app em execução (contém titan_match/, templates/, assets/)."""
    here = Path(__file__).resolve().parent  # .../titan_match
    # Em desenvolvimento: <repo>/src/titan_match → raiz do repo; instalado: <install>/app/titan_match → <install>/app
    return here.parents[1] if here.parent.name == "src" else here.parent
