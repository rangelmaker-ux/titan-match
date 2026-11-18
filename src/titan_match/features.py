"""Medidas de imagem que decidem quais nós extras entram na árvore.

Tudo aqui é medida explícita com limiar documentado (heurística, não ML):
  * pele      -> fração de pixels na faixa de pele em Lab
  * ruído     -> desvio robusto do passa-alta da luma em áreas planas
  * grão      -> mesma medida na referência (grão de filme / textura)
  * glow      -> brilho do "anel" em volta das altas luzes, relativo à mediana
  * halation  -> avermelhamento (a*) desse anel
  * haze      -> neblina/fumaça no ar: dark channel (mínimo local entre canais) mais alto
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import profiles as pf

SKIN_HUE = (20.0, 75.0)  # graus Lab
SKIN_CHROMA = (8.0, 50.0)
SKIN_L = (15.0, 92.0)
SKIN_MIN_FRACTION = 0.03

NR_MIN_NOISE = 0.004
NR_RATIO = 1.5
GRAIN_MIN_NOISE = 0.003
GRAIN_RATIO = 1.3
GLOW_RATIO = 1.15
HALATION_A = 4.0
HIGHLIGHT_MIN_FRACTION = 0.003


def skin_mask(working: np.ndarray) -> np.ndarray:
    lab = pf.working_to_lab(np.clip(working, 0, 1))
    hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    return ((hue >= SKIN_HUE[0]) & (hue <= SKIN_HUE[1]) & (chroma >= SKIN_CHROMA[0]) & (chroma <= SKIN_CHROMA[1])
            & (lab[..., 0] >= SKIN_L[0]) & (lab[..., 0] <= SKIN_L[1]))


@dataclass
class SkinInfo:
    mask: np.ndarray  # HxW bool
    faces: list  # [(x, y, w, h)] na imagem de análise
    method: str  # "rosto" (cor aprendida no rosto) | "cor" (faixa fixa de pele)

    @property
    def present(self) -> bool:
        return bool(self.faces) or float(self.mask.mean()) >= SKIN_MIN_FRACTION


def detect_faces(display: np.ndarray) -> list:
    """Rostos (frontal + perfil) com as cascatas de Haar do OpenCV. Lista vazia se o OpenCV faltar."""
    try:
        import cv2
    except ImportError:
        return []
    gray = cv2.cvtColor((np.clip(display, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    h, w = gray.shape
    mins = max(14, int(min(h, w) * 0.035))
    found = []
    for name in ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"):
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for flip in (False, True) if "profile" in name else (False,):
            g = cv2.flip(gray, 1) if flip else gray
            for (x, y, fw, fh) in casc.detectMultiScale(g, scaleFactor=1.08, minNeighbors=5, minSize=(mins, mins)):
                if flip:
                    x = w - x - fw
                found.append((int(x), int(y), int(fw), int(fh)))
    # remove sobreposições (fica a maior)
    found.sort(key=lambda b: -b[2] * b[3])
    keep = []
    for b in found:
        if all(_iou(b, k) < 0.3 for k in keep):
            keep.append(b)
    return keep


def _iou(a, b) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    return inter / max(a[2] * a[3] + b[2] * b[3] - inter, 1)


def skin_info(working: np.ndarray, display: np.ndarray) -> SkinInfo:
    """Pele: se houver rosto, aprende a cor da pele DAQUELA pessoa no centro do rosto e
    procura pixels parecidos (braços, mãos), separando de parede bege; senão usa a faixa fixa."""
    faces = detect_faces(display)
    if not faces:
        return SkinInfo(skin_mask(working), [], "cor")
    lab = pf.working_to_lab(np.clip(working, 0, 1))
    h, w = lab.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    core = np.zeros((h, w), bool)
    face_area = np.zeros((h, w), bool)
    for (x, y, fw, fh) in faces:
        cx, cy = x + fw / 2, y + fh * 0.55
        core |= ((xx - cx) / (fw * 0.28)) ** 2 + ((yy - cy) / (fh * 0.30)) ** 2 <= 1  # bochechas/testa/nariz
        face_area |= ((xx - cx) / (fw * 0.45)) ** 2 + ((yy - (y + fh / 2)) / (fh * 0.55)) ** 2 <= 1
    sample = lab[core]
    ab = sample[:, 1:]
    mu = ab.mean(axis=0)
    cov = np.cov(ab.T) + np.eye(2) * 4.0  # regularização (≥ 2 unidades de a*/b*)
    inv = np.linalg.inv(cov)
    d = lab[..., 1:] - mu
    md2 = np.einsum("...i,ij,...j->...", d, inv, d)
    l_lo, l_hi = np.percentile(sample[:, 0], [3, 97])
    # Fundo: pixels fora da região das pessoas. O pixel só é pele se for mais parecido
    # com a pele do rosto do que com o fundo (separa parede bege de pele em footage dessaturado).
    body = np.zeros((h, w), bool)
    for (x, y, fw, fh) in faces:
        body |= (xx >= x - 2.5 * fw) & (xx <= x + 3.5 * fw) & (yy >= y - 0.3 * fh) & (yy <= y + 7.0 * fh)
    bg = lab[~body][:, 1:] if (~body).any() else lab.reshape(-1, 3)[:, 1:]
    mu_b = bg.mean(axis=0)
    inv_b = np.linalg.inv(np.cov(bg.T) + np.eye(2) * 4.0)
    db = lab[..., 1:] - mu_b
    md2_b = np.einsum("...i,ij,...j->...", db, inv_b, db)
    similar = ((md2 <= 2.5 ** 2) & (md2 < md2_b) & body
               & (lab[..., 0] >= l_lo - 12) & (lab[..., 0] <= l_hi + 12))
    # Abertura morfológica: tira pontinhos soltos (madeira, tecido) e mantém áreas contínuas.
    from PIL import Image, ImageFilter

    m = Image.fromarray((similar * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    similar = np.asarray(m) > 127
    return SkinInfo(similar | face_area, faces, "rosto")


def _box3(x: np.ndarray) -> np.ndarray:
    p = np.pad(x, 1, mode="edge")
    return sum(p[i:i + x.shape[0], j:j + x.shape[1]] for i in range(3) for j in range(3)) / 9.0


def noise_level(working: np.ndarray) -> float:
    """Desvio robusto (MAD) do passa-alta da luma DI, só nas áreas planas (50 % menor gradiente)."""
    y = pf.working_luma(np.clip(working, 0, 1))
    hp = y - _box3(y)
    gy, gx = np.gradient(_box3(y))
    grad = np.hypot(gx, gy)
    flat = grad <= np.percentile(grad, 50)
    return float(1.4826 * np.median(np.abs(hp[flat] - np.median(hp[flat]))))


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    from PIL import Image, ImageFilter

    im = Image.fromarray((mask * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.MaxFilter(2 * radius + 1))) > 127


def highlight_halo(display: np.ndarray) -> dict:
    """Mede o anel em volta das altas luzes (display Rec.709)."""
    from .colorspaces import xyz_to_lab, apply_matrix, rgb_to_xyz_matrix, gamma24_decode

    luma = display @ np.array([0.2126, 0.7152, 0.0722])
    thr = max(np.percentile(luma, 99.0), 0.85)
    hi = luma >= thr
    frac = float(hi.mean())
    if frac < HIGHLIGHT_MIN_FRACTION:
        return {"altas_fracao": round(frac, 4), "anel_rel": None, "anel_a": None}
    near = _dilate(hi, 6) & ~hi
    if not near.any():
        return {"altas_fracao": round(frac, 4), "anel_rel": None, "anel_a": None}
    lab = xyz_to_lab(apply_matrix(rgb_to_xyz_matrix("Rec.709"), gamma24_decode(display)))
    rel = float(luma[near].mean() / max(np.median(luma), 1e-3))
    a_ring = float(lab[near][:, 1].mean() - lab[..., 1].mean())
    return {"altas_fracao": round(frac, 4), "anel_rel": round(rel, 3), "anel_a": round(a_ring, 2)}


HAZE_RATIO = 0.45  # pixel "dentro da névoa" (só informativo): dark channel ≥ 45 % da luz atmosférica
HAZE_MIN_INDEX = 0.18  # índice de névoa mínimo na referência (média de dark channel / luz da névoa)
HAZE_AIRLIGHT = (0.15, 0.85)  # luz da névoa nem preta nem branco estourado (parede/lâmpada enganam o método)
HAZE_PATCH = 15  # px (na imagem de análise, ~640 px)


def haze_measure(display: np.ndarray) -> dict:
    """Densidade de neblina/fumaça pelo dark channel (He, Sun & Tang, 2009).

    Em imagem limpa, quase toda região tem algum pixel com um canal perto de zero.
    Com névoa/fumaça, o ar adiciona luz a tudo e esse mínimo sobe. Mede também a cor
    da luz atmosférica (média dos 0,1 % pixels de maior dark channel) e o contraste local.
    """
    from PIL import Image, ImageFilter

    img = np.clip(np.asarray(display, dtype=np.float64), 0, 1)
    mn = img.min(axis=2)
    dc_img = Image.fromarray((mn * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(HAZE_PATCH))
    dc = np.asarray(dc_img, dtype=np.float64) / 255.0
    flat = dc.reshape(-1)
    k = max(1, int(flat.size * 0.001))
    top = np.argpartition(flat, -k)[-k:]
    atm = img.reshape(-1, 3)[top].mean(axis=0)
    luma = img @ np.array([0.2126, 0.7152, 0.0722])
    contrast = float(np.percentile(luma, 95) - np.percentile(luma, 5))
    # Normaliza pela própria luz da névoa: névoa escura (madrugada) e clara (fumaça
    # num escritório) ficam na mesma escala. 1 − ratio = transmissão estimada.
    ratio = np.clip(dc / max(float(atm.min()), 0.04), 0.0, 1.0)
    return {"dark_channel_mediana": round(float(np.median(dc)), 4),
            "dark_channel_p90": round(float(np.percentile(dc, 90)), 4),
            "luz_atmosferica_rgb": [round(float(x), 3) for x in atm],
            "nevoa_indice": round(float(ratio.mean()), 4),
            "nevoa_cobertura": round(float((ratio > HAZE_RATIO).mean()), 4),
            "contraste_p95_p5": round(contrast, 4)}


HAZE_TINT_NEUTRAL = 0.03  # croma (RGB display) abaixo disso = luz da névoa da referência é "branca"
HAZE_TINT_GAIN = 0.6      # fração do croma alvo que vira Offset no nó HAZE (por unidade de densidade)
HAZE_TINT_MAX = 0.03      # teto do Offset por canal (espaço de trabalho)


def haze_tint(ref_airlight_rgb, graded_display: np.ndarray, density: float) -> dict:
    """Cor da névoa: a fumaça raramente é branca pura — pega a tonalidade do ar da referência
    e, quando o ar da referência é neutro, a tonalidade do próprio grade que está sendo construído.

    Modelo de névoa: I = J·t + A·(1−t). A parte A·(1−t) é aditiva, então a cor vira um Offset
    (média zero: só tinge, não levanta o preto) no nó HAZE, proporcional à densidade.
    Retorna o Offset em espaço de trabalho e a origem de cada número.
    """
    air = np.asarray(ref_airlight_rgb, dtype=np.float64)
    air_chroma = air - air.mean()
    g = np.clip(np.asarray(graded_display, dtype=np.float64), 0, 1).reshape(-1, 3)
    luma = g @ np.array([0.2126, 0.7152, 0.0722])
    # Tonalidade do grade: médios-altos (onde a névoa aparece), não as sombras.
    sel = (luma > np.percentile(luma, 40)) & (luma < np.percentile(luma, 97))
    tone = g[sel].mean(axis=0) if sel.any() else g.mean(axis=0)
    tone_chroma = tone - tone.mean()
    w_air = float(np.clip(np.abs(air_chroma).max() / HAZE_TINT_NEUTRAL, 0.0, 1.0))
    target = w_air * air_chroma + (1.0 - w_air) * tone_chroma
    # Display -> trabalho: diferença entre a cor alvo e o cinza de mesma luminância.
    base = float(np.clip(air.mean(), 0.2, 0.8))
    col_w = pf.display_to_working(np.clip(np.array([[base + target]]), 0, 1))[0, 0]
    gray_w = pf.display_to_working(np.array([[[base, base, base]]]))[0, 0]
    off = (col_w - gray_w) * HAZE_TINT_GAIN * float(np.clip(density, 0.0, 1.0))
    off = np.clip(off - off.mean(), -HAZE_TINT_MAX, HAZE_TINT_MAX)
    origem = ("luz atmosférica da referência" if w_air >= 0.99 else
              "tonalidade do grade (ar da referência neutro)" if w_air <= 0.01 else
              f"mistura: {round(w_air * 100)} % ar da referência + {round((1 - w_air) * 100)} % tonalidade do grade")
    return {"offset": [round(float(x), 5) for x in off], "origem": origem,
            "croma_ar_ref": [round(float(x), 4) for x in air_chroma],
            "croma_grade": [round(float(x), 4) for x in tone_chroma],
            "peso_ar_ref": round(w_air, 3), "densidade": round(float(density), 3)}


@dataclass
class Decision:
    role: str
    enabled: bool
    reason: str
    measured: dict = field(default_factory=dict)


def decide_extras(src_working: np.ndarray, ref_working: np.ndarray, graded_display: np.ndarray,
                  ref_display: np.ndarray, *, film_emulation: bool = False,
                  neutral_display: np.ndarray | None = None, haze_mode: str = "auto") -> dict[str, Decision]:
    """neutral_display: footage só com Input+Output CST (sem grade), usado para a densidade sugerida.
    haze_mode: "auto" (pela referência), "on" (sempre) ou "off" (nunca)."""
    n_src, n_ref = noise_level(src_working), noise_level(ref_working)
    out: dict[str, Decision] = {}

    nr = n_src > NR_MIN_NOISE and n_src > NR_RATIO * n_ref
    out["nr"] = Decision("nr", nr, f"ruído footage {n_src:.4f} vs ref {n_ref:.4f} "
                         f"(liga se > {NR_MIN_NOISE} e > {NR_RATIO}× ref)", {"ruido_footage": n_src, "ruido_ref": n_ref})

    grain = (n_ref > GRAIN_MIN_NOISE and n_ref > GRAIN_RATIO * n_src) or film_emulation
    out["grain"] = Decision("grain", grain, f"textura ref {n_ref:.4f} vs footage {n_src:.4f} "
                            f"(liga se > {GRAIN_MIN_NOISE} e > {GRAIN_RATIO}× footage)"
                            + (" | forçado pela flag de film emulation" if film_emulation else ""),
                            {"ruido_ref": n_ref, "ruido_footage": n_src})

    h_ref, h_out = highlight_halo(ref_display), highlight_halo(graded_display)
    glow = (h_ref["anel_rel"] is not None and h_out["anel_rel"] is not None
            and h_ref["anel_rel"] > GLOW_RATIO * h_out["anel_rel"]) or film_emulation
    out["glow"] = Decision("glow", glow, f"anel das altas ref {h_ref['anel_rel']} vs resultado {h_out['anel_rel']} "
                           f"(liga se ref > {GLOW_RATIO}× resultado)", {"ref": h_ref, "resultado": h_out})

    hal = (h_ref["anel_a"] is not None and h_ref["anel_a"] > HALATION_A) or film_emulation
    out["halation"] = Decision("halation", hal, f"a* do anel na ref {h_ref['anel_a']} (liga se > {HALATION_A})",
                               {"ref": h_ref})

    hz_ref = haze_measure(ref_display)
    hz_out = haze_measure(neutral_display if neutral_display is not None else graded_display)
    atm_max = max(hz_ref["luz_atmosferica_rgb"])
    auto = hz_ref["nevoa_indice"] >= HAZE_MIN_INDEX and HAZE_AIRLIGHT[0] <= atm_max <= HAZE_AIRLIGHT[1]
    haze = {"on": True, "off": False}.get(haze_mode, auto)
    strength = float(np.clip((hz_ref["nevoa_indice"] - HAZE_MIN_INDEX) / 0.4 + 0.15, 0.0, 1.0)) if auto else 0.0
    out["haze"] = Decision(
        "haze", haze,
        f"índice de névoa da referência {hz_ref['nevoa_indice']} (footage original {hz_out['nevoa_indice']}); "
        f"automático liga se ≥ {HAZE_MIN_INDEX} e a luz da névoa ({round(atm_max, 2)}) estiver entre "
        f"{HAZE_AIRLIGHT[0]} e {HAZE_AIRLIGHT[1]}; modo: {haze_mode}; densidade sugerida ≈ {round(strength * 100)} % "
        "(heurística: imagem lavada ou parede clara podem parecer névoa)",
        {"ref": hz_ref, "resultado": hz_out, "densidade_sugerida": round(strength, 3)})

    out["haze"].measured["cor"] = haze_tint(hz_ref["luz_atmosferica_rgb"], graded_display, strength if auto else 0.35)

    look = film_emulation or grain or glow or hal
    out["look"] = Decision("look", look, "liga se film emulation pedida ou se grão/glow/halation foram detectados",
                           {})
    return out
