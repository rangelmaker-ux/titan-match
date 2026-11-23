"""Color Space Transform nativo do DaVinci (ResolveFX "colorspacetransformv2") dentro do .drx.

A API de scripting não coloca OFX em nós, mas o .drx guarda cada OFX como protobuf no campo 10
do nó. O CST v2 grava os parâmetros como texto (só os que fogem do padrão), por exemplo:

    inputColorSpace = SGAMUT_COLORSPACE      inputGamma  = SONY_SLOG2_GAMMA
    outputColorSpace = DWG_COLORSPACE        outputGamma = DAV_INTER_OETF_GAMMA

Os nomes internos e o nome que aparece no menu do CST foram lidos do próprio DaVinci Resolve 21
(tabela de enums do fusionsystem.dll). Tone mapping: `tmType` (TM_NONE, TM_CLIP, TM_SIMPLE,
TM_DRT_V1, TM_DRT_V2...); o padrão "DaVinci" não é gravado. Entrada com TM_NONE (conversão pura,
igual à simulação); saída no padrão DaVinci, que faz o ombro suave das altas (a simulação usa a
mesma curva, medida: profiles.TM_DISPLAY). Gamut mapping fica no padrão (None).
"""
from __future__ import annotations

from . import drx_layout as d

PLUGIN = b"com.blackmagicdesign.resolvefx.colorspacetransformv2"
CONTEXT = b"OfxImageEffectContextFilter"
# Identificador de contexto que o DaVinci grava junto do OFX (igual em todos os nós do mesmo .drx).
_CTX_ID = "a1411d4c-a935-4151-9de2-59a5195ef72d"

WORKING = ("DWG_COLORSPACE", "DAV_INTER_OETF_GAMMA")       # DaVinci Wide Gamut / DaVinci Intermediate
OUTPUT = ("REC709_COLORSPACE", "TWOPOINTFOUR_GAMMA")       # Rec.709 / Gamma 2.4

# perfil da câmera -> (Input Color Space, Input Gamma) do CST. None = o DaVinci não tem esse
# espaço no CST; o plugin usa o LUT de CST para esse perfil.
CAMERA: dict[str, tuple[str, str] | None] = {
    "sony_slog3": ("SGAMUT3CINE_COLORSPACE", "SONY_SLOG3_GAMMA"),
    "sony_slog3_sg3": ("SGAMUT3_COLORSPACE", "SONY_SLOG3_GAMMA"),
    "sony_slog3_venice": ("VENICE_SGAMUT3CINE_COLORSPACE", "SONY_SLOG3_GAMMA"),
    "sony_slog2": ("SGAMUT_COLORSPACE", "SONY_SLOG2_GAMMA"),
    "canon_clog3": ("CANONLOG2_COLORSPACE", "CANONLOG3_GAMMA"),      # Canon Cinema Gamut
    "canon_clog2": ("CANONLOG2_COLORSPACE", "CANONLOG2_GAMMA"),
    "canon_clog_cg": ("CANONLOG2_COLORSPACE", "CANONLOG_GAMMA"),
    "canon_clog_709": ("REC709_COLORSPACE", "CANONLOG_GAMMA"),
    "panasonic_vlog": ("VLOG_COLORSPACE", "PANASONIC_VLOG_GAMMA"),
    "fuji_flog": ("REC2020_COLORSPACE", "FLOG_OETF_GAMMA"),
    "fuji_flog2": ("REC2020_COLORSPACE", "FLOG2_OETF_GAMMA"),
    "fuji_flog2c": ("FGAMUT_C_COLORSPACE", "FLOG2_OETF_GAMMA"),
    "nikon_nlog": ("REC2020_COLORSPACE", "NLOG_OETF_GAMMA"),
    "dji_dlog": ("DGAMUT_COLORSPACE", "DJI_DLOG_GAMMA"),
    "gopro_protune": None,  # Protune Flat não existe no CST (só GP-Log2)
    "apple_log": ("REC2020_COLORSPACE", "APPLE_LOG_GAMMA"),
    "leica_llog": ("REC2020_COLORSPACE", "LLOG_OETF_GAMMA"),
    "bmd_film_gen5": ("BMD4KBCASTFILM_COLORSPACE", "BMDFILMV5_GAMMA"),  # BMD Wide Gamut Gen 4/5
    "arri_logc3": ("ALEXA3_COLORSPACE", "LOGC_EI800_GAMMA"),
    "arri_logc4": ("ARRI_LOGC4_COLORSPACE", "LOGC4_EI800_GAMMA"),
    "red_log3g10": ("RWG_COLORSPACE", "RED_LOG3G10_GAMMA"),
    "rec709": ("REC709_COLORSPACE", "TWOPOINTFOUR_GAMMA"),
}


def has_cst(profile_key: str) -> bool:
    return CAMERA.get(profile_key) is not None


def _kv(key: int, value: bytes) -> list:
    return [1, 2, d.dump([[1, 0, key], [2, 2, value]])]


def _param(name: str, value) -> list:
    v = [[3, 0, int(value)]] if isinstance(value, (bool, int)) else [[5, 2, value.encode()]]
    return [5, 2, d.dump([[1, 2, name.encode()], [2, 2, d.dump(v)]])]


def payload(in_space: str, in_gamma: str, out_space: str, out_gamma: str, *, instance: int = 41,
            fwd_ootf: bool = False, inv_ootf: bool = False, tone_mapping: str | None = None) -> bytes:
    """Campo 10 de um nó com o CST v2 configurado (mesmo formato que o DaVinci 21 grava).

    tone_mapping: None deixa o padrão do DaVinci ("DaVinci", que não é gravado); "TM_NONE" desliga.
    """
    params = [
        _param("doFwdOOTF", fwd_ootf), _param("doInvOOTF", inv_ootf),
        _param("inputColorSpace", in_space), _param("inputGamma", in_gamma),
        _param("isRec2390ScalingEnabled", False), _param("isRec2408ConversionEnabled", False),
        _param("outputColorSpace", out_space), _param("outputGamma", out_gamma),
        _param("resolvefxVersion", "1.4"),
    ] + ([_param("tmType", tone_mapping)] if tone_mapping else [])
    ofx = d.dump([[1, 0, 5195353], [2, 2, PLUGIN], [3, 2, CONTEXT], [4, 0, 1]] + params)
    inst = f"{CONTEXT.decode()}_{_CTX_ID}_{instance}".encode()
    return d.dump([
        _kv(3221225473, d.dump([[2, 0, 2]])),
        _kv(3221225545, d.dump([[5, 2, PLUGIN]])),
        _kv(3221225566, d.dump([[5, 2, inst]])),
        _kv(3221225571, d.dump([[4, 0, 0]])),
        _kv(3221225607, d.dump([[21, 2, ofx]])),
        _kv(3221225682, d.dump([[4, 0, 0]])),
    ])


def input_payload(profile_key: str) -> bytes | None:
    cam = CAMERA.get(profile_key)
    # Tone mapping DESLIGADO na entrada: o padrão do CST ("DaVinci") comprime a imagem log ao levar
    # para o DaVinci Intermediate e ela fica lavada/fria depois das correções (visto no DaVinci 21).
    return payload(cam[0], cam[1], *WORKING, instance=41, tone_mapping="TM_NONE") if cam else None


def output_payload() -> bytes:
    return payload(*WORKING, *OUTPUT, instance=47)


def params(field10: bytes) -> dict[str, object]:
    """Parâmetros do CST gravados num nó (vazio se o nó não tem CST)."""
    out: dict[str, object] = {}
    try:
        for f, _, kv in d.parse(field10 or b""):
            if f != 1:
                continue
            val = d._get(d.parse(kv), 2) or b""
            ofx = d._get(d.parse(val), 21) if val[:1] == b"\xaa" else None
            if not ofx:
                continue
            msg = d.parse(ofx)
            if d._get(msg, 2) != PLUGIN:
                continue
            for ff, _, p in msg:
                if ff == 5:
                    pm = d.parse(p)
                    v = d.parse(d._get(pm, 2))
                    out[d._get(pm, 1).decode()] = (d._get(v, 5).decode() if d._get(v, 5) is not None
                                                   else d._get(v, 3))
    except (ValueError, TypeError, AttributeError):
        return {}
    return out


def aplicar_no_drx(xml: str, profile_key: str, in_labels: set[str], out_labels: set[str]) -> str:
    """Devolve o .drx com CST nativo nos nós de entrada/saída (achados pelo rótulo).

    Perfil sem CST no DaVinci: devolve o .drx igual (o plugin usa o LUT nesses nós).
    """
    pin = input_payload(profile_key)
    if pin is None:
        return xml
    pout = output_payload()
    g, m = d.ler(xml)
    ins = {s.casefold() for s in in_labels}
    outs = {s.casefold() for s in out_labels}
    novo = []
    for f, t, v in g.grafo:
        if f == 7:
            n = d.parse(v)
            lab = (d._get(n, 6) or b"").decode("utf-8", "replace").casefold()
            if lab in ins or lab in outs:
                for item in n:
                    if item[0] == 10:
                        item[2] = pin if lab in ins else pout
                v = d.dump(n)
        novo.append([f, t, v])
    g.grafo = novo
    return d.gravar(xml, m, g)
