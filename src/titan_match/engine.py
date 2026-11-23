"""Orquestração: referência + frame -> análise -> plano (dry-run) -> conferência simulada.

Não depende do Resolve: tudo aqui roda com numpy/Pillow e é testável.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import cst_ofx, features
from . import profiles as pf
from .cdl import CDL, apply_cdl, apply_cdl_masked, fit_cdl
from .lut import LUT_SUBFOLDER, build_cst_luts
from .mapping import map_skin
from .matching import MatchOptions, get_matcher
from .nodes import GradePlan, NodeSpec, Provenance
from .stats import ImageStats, compute_stats, histogram_distance
from .templates import CHAIN_ORDER, Template, load_templates

MAX_ANALYSIS_DIM = 1024
ANALYSIS_DIM = 640


def _limit(img: np.ndarray, max_dim: int) -> np.ndarray:
    img = np.asarray(img, dtype=np.float64)
    h, w = img.shape[:2]
    if max(h, w) <= max_dim:
        return img
    from PIL import Image

    s = max_dim / max(h, w)
    # Canal a canal em float 32 (mantém a precisão; Pillow não redimensiona RGB float direto).
    chans = [np.asarray(Image.fromarray(img[..., c].astype(np.float32), mode="F").resize(
        (max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR)) for c in range(3)]
    return np.stack(chans, axis=-1).astype(np.float64)


def load_image(path: str | Path, max_dim: int = MAX_ANALYSIS_DIM) -> np.ndarray:
    """Carrega JPEG/PNG como float RGB [0,1] (8 ou 16 bits)."""
    from PIL import Image

    im = Image.open(path)
    if im.mode in ("I;16", "I;16B", "I"):
        arr = np.asarray(im, dtype=np.float64) / 65535.0
        arr = np.repeat(arr[..., None], 3, axis=-1)
    else:
        im = im.convert("RGB")
        if max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim))
        arr = np.asarray(im, dtype=np.float64) / 255.0
    return arr


def trim_frame(img: np.ndarray, tol: float = 0.02, inset: float = 0.03) -> np.ndarray:
    """Tira moldura de print de tela: bordas brancas/pretas uniformes (print, letterbox) e cantos arredondados.

    Só sai linha/coluna de borda quase constante E quase branca ou quase preta, e só se isso
    acontece em pelo menos dois lados (print: quatro; letterbox: dois). Depois um recuo de `inset`
    do lado menor tira os cantos arredondados. Sem moldura, a imagem volta igual.
    """
    img = np.asarray(img)
    h, w = img.shape[:2]
    if h < 40 or w < 40:
        return img

    def flat(v: np.ndarray) -> bool:
        v = v.reshape(-1, v.shape[-1])
        if float(v.std(axis=0).max()) >= tol:
            return False
        m = v.mean(axis=0)
        return bool(m.min() > 0.92 or m.max() < 0.06)

    t, b, l, r = 0, h, 0, w
    while t < h // 4 and flat(img[t]):
        t += 1
    while b > h * 3 // 4 and flat(img[b - 1]):
        b -= 1
    while l < w // 4 and flat(img[:, l]):
        l += 1
    while r > w * 3 // 4 and flat(img[:, r - 1]):
        r -= 1
    # Moldura de print (4 lados) ou letterbox (2 lados opostos). Um lado só é conteúdo
    # (janela estourada, parede escura na borda): não recorta.
    if sum((t > 0, b < h, l > 0, r < w)) < 2:
        return img
    img = img[t:b, l:r]
    h, w = img.shape[:2]
    m = max(1, int(round(min(h, w) * inset)))  # cantos arredondados do print
    return img[m:h - m, m:w - m]


def decode_image_bytes(data: bytes, max_dim: int = MAX_ANALYSIS_DIM) -> np.ndarray:
    import io

    return load_image(io.BytesIO(data), max_dim)


@dataclass
class Analysis:
    plan: GradePlan
    reference_stats: ImageStats
    source_stats: ImageStats  # footage após Input CST, antes das correções
    result_stats: ImageStats  # footage após toda a cadeia simulada
    before_display: np.ndarray  # frame log original (como a câmera gravou)
    neutral_display: np.ndarray  # só Input CST + Output CST
    after_display: np.ndarray  # cadeia completa simulada
    reference_display: np.ndarray
    extras: dict = field(default_factory=dict)  # decisões de nós extras (features.Decision)
    source_working: np.ndarray | None = None  # footage após Input CST (para o painel de ajustes)


def lut_relative_paths(profile_key: str) -> dict[str, str]:
    return {
        "input_cst": f"{LUT_SUBFOLDER}/TitanMatch_Input_{profile_key}_to_DWG-DI.cube",
        "output_cst": f"{LUT_SUBFOLDER}/TitanMatch_Output_DWG-DI_to_Rec709-G24.cube",
    }


def fold_missing(core: dict, roles: list[str], src_w: np.ndarray) -> dict:
    """Correções sem nó na árvore escolhida vão para o nó anterior da cadeia (ou o seguinte).

    Ex.: na Starter não há Shadows/Midtones/Highlights/Color Balance: elas são combinadas com
    Exposure & Contraste num único CDL ajustado à curva composta, medida nos valores reais da
    imagem (as correções combinadas são curvas por canal; só a saturação mexe em saturação e
    ela tem nó próprio). Devolve {role: NodeCorrection} só para os nós que mudaram.
    """
    from .nodes import NodeCorrection

    chain = [r for r in CHAIN_ORDER if r != "skin" and r in core]
    present = [r for r in chain if r in roles]
    missing = [r for r in chain if r not in roles and core[r].enabled and not core[r].cdl.is_identity()
               and abs(core[r].cdl.saturation - 1.0) < 1e-9]
    if not present or not missing:
        return {}
    groups: dict[str, list[str]] = {}
    for r in missing:
        before = [p for p in present if chain.index(p) < chain.index(r)]
        target = before[-1] if before else present[0]
        groups.setdefault(target, []).append(r)
    out = {}
    pix = src_w.reshape(-1, 3)
    for target, extra in groups.items():
        members = sorted([target] + extra, key=chain.index)
        tc = core[target]
        # Entrada real do nó: a imagem depois dos nós presentes que vêm antes dele.
        x = pix
        for r in present[:present.index(target)]:
            if core[r].enabled:
                x = apply_cdl(x, core[r].cdl)
        # Só os valores que a imagem tem (quantis por canal): o ajuste vale onde há pixel.
        xs = np.quantile(x, np.linspace(0.002, 0.998, 400), axis=0)
        ys = xs
        for r in members:
            if r == target and not tc.enabled:
                continue
            ys = apply_cdl(ys, CDL(core[r].cdl.slope, core[r].cdl.offset, core[r].cdl.power))
        fit, err = fit_cdl(xs, ys)
        fit.saturation = tc.cdl.saturation if tc.enabled else 1.0
        nomes = ", ".join(extra)
        prov = list(tc.provenance) + [Provenance(
            "CDL combinado", f"ajuste de curva de {' → '.join(members)} (a árvore não tem nó para {nomes})",
            {"erro_max": round(err, 4)}, note="Mínimos quadrados por canal nos valores reais da imagem.")]
        out[target] = NodeCorrection(target, fit, prov, True,
                                     list(tc.notes) + [f"Inclui {nomes} (esta árvore não tem nó para eles)."])
    return out


DEFAULT_TEMPLATE = "starter"


def choose_template(templates: dict[str, Template], requested: str, wants: dict[str, bool]) -> tuple[Template, str]:
    """Escolhe a árvore.

    'auto': a Starter (padrão escolhido pelo usuário em 19/11/2026), se o .drx dela estiver
    instalado; sem ela, a mais completa que cobre o que a análise pediu, entre as que têm .drx.
    """
    if requested != "auto":
        if requested not in templates:
            raise ValueError(f"Template desconhecido: {requested}")
        return templates[requested], "escolhido pelo usuário"
    needed = [r for r, on in wants.items() if on]
    usable = [t for t in templates.values() if t.drx is not None] or list(templates.values())
    padrao = templates.get(DEFAULT_TEMPLATE)
    if padrao is not None and padrao.drx is not None:
        return padrao, "árvore padrão (Starter)"
    covering = [t for t in usable if all(r in t.roles() for r in needed)]
    if needed and covering:
        best = min(covering, key=lambda t: len(t.nodes))
        return best, f"análise pediu {', '.join(needed)} → árvore que cobre tudo"
    if needed:
        best = max(usable, key=lambda t: sum(r in t.roles() for r in needed))
        missing = [r for r in needed if r not in best.roles()]
        return best, (f"análise pediu {', '.join(needed)}; nenhuma árvore instalada cobre tudo "
                      f"(faltam {', '.join(missing)})")
    basic = templates.get("basico")
    return (basic if basic in usable else usable[0]), "nada extra detectado → árvore básica"


def analyze(
    reference_display: np.ndarray,
    source_log: np.ndarray,
    profile_key: str,
    matcher_name: str = "statistical_zone_lab",
    options: MatchOptions | None = None,
    templates: dict[str, Template] | None = None,
) -> Analysis:
    options = options or MatchOptions()
    prof = pf.get_profile(profile_key)
    # Estatística não precisa de resolução alta: 640 px no lado maior deixa a análise ~4× mais rápida.
    source_log = _limit(source_log, ANALYSIS_DIM)
    reference_display = trim_frame(_limit(reference_display, ANALYSIS_DIM))
    templates = templates if templates is not None else load_templates()
    # Árvore que deve ser usada, se já dá para saber (escolhida no menu, ou a padrão da Automática).
    tpl_pre = templates.get(options.template) if options.template != "auto" else (
        templates.get(DEFAULT_TEMPLATE) if templates.get(DEFAULT_TEMPLATE) and templates[DEFAULT_TEMPLATE].drx
        else None)
    tree_has_skin = tpl_pre is None or "skin" in tpl_pre.roles()
    s = float(min(max(options.strength, 0.0), 1.0))

    options.report(5, "Aplicando Input CST…")
    # 1) CST de entrada ANTES de qualquer comparação.
    src_w = np.clip(pf.input_cst(np.clip(source_log, 0, 1), prof), 0, 1)
    # 2) Referência renderizada -> espaço de trabalho (inverso exato do Output CST).
    ref_w = np.clip(pf.display_to_working(reference_display), 0, 1)

    options.report(10, "Medindo pele…")
    options.report(12, "Procurando pessoas…")
    src_info = features.skin_info(src_w, pf.output_cst(src_w))  # rostos + pele aprendida no rosto
    ref_info = features.skin_info(ref_w, np.clip(reference_display, 0, 1))
    src_skin, ref_skin = src_info.mask, ref_info.mask
    skin_present = src_info.present
    # Separar pele e entorno só faz sentido se a árvore tem o nó SKIN para cuidar do rosto. Sem ele
    # (Starter), a pele entra na conta: senão o contraste/ganho calculados no fundo estouram o rosto.
    separate = options.separate_skin and skin_present and ref_info.present and tree_has_skin

    ref_stats = compute_stats(ref_w, exclude=ref_skin if separate else None)
    src_stats = compute_stats(src_w)
    options.source_exclude = src_skin if separate else None

    # 3) Matching (plugável).
    result = get_matcher(matcher_name).match(src_w, ref_stats, options)
    core = {r: c for r, c in result.corrections.items()}
    for c in core.values():
        if s < 1.0 and not c.cdl.is_identity():
            c.cdl = c.cdl.scaled(s)
            c.notes.append(f"Força do match {round(s * 100)} %: valores escalados em direção ao neutro.")

    options.report(72, "Simulando a cadeia…")
    graded = src_w.copy()
    for role in CHAIN_ORDER:
        if role in core and role != "skin":
            graded = apply_cdl(graded, core[role].cdl)

    skin_corr = None
    if options.protect_skin and skin_present:
        skin_corr = map_skin(graded, src_w, src_skin, ambience=options.skin_ambience)
        if s < 1.0 and not skin_corr.cdl.is_identity():
            skin_corr.cdl = skin_corr.cdl.scaled(s)

    options.report(80, "Medindo ruído, grão, glow e halation…")
    graded_for_extras = apply_cdl_masked(graded, skin_corr.cdl, src_skin) if skin_corr else graded
    extras = features.decide_extras(src_w, ref_w, pf.output_cst(graded_for_extras), np.clip(reference_display, 0, 1),
                                    film_emulation=options.film_emulation, neutral_display=pf.output_cst(src_w),
                                    haze_mode=options.haze)

    wants = {"skin": bool(skin_corr and skin_corr.enabled and not skin_corr.cdl.is_identity()),
             "nr": extras["nr"].enabled, "glow": extras["glow"].enabled,
             "halation": extras["halation"].enabled, "grain": extras["grain"].enabled,
             "haze": extras["haze"].enabled}
    tpl, reason = choose_template(templates, options.template, wants)

    # 4) Plano de nós na ordem do template.
    core.update(fold_missing(core, tpl.roles(), src_w))
    luts = lut_relative_paths(profile_key)
    nodes: list[NodeSpec] = []
    for i, tn in enumerate(tpl.nodes, start=1):
        if tn.kind in ("struct", "keysrc", "free"):
            continue  # mixer / fonte de chave / nó livre do colorista: nada a calcular ou escrever
        if tn.kind == "lut_in":
            cam = cst_ofx.CAMERA.get(profile_key)
            native = f"Color Space Transform: {cam[0]} / {cam[1]} -> DaVinci Wide Gamut / Intermediate" if cam else None
            nodes.append(NodeSpec(i, tn.role, tn.label, tn.color, cdl=None, lut_path=luts["input_cst"],
                                  native_cst=native, provenance=[
                Provenance("Color Space Transform" if native else "LUT de CST",
                           "câmera -> DaVinci Wide Gamut / DaVinci Intermediate",
                           {"profile": f"{prof.brand} — {prof.label}", "gamut": prof.gamut},
                           note="Origem: escolha do usuário (profile), não estatística da imagem.")],
                notes=[] if native else ["O CST do DaVinci não tem este perfil: o nó usa o LUT de CST do Titan Match."]))
        elif tn.kind == "lut_out":
            native = ("Color Space Transform: DaVinci Wide Gamut / Intermediate -> Rec.709 / Gamma 2.4"
                      if cst_ofx.has_cst(profile_key) else None)
            nodes.append(NodeSpec(i, tn.role, tn.label, tn.color, cdl=None, lut_path=luts["output_cst"],
                                  native_cst=native, provenance=[
                Provenance("Color Space Transform" if native else "LUT de CST",
                           "DaVinci Wide Gamut / Intermediate -> Rec.709 Gamma 2.4", {},
                           note="Transformação fixa de saída.")]))
        elif tn.kind == "cdl":
            c = core[tn.role]
            nodes.append(NodeSpec(i, tn.role, tn.label, tn.color, cdl=c.cdl, enabled=c.enabled,
                                  provenance=c.provenance, notes=c.notes))
        elif tn.kind == "skin":
            if skin_corr is None:
                why = "Proteção de pele desligada." if not options.protect_skin else "Sem pele suficiente na imagem."
                nodes.append(NodeSpec(i, tn.role, tn.label, tn.color, cdl=CDL(), enabled=False, notes=[why]))
            else:
                nodes.append(NodeSpec(i, tn.role, tn.label, tn.color, cdl=skin_corr.cdl, enabled=skin_corr.enabled,
                                      provenance=skin_corr.provenance, notes=skin_corr.notes))
        else:  # toggle: efeito pré-configurado no template
            d = extras.get(tn.role)
            on = bool(d and d.enabled)
            prov = [Provenance("ligar/desligar", d.reason, _jsonable(d.measured))] if d else []
            notes = ["Efeito pré-configurado no template; a API não ajusta a intensidade, só liga/desliga."]
            cdl = CDL()
            tint = d.measured.get("cor") if (d and tn.role == "haze") else None
            if tint and options.haze_color:
                cdl = CDL(offset=tuple(tint["offset"]))
                if s < 1.0:
                    cdl = cdl.scaled(s)
                prov.append(Provenance("Offset (cor da névoa)", f"origem: {tint['origem']}", _jsonable(tint),
                                       note="Offset de média zero no nó HAZE: tinge a névoa sem levantar o preto."))
                notes.append(f"Cor da névoa automática: {tint['origem']}.")
            nodes.append(NodeSpec(i, tn.role, tn.label, tn.color, cdl=cdl, enabled=on, provenance=prov, notes=notes))

    plan = GradePlan(profile_key, result.matcher, nodes, template_key=tpl.key, template_title=tpl.title,
                     template_reason=reason, strength=s)
    if tpl.drx is None:
        plan.warnings.append(f"A árvore '{tpl.title}' ainda não tem .drx instalado: dá para ver o dry-run, "
                             "mas não para aplicar.")
    if plan.has("skin") and plan.node("skin").enabled:
        plan.warnings.append(
            "Pele: depois de Aplicar, o nó SKIN fica desligado até você marcar a pele. No Resolve, selecione o nó "
            "SKIN, abra o Magic Mask, clique no rosto e aperte Ativar pele no Titan Match.")
    for r, want in wants.items():
        if want and not plan.has(r):
            plan.warnings.append(f"A análise pediu o nó '{r}', mas a árvore escolhida não tem esse nó "
                                 "(a árvore Cinema tem).")

    # 5) Conferência simulada: histograma final vs referência (só nós que o plano liga).
    out_w = src_w.copy()
    for role in CHAIN_ORDER:
        if plan.has(role):
            n = plan.node(role)
            if n.enabled and n.cdl is not None:
                out_w = apply_cdl_masked(out_w, n.cdl, src_skin) if role == "skin" else apply_cdl(out_w, n.cdl)
    options.report(92, "Conferindo…")
    res_stats = compute_stats(out_w, exclude=src_skin if separate else None)
    src_stats_cmp = compute_stats(src_w, exclude=src_skin if separate else None)
    neutral_display = pf.output_cst(src_w)
    after_display = pf.output_cst(out_w)
    d_before = histogram_distance(src_stats_cmp.hist_display, ref_stats.hist_display)
    d_after = histogram_distance(res_stats.hist_display, ref_stats.hist_display)
    plan.verification = {
        "metodo": "simulação numpy da cadeia (Input CST -> CDLs -> Output CST)"
                  + (" | estatísticas sem a pele (separar pele e entorno)" if separate else ""),
        "hist_dist_display_antes": round(d_before, 5),
        "hist_dist_display_depois": round(d_after, 5),
        "melhorou": bool(d_after < d_before),
        "delta_lab_medios_antes": _delta_lab(src_stats_cmp, ref_stats),
        "delta_lab_medios_depois": _delta_lab(res_stats, ref_stats),
        "pele_fracao_footage": round(float(src_skin.mean()), 4),
        "pessoas_footage": len(src_info.faces),
        "pessoas_referencia": len(ref_info.faces),
        "pele_metodo": src_info.method,
        "trace": result.diagnostics.get("trace", []),
    }
    if d_after >= d_before and s > 0:
        plan.warnings.append("A simulação NÃO aproximou o histograma da referência. Revise antes de aplicar.")
    for n in nodes:
        for note in n.notes:
            if "limitado" in note:
                plan.warnings.append(f"{n.label}: {note}")
    options.report(100, "Pronto.")

    return Analysis(plan, ref_stats, src_stats, res_stats, np.clip(source_log, 0, 1), neutral_display,
                    after_display, np.clip(reference_display, 0, 1), extras, src_w)


def _jsonable(d):
    if isinstance(d, dict):
        return {k: _jsonable(v) for k, v in d.items()}
    if isinstance(d, (np.floating, float)):
        return round(float(d), 5)
    return d


def _delta_lab(a: ImageStats, b: ImageStats) -> list[float]:
    d = a.zones["midtones"].lab_mean - b.zones["midtones"].lab_mean
    return [round(float(x), 3) for x in d]


def export_luts(profile_key: str, lut_root: str | Path) -> dict[str, Path]:
    return build_cst_luts(profile_key, Path(lut_root) / LUT_SUBFOLDER)
