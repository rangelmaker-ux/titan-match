"""Adaptador do Resolve contra um Resolve FALSO (só confere a lógica de segurança)."""
import base64
import io

import numpy as np
import pytest

from titan_match.engine import analyze
from titan_match.nodes import LABELS, ROLES
from titan_match.matching import MatchOptions
from titan_match.resolve_bridge import (ApprovalRequired, NodeInfo, ResolveBridge, ResolveError, check_block,
                                        locate_nodes, locate_titan_block)
from synth import make_pair


def _png(arr):
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeNode:
    def __init__(self, label="", tools=None, lut=""):
        self.label, self.tools, self.lut, self.color, self.enabled = label, tools if tools is not None else [], lut, "", True
        self.cdl = None


class FakeGraph:
    def __init__(self, nodes):
        self.nodes = nodes
        self.writes = []

    def GetNumNodes(self): return len(self.nodes)
    def GetNodeLabel(self, i): return self.nodes[i - 1].label
    def GetToolsInNode(self, i): return self.nodes[i - 1].tools
    def GetLUT(self, i): return self.nodes[i - 1].lut

    def SetNodeLabel(self, i, label):
        self.writes.append(("label", i)); self.nodes[i - 1].label = label; return True

    def SetNodeColor(self, i, c):
        self.writes.append(("color", i)); self.nodes[i - 1].color = c; return True

    def SetLUT(self, i, p):
        self.writes.append(("lut", i)); self.nodes[i - 1].lut = p; return True

    def SetNodeEnabled(self, i, e):
        self.writes.append(("enabled", i)); self.nodes[i - 1].enabled = e; return True


class FakeItem:
    def __init__(self, nodes, frame):
        self.graph = FakeGraph(nodes)
        self.frame = frame
        self.cdl_calls = []

    def GetName(self): return "clip"
    def GetNodeGraph(self, layer=None): return self.graph
    def GetMediaPoolItem(self): return self
    def GetSourceStartFrame(self): return 0
    def GetDuration(self): return 10
    def ExportFrame(self, off, opts): return {"success": True, "data": _png(self.frame)}

    def SetCDL(self, d):
        self.cdl_calls.append(d)
        node = self.graph.nodes[d["NodeIndex"] - 1]
        node.tools = list(dict.fromkeys((node.tools or []) + ["Primary"]))  # como o Resolve: acrescenta
        return True


class FakeProject:
    def RefreshLUTList(self): return True


class FakeResolve:
    def __init__(self, item):
        self.item = item

    def GetProjectManager(self): return self

    def GetCurrentProject(self): return FakeProject()


def user_nodes():
    return [FakeNode("Denoise", ["Noise Reduction"]), FakeNode("Look do usuário", ["Custom Curves"])]


def titan_block():
    return [FakeNode(LABELS[r]) for r in ROLES]


@pytest.fixture
def plan_and_ref():
    log, ref = make_pair()
    return analyze(ref, log, "sony_slog3", options=MatchOptions(template="basico")).plan, ref


def test_locate_by_label_any_topology():
    labels = [LABELS[r] for r in ROLES]
    nodes = [NodeInfo(i + 1, l, [], "") for i, l in enumerate(["A"] + labels)]
    assert locate_titan_block(nodes) == 2
    shuffled = [NodeInfo(i + 1, l, [], "") for i, l in enumerate(reversed(labels))]
    m = locate_nodes(shuffled, labels)  # ordem de índice não importa (paralelos/mixers)
    assert m is not None and m[labels[0].casefold()] == 10
    dup = nodes + [NodeInfo(99, labels[3], [], "")]
    assert locate_nodes(dup, labels) is None  # label repetido = ambíguo
    missing = nodes[:-1]
    assert locate_nodes(missing, labels) is None


def test_missing_block_blocks_and_writes_nothing(tmp_path, plan_and_ref):
    plan, ref = plan_and_ref
    item = FakeItem(user_nodes(), ref)
    br = ResolveBridge(FakeResolve(item))
    assert not check_block(br.inspect(item)).ok
    with pytest.raises(ResolveError):
        br.fill_block(item, plan, approved=True, lut_root=tmp_path)
    assert item.graph.writes == [] and item.cdl_calls == []


def test_no_write_without_approval(tmp_path, plan_and_ref):
    plan, ref = plan_and_ref
    item = FakeItem(user_nodes() + titan_block(), ref)
    with pytest.raises(ApprovalRequired):
        ResolveBridge(FakeResolve(item)).fill_block(item, plan, approved=False, lut_root=tmp_path)
    assert item.graph.writes == [] and item.cdl_calls == []


def test_fill_block_writes_only_titan_nodes(tmp_path, plan_and_ref):
    plan, ref = plan_and_ref
    item = FakeItem(user_nodes() + titan_block(), ref)
    rep = ResolveBridge(FakeResolve(item)).fill_block(item, plan, approved=True, lut_root=tmp_path,
                                                      reference_display=ref)
    assert rep.ok, rep.errors
    written = {i for _, i in item.graph.writes} | {c["NodeIndex"] for c in item.cdl_calls}
    assert written == set(range(3, 13))  # usuário tem nós 1-2; bloco é 3..12
    assert item.graph.nodes[0].label == "Denoise" and item.graph.nodes[1].tools == ["Custom Curves"]
    assert len(item.cdl_calls) == 7  # nós 02..08; o 09 (Look) é efeito pré-configurado: só liga/desliga
    assert item.graph.nodes[2].lut.endswith(".cube") and item.graph.nodes[11].lut.endswith(".cube")
    assert (tmp_path / "Titan Match").is_dir()
    assert "hist_dist_display" in rep.verification
    first = item.cdl_calls[0]
    assert set(first) == {"NodeIndex", "Slope", "Offset", "Power", "Saturation"}
    assert len(first["Slope"].split()) == 3


def test_overwrite_titan_content_requires_explicit_flag(tmp_path, plan_and_ref):
    plan, ref = plan_and_ref
    block = titan_block()
    block[3].tools = ["Primary"]
    item = FakeItem(block, ref)
    br = ResolveBridge(FakeResolve(item))
    with pytest.raises(ApprovalRequired):
        br.fill_block(item, plan, approved=True, lut_root=tmp_path)
    assert item.cdl_calls == []
    assert br.fill_block(item, plan, approved=True, overwrite_titan=True, lut_root=tmp_path).ok


def test_warns_about_user_nodes_before_block():
    nodes = [NodeInfo(1, "Denoise", ["Noise Reduction"], "")] + \
            [NodeInfo(i + 2, LABELS[r], [], "") for i, r in enumerate(ROLES)] + [NodeInfo(12, "Extra", [], "")]
    chk = check_block(nodes)
    assert chk.ok
    assert any("antes da árvore Titan" in w for w in chk.warnings)


def _cinema_plan_and_item(tmp_path, skin_tools):
    from titan_match.matching import MatchOptions
    from titan_match.templates import BUILTIN, Template

    ts = {k: Template(t.key, t.title, list(t.nodes)) for k, t in BUILTIN.items()}
    log, ref = make_pair()
    plan = analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema"), templates=ts).plan
    nodes = []
    for n in plan.nodes:
        fn = FakeNode(n.label)
        if n.role == "skin":
            fn.tools = skin_tools
        nodes.append(fn)
    return plan, FakeItem(nodes, ref)


def test_skin_node_waits_for_the_skin_click(tmp_path):
    plan, item = _cinema_plan_and_item(tmp_path, None)
    if not plan.node("skin").enabled:
        import pytest as _p
        _p.skip("análise não ligou o SKIN neste cenário sintético")
    br = ResolveBridge(FakeResolve(item))
    rep = br.fill_block(item, plan, approved=True, overwrite_titan=True, lut_root=tmp_path)
    skin = next(n for n in item.graph.nodes if n.label == "SKIN - Pele")
    assert rep.skin_pending and skin.enabled is False  # sem chave: não corrige a tela inteira
    ok, msg = br.enable_skin(item)
    assert not ok and "Magic Mask" in msg
    skin.tools = ["Primary Balance", "External Key", "AI Magic Mask"]  # como o Resolve reporta após o clique
    ok, msg = br.enable_skin(item)
    assert ok and skin.enabled is True


def test_skin_node_turns_on_directly_when_key_already_exists(tmp_path):
    plan, item = _cinema_plan_and_item(tmp_path, ["HSL Qualifier"])
    if not plan.node("skin").enabled:
        import pytest as _p
        _p.skip("análise não ligou o SKIN neste cenário sintético")
    rep = ResolveBridge(FakeResolve(item)).fill_block(item, plan, approved=True, overwrite_titan=True,
                                                      lut_root=tmp_path)
    skin = next(n for n in item.graph.nodes if n.label == "SKIN - Pele")
    assert not rep.skin_pending and skin.enabled is True


class Graph21_0(FakeGraph):
    """Resolve 21.0.x: SetNodeLabel / SetNodeColor só chegaram na 21.1.2 (o fusionscript devolve None)."""
    SetNodeLabel = None
    SetNodeColor = None


def test_resolve_21_0_sem_rotulo_e_cor_aplica_mesmo_assim(tmp_path, plan_and_ref):
    plan, ref = plan_and_ref
    item = FakeItem(user_nodes() + titan_block(), ref)
    item.graph = Graph21_0(item.graph.nodes)
    br = ResolveBridge(FakeResolve(item))
    br.checar_api(item)  # não pode bloquear: rótulo e cor são opcionais
    rep = br.fill_block(item, plan, approved=True, lut_root=tmp_path)
    assert rep.ok, rep.errors
    assert not any(k in ("label", "color") for k, _ in item.graph.writes)
    assert len(item.cdl_calls) == 7 and item.graph.nodes[2].lut.endswith(".cube")


def test_cst_nativo_nao_recebe_lut(tmp_path, plan_and_ref):
    plan, ref = plan_and_ref
    for n in plan.nodes:
        if n.role in ("input_cst", "output_cst"):
            n.native_cst = "Color Space Transform"
    item = FakeItem(user_nodes() + titan_block(), ref)
    rep = ResolveBridge(FakeResolve(item)).fill_block(item, plan, approved=True, lut_root=tmp_path,
                                                      cst_no_drx=True)
    assert rep.ok, rep.errors
    assert not any(k == "lut" for k, _ in item.graph.writes)
    # Árvore que já estava no clipe, sem CST no nó: cai no LUT de reserva.
    item2 = FakeItem(user_nodes() + titan_block(), ref)
    ResolveBridge(FakeResolve(item2)).fill_block(item2, plan, approved=True, lut_root=tmp_path)
    assert sum(k == "lut" for k, _ in item2.graph.writes) == 2
