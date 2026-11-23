"""Adaptador para a API DaVinciResolveScript (Resolve Studio 21.1.2, Windows).

Fatos verificados no README/.pyi e em teste real (ver docs/API_FINDINGS.md):
  * Graph NÃO tem AddNode/InsertNode/SetNumNodes: a API não cria nem conecta nós.
  * TimelineItem.SetCDL({'NodeIndex', 'Slope', 'Offset', 'Power', 'Saturation'}) age no nó indicado (1-based).
  * Graph.SetLUT / GetLUT / SetNodeLabel / SetNodeColor / SetNodeEnabled / GetToolsInNode funcionam.
  * Graph.ApplyGradeFromDRX SUBSTITUI o grafo inteiro e preserva os labels do .drx.
  * Nenhum Export* devolve o frame com o grade feito pela API: a conferência no Resolve é visual.

O Titan Match nunca cria, move ou apaga nós do usuário. Ele preenche os nós da
árvore Titan encontrados PELO LABEL (qualquer topologia: série, paralelo, mixers),
ou, com aprovação, cria uma NOVA versão local com a árvore (.drx) e preenche nela.
"""
from __future__ import annotations

import base64
import datetime as _dt
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import lut as lutmod
from . import cst_ofx, drx_layout
from .cdl import CDL
from .engine import decode_image_bytes, export_luts
from .nodes import GradePlan
from .templates import BASIC, ROLE_INFO, Template

from .paths import lut_roots, resolve_scripting

WIN_API, WIN_LIB = resolve_scripting()  # nomes mantidos por compatibilidade; valem para Windows e macOS


class ResolveError(RuntimeError):
    pass


class ApprovalRequired(ResolveError):
    pass


def connect():
    """Conecta ao Resolve em execução (requer Studio + scripting externo 'Local')."""
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError:
        os.environ.setdefault("RESOLVE_SCRIPT_API", WIN_API)
        os.environ.setdefault("RESOLVE_SCRIPT_LIB", WIN_LIB)
        sys.path.append(os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules"))
        try:
            import DaVinciResolveScript as dvr  # type: ignore
        except ImportError as e:
            raise ResolveError("Módulo DaVinciResolveScript não encontrado. O Resolve está instalado?") from e
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise ResolveError("Não foi possível conectar. Abra o Resolve Studio e ative "
                           "Preferences > System > General > External scripting = Local.")
    return resolve


@dataclass
class NodeInfo:
    index: int
    label: str
    tools: list[str] | None
    lut: str
    enabled_known: bool = False

    @property
    def is_empty(self) -> bool:
        # Medido no Resolve 21.1.2: nó novo vazio devolve GetToolsInNode() == None.
        # Atenção: alguns nós com OFX (ex.: CST) também devolvem None, então "vazio" aqui
        # significa "nenhuma ferramenta reportada pela API e sem LUT".
        return not self.tools and not self.lut


@dataclass
class BlockCheck:
    index_of: dict[str, int] | None  # label normalizado -> índice do nó
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    titan_nodes_with_content: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.index_of is not None and not self.blockers

    @property
    def start(self) -> int | None:
        return min(self.index_of.values()) if self.index_of else None


@dataclass
class ApplyReport:
    mode: str
    item_name: str
    index_of: dict[str, int]
    calls: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    version_created: str | None = None
    original_version: dict | None = None
    labels: list[str] = field(default_factory=list)
    skin_pending: bool = False  # pele calculada, aguardando o clique na pele (chave) para ligar o nó SKIN
    skin_index: int | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def _norm(s: str | None) -> str:
    return (s or "").strip().casefold()


def has_skin_key(tools) -> bool:
    """O nó tem alguma chave que limite a correção (qualifier, janela ou Magic Mask)?

    "External Key" não conta: medido no Resolve 21.1.2, o rótulo continua aparecendo mesmo com a
    entrada de chave desligada, e sozinho ele não limita a correção à pele."""
    keys = ("Qualifier", "Window", "Magic Mask")
    return any(any(k in t for k in keys) for t in (tools or []))


def locate_nodes(nodes: list[NodeInfo], labels: list[str]) -> dict[str, int] | None:
    """Mapa label->índice se TODOS os labels existem exatamente uma vez no grafo."""
    want = [_norm(l) for l in labels]
    found: dict[str, list[int]] = {}
    for n in nodes:
        k = _norm(n.label)
        if k in want:
            found.setdefault(k, []).append(n.index)
    if all(len(found.get(k, [])) == 1 for k in want):
        return {k: found[k][0] for k in want}
    return None


def locate_titan_block(nodes: list[NodeInfo], labels: list[str] | None = None) -> int | None:
    """Compatibilidade: índice do primeiro nó da árvore Titan (ou None)."""
    m = locate_nodes(nodes, labels or [n.label for n in BASIC.nodes])
    return min(m.values()) if m else None


def check_block(nodes: list[NodeInfo], labels: list[str] | None = None) -> BlockCheck:
    labels = labels or [n.label for n in BASIC.nodes]
    m = locate_nodes(nodes, labels)
    chk = BlockCheck(m)
    if m is None:
        chk.blockers.append(
            "Árvore Titan não encontrada neste clipe. Use o modo Automático: ele cria uma versão local "
            "nova com a árvore e preenche (sua versão atual fica intacta)."
        )
        return chk
    titan = set(m.values())
    first = min(titan)
    in_cst = m.get(_norm(labels[0]))
    for n in nodes:
        if n.index in titan:
            if not n.is_empty:
                chk.titan_nodes_with_content.append(n.index)
            continue
        if n.index < first and not n.is_empty:
            chk.warnings.append(
                f"Nó {n.index} '{n.label}' (antes da árvore Titan) tem correções {n.tools}: o Input CST "
                "espera o footage log original. Desabilite/neutralize esse nó ou o resultado não vai bater."
            )
    if in_cst is not None and in_cst != first:
        chk.warnings.append("O nó de Input CST não é o primeiro da árvore Titan.")
    if chk.titan_nodes_with_content:
        chk.warnings.append(f"Nós Titan já têm conteúdo ({chk.titan_nodes_with_content}); serão sobrescritos "
                            "só com aprovação explícita.")
    return chk


# Funções da API que a aplicação usa, por objeto. Conferidas ANTES de escrever qualquer coisa:
# em versões antigas do Resolve a API devolve None para o que não existe, e a falha viria no meio.
API_APLICAR = {
    "TimelineItem": ("GetNodeGraph", "SetCDL", "GetName"),
    "Graph": ("GetNumNodes", "GetNodeLabel", "GetToolsInNode", "GetLUT", "SetLUT", "SetNodeEnabled"),
    "Project": ("RefreshLUTList",),
}
# SetNodeLabel / SetNodeColor só existem a partir da 21.1.2 e são opcionais: os nós Titan já são achados
# pelo rótulo que vem no template .drx; sem elas o rótulo e a cor ficam como estão no template.
API_OPCIONAL = {"Graph": ("SetNodeLabel", "SetNodeColor")}
# Além das de cima, para criar a versão nova com a árvore:
API_NOVA_VERSAO = {
    "TimelineItem": ("AddVersion", "LoadVersionByName", "GetCurrentVersion"),
    "Graph": ("ApplyGradeFromDRX",),
}


def faltando(objs: dict, req: dict = API_APLICAR) -> list[str]:
    """Nomes 'Objeto.Função' que esta versão do Resolve não tem."""
    out = []
    for kind, names in req.items():
        obj = objs.get(kind)
        if obj is None:
            continue
        out += [f"{kind}.{n}" for n in names if not callable(getattr(obj, n, None))]
    return out


def _tem_cst(tools) -> bool:
    return any("color space" in str(t).casefold() for t in (tools or []))


class SemExportFrame(ResolveError):
    """A versão do Resolve não tem ExportFrame (API nova da 21.1.2)."""


_STILLS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".dpx", ".exr")


class ResolveBridge:
    def __init__(self, resolve=None):
        self.resolve = resolve or connect()
        try:  # diagnóstico: versão do Resolve e do sistema vão para o log
            import platform

            from .log import get_logger

            get_logger().info("resolve: versao=%s produto=%s sistema=%s %s python=%s", self.versao(),
                              getattr(self.resolve, "GetProductName", lambda: "?")(), platform.system(),
                              platform.machine(), platform.python_version())
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ leitura
    @property
    def project(self):
        p = self.resolve.GetProjectManager().GetCurrentProject()
        if not p:
            raise ResolveError("Nenhum projeto aberto.")
        return p

    @property
    def timeline(self):
        t = self.project.GetCurrentTimeline()
        if not t:
            raise ResolveError("Nenhuma timeline ativa.")
        return t

    def target_item(self):
        tl = self.timeline
        sel = []
        if hasattr(tl, "GetSelectedClips"):
            try:
                sel = [c for c in (tl.GetSelectedClips() or []) if c.GetMediaPoolItem()]
            except Exception:
                sel = []
        if len(sel) == 1:
            return sel[0]
        item = tl.GetCurrentVideoItem()
        if not item:
            raise ResolveError("Nenhum clipe selecionado nem sob o playhead.")
        return item

    def inspect(self, item) -> list[NodeInfo]:
        g = item.GetNodeGraph()
        if not g:
            raise ResolveError("GetNodeGraph() não retornou grafo para o clipe.")
        return [NodeInfo(i, g.GetNodeLabel(i) or "", g.GetToolsInNode(i), g.GetLUT(i) or "")
                for i in range(1, g.GetNumNodes() + 1)]

    def _frame(self, obj, offset: int, max_dim: int) -> np.ndarray:
        import time

        export = getattr(obj, "ExportFrame", None)
        if not callable(export):  # a API devolve None para funções que a versão do Resolve não tem
            raise SemExportFrame(f"ExportFrame não existe no DaVinci Resolve {self.versao()} (só na 21.1.2+).")
        res = None
        for attempt in range(3):  # medido: logo após trocar de timeline o Resolve responde "Failed to render frame"
            res = export(int(offset), {"outputType": "encodedString", "encodedImageFormat": "png",
                                                "maxDimension": int(max_dim)})
            if res and res.get("success"):
                return decode_image_bytes(base64.b64decode(res["data"]), max_dim)
            if "out of range" in str(res and res.get("error")):
                break  # offset inválido: tentar de novo não adianta
            time.sleep(1.0)
        raise ResolveError(f"ExportFrame falhou: {res and res.get('error')}")

    def source_frame(self, item, max_dim: int = 1024) -> np.ndarray:
        """Frame ORIGINAL (sem grade) do meio do clipe, via MediaPoolItem.ExportFrame."""
        mpi = item.GetMediaPoolItem()
        if not mpi:
            raise ResolveError("Clipe sem MediaPoolItem (gerador/título?).")
        start = int(item.GetSourceStartFrame())
        # Meio do clipe; stills têm 1 frame na Media Pool (medido: 'frameOffset is out of range').
        last_err = None
        for offset in dict.fromkeys([start + int(item.GetDuration()) // 2, start, 0]):
            try:
                return self._frame(mpi, offset, max_dim)
            except SemExportFrame:
                return self._frame_do_arquivo(mpi, start + int(item.GetDuration()) // 2, max_dim)
            except ResolveError as e:
                last_err = e
        raise last_err

    def graded_frame(self, item, max_dim: int = 1024) -> np.ndarray:
        try:
            return self._frame(item, int(item.GetDuration()) // 2, max_dim)
        except SemExportFrame:  # ExportFrame também volta sem grade; o arquivo dá o mesmo frame
            return self.source_frame(item, max_dim)

    def versao(self) -> str:
        try:
            return str(self.resolve.GetVersionString())
        except Exception:  # noqa: BLE001
            return "?"

    def _frame_do_arquivo(self, mpi, offset: int, max_dim: int) -> np.ndarray:
        """Resolve sem ExportFrame (antes da 21.1.2): lê o frame original direto do arquivo de mídia."""
        import cv2

        path = str(mpi.GetClipProperty("File Path") or "")
        dica = (f"Seu DaVinci Resolve ({self.versao()}) não exporta frames pela API (só a 21.1.2+). "
                "Atualize o Resolve ou use 'Arquivo (offline)' com um print do frame.")
        if not path or not os.path.isfile(path):
            raise ResolveError(f"{dica}\n(arquivo do clipe não encontrado: {path or '?'})")
        img = cv2.imread(path, cv2.IMREAD_COLOR) if path.lower().endswith(_STILLS) else None
        if img is None:
            cap = cv2.VideoCapture(path)
            try:
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if total > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(int(offset), total - 1)))
                ok, img = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, img = cap.read()
                img = img if ok else None
            finally:
                cap.release()
        if img is None:
            raise ResolveError(f"{dica}\n(não consegui ler o vídeo: {os.path.basename(path)})")
        ok, png = cv2.imencode(".png", img)
        if not ok:
            raise ResolveError(dica)
        return decode_image_bytes(png.tobytes(), max_dim)

    # ------------------------------------------------------------ escrita (sempre com aprovação)
    def checar_api(self, item, nova_versao: bool = False) -> None:
        """Erro claro (antes de qualquer escrita) se esta versão do Resolve não tem algo que a aplicação usa."""
        g = item.GetNodeGraph() if callable(getattr(item, "GetNodeGraph", None)) else None
        objs = {"TimelineItem": item, "Graph": g, "Project": self.project}
        falta = faltando(objs) + (faltando(objs, API_NOVA_VERSAO) if nova_versao else [])
        if falta:
            raise ResolveError(f"Seu DaVinci Resolve ({self.versao()}) não tem funções que o Titan Match usa "
                               f"({', '.join(falta)}). Atualize para o DaVinci Resolve Studio 21 ou mais novo.")

    def _install_luts(self, plan: GradePlan, lut_root: Path | None) -> None:
        root = lut_root or lutmod.default_lut_root()
        try:
            export_luts(plan.profile_key, root)
        except OSError as e:
            raise ResolveError(f"Não consegui gravar os LUTs do Titan Match em {root} ({e.strerror or e}). "
                               "Dê permissão de escrita nessa pasta ou rode o Titan Match como administrador.") from e
        if not self.project.RefreshLUTList():
            raise ResolveError("Project.RefreshLUTList() falhou.")

    @staticmethod
    def _snapshot_outside(nodes: list[NodeInfo], titan: set[int]) -> list[tuple]:
        return [(n.index, n.label, tuple(n.tools) if n.tools else n.tools, n.lut)
                for n in nodes if n.index not in titan]

    def fill_block(self, item, plan: GradePlan, *, approved: bool, overwrite_titan: bool = False,
                   lut_root: Path | None = None, reference_display: np.ndarray | None = None,
                   cst_no_drx: bool = False) -> ApplyReport:
        """Preenche os nós Titan (achados pelo label) com o plano.

        cst_no_drx: os nós de CST acabaram de vir do .drx com o Color Space Transform nativo da câmera
        (versão nova); aí não recebem LUT. Na árvore que já estava no clipe, o CST nativo só é mantido
        se o nó já tiver um Color Space Transform; senão o nó recebe o LUT de CST (reserva).
        """
        if not approved:
            raise ApprovalRequired("Aplicação exige aprovação explícita do dry-run.")
        self.checar_api(item)
        labels = [n.label for n in plan.nodes]
        before = self.inspect(item)
        chk = check_block(before, labels)
        if not chk.ok:
            raise ResolveError("; ".join(chk.blockers))
        if chk.titan_nodes_with_content and not overwrite_titan:
            raise ApprovalRequired(
                f"Nós Titan {chk.titan_nodes_with_content} já têm conteúdo. Confirme a sobrescrita explicitamente.")
        rep = ApplyReport("fill_block", item.GetName(), dict(chk.index_of), labels=labels)
        self._install_luts(plan, lut_root)
        g = item.GetNodeGraph()
        set_label = getattr(g, "SetNodeLabel", None)
        set_color = getattr(g, "SetNodeColor", None)
        for n in plan.nodes:
            idx = chk.index_of[_norm(n.label)]
            if callable(set_label):
                self._call(rep, f"SetNodeLabel({idx})", set_label(idx, n.label))
            if callable(set_color):
                self._call(rep, f"SetNodeColor({idx})", set_color(idx, ROLE_INFO[n.role][1]))
            usar_cst = bool(n.native_cst) and (cst_no_drx or _tem_cst(g.GetToolsInNode(idx)))
            if n.lut_path and not usar_cst:
                self._call(rep, f"SetLUT({idx})", g.SetLUT(idx, n.lut_path))
                if not (g.GetLUT(idx) or ""):
                    rep.errors.append(f"LUT do nó {idx} não aplicado: o Resolve não achou {Path(n.lut_path).name} "
                                      f"(pastas de LUT: {', '.join(str(r) for r in lut_roots())}).")
            if n.cdl is not None and (ROLE_INFO[n.role][0] in ("cdl", "skin") or n.role == "haze"):
                self._call(rep, f"SetCDL({idx})", item.SetCDL(n.cdl.to_resolve(idx)))
            enabled = bool(n.enabled)
            if n.role == "skin" and enabled:
                # Sem chave o nó SKIN corrigiria a tela inteira: só liga se já houver chave marcada.
                rep.skin_index = idx
                if not has_skin_key(g.GetToolsInNode(idx)):
                    enabled = False
                    rep.skin_pending = True
            self._call(rep, f"SetNodeEnabled({idx},{enabled})", g.SetNodeEnabled(idx, enabled))

        after = self.inspect(item)
        titan = set(chk.index_of.values())
        if len(after) != len(before):
            rep.errors.append(f"Número de nós mudou de {len(before)} para {len(after)}!")
        if self._snapshot_outside(after, titan) != self._snapshot_outside(before, titan):
            rep.errors.append("Nós fora da árvore Titan mudaram — verifique o grade do usuário.")
        by_idx = {n.index: n for n in after}
        for n in plan.nodes:
            idx = chk.index_of[_norm(n.label)]
            if _norm(by_idx[idx].label) != _norm(n.label):
                rep.errors.append(f"Label do nó {idx} não confere após escrita.")
        rep.verification = self.verify(item, reference_display) if reference_display is not None else {}
        return rep

    def enable_skin(self, item, label: str = "SKIN - Pele") -> tuple[bool, str]:
        """Liga o nó SKIN depois que o usuário marcou a pele (conta-gotas do Qualifier, janela ou Magic Mask)."""
        nodes = self.inspect(item)
        m = locate_nodes(nodes, [label])
        if not m:
            return False, "Nó SKIN não encontrado neste clipe. Aplique a árvore Cinema primeiro."
        idx = m[_norm(label)]
        tools = item.GetNodeGraph().GetToolsInNode(idx)
        if not has_skin_key(tools):
            return False, ("O nó SKIN ainda não tem a pele marcada. No Resolve: selecione o nó SKIN, abra a paleta "
                           "Magic Mask e clique no rosto (e nos braços, se quiser). Em imagem com bastante cor, o "
                           "conta-gotas do Qualifier também serve. Depois clique em Ativar pele de novo.")
        ok = bool(item.GetNodeGraph().SetNodeEnabled(idx, True))
        return ok, ("Pele protegida: nó SKIN ligado." if ok else "SetNodeEnabled falhou.")

    def set_node_cdl(self, item, index_of: dict[str, int], label: str, cdl: CDL, enabled: bool = True) -> bool:
        """Reescreve um único nó Titan (usado pelo painel de ajustes ao vivo)."""
        idx = index_of[_norm(label)]
        g = item.GetNodeGraph()
        ok = bool(item.SetCDL(cdl.to_resolve(idx)))
        return bool(g.SetNodeEnabled(idx, bool(enabled))) and ok

    def apply_as_new_version(self, item, plan: GradePlan, template_drx: str | Path, *, approved: bool,
                             lut_root: Path | None = None, reference_display: np.ndarray | None = None,
                             animate: bool = True, on_frame=None) -> ApplyReport:
        """Cria versão local nova, aplica a árvore (.drx) só nela e preenche.

        Com `animate`, a árvore aparece nó por nó (árvores parciais aplicadas em sequência)
        antes da árvore completa; se algo falhar na animação, segue direto para a completa.

        A versão original do usuário não é alterada; 'restore' volta para ela.
        """
        if not approved:
            raise ApprovalRequired("Aplicação exige aprovação explícita do dry-run.")
        self.checar_api(item, nova_versao=True)
        template_drx = Path(template_drx)
        if not template_drx.is_file():
            raise ResolveError(f"Template .drx não encontrado: {template_drx}")
        original = item.GetCurrentVersion()
        name = "Titan Match " + _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        if not item.AddVersion(name, 0):
            raise ResolveError("AddVersion falhou.")
        if not item.LoadVersionByName(name, 0):
            raise ResolveError("LoadVersionByName falhou; a versão foi criada mas não carregada.")
        g = item.GetNodeGraph()
        with tempfile.TemporaryDirectory(prefix="titan_cst_") as tmp:
            drx, nativo = self._drx_com_cst(template_drx, plan, Path(tmp))
            if animate:
                self._animate_tree(g, drx, on_frame)
            if not g.ApplyGradeFromDRX(str(drx), 0):
                raise ResolveError("ApplyGradeFromDRX falhou na nova versão.")
        rep = self.fill_block(item, plan, approved=True, overwrite_titan=True, lut_root=lut_root,
                              reference_display=reference_display, cst_no_drx=nativo)
        rep.mode = "new_version"
        rep.version_created = name
        rep.original_version = original
        return rep

    @staticmethod
    def _drx_com_cst(template_drx: Path, plan: GradePlan, tmp: Path) -> tuple[Path, bool]:
        """Cópia do template com o Color Space Transform nativo da câmera nos nós de CST."""
        ins = {n.label for n in plan.nodes if n.role == "input_cst" and n.native_cst}
        outs = {n.label for n in plan.nodes if n.role == "output_cst" and n.native_cst}
        if not ins:
            return template_drx, False
        xml = cst_ofx.aplicar_no_drx(template_drx.read_text(encoding="utf-8"), plan.profile_key, ins, outs)
        out = tmp / template_drx.name
        out.write_text(xml, encoding="utf-8", newline="")
        return out, True

    @staticmethod
    def _animate_tree(g, template_drx: Path, on_frame=None, delay: float = 0.12) -> int:
        """Mostra a árvore se montando nó por nó. Nunca impede a aplicação: devolve quantos quadros mostrou."""
        try:
            frames = drx_layout.quadros(template_drx.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return 0
        shown = 0
        with tempfile.TemporaryDirectory(prefix="titan_arvore_") as tmp:
            for i, xml in enumerate(frames):
                f = Path(tmp) / f"quadro_{i:02d}.drx"
                f.write_text(xml, encoding="utf-8", newline="")
                try:
                    ok = bool(g.ApplyGradeFromDRX(str(f), 0))
                except Exception:  # noqa: BLE001 - animação é só visual
                    ok = False
                if not ok:
                    break
                shown += 1
                if on_frame:
                    on_frame(i + 1, len(frames) + 1)
                time.sleep(delay)
        return shown

    def restore(self, item, rep: ApplyReport, *, approved: bool) -> str:
        """Desfaz a última aplicação: volta à versão original ou neutraliza os nós Titan preenchidos."""
        if not approved:
            raise ApprovalRequired("Restaurar exige confirmação.")
        if rep.version_created and rep.original_version:
            name = rep.original_version.get("versionName")
            vtype = int(rep.original_version.get("versionType", 0))
            if not item.LoadVersionByName(name, vtype):
                raise ResolveError(f"Não consegui carregar a versão original '{name}'.")
            return f"Versão original '{name}' carregada. A versão '{rep.version_created}' continua disponível."
        g = item.GetNodeGraph()
        for label, idx in rep.index_of.items():
            item.SetCDL(CDL().to_resolve(idx))
            g.SetNodeEnabled(idx, False)
        return "Nós Titan neutralizados e desligados (os seus nós não foram tocados)."

    def prepare_template(self, item, out_dir: str | Path, *, approved: bool, template: Template = BASIC) -> Path:
        """Rotula os nós da árvore conforme o manifesto e exporta como .drx.

        MEDIDO no Resolve 21.1.2: os índices dos nós são renumerados pela ordem do grafo
        (inserir um nó ou ligar uma chave muda tudo). Por isso:
          * árvore nova (nenhum nó rotulado): rotula pela ordem do manifesto;
          * árvore já rotulada: mantém os rótulos e só rotula os nós sem rótulo que faltam,
            se houver exatamente uma correspondência possível para cada um.
        """
        if not approved:
            raise ApprovalRequired("Preparar template exige aprovação explícita.")
        nodes = self.inspect(item)
        if len(nodes) != len(template.nodes):
            raise ResolveError(f"O clipe precisa ter exatamente {len(template.nodes)} nós para a árvore "
                               f"'{template.title}' (tem {len(nodes)}).")
        busy = [n.index for n in nodes if n.lut]  # efeitos pré-configurados (OFX, qualifier) são permitidos
        if busy:
            raise ResolveError(f"Os nós {busy} têm LUT; use nós novos.")
        g = item.GetNodeGraph()
        falta = faltando({"Graph": g}, API_OPCIONAL)
        if falta:
            raise ResolveError(f"Criar template precisa de {', '.join(falta)} (DaVinci Resolve 21.1.2 ou mais novo; "
                               f"o seu é {self.versao()}).")
        n_mix_tpl = sum(tn.kind == "struct" for tn in template.nodes)
        n_mix = sum(any("Mixer" in t for t in (n.tools or [])) for n in nodes)
        if n_mix != n_mix_tpl:
            raise ResolveError(f"A árvore precisa de {n_mix_tpl} mixer(s); o clipe tem {n_mix}.")
        wanted = [tn for tn in template.nodes if tn.kind != "struct"]
        labeled = {_norm(n.label): n for n in nodes if n.label}
        if not labeled:
            plan = [(i, tn) for i, tn in enumerate(template.nodes, start=1) if tn.kind != "struct"]
            for i, tn in plan:
                if any("Mixer" in t for t in (nodes[i - 1].tools or [])):
                    raise ResolveError(f"O nó {i} é um mixer, mas o manifesto espera '{tn.label}'.")
        else:
            missing = [tn for tn in wanted if _norm(tn.label) not in labeled]
            free = [n for n in nodes if not n.label and not any("Mixer" in t for t in (n.tools or []))]
            if len(missing) != len(free):
                raise ResolveError(f"Faltam rótulos {[t.label for t in missing]} mas há {len(free)} nó(s) sem rótulo.")
            if len(missing) > 1:
                raise ResolveError("Mais de um nó sem rótulo: ambíguo. Rotule-os no Resolve ou adicione um por vez.")
            plan = [(free[0].index, missing[0])] if missing else []
            plan += [(labeled[_norm(tn.label)].index, tn) for tn in wanted if _norm(tn.label) in labeled]
        for i, tn in plan:
            if not g.SetNodeLabel(i, tn.label):
                raise ResolveError(f"SetNodeLabel({i}) falhou.")
            g.SetNodeColor(i, tn.color)
        still = self.timeline.GrabStill()
        if not still:
            raise ResolveError("GrabStill falhou (abra a página Color?).")
        album = self.project.GetGallery().GetCurrentStillAlbum()
        album.SetLabel(still, f"Titan Match - {template.title}")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"TitanMatch_{template.key}_export"
        if not album.ExportStills([still], str(out_dir), prefix, "drx"):
            raise ResolveError("ExportStills(drx) falhou.")
        found = sorted(out_dir.glob(f"{prefix}*.drx"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise ResolveError("ExportStills retornou sucesso mas nenhum .drx apareceu.")
        final = out_dir / (f"TitanMatch_{template.key}.drx")
        if final.exists():
            final.unlink()
        found[-1].rename(final)
        return final

    def verify(self, item, reference_display: np.ndarray) -> dict:
        """Números via ExportFrame — NÃO conferem o grade (limitação medida no Resolve 21.1.2)."""
        from . import profiles as pf
        from .stats import compute_stats, histogram_distance

        graded = self.graded_frame(item)
        s_out = compute_stats(pf.display_to_working(graded))
        s_ref = compute_stats(pf.display_to_working(reference_display))
        return {
            "metodo": "TimelineItem.ExportFrame vs referência",
            "confiavel": False,
            "aviso": "No Resolve 21.1.2 o ExportFrame não reflete o grade aplicado pela API (medido) e vem "
                     "no enquadramento da timeline. Estes números NÃO conferem o grade: confira no viewer.",
            "hist_dist_display": round(histogram_distance(s_out.hist_display, s_ref.hist_display), 5),
            "delta_lab_medios": [round(float(x), 3) for x in
                                 s_out.zones["midtones"].lab_mean - s_ref.zones["midtones"].lab_mean],
        }

    @staticmethod
    def _call(rep: ApplyReport, name: str, result) -> None:
        rep.calls.append({"call": name, "ok": bool(result)})
        if not result:
            rep.errors.append(f"{name} retornou False")
