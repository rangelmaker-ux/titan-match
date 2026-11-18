"""Mapeamento diferença-estatística -> CDL de um nó.

Cada função recebe as estatísticas do footage (no ponto da cadeia em que o
nó está) e da referência, e devolve a correção daquele nó com a origem de
cada número registrada. Todos os valores operam no domínio DWG/DI, onde
os nós 02–09 ficam (entre o Input CST e o Output CST).
"""
from __future__ import annotations

import math

import numpy as np

from . import profiles as pf
from .cdl import CDL, apply_cdl
from .nodes import NodeCorrection, Provenance
from .stats import ImageStats

LIMITS = {
    "contrast_slope": (0.5, 2.0),
    "lift_slope": (0.5, 1.5),
    "gamma_power": (0.6, 1.6),
    "gain_slope": (0.5, 2.0),
    "wb_offset": (-0.15, 0.15),
    "balance_offset": (-0.10, 0.10),
    "saturation": (0.0, 2.0),
}
EPS = 1e-4


def _r(x, n=4):
    if isinstance(x, (list, tuple, np.ndarray)) and np.ndim(x) > 0:
        return [round(float(v), n) for v in x]
    return round(float(x), n)


def _clamp(name: str, value, notes: list[str]):
    lo, hi = LIMITS[name]
    arr = np.asarray(value, dtype=float)
    clamped = np.clip(arr, lo, hi)
    if not np.allclose(arr, clamped):
        notes.append(f"{name} limitado de {_r(arr)} para {_r(clamped)} (faixa segura {lo}..{hi})")
    return clamped


def _luma_neutral(offsets: np.ndarray) -> np.ndarray:
    """Remove a componente de luma para que o nó só mexa em cor."""
    return offsets - float(np.dot(offsets, pf.DWG_LUMA))


# --------------------------------------------------------------- 02 White Balance

TEMP_AXIS = np.array([-1.0, 0.0, 1.0])  # + = mais azul (mais frio)
TINT_AXIS = np.array([-0.5, 1.0, -0.5])  # + = mais verde


def map_white_balance(cur: ImageStats, ref: ImageStats) -> NodeCorrection:
    def dev(s: ImageStats, z: str):
        m = s.zones[z].rgb_mean
        return m - float(np.dot(m, pf.DWG_LUMA))

    delta = np.mean([dev(ref, z) - dev(cur, z) for z in ("midtones", "highlights")], axis=0)
    basis = np.stack([TEMP_AXIS, TINT_AXIS], axis=1)
    (temp, tint), *_ = np.linalg.lstsq(basis, delta, rcond=None)
    notes: list[str] = []
    offsets = _clamp("wb_offset", _luma_neutral(temp * TEMP_AXIS + tint * TINT_AXIS), notes)
    prov = [
        Provenance(
            "temperatura (eixo B-R, DI)",
            "mínimos quadrados de Δ(RGB−Y) médios+altas sobre eixos temp/tint",
            {"delta_rgb_minus_Y": _r(delta), "cct_footage_K": _r(cur.cct_kelvin, 0), "cct_ref_K": _r(ref.cct_kelvin, 0)},
            note=f"temp={temp:+.4f} ({'mais frio' if temp > 0 else 'mais quente'})",
        ),
        Provenance(
            "tint (eixo G-M, DI)",
            "mesmo ajuste de mínimos quadrados",
            {"a_medios_footage": _r(cur.tint_duv_proxy, 3), "a_medios_ref": _r(ref.tint_duv_proxy, 3)},
            note=f"tint={tint:+.4f} ({'mais verde' if tint > 0 else 'mais magenta'})",
        ),
        Provenance("offset RGB", "temp*(-1,0,1) + tint*(-.5,1,-.5), luma neutralizada", {"offset": _r(offsets)}),
    ]
    return NodeCorrection("white_balance", CDL(offset=tuple(offsets)), prov, notes=notes)


# --------------------------------------------------------------- 03 Exposure & Contraste

def map_exposure_contrast(cur: ImageStats, ref: ImageStats) -> NodeCorrection:
    cp, rp = cur.luma_percentiles, ref.luma_percentiles
    notes: list[str] = []
    raw_slope = (rp[90] - rp[10]) / max(cp[90] - cp[10], EPS)
    slope = float(_clamp("contrast_slope", raw_slope, notes))
    pivot = cp[50]
    offset = rp[50] - slope * pivot
    prov = [
        Provenance(
            "contraste (slope)",
            "(ref_p90 − ref_p10) / (footage_p90 − footage_p10) da luma DI",
            {"footage_p10": _r(cp[10]), "footage_p90": _r(cp[90]), "ref_p10": _r(rp[10]), "ref_p90": _r(rp[90])},
        ),
        Provenance(
            "pivot / exposição (offset)",
            "offset = ref_p50 − slope × footage_p50 (pivot na mediana do footage)",
            {"pivot_footage_p50": _r(pivot), "ref_p50": _r(rp[50]), "offset": _r(offset)},
        ),
    ]
    return NodeCorrection("exposure_contrast", CDL(slope=(slope,) * 3, offset=(offset,) * 3), prov, notes=notes)


# --------------------------------------------------------------- 04/05/06 Lift / Gamma / Gain

def map_lift(cur: ImageStats, ref: ImageStats) -> NodeCorrection:
    s, h = cur.zones["shadows"].rgb_mean, cur.zones["highlights"].rgb_mean
    st = ref.zones["shadows"].rgb_mean
    notes: list[str] = []
    slope = _clamp("lift_slope", (h - st) / np.maximum(h - s, EPS), notes)
    offset = h - slope * h  # altas ficam fixas
    prov = [
        Provenance(
            "lift por canal",
            "slope=(h − s_ref)/(h − s), offset=h − slope·h; pivô nas altas (médias DI por zona)",
            {"sombras_footage": _r(s), "sombras_ref": _r(st), "altas_footage(pivo)": _r(h)},
        )
    ]
    return NodeCorrection("shadows", CDL(slope=tuple(slope), offset=tuple(offset)), prov, notes=notes)


def map_gamma(cur: ImageStats, ref: ImageStats) -> NodeCorrection:
    m = np.clip(cur.zones["midtones"].rgb_mean, EPS, 1 - EPS)
    mt = np.clip(ref.zones["midtones"].rgb_mean, EPS, 1 - EPS)
    notes: list[str] = []
    power = _clamp("gamma_power", np.log(mt) / np.log(m), notes)
    prov = [
        Provenance(
            "gamma (power) por canal",
            "power = ln(médios_ref) / ln(médios_footage) (médias DI por zona)",
            {"medios_footage": _r(m), "medios_ref": _r(mt)},
        )
    ]
    return NodeCorrection("midtones", CDL(power=tuple(power)), prov, notes=notes)


def map_gain(cur: ImageStats, ref: ImageStats) -> NodeCorrection:
    s, h = cur.zones["shadows"].rgb_mean, cur.zones["highlights"].rgb_mean
    ht = ref.zones["highlights"].rgb_mean
    notes: list[str] = []
    slope = _clamp("gain_slope", (ht - s) / np.maximum(h - s, EPS), notes)
    offset = s - slope * s  # sombras ficam fixas
    prov = [
        Provenance(
            "gain por canal",
            "slope=(h_ref − s)/(h − s), offset=s − slope·s; pivô nas sombras",
            {"altas_footage": _r(h), "altas_ref": _r(ht), "sombras_footage(pivo)": _r(s)},
        )
    ]
    return NodeCorrection("highlights", CDL(slope=tuple(slope), offset=tuple(offset)), prov, notes=notes)


# --------------------------------------------------------------- 07 Color Balance

def map_color_balance(cur: ImageStats, ref: ImageStats, sat_hint: float = 1.0) -> NodeCorrection:
    """sat_hint: saturação que o nó 08 vai aplicar depois; como ela escala a*/b*,
    o alvo aqui é ref_ab / sat_hint para o resultado final cair na referência."""
    cur_lab = cur.mean_lab
    sat_hint = max(float(sat_hint), 0.2)
    target_lab = np.array([cur_lab[0], ref.mean_lab[1] / sat_hint, ref.mean_lab[2] / sat_hint])
    cur_rgb = pf.lab_to_working(cur_lab[None])[0]
    tgt_rgb = pf.lab_to_working(target_lab[None])[0]
    notes: list[str] = []
    offsets = _clamp("balance_offset", _luma_neutral(tgt_rgb - cur_rgb), notes)
    hue_cur = math.degrees(math.atan2(cur_lab[2], cur_lab[1])) % 360
    hue_ref = math.degrees(math.atan2(ref.mean_lab[2], ref.mean_lab[1])) % 360
    prov = [
        Provenance(
            "balanço a*/b* (offset RGB)",
            "Lab médio do footage com a*/b* da referência ÷ saturação do nó 08 -> DWG/DI; Δ com luma neutralizada",
            {"lab_footage": _r(cur_lab, 3), "lab_ref": _r(ref.mean_lab, 3), "sat_hint_no08": _r(sat_hint, 4),
             "offset": _r(offsets)},
            note=f"ângulo de hue médio footage {hue_cur:.1f}° vs ref {hue_ref:.1f}°",
        )
    ]
    notes.append("CDL não faz rotação de hue; o hue shift é aproximado por deslocamento do eixo a*/b*.")
    return NodeCorrection("color_balance", CDL(offset=tuple(offsets)), prov, notes=notes)


# --------------------------------------------------------------- 08 Saturação

def map_saturation(cur: ImageStats, ref: ImageStats, cur_image: np.ndarray | None = None,
                   exclude: np.ndarray | None = None) -> NodeCorrection:
    """Saturação global; razões por zona ficam registradas (CDL só tem 1 escalar)."""
    from .stats import compute_stats  # evita import circular

    zone_ratio = {
        z: _r(ref.zones[z].chroma_mean / max(cur.zones[z].chroma_mean, EPS), 3) for z in ("shadows", "midtones", "highlights")
    }
    target = ref.mean_chroma
    ratio = target / max(cur.mean_chroma, EPS)
    sat = ratio
    method = "razão de croma médio (ref/footage)"
    if cur_image is not None and cur.mean_chroma > EPS:
        # Busca por bisseção do escalar CDL que iguala o croma médio simulado.
        # Amostra fixa de até 40 mil pixels (mesma máscara de exclusão): só o croma médio
        # é recalculado em cada passo, em vez de todas as estatísticas da imagem.
        px = np.asarray(cur_image, dtype=np.float64).reshape(-1, 3)
        if exclude is not None:
            keep = ~np.asarray(exclude, dtype=bool).reshape(-1)
            if keep.mean() >= 0.05:
                px = px[keep]
        px = np.clip(px[:: max(1, len(px) // 40000)], 0.0, 1.0)

        def mean_chroma(s: float) -> float:
            lab = pf.working_to_lab(apply_cdl(px, CDL(saturation=s)))
            return float(np.hypot(lab[:, 1], lab[:, 2]).mean())

        lo, hi = 0.0, 2.0
        for _ in range(18):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if mean_chroma(mid) < target else (lo, mid)
        sat = (lo + hi) / 2
        method = "bisseção sobre o croma médio Lab simulado até igualar o da referência"
    notes: list[str] = []
    sat = float(_clamp("saturation", sat, notes))
    spread = max(zone_ratio.values()) - min(zone_ratio.values())
    if spread > 0.25:
        notes.append(
            f"Razões de saturação por zona divergem ({zone_ratio}); saturação por faixa de luminância "
            "precisa de curva Lum vs Sat, que a API não permite escrever. Aplicado só o valor global."
        )
    prov = [
        Provenance(
            "saturação CDL",
            method,
            {"croma_footage": _r(cur.mean_chroma, 3), "croma_ref": _r(target, 3), "razao_por_zona": zone_ratio},
        )
    ]
    return NodeCorrection("saturation", CDL(saturation=sat), prov, notes=notes)


# --------------------------------------------------------------- SKIN (proteção de pele)

SKIN_AMBIENCE_DEFAULT = 0.35  # quanto da cor do ambiente a pele recebe (0 = pele original, 1 = igual ao resto)
SKIN_VIVID = 1.08  # croma da pele no mínimo 8 % acima do original ("pele viva")
SKIN_LINE_HUE = 55.0  # graus Lab: linha de tom de pele (a "skin tone line" do vectorscope)
SKIN_HUE_TOL = 20.0  # a ambiência pode girar o tom da pele no máximo isso a partir da linha
SKIN_MIN_CHROMA = 14.0  # croma natural mínimo de pele (Lab), reduzido conforme a ambiência


def map_skin(graded: np.ndarray, original: np.ndarray, mask: np.ndarray,
             ambience: float = SKIN_AMBIENCE_DEFAULT) -> NodeCorrection:
    """Pele com ambiência parcial e viva.

    O tom (a*/b*) alvo da pele é uma mistura: `ambience` da pele graduada (cor do ambiente)
    + (1 − ambience) da pele original após o Input CST. O croma alvo nunca fica abaixo do
    croma original × SKIN_VIVID. Luminância: a do grade.
    Implementado no nó SKIN como offset (tom) + saturação (vida), só dentro da chave de pele.
    graded/original: imagens DI (HxWx3) depois e antes das correções; mask: pele (HxW).
    """
    notes: list[str] = ["No Resolve a área é a chave de pele calculada no material ORIGINAL (nó SKIN KEY "
                        "→ entrada de chave do SKIN); a simulação usa a máscara Lab do Titan, que é uma aproximação."]
    if mask.mean() < 0.005:
        return NodeCorrection("skin", CDL(), [], enabled=False, notes=["Sem pele suficiente na imagem: nó desligado."])
    amb = float(np.clip(ambience, 0.0, 1.0))
    g_px, o_px = np.clip(graded[mask], 0, 1), np.clip(original[mask], 0, 1)
    lab_g = pf.working_to_lab(g_px).mean(axis=0)
    lab_o = pf.working_to_lab(o_px).mean(axis=0)
    ab_t = amb * lab_g[1:] + (1 - amb) * lab_o[1:]
    c_orig = float(np.hypot(*lab_o[1:]))
    # Piso de "pele viva": 108 % do croma original até 35 % de ambiência; acima disso o piso cai
    # junto (quem pede mais ambiência aceita a pele mais próxima do ambiente).
    vivid = SKIN_VIVID * (1.0 - max(0.0, amb - SKIN_AMBIENCE_DEFAULT))
    c_floor = SKIN_MIN_CHROMA * (1.0 - amb)
    c_t = max(float(np.hypot(*ab_t)), c_orig * vivid, c_floor)
    hue_mix = math.degrees(math.atan2(ab_t[1], ab_t[0]))
    dh = (hue_mix - SKIN_LINE_HUE + 180.0) % 360.0 - 180.0
    hue_t = SKIN_LINE_HUE + float(np.clip(dh, -SKIN_HUE_TOL, SKIN_HUE_TOL))
    ab_t = np.array([math.cos(math.radians(hue_t)), math.sin(math.radians(hue_t))]) * c_t
    target = np.array([lab_g[0], ab_t[0], ab_t[1]])
    cur_rgb = pf.lab_to_working(lab_g[None])[0]
    tgt_rgb = pf.lab_to_working(target[None])[0]
    lim_notes: list[str] = []
    offsets = np.clip(_luma_neutral(tgt_rgb - cur_rgb), -0.18, 0.18)
    if not np.allclose(offsets, _luma_neutral(tgt_rgb - cur_rgb)):
        lim_notes.append("offset da pele limitado a ±0.18")

    # Saturação do nó: bisseção no croma médio da pele (já com o offset) até o croma alvo.
    px = g_px[:: max(1, len(g_px) // 20000)]

    def chroma(s: float) -> float:
        lab = pf.working_to_lab(apply_cdl(px, CDL(offset=tuple(offsets), saturation=s)))
        return float(np.hypot(lab[:, 1], lab[:, 2]).mean())

    lo, hi = 0.5, 2.0
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if chroma(mid) < c_t else (lo, mid)
    sat = float(np.clip((lo + hi) / 2, 0.5, 2.0))
    prov = [
        Provenance(
            "tom da pele (offset RGB)",
            f"a*/b* alvo = {round(amb * 100)} % pele graduada (ambiente) + {round((1 - amb) * 100)} % pele original "
            "(após Input CST) → DWG/DI; luma neutralizada",
            {"pele_graduada_lab": _r(lab_g, 3), "pele_original_lab": _r(lab_o, 3), "ab_alvo": _r(ab_t, 3),
             "tom_mistura_graus": _r(hue_mix, 1), "tom_alvo_graus": _r(hue_t, 1),
             "linha_de_pele_graus": SKIN_LINE_HUE,
             "pele_fracao": _r(float(mask.mean()), 4), "offset": _r(offsets)}),
        Provenance(
            "vida da pele (saturação)",
            f"bisseção até croma alvo = max(croma da mistura, croma original × {round(vivid, 3)}, "
            f"croma natural mínimo {round(c_floor, 1)}); tom limitado a ±{SKIN_HUE_TOL}° da linha de pele",
            {"croma_original": _r(c_orig, 3), "croma_graduado": _r(float(np.hypot(*lab_g[1:])), 3),
             "croma_alvo": _r(c_t, 3), "saturacao": _r(sat, 4)}),
    ]
    return NodeCorrection("skin", CDL(offset=tuple(offsets), saturation=sat), prov, notes=notes + lim_notes)

# --------------------------------------------------------------- 09 Look

def map_look(enabled: bool) -> NodeCorrection:
    notes = [
        "Nó neutro (CDL identidade): nenhum parâmetro derivado de estatística.",
        "Grain e halation são ResolveFX/OFX e a API não permite adicioná-los; adicione manualmente neste nó.",
    ]
    if not enabled:
        notes.append("Flag de film emulation desligada: o nó é criado desabilitado.")
    return NodeCorrection("look", CDL(), [], enabled=enabled, notes=notes)
