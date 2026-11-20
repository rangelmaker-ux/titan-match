"""Biblioteca de árvores de nós (templates .drx + manifesto).

A API do Resolve não cria nem conecta nós, e o .drx guarda o grafo num bloco
binário fechado. Por isso cada árvore (série, paralelos, mixers) é montada
uma vez no Resolve, exportada como .drx e descrita aqui por um manifesto:
para cada nó, o label e a função (role). O plugin escolhe a árvore pela
análise, aplica o .drx numa versão nova e preenche/liga/desliga cada nó
pelo label.

Funções (roles):
  lut_in / lut_out  -> LUT de CST (input_cst, output_cst)
  cdl               -> correção calculada (white_balance … saturation)
  skin              -> CDL calculado, aplicado só na chave de pele do nó
  toggle            -> efeito pré-configurado no template (NR, glow, halation,
                       grain, look): o plugin só liga/desliga pela análise
  free              -> nó livre para o colorista: o plugin nunca escreve nele
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROLE_INFO: dict[str, tuple[str, str]] = {
    # role: (kind, cor do nó)
    "input_cst": ("lut_in", "Teal"),
    "nr": ("toggle", "Lime"),
    "white_balance": ("cdl", "Yellow"),
    "exposure_contrast": ("cdl", "Orange"),
    "shadows": ("cdl", "Navy"),
    "midtones": ("cdl", "Blue"),
    "highlights": ("cdl", "Apricot"),
    "color_balance": ("cdl", "Purple"),
    "saturation": ("cdl", "Pink"),
    "skin": ("skin", "Tan"),
    # Chave de pele calculada no material ORIGINAL (logo após o Input CST); a saída de chave
    # (azul) vai para a entrada de chave do nó SKIN. O plugin só rotula; nunca escreve nele.
    "skin_key": ("keysrc", "Tan"),
    "look": ("toggle", "Brown"),
    "glow": ("toggle", "Olive"),
    "halation": ("toggle", "Chocolate"),
    "grain": ("toggle", "Beige"),
    "haze": ("toggle", "Violet"),  # OFX Cinematic Haze: neblina/fumaça no ar
    "output_cst": ("lut_out", "Teal"),
    # Nó estrutural (Parallel/Layer Mixer): ocupa um índice no grafo (medido no Resolve 21.1.2),
    # mas não tem label nem correção; o plugin nunca escreve nele.
    "mixer": ("struct", ""),
    # Nó vazio de propósito (Starter: objetos, ADJ, power windows, look, sharpening): fica para o colorista.
    "free": ("free", ""),
}
# Roles que podem se repetir numa árvore (não têm correção própria).
REPEATABLE = {"mixer", "free"}
# Ordem de processamento (simulação) dos nós que alteram cor de forma calculada.
CHAIN_ORDER = ["white_balance", "exposure_contrast", "shadows", "midtones", "highlights",
               "color_balance", "saturation", "skin"]
from .paths import app_root

TEMPLATES_DIR = app_root() / "templates"


@dataclass
class TemplateNode:
    label: str
    role: str

    @property
    def kind(self) -> str:
        return ROLE_INFO[self.role][0]

    @property
    def color(self) -> str:
        return ROLE_INFO[self.role][1]


@dataclass
class Template:
    key: str
    title: str
    nodes: list[TemplateNode]  # na ordem dos índices de nó do Resolve (1..N)
    drx: Path | None = None
    description: str = ""
    topology: str = ""
    verified: bool = False

    def roles(self) -> list[str]:
        return [n.role for n in self.nodes]

    def node(self, role: str) -> TemplateNode | None:
        return next((n for n in self.nodes if n.role == role), None)

    def validate(self) -> None:
        roles = [r for r in self.roles() if r not in REPEATABLE]
        for r in self.roles():
            if r not in ROLE_INFO:
                raise ValueError(f"{self.key}: role desconhecida {r!r}")
        if len(set(roles)) != len(roles):
            raise ValueError(f"{self.key}: role repetida")
        labels = [n.label.casefold() for n in self.nodes if n.kind != "struct"]
        if len(set(labels)) != len(labels):
            raise ValueError(f"{self.key}: label repetido")
        for must in ("input_cst", "output_cst"):
            if must not in roles:
                raise ValueError(f"{self.key}: falta {must}")


BASIC = Template(
    "basico", "Básica (10 nós em série)",
    [TemplateNode(l, r) for r, l in [
        ("input_cst", "01 - Input CST"), ("white_balance", "02 - White Balance"),
        ("exposure_contrast", "03 - Exposure & Contraste"), ("shadows", "04 - Shadows (Lift)"),
        ("midtones", "05 - Midtones (Gamma)"), ("highlights", "06 - Highlights (Gain)"),
        ("color_balance", "07 - Color Balance"), ("saturation", "08 - Saturacao"),
        ("look", "09 - Look / Film Emulation"), ("output_cst", "10 - Output CST")]],
    description="Uma função por nó, tudo em série.",
    topology="01→02→03→04→05→06→07→08→09→10",
    verified=True,
)

CINEMA = Template(
    "cinema", "Cinema (pele + finalização em paralelo)",
    [TemplateNode(l, r) for r, l in [
        ("input_cst", "01 - Input CST"), ("nr", "NR - Ruido"), ("white_balance", "02 - White Balance"),
        ("exposure_contrast", "03 - Exposure & Contraste"), ("shadows", "04 - Shadows (Lift)"),
        ("midtones", "05 - Midtones (Gamma)"), ("highlights", "06 - Highlights (Gain)"),
        ("color_balance", "07 - Color Balance"), ("saturation", "08 - Saturacao"),
        ("haze", "HAZE"), ("skin", "SKIN - Pele"), ("glow", "GLOW"), ("halation", "HALATION"), ("grain", "GRAIN"),
        ("mixer", ""), ("output_cst", "10 - Output CST")]],
    description="Correções em série; neblina (Cinematic Haze); pele com chave própria (um clique no rosto); "
                "glow, halation e grain em paralelo.",
    topology="01→NR→02→…→08→HAZE→SKIN→[GLOW ∥ HALATION ∥ GRAIN]→mixer→10 (16 índices)",
)

STARTER = Template(
    "starter", "Starter (20 nós, espaço para o colorista)",
    [TemplateNode(l, r) for r, l in [
        ("input_cst", "CST in"), ("white_balance", "Exp/bal"), ("exposure_contrast", "Contrast"),
        ("saturation", "Sat"), ("free", "background"), ("free", "2nd obj"), ("free", "Main obj"), ("mixer", ""),
        ("free", "Global"), ("free", "ADJ 1"), ("free", "ADJ 2"), ("free", "ADJ 3"), ("free", "PW 1"),
        ("free", "PW 2"), ("free", "PW 3"), ("mixer", ""), ("free", "Final look"), ("free", "Fine Tune"),
        ("output_cst", "CST out"), ("free", "Sharpening")]],
    description="O match vai em Exp/bal, Contrast e Sat (sombras, médios, altas e color balance combinados "
                "no Contrast); objetos, ajustes, power windows, look, fine tune e sharpening ficam vazios.",
    topology="CST in→Exp/bal→Contrast→Sat→[background ∥ 2nd obj ∥ Main obj]→mixer→Global→"
             "[ADJ 1-3 ∥ PW 1-3]→mixer→Final look→Fine Tune→CST out→Sharpening (20 índices)",
)

BUILTIN = {t.key: t for t in (BASIC, CINEMA, STARTER)}


def _from_manifest(path: Path) -> Template:
    d = json.loads(path.read_text(encoding="utf-8"))
    t = Template(d["key"], d.get("title", d["key"]), [TemplateNode(n["label"], n["role"]) for n in d["nodes"]],
                 description=d.get("description", ""), topology=d.get("topology", ""),
                 verified=bool(d.get("verified", False)))
    t.validate()
    return t


def load_templates(folder: Path = TEMPLATES_DIR) -> dict[str, Template]:
    """Templates disponíveis: manifestos .json na pasta (prioridade) + embutidos; só os que têm .drx."""
    out: dict[str, Template] = {}
    for key, t in BUILTIN.items():
        out[key] = Template(t.key, t.title, list(t.nodes), None, t.description, t.topology, t.verified)
    if folder.is_dir():
        for js in folder.glob("*.json"):
            try:
                t = _from_manifest(js)
                out[t.key] = t
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    for key, t in out.items():
        cand = [folder / f"TitanMatch_{key}.drx"]
        if key == "basico":
            cand.append(folder / "TitanMatch_Template.drx")
        t.drx = next((c for c in cand if c.is_file()), None)
    return out


def save_manifest(t: Template, folder: Path = TEMPLATES_DIR) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"TitanMatch_{t.key}.json"
    p.write_text(json.dumps({
        "key": t.key, "title": t.title, "description": t.description, "topology": t.topology,
        "verified": t.verified, "nodes": [{"label": n.label, "role": n.role} for n in t.nodes],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
