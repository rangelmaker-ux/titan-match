"""Compatibilidade com versões antigas do Resolve e com o Tk do Mac."""
import numpy as np
import pytest

from titan_match import resolve_bridge as rb


class _Proxy:
    """Imita o fusionscript: função que não existe vira None."""

    def __init__(self, **funcs):
        self._f = funcs

    def __getattr__(self, name):
        return self._f.get(name)


def _ok(*a, **k):
    return True


def _item(graph_funcs, item_extra=None):
    g = _Proxy(**{n: _ok for n in graph_funcs})
    funcs = {n: _ok for n in rb.API_APLICAR["TimelineItem"] + rb.API_NOVA_VERSAO["TimelineItem"]}
    funcs["GetNodeGraph"] = lambda: g
    funcs.update(item_extra or {})
    return _Proxy(**funcs)


class _Resolve:
    def __init__(self, project):
        self.project = project

    def GetVersionString(self):
        return "19.1.4"

    def GetProjectManager(self):
        return _Proxy(GetCurrentProject=lambda: self.project)


def test_api_completa_passa():
    br = rb.ResolveBridge(_Resolve(_Proxy(RefreshLUTList=_ok)))
    br.checar_api(_item(rb.API_APLICAR["Graph"] + rb.API_NOVA_VERSAO["Graph"]), nova_versao=True)


def test_api_faltando_avisa_antes_de_escrever():
    graph = list(rb.API_APLICAR["Graph"])  # sem ApplyGradeFromDRX
    br = rb.ResolveBridge(_Resolve(_Proxy(RefreshLUTList=_ok)))
    br.checar_api(_item(graph))  # só preencher a árvore existente: não precisa dela
    with pytest.raises(rb.ResolveError, match=r"19\.1\.4.*Graph\.ApplyGradeFromDRX"):
        br.checar_api(_item(graph), nova_versao=True)


def test_sem_getnodegraph():
    br = rb.ResolveBridge(_Resolve(_Proxy(RefreshLUTList=_ok)))
    with pytest.raises(rb.ResolveError, match="TimelineItem.GetNodeGraph"):
        br.checar_api(_item(rb.API_APLICAR["Graph"], {"GetNodeGraph": None}))


def test_preview_sem_imagetk():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("sem display")
    try:
        from titan_match.ui import _to_photo

        ph = _to_photo(np.random.rand(120, 200, 3))
        assert ph.width() > 0 and ph.height() > 0
    finally:
        root.destroy()
