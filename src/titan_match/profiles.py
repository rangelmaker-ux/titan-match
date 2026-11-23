"""Profiles de câmera e as transformações Input CST / Output CST.

Espaço de trabalho: DaVinci Wide Gamut / DaVinci Intermediate (DWG/DI).
Saída: Rec.709 Gamma 2.4 com o tone mapping "DaVinci" do Color Space Transform (padrão do CST de
saída), medido no DaVinci Resolve 21: uma curva por canal no DaVinci Wide Gamut, antes da matriz
para Rec.709 (tabela TM_DISPLAY). Entradas também conferidas no DaVinci (ExportLUT), perfil a perfil.

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
# Tone mapping "DaVinci" do CST de saída (DWG/DI -> Rec.709/Gamma 2.4), medido no DaVinci 21:
# valor exibido (Gamma 2.4) de um cinza com código DI = linspace(0, 1, 65). Aplicado por canal no
# DaVinci Wide Gamut, antes da matriz para Rec.709 (modelo conferido no LUT exportado: erro 0,0).
TM_DISPLAY = np.array([
    0.0, 0.069078, 0.092241, 0.110872, 0.128023, 0.144472, 0.160678, 0.176883, 0.193286, 0.21001,
    0.227161, 0.244846, 0.263111, 0.282017, 0.30161, 0.321935, 0.343008, 0.364828, 0.387427, 0.410773,
    0.434821, 0.459541, 0.484871, 0.510704, 0.536965, 0.563516, 0.590234, 0.616938, 0.643473, 0.669673,
    0.695354, 0.720348, 0.744488, 0.767636, 0.789654, 0.810452, 0.829938, 0.848066, 0.864836, 0.880217,
    0.89424, 0.906981, 0.918456, 0.928771, 0.937972, 0.946181, 0.953445, 0.959869, 0.96553, 0.970504,
    0.974853, 0.978668, 0.981994, 0.984909, 0.987427, 0.989624, 0.991531, 0.993194, 0.994629, 0.99588,
    0.996963, 0.997894, 0.998703, 0.99939, 1.0])
_TM_X = np.linspace(0.0, 1.0, TM_DISPLAY.size)
_TM_LIN = cs.gamma24_decode(TM_DISPLAY)

# Matrizes câmera -> DWG (linear) medidas no CST do DaVinci quando diferem das primárias publicadas.
# "Sony SGamut3.Cine Venice" no DaVinci é bem menos saturado que o S-Gamut3.Cine comum.
MATRIX_TO_DWG: dict[str, np.ndarray] = {
    "sony_slog3_venice": np.array([[0.562764, 0.323515, 0.113714],
                                   [0.077753, 0.749574, 0.172665],
                                   [0.064668, 0.191996, 0.743328]]),
}


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
    m = MATRIX_TO_DWG.get(profile.key)
    lin_dwg = cs.apply_matrix(m if m is not None else cs.gamut_matrix(profile.gamut, WORKING_GAMUT), lin)
    return cs.di_encode(lin_dwg)


def output_cst(working: np.ndarray) -> np.ndarray:
    """DWG/DI -> Rec.709 Gamma 2.4 (display), em [0, 1], como o CST de saída do DaVinci."""
    t = np.interp(np.clip(working, 0.0, 1.0), _TM_X, _TM_LIN)
    lin = cs.apply_matrix(cs.gamut_matrix(WORKING_GAMUT, OUTPUT_GAMUT), t)
    return np.clip(cs.gamma24_encode(np.clip(lin, 0.0, None)), 0.0, 1.0)


def display_to_working(display: np.ndarray) -> np.ndarray:
    """Inverso de output_cst (dentro do gamut Rec.709).

    Usado para levar a imagem de referência (já renderizada) ao espaço de trabalho: a comparação
    nunca é feita log x imagem renderizada.
    """
    lin709 = cs.gamma24_decode(np.clip(display, 0.0, 1.0))
    t = cs.apply_matrix(cs.gamut_matrix(OUTPUT_GAMUT, WORKING_GAMUT), lin709)
    return np.interp(np.clip(t, 0.0, 1.0), _TM_LIN, _TM_X)


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
