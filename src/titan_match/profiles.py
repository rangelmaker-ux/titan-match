"""Profiles de câmera e as transformações Input CST / Output CST.

Espaço de trabalho: DaVinci Wide Gamut / DaVinci Intermediate (DWG/DI).
Saída: Rec.709 Gamma 2.4 com um ombro suave (invertível) acima de KNEE. No DaVinci a saída é o
Color Space Transform nativo (DWG/DI -> Rec.709 / Gamma 2.4); o LUT .cube fica de reserva.

As mesmas funções geram os LUTs .cube de reserva e as estatísticas da análise, então o que é
medido é o que é aplicado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import colorspaces as cs

WORKING_GAMUT = "DaVinci Wide Gamut"
OUTPUT_GAMUT = "Rec.709"
# Ombro suave acima de KNEE na simulação da saída. Só mexe nos 20% mais claros; sem ele, o branco
# estourado da referência fica irrecuperável e o match piora muito (teste: erro de cor 3 -> 6).
KNEE = 0.8


@dataclass(frozen=True)
class CameraProfile:
    key: str
    label: str
    decode: Callable[[np.ndarray], np.ndarray]
    gamut: str
    brand: str = "Outros"
    note: str = ""


_P = CameraProfile
PROFILES: dict[str, CameraProfile] = {
    p.key: p
    for p in [
        # Sony
        _P("sony_slog3", "S-Log3 / S-Gamut3.Cine", cs.slog3_decode, "S-Gamut3.Cine", "Sony"),
        _P("sony_slog3_sg3", "S-Log3 / S-Gamut3", cs.slog3_decode, "S-Gamut3", "Sony"),
        _P("sony_slog3_venice", "S-Log3 / Venice S-Gamut3.Cine", cs.slog3_decode, "Venice S-Gamut3.Cine", "Sony"),
        _P("sony_slog2", "S-Log2 / S-Gamut", cs.slog2_decode, "S-Gamut3", "Sony", "S-Gamut tem as mesmas primárias do S-Gamut3"),
        # Canon
        _P("canon_clog3", "C-Log3 / Cinema Gamut", cs.clog3_decode, "Cinema Gamut", "Canon"),
        _P("canon_clog2", "C-Log2 / Cinema Gamut", cs.clog2_decode, "Cinema Gamut", "Canon"),
        _P("canon_clog_cg", "C-Log / Cinema Gamut", cs.clog_decode, "Cinema Gamut", "Canon"),
        _P("canon_clog_709", "C-Log / BT.709", cs.clog_decode, "Rec.709", "Canon", "Canon Log em câmeras sem Cinema Gamut"),
        # Panasonic Lumix
        _P("panasonic_vlog", "V-Log / V-Log L / V-Gamut", cs.vlog_decode, "V-Gamut", "Panasonic Lumix"),
        # Fujifilm
        _P("fuji_flog", "F-Log / F-Gamut", cs.flog_decode, "Rec.2020", "Fujifilm", "F-Gamut = Rec.2020"),
        _P("fuji_flog2", "F-Log2 / F-Gamut", cs.flog2_decode, "Rec.2020", "Fujifilm"),
        _P("fuji_flog2c", "F-Log2 C / F-Gamut C", cs.flog2_decode, "F-Gamut C", "Fujifilm"),
        # Nikon
        _P("nikon_nlog", "N-Log / N-Gamut", cs.nlog_decode, "Rec.2020", "Nikon", "N-Gamut = Rec.2020"),
        # DJI
        _P("dji_dlog", "D-Log / D-Gamut", cs.dlog_decode, "D-Gamut", "DJI"),
        # GoPro
        _P("gopro_protune", "Protune Flat / Protune Native", cs.protune_decode, "Protune Native", "GoPro"),
        # Apple
        _P("apple_log", "Apple Log / Rec.2020 (iPhone)", cs.apple_log_decode, "Rec.2020", "Apple"),
        # Leica
        _P("leica_llog", "L-Log / Rec.2020", cs.llog_decode, "Rec.2020", "Leica", "gamut Rec.2020 assumido (não verificado)"),
        # Blackmagic
        _P("bmd_film_gen5", "Blackmagic Film Gen 5 / BMD Wide Gamut", cs.bmdfilm_gen5_decode, "Blackmagic Wide Gamut", "Blackmagic"),
        # ARRI
        _P("arri_logc3", "LogC3 (EI 800) / AWG3", cs.logc3_decode, "ARRI Wide Gamut 3", "ARRI"),
        _P("arri_logc4", "LogC4 / AWG4", cs.logc4_decode, "ARRI Wide Gamut 4", "ARRI"),
        # RED
        _P("red_log3g10", "Log3G10 / REDWideGamutRGB", cs.log3g10_decode, "REDWideGamutRGB", "RED"),
        # Sem log
        _P("rec709", "Rec.709 Gamma 2.4 (sem log)", cs.gamma24_decode, "Rec.709", "Outros"),
    ]
}


def brands() -> list[str]:
    return list(dict.fromkeys(p.brand for p in PROFILES.values()))


def profiles_for_brand(brand: str) -> list[CameraProfile]:
    return [p for p in PROFILES.values() if p.brand == brand]


def full_label(p: CameraProfile) -> str:
    return f"{p.brand} — {p.label}"

_DWG_TO_XYZ = cs.rgb_to_xyz_matrix(WORKING_GAMUT)
DWG_LUMA = _DWG_TO_XYZ[1].copy()  # pesos de Y para DWG linear


def get_profile(key: str) -> CameraProfile:
    try:
        return PROFILES[key]
    except KeyError:
        raise ValueError(f"Profile desconhecido: {key!r}. Opções: {', '.join(PROFILES)}") from None


def input_cst(log_rgb: np.ndarray, profile: CameraProfile) -> np.ndarray:
    """Footage codificado no profile da câmera -> DWG/DI."""
    lin = profile.decode(log_rgb)
    lin_dwg = cs.apply_matrix(cs.gamut_matrix(profile.gamut, WORKING_GAMUT), lin)
    return cs.di_encode(lin_dwg)


def _shoulder(x):
    k = KNEE
    if k >= 1.0:
        return np.minimum(x, 1.0)
    return np.where(x <= k, x, k + (1 - k) * (1 - np.exp(-(x - k) / (1 - k))))


def _shoulder_inv(y):
    k = KNEE
    if k >= 1.0:
        return np.minimum(y, 1.0)
    y = np.minimum(y, 0.99999)
    return np.where(y <= k, y, k - (1 - k) * np.log(1 - (y - k) / (1 - k)))


def output_cst(working: np.ndarray) -> np.ndarray:
    """DWG/DI -> Rec.709 Gamma 2.4 (display), em [0, 1]."""
    lin = cs.apply_matrix(cs.gamut_matrix(WORKING_GAMUT, OUTPUT_GAMUT), cs.di_decode(working))
    return np.clip(cs.gamma24_encode(_shoulder(np.clip(lin, 0.0, None))), 0.0, 1.0)


def display_to_working(display: np.ndarray) -> np.ndarray:
    """Inverso exato de output_cst para valores dentro do gamut Rec.709.

    Usado para levar a imagem de referência (já renderizada) ao espaço de
    trabalho: a comparação nunca é feita log x imagem renderizada.
    """
    lin709 = _shoulder_inv(cs.gamma24_decode(np.clip(display, 0.0, 1.0)))
    return cs.di_encode(cs.apply_matrix(cs.gamut_matrix(OUTPUT_GAMUT, WORKING_GAMUT), lin709))


def working_to_lab(working: np.ndarray) -> np.ndarray:
    """DWG/DI -> CIE Lab (D65). Y=1 normalizado ao branco de difusão 100%."""
    xyz = cs.apply_matrix(_DWG_TO_XYZ, np.clip(cs.di_decode(working), 0.0, None))
    return cs.xyz_to_lab(xyz)


def lab_to_working(lab: np.ndarray) -> np.ndarray:
    xyz = cs.lab_to_xyz(lab)
    return cs.di_encode(cs.apply_matrix(np.linalg.inv(_DWG_TO_XYZ), xyz))


def working_luma(working: np.ndarray) -> np.ndarray:
    """Luma no domínio DI (pesos Y do DWG sobre os valores codificados)."""
    return np.einsum("...c,c->...", working, DWG_LUMA)
