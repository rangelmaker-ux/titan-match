"""Smoke test da UI Tkinter (modo arquivo, sem Resolve). Pulado se não houver display."""
import numpy as np
import pytest

from synth import make_pair


def test_ui_does_not_shadow_tkinter_internals():
    """Um método da janela com nome interno do Tk (ex.: _options) quebra TODAS as caixas de diálogo."""
    import tkinter as tk

    from titan_match.ui import TitanMatchApp

    allowed = {"__init__", "__module__", "__doc__", "__qualname__", "__firstlineno__", "__static_attributes__",
               "report_callback_exception"}
    clashes = [n for n in vars(TitanMatchApp) if n not in allowed and hasattr(tk.Tk, n)]
    assert clashes == [], f"métodos que sobrescrevem o Tkinter: {clashes}"


def test_ui_dialog_machinery_works():
    tk = pytest.importorskip("tkinter")
    from titan_match.ui import TitanMatchApp
    try:
        app = TitanMatchApp()
    except tk.TclError as e:
        pytest.skip(f"sem display: {e}")
    try:
        # É exatamente a chamada que messagebox/filedialog fazem por dentro.
        assert isinstance(app._options({"title": "x"}), tuple)
    finally:
        app.destroy()


def test_ui_generates_dry_run_offline(tmp_path):
    tk = pytest.importorskip("tkinter")
    from PIL import Image

    from titan_match.engine import analyze
    try:
        from titan_match.ui import TitanMatchApp
        app = TitanMatchApp()
    except tk.TclError as e:
        pytest.skip(f"sem display: {e}")
    try:
        log, ref = make_pair()
        app._show(analyze(ref, log, "sony_slog3"))
        app.update()
        txt = app.text.get("1.0", "end")
        assert "CST in" in txt and "CST out" in txt and "DRY-RUN" in txt  # árvore padrão: Starter
        assert str(app.apply_btn["state"]) == "disabled"  # modo offline nunca habilita escrita
        assert len(app._photos) == 3
    finally:
        app.destroy()
