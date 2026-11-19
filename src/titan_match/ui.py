"""UI do Titan Match no design system da família Titan ("Obsidian Frosted Glass").

Referência visual: Titan Editor (cores, cards numerados "01 — …", botões por função,
indicador de conexão com o DaVinci Resolve, logo Titan).
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

from . import __version__
from .engine import Analysis, analyze, load_image
from .log import get_logger, log_dir
from .matching import MatchOptions
from .profiles import PROFILES, brands, profiles_for_brand
from .report import format_dry_run, save_plan_json
from .templates import load_templates

PREVIEW_W = 236
PREVIEW_H = 133
from .paths import app_root, user_data_dir

ROOT_DIR = app_root()
TEMPLATES_DIR = ROOT_DIR / "templates"
ASSETS_DIR = ROOT_DIR / "assets"
APP_ID = "Titan.TitanMatch"

# ---- Paleta Titan (igual ao Titan Editor) ----
BG_MAIN = "#090B14"
BG_SURFACE = "#131525"
BG_ELEVATED = "#1C2034"
BG_INPUT = "#0E1020"
BORDER = "#232742"
PURPLE = "#8855F7"
VIOLET = "#A45FFF"
BLUE = "#278BFF"
CYAN = "#40C9FF"
GREEN = "#10B981"
GREEN_HOVER = "#059669"
AMBER = "#F59E0B"
RED = "#EF4444"
TEXT = "#F1F5F9"
TEXT_2 = "#CBD5E1"
TEXT_MUTED = "#94A3B8"
TEXT_DIM = "#64748B"
FONT = "Segoe UI"


def default_template() -> Path | None:
    """Template .drx que acompanha o plugin (o mais recente da pasta templates)."""
    if not TEMPLATES_DIR.is_dir():
        return None
    preferred = TEMPLATES_DIR / "TitanMatch_Template.drx"
    if preferred.is_file():
        return preferred
    found = sorted(TEMPLATES_DIR.glob("*.drx"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _config_path() -> Path:
    return user_data_dir() / "config.json"


def _load_config() -> dict:
    import json

    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_config(**kw) -> None:
    import json

    try:
        cfg = _load_config()
        cfg.update(kw)
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # preferência é conveniência, nunca impede o uso


def _to_photo(arr: np.ndarray):
    from PIL import Image, ImageTk

    im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    im.thumbnail((PREVIEW_W, PREVIEW_H))
    return ImageTk.PhotoImage(im)


def _set_app_id() -> None:
    """Identidade própria na barra de tarefas do Windows (senão o ícone é o do Python)."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001  (fora do Windows ou sem shell32)
        pass


class TitanButton(tk.Label):
    """Botão plano com cor por função, hover e estado desabilitado (estilo Titan)."""

    STYLES = {
        "primary": (PURPLE, VIOLET, "#FFFFFF"),
        "success": (GREEN, GREEN_HOVER, "#FFFFFF"),
        "warning": (BG_ELEVATED, "#2A2F4A", AMBER),
        "ghost": (BG_ELEVATED, "#262B45", TEXT_2),
    }

    def __init__(self, master, text, command, kind="ghost", **kw):
        bg, hover, fg = self.STYLES[kind]
        super().__init__(master, text=text, bg=bg, fg=fg, font=(FONT, 10, "bold"), padx=14, pady=7,
                         cursor="hand2", highlightthickness=1, highlightbackground=BORDER if kind in ("ghost", "warning") else bg,
                         **kw)
        self._colors = (bg, hover, fg)
        self._command = command
        self._enabled = True
        self.bind("<Enter>", lambda e: self._enabled and self.configure(bg=self._colors[1]))
        self.bind("<Leave>", lambda e: self._enabled and self.configure(bg=self._colors[0]))
        self.bind("<Button-1>", lambda e: self._enabled and self._command())

    def configure(self, cnf=None, **kw):  # aceita state="disabled"/"normal" como um Button
        state = kw.pop("state", None)
        if state is not None:
            self._enabled = state != "disabled"
            bg, _, fg = self._colors
            kw.setdefault("bg", bg if self._enabled else "#151829")
            kw.setdefault("fg", fg if self._enabled else TEXT_DIM)
            kw.setdefault("cursor", "hand2" if self._enabled else "arrow")
        return super().configure(cnf, **kw)

    config = configure

    def cget(self, key):
        if key == "state":
            return "normal" if self._enabled else "disabled"
        return super().cget(key)

    def __getitem__(self, key):
        return self.cget(key)


class TitanMatchApp(tk.Tk):
    def __init__(self):
        _set_app_id()
        super().__init__()
        self.title("Titan Match")
        self.geometry("790x830")
        self.minsize(760, 660)
        self.configure(bg=BG_MAIN)
        self.analysis: Analysis | None = None
        self.bridge = None
        self.item = None
        self.last_report = None
        self._photos = []
        self._images = {}
        self._apply_icon()
        self._apply_theme()

        cfg = _load_config()

        # ---------------- cabeçalho
        header = tk.Frame(self, bg=BG_SURFACE, height=58, highlightthickness=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        logo = self._image("titan_match_logo.png")
        if logo:
            tk.Label(header, image=logo, bg=BG_SURFACE).pack(side="left", padx=(16, 8))
        else:
            tk.Label(header, text="TITAN MATCH", bg=BG_SURFACE, fg=TEXT, font=(FONT, 14, "bold")).pack(side="left", padx=20)
        def head_btn(text, cmd, fg=TEXT_2):
            b = tk.Label(header, text=text, bg=BG_ELEVATED, fg=fg, font=(FONT, 9, "bold"), padx=10, pady=5,
                         cursor="hand2", highlightthickness=1, highlightbackground=BORDER)
            b.bind("<Button-1>", lambda e: cmd())
            return b

        self.pin_btn = head_btn("📌", self._toggle_topmost, TEXT_MUTED)
        self.pin_btn.pack(side="right", padx=(6, 16), pady=14)
        head_btn("≡  Logs", self._show_logs).pack(side="right", padx=(6, 0), pady=14)
        self.lic_btn = head_btn("🔑", self._show_license, TEXT_MUTED)
        self.lic_btn.pack(side="right", padx=(6, 0), pady=14)
        self.update_btn = head_btn("⬆ Atualizar", self._do_update, VIOLET)  # aparece só com versão nova
        self._release = None
        head_btn("⟳", self._check_resolve, VIOLET).pack(side="right", padx=(6, 0), pady=14)
        self.conn_pill = tk.Label(header, text="●  Verificando Resolve…", bg=BG_SURFACE, fg=TEXT_MUTED,
                                  font=(FONT, 9, "bold"), padx=10, pady=4, highlightthickness=1,
                                  highlightbackground=BORDER)
        self.conn_pill.pack(side="right", pady=16)

        # ---------------- rodapé (status + progresso)
        footer = tk.Frame(self, bg=BG_SURFACE, height=34)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="Pronto.")
        tk.Label(footer, textvariable=self.status, bg=BG_SURFACE, fg=TEXT_MUTED, font=(FONT, 9),
                 anchor="w").pack(side="left", fill="x", expand=True, padx=16)
        tk.Label(footer, text=f"Titan Match v{__version__}", bg=BG_SURFACE, fg=TEXT_DIM,
                 font=(FONT, 8)).pack(side="right", padx=16)
        self.progress = ttk.Progressbar(footer, length=140, maximum=100, style="Titan.Horizontal.TProgressbar")
        self.progress.pack(side="right", pady=12)

        # ---------------- corpo: coluna de controles + coluna de resultado
        body = tk.Frame(self, bg=BG_MAIN)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        left = tk.Frame(body, bg=BG_MAIN, width=450)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = tk.Frame(body, bg=BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        # Ações fixas no rodapé da coluna (empacotadas antes dos cards para nunca sumirem)
        bottom = tk.Frame(left, bg=BG_MAIN)
        bottom.pack(side="bottom", fill="x")

        # 01 — Câmera
        cam = self._card(left, "01", "Câmera / Log do material", "", PURPLE)
        self._field_label(cam, "Marca", 0, 0)
        self._field_label(cam, "Log / Gamut", 0, 1)
        self.brand_var = tk.StringVar()
        self.brand_cb = ttk.Combobox(cam, textvariable=self.brand_var, values=brands(), state="readonly", width=13,
                                     style="Titan.TCombobox")
        self.brand_cb.grid(row=1, column=0, sticky="we", padx=(0, 8))
        self.profile_var = tk.StringVar()
        self.profile_cb = ttk.Combobox(cam, textvariable=self.profile_var, state="readonly", width=28,
                                       style="Titan.TCombobox")
        self.profile_cb.grid(row=1, column=1, sticky="we")
        TitanButton(cam, "◐ Ver CST", self._preview_cst).grid(row=1, column=2, sticky="e", padx=(8, 0))
        self.profile_note = tk.StringVar()
        tk.Label(cam, textvariable=self.profile_note, bg=BG_SURFACE, fg=TEXT_DIM, font=(FONT, 8), anchor="w",
                 wraplength=410, justify="left").grid(row=2, column=0, columnspan=3, sticky="we", pady=(5, 0))
        cam.columnconfigure(1, weight=1)
        self.brand_cb.bind("<<ComboboxSelected>>", lambda e: self._on_brand())
        self.profile_cb.bind("<<ComboboxSelected>>", lambda e: self._on_profile())

        # 02 — Referência e frame
        ref = self._card(left, "02", "Referência e frame", "", BLUE)
        self._field_label(ref, "Imagem de referência (JPEG/PNG)", 0, 0)
        self.ref_var = tk.StringVar(value=cfg.get("reference", ""))
        row = tk.Frame(ref, bg=BG_SURFACE)
        row.grid(row=1, column=0, columnspan=2, sticky="we")
        ttk.Entry(row, textvariable=self.ref_var, style="Titan.TEntry").pack(side="left", fill="x", expand=True)
        TitanButton(row, "📁  Escolher", self._pick_ref).pack(side="left", padx=(8, 0))
        self._field_label(ref, "Frame do footage", 2, 0)
        self.src_mode = tk.StringVar(value="resolve")
        seg = tk.Frame(ref, bg=BG_INPUT, highlightthickness=1, highlightbackground=BORDER)
        seg.grid(row=3, column=0, sticky="w")
        self._seg_buttons = {}
        for val, txt in (("resolve", "Clipe atual no Resolve"), ("file", "Arquivo (offline)")):
            b = tk.Label(seg, text=txt, font=(FONT, 9, "bold"), padx=10, pady=5, cursor="hand2")
            b.pack(side="left", padx=3, pady=3)
            b.bind("<Button-1>", lambda e, v=val: self._set_src_mode(v))
            self._seg_buttons[val] = b
        frow = tk.Frame(ref, bg=BG_SURFACE)
        frow.grid(row=4, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self._file_row = frow
        self.src_var = tk.StringVar()
        ttk.Entry(frow, textvariable=self.src_var, style="Titan.TEntry").pack(side="left", fill="x", expand=True)
        TitanButton(frow, "…", self._pick_src).pack(side="left", padx=(8, 0))
        ref.columnconfigure(1, weight=1)
        self._set_src_mode("resolve")

        # 03 — Match
        mt = self._card(left, "03", "Match", "", CYAN)
        top = tk.Frame(mt, bg=BG_SURFACE)
        top.grid(row=0, column=0, columnspan=2, sticky="we")
        tk.Label(top, text="Força do match", bg=BG_SURFACE, fg=TEXT_2, font=(FONT, 9)).pack(side="left")
        self.strength_lbl = tk.StringVar()
        tk.Label(top, textvariable=self.strength_lbl, bg=BG_SURFACE, fg=TEXT, font=("Consolas", 10, "bold")).pack(side="right")
        self.strength_var = tk.IntVar(value=int(cfg.get("strength", 100)))
        self.strength_lbl.set(f"{self.strength_var.get()} %")
        ttk.Scale(mt, from_=0, to=100, variable=self.strength_var, style="Titan.Horizontal.TScale",
                  command=lambda v: self.strength_lbl.set(f"{int(float(v))} %")).grid(
            row=1, column=0, columnspan=2, sticky="we", pady=(2, 4))
        self.separate_var = tk.BooleanVar(value=bool(cfg.get("separate_skin", True)))
        self.protect_var = tk.BooleanVar(value=bool(cfg.get("protect_skin", True)))
        self.film_var = tk.BooleanVar(value=bool(cfg.get("film", False)))
        ttk.Checkbutton(mt, text="Separar pele e entorno", variable=self.separate_var,
                        style="Titan.TCheckbutton").grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(mt, text="Proteger tons de pele", variable=self.protect_var,
                        style="Titan.TCheckbutton").grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(mt, text="Film emulation", variable=self.film_var,
                        style="Titan.TCheckbutton").grid(row=3, column=0, sticky="w", pady=(0, 2))
        hz = tk.Frame(mt, bg=BG_SURFACE)
        hz.grid(row=3, column=1, sticky="w", pady=(0, 2))
        tk.Label(hz, text="Neblina / fumaça:", bg=BG_SURFACE, fg=TEXT_2, font=(FONT, 9)).pack(side="left")
        self.haze_names = {"Auto": "auto", "Ligada": "on", "Desligada": "off"}
        self.haze_var = tk.StringVar(value={v: k for k, v in self.haze_names.items()}.get(cfg.get("haze", "auto"), "Auto"))
        ttk.Combobox(hz, textvariable=self.haze_var, values=list(self.haze_names), state="readonly", width=9,
                     style="Titan.TCombobox").pack(side="left", padx=(6, 0))
        self.haze_color_var = tk.BooleanVar(value=bool(cfg.get("haze_color", True)))
        ttk.Checkbutton(hz, text="cor auto", variable=self.haze_color_var,
                        style="Titan.TCheckbutton").pack(side="left", padx=(6, 0))
        self._field_label(mt, "Árvore de nós", 4, 0)
        self.templates = load_templates()
        self.tree_names = {"Automática (pela análise)": "auto"}
        self.tree_names.update({t.title + ("" if t.drx else " — sem .drx"): k for k, t in self.templates.items()})
        self.tree_var = tk.StringVar(value=next(iter(self.tree_names)))
        ttk.Combobox(mt, textvariable=self.tree_var, values=list(self.tree_names), state="readonly",
                     style="Titan.TCombobox").grid(row=5, column=0, columnspan=2, sticky="we")
        sk = tk.Frame(mt, bg=BG_SURFACE)
        sk.grid(row=6, column=0, columnspan=2, sticky="we", pady=(8, 0))
        tk.Label(sk, text="Pele no ambiente:", bg=BG_SURFACE, fg=TEXT_2, font=(FONT, 9)).pack(side="left")
        self.amb_names = {"Pouco (20 %)": 0.20, "Médio (35 %)": 0.35, "Muito (60 %)": 0.60}
        amb_cfg = float(cfg.get("skin_ambience", 0.35))
        self.amb_var = tk.StringVar(value=min(self.amb_names, key=lambda k: abs(self.amb_names[k] - amb_cfg)))
        ttk.Combobox(sk, textvariable=self.amb_var, values=list(self.amb_names), state="readonly", width=13,
                     style="Titan.TCombobox").pack(side="left", padx=(6, 0))
        self.skin_btn = TitanButton(sk, "✋ Ativar pele", self._enable_skin, kind="ghost")
        self.skin_btn.pack(side="right")
        self.skin_btn.configure(state="disabled")
        self.people_lbl = tk.Label(sk, text="👤 pessoas: —", bg=BG_SURFACE, fg=TEXT_MUTED, font=(FONT, 9, "bold"))
        self.people_lbl.pack(side="right", padx=(0, 8))
        mt.columnconfigure(0, weight=1)
        mt.columnconfigure(1, weight=1)

        # Ações
        act = tk.Frame(bottom, bg=BG_MAIN)
        act.pack(fill="x", pady=(2, 0))
        TitanButton(act, "✦  Gerar Grade", self._generate, kind="primary").pack(side="left")
        self.apply_btn = TitanButton(act, "▶  Aplicar no Resolve", self._apply, kind="success")
        self.apply_btn.pack(side="left", padx=8)
        self.restore_btn = TitanButton(act, "↺  Restaurar", self._restore, kind="warning")
        self.restore_btn.pack(side="left")
        self.apply_btn.configure(state="disabled")
        self.restore_btn.configure(state="disabled")
        modes = tk.Frame(bottom, bg=BG_MAIN)
        modes.pack(fill="x", pady=(8, 0))
        tk.Label(modes, text="Aplicar:", bg=BG_MAIN, fg=TEXT_MUTED, font=(FONT, 9)).pack(side="left")
        self.mode_var = tk.StringVar(value="auto")
        for val, txt in (("auto", "Automático"), ("fill_block", "Só árvore já no clipe"),
                         ("new_version", "Sempre nova versão")):
            ttk.Radiobutton(modes, text=txt, variable=self.mode_var, value=val,
                            style="Titan.Main.TRadiobutton").pack(side="left", padx=(8, 0))
        links = tk.Frame(bottom, bg=BG_MAIN)
        links.pack(fill="x", pady=(8, 0))
        for txt, cmd in (("Criar template da árvore selecionada", self._make_template),
                         ("Ver logs (dry-run)", self._show_logs)):
            l = tk.Label(links, text=txt, bg=BG_MAIN, fg=CYAN, font=(FONT, 9, "underline"), cursor="hand2")
            l.pack(side="left", padx=(0, 16))
            l.bind("<Button-1>", lambda e, c=cmd: c())

        # 04 — Pré-visualização (coluna estreita, imagens empilhadas)
        pv = self._card(right, "04", "Pré-visualização", "", PURPLE, expand=True)
        self.prev_labels = []
        self.prev_titles = []
        for i, name in enumerate(["Antes (CST neutro)", "Depois (simulado)", "Referência"]):
            t = tk.StringVar(value=name)
            self.prev_titles.append(t)
            tk.Label(pv, textvariable=t, bg=BG_SURFACE, fg=TEXT_MUTED, font=(FONT, 8, "bold"), anchor="w").grid(
                row=2 * i, column=0, sticky="w", pady=(0 if i == 0 else 6, 3))
            blank = tk.PhotoImage(width=PREVIEW_W, height=PREVIEW_H)  # com imagem, width/height ficam em pixels
            self._images[f"_blank{i}"] = blank
            lbl = tk.Label(pv, image=blank, bg=BG_INPUT, highlightthickness=1, highlightbackground=BORDER)
            lbl.grid(row=2 * i + 1, column=0)
            self.prev_labels.append(lbl)
        pv.columnconfigure(0, weight=1)

        # Logs (dry-run e conferência): janela separada, fechada por padrão
        self._build_logs()

        start = PROFILES.get(cfg.get("profile", ""), next(iter(PROFILES.values())))
        self.brand_var.set(start.brand)
        self._on_brand(select=start.key)
        self.after(200, lambda: self._dark_title_bar(self))
        self.after(300, self._check_resolve)
        self.after(600, self._check_license)
        self.after(1500, self._check_update)

    # ------------------------------------------------------------ visual
    def _image(self, name):
        if name in self._images:
            return self._images[name]
        p = ASSETS_DIR / name
        img = None
        if p.is_file():
            try:
                img = tk.PhotoImage(file=str(p))
            except tk.TclError:
                img = None
        self._images[name] = img
        return img

    def _apply_icon(self):
        ico = ASSETS_DIR / "titan_match.ico"
        try:
            if ico.is_file():
                self.iconbitmap(default=str(ico))
            png = self._image("titan_match_icon.png")
            if png:
                self.iconphoto(True, png)
        except tk.TclError:
            pass

    @staticmethod
    def _dark_title_bar(win):
        """Barra de título escura no Windows 10/11 (como o Titan Editor)."""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20; 19 em builds antigas)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                    break
            color = ctypes.c_int(0x00140B09)  # BG_MAIN em COLORREF (0x00BBGGRR)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        except Exception:  # noqa: BLE001
            pass

    def _build_logs(self):
        """Janela 'Logs': dry-run completo, conferência e resultado da escrita (fechada por padrão)."""
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("Titan Match — Logs")
        win.geometry("760x620")
        win.configure(bg=BG_MAIN)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)  # fechar só esconde; o conteúdo continua
        try:
            ico = ASSETS_DIR / "titan_match.ico"
            if ico.is_file():
                win.iconbitmap(str(ico))
        except tk.TclError:
            pass
        box = self._card(win, "05", "Logs — dry-run e conferência", "Todos os valores com a origem de cada número.",
                         GREEN, expand=True)
        box.master.pack_configure(padx=14, pady=14)
        self.text = tk.Text(box, wrap="none", font=("Consolas", 9), bg=BG_INPUT, fg=TEXT_2, insertbackground=TEXT,
                            relief="flat", highlightthickness=1, highlightbackground=BORDER, padx=10, pady=8,
                            selectbackground=PURPLE)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.text.yview, style="Titan.Vertical.TScrollbar")
        self.text.configure(yscrollcommand=sb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        bar = tk.Frame(box, bg=BG_SURFACE)
        bar.grid(row=1, column=0, columnspan=2, sticky="we", pady=(10, 0))
        TitanButton(bar, "Salvar plano JSON", self._save_json).pack(side="left")
        TitanButton(bar, "Abrir pasta de logs", self._open_log_dir).pack(side="left", padx=8)
        self.text.insert("1.0", "Nenhuma análise ainda. Clique em Gerar Grade na janela principal.\n"
                                "Nada é escrito no DaVinci Resolve antes de você aprovar.")
        self.log_win = win

    def _show_logs(self):
        self.log_win.deiconify()
        self.log_win.lift()
        self.after(100, lambda: self._dark_title_bar(self.log_win))

    def _open_log_dir(self):
        import os

        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    # ------------------------------------------------------------ licença
    def _check_license(self, online: bool = True):
        from . import licenca

        def work():
            st = licenca.status(online=online)
            self.after(0, self._apply_license_state, st)

        threading.Thread(target=work, daemon=True).start()

    def _apply_license_state(self, st):
        self.license_state = st
        self.lic_btn.configure(fg=GREEN if (st.valid and ("ativa" in st.reason.lower() or "ativo" in st.reason.lower()) and "não" not in st.reason.lower())
                               else (RED if not st.valid else TEXT_MUTED))
        if not st.valid:
            for b in (self.apply_btn,):
                b.configure(state="disabled")
            self.status.set("Licença: " + st.reason)
            self._show_license()

    def _show_license(self):
        from . import licenca

        win = tk.Toplevel(self)
        win.title("Titan Match — Licença")
        win.configure(bg=BG_MAIN)
        win.resizable(False, False)
        win.transient(self)
        try:
            win.iconbitmap(str(ASSETS_DIR / "titan_match.ico"))
        except tk.TclError:
            pass
        box = self._card(win, "🔑", "Licença Titan Loja", "Cole a chave que você recebeu na compra.", PURPLE)
        box.master.pack_configure(padx=14, pady=14)
        st = licenca.status(online=False)
        tk.Label(box, text=("Situação: " + st.reason + (f"  ({st.nome})" if st.nome else "")), bg=BG_SURFACE,
                 fg=GREEN if st.valid and ("ativa" in st.reason or "ativo" in st.reason) else TEXT_MUTED, font=(FONT, 9)).pack(anchor="w")
        var = tk.StringVar()
        e = ttk.Entry(box, textvariable=var, width=46, style="Titan.TEntry")
        e.pack(fill="x", pady=(8, 8))
        msg = tk.StringVar(value="" if licenca.ENFORCE_LICENSE else
                           "Durante o lançamento a licença ainda não é obrigatória.")
        msg_lbl = tk.Label(box, textvariable=msg, bg=BG_SURFACE, fg=TEXT_MUTED, font=(FONT, 10), wraplength=360,
                           justify="left")
        msg_lbl.pack(anchor="w")

        def ativar():
            # Rede fora da thread da interface: a janela não congela e mostra o andamento.
            chave = var.get()
            btn.configure(state="disabled")
            msg_lbl.configure(fg=TEXT_MUTED)
            msg.set("Ativando… conectando à Titan Loja.")

            def work():
                try:
                    s, erro = licenca.activate(chave), None
                except Exception as ex:  # noqa: BLE001
                    s, erro = None, ex
                    get_logger().warning("ativar licença falhou: %r", ex, exc_info=not isinstance(ex, licenca.LicenseError))
                self.after(0, lambda: fim(s, erro))

            def fim(s, erro):
                try:
                    btn.configure(state="normal")
                    if erro is not None:
                        msg_lbl.configure(fg=AMBER)
                        msg.set(str(erro) or erro.__class__.__name__)
                        return
                    get_logger().info("ativar licença: %s", s.reason)
                    msg_lbl.configure(fg=GREEN)
                    msg.set(s.reason)
                    self._apply_license_state(s)
                    self.after(1200, win.destroy)
                except tk.TclError:  # janela fechada no meio
                    pass

            threading.Thread(target=work, daemon=True).start()

        row = tk.Frame(box, bg=BG_SURFACE)
        row.pack(fill="x", pady=(10, 0))
        btn = TitanButton(row, "Ativar", ativar, kind="primary")
        btn.pack(side="left")
        e.bind("<Return>", lambda ev: btn.cget("state") == "normal" and ativar())
        TitanButton(row, "Fechar", win.destroy).pack(side="left", padx=8)
        e.focus_set()
        self.after(100, lambda: self._dark_title_bar(win))

    # ------------------------------------------------------------ atualização
    def _check_update(self):
        from . import update

        def work():
            from . import licenca

            lic = licenca.status(online=False)
            if licenca.ENFORCE_LICENSE and not lic.atualizacoes:
                get_logger().info("atualização: bloqueada pela licença (%s)", lic.reason)
                return
            st, rel = update.check()
            get_logger().info("atualização: %s %s", st, rel.version if rel else "")
            if st == "available":
                self.after(0, self._offer_update, rel)

        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, rel):
        self._release = rel
        self.update_btn.configure(text=f"⬆ v{rel.version}")
        self.update_btn.pack(side="right", padx=(6, 0), pady=14)

    def _do_update(self):
        from . import update

        rel = self._release
        if not rel:
            return
        if not update.installed_layout():
            messagebox.showinfo("Titan Match", "Modo desenvolvimento: atualize pelo git (git pull).")
            return
        if not messagebox.askyesno("Atualizar Titan Match",
                                   f"Instalar a versão {rel.version}?\n\nUm backup da versão atual é guardado."):
            return
        self.status.set("Baixando atualização…")
        self._set_progress_style("busy")
        self.progress["value"] = 30

        def work():
            try:
                pkg = update.download(rel)
                update.install_package(pkg, rel.version)
            except Exception as ex:  # noqa: BLE001
                self._report_error(ex)
                return

            def done():
                self.progress["value"] = 100
                self._set_progress_style("done")
                self.status.set(f"Atualizado para {rel.version}. Feche e abra o Titan Match.")
                messagebox.showinfo("Titan Match", f"Atualizado para a versão {rel.version}.\n\n"
                                                   "Feche e abra o Titan Match para usar a nova versão.")
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_topmost(self):
        on = not bool(self.attributes("-topmost"))
        self.attributes("-topmost", on)
        self.pin_btn.configure(fg=VIOLET if on else TEXT_MUTED, highlightbackground=PURPLE if on else BORDER)
        self.status.set("Janela fixada por cima do Resolve." if on else "Janela solta.")

    def _apply_theme(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG_SURFACE, foreground=TEXT_2, font=(FONT, 9))
        st.configure("Titan.TCombobox", fieldbackground=BG_INPUT, background=BG_ELEVATED, foreground=TEXT,
                     arrowcolor=VIOLET, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
        st.map("Titan.TCombobox", fieldbackground=[("readonly", BG_INPUT)], foreground=[("readonly", TEXT)],
               selectbackground=[("readonly", BG_INPUT)], selectforeground=[("readonly", TEXT)],
               bordercolor=[("focus", PURPLE)])
        self.option_add("*TCombobox*Listbox.background", BG_ELEVATED)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", PURPLE)
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.option_add("*TCombobox*Listbox.font", (FONT, 9))
        st.configure("Titan.TEntry", fieldbackground=BG_INPUT, foreground=TEXT, insertcolor=TEXT, bordercolor=BORDER,
                     lightcolor=BORDER, darkcolor=BORDER, padding=6)
        st.map("Titan.TEntry", bordercolor=[("focus", PURPLE)])
        for name, bg in (("Titan.TCheckbutton", BG_SURFACE), ("Titan.TRadiobutton", BG_SURFACE),
                         ("Titan.Main.TRadiobutton", BG_MAIN)):
            st.configure(name, background=bg, foreground=TEXT_2, indicatorbackground=BG_INPUT,
                         indicatorforeground=VIOLET, focuscolor=bg, font=(FONT, 9))
            st.map(name, background=[("active", bg)], foreground=[("active", TEXT)],
                   indicatorbackground=[("selected", BG_INPUT), ("active", BG_ELEVATED)],
                   indicatorforeground=[("selected", VIOLET)])
        st.configure("Titan.Horizontal.TScale", background=PURPLE, troughcolor=BG_INPUT, bordercolor=BORDER,
                     lightcolor=VIOLET, darkcolor=PURPLE, sliderthickness=14)
        st.configure("Titan.Horizontal.TProgressbar", troughcolor=BG_INPUT, background=PURPLE, bordercolor=BORDER,
                     lightcolor=VIOLET, darkcolor=BLUE, thickness=8)
        st.configure("Titan.Done.Horizontal.TProgressbar", troughcolor=BG_INPUT, background=GREEN, bordercolor=BORDER,
                     lightcolor="#34D399", darkcolor=GREEN_HOVER, thickness=8)
        st.configure("Titan.Error.Horizontal.TProgressbar", troughcolor=BG_INPUT, background=RED, bordercolor=BORDER,
                     lightcolor="#F87171", darkcolor="#DC2626", thickness=8)
        st.configure("Titan.Vertical.TScrollbar", background=BG_ELEVATED, troughcolor=BG_INPUT, bordercolor=BG_INPUT,
                     arrowcolor=TEXT_MUTED, lightcolor=BG_ELEVATED, darkcolor=BG_ELEVATED, gripcount=0)
        st.map("Titan.Vertical.TScrollbar",
               background=[("pressed", PURPLE), ("active", "#2A2F4A"), ("!disabled", BG_ELEVATED)],
               lightcolor=[("!disabled", BG_ELEVATED)], darkcolor=[("!disabled", BG_ELEVATED)])

    def _card(self, parent, num, title, subtitle, accent, expand=False):
        outer = tk.Frame(parent, bg=BG_SURFACE, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 10))
        head = tk.Frame(outer, bg=BG_SURFACE)
        head.pack(fill="x", padx=14, pady=(10, 6))
        badge = tk.Label(head, text=num, bg=BG_ELEVATED, fg=accent, font=("Consolas", 9, "bold"), width=3, pady=2,
                         highlightthickness=1, highlightbackground=BORDER)
        badge.pack(side="left", anchor="n")
        tt = tk.Frame(head, bg=BG_SURFACE)
        tt.pack(side="left", padx=10)
        tk.Label(tt, text=f"{num} — {title}", bg=BG_SURFACE, fg=TEXT, font=(FONT, 11, "bold"), anchor="w").pack(anchor="w")
        if subtitle:
            tk.Label(tt, text=subtitle, bg=BG_SURFACE, fg=TEXT_MUTED, font=(FONT, 9), anchor="w").pack(anchor="w")
        body = tk.Frame(outer, bg=BG_SURFACE)
        body.pack(fill="both", expand=expand, padx=14, pady=(0, 10))
        return body

    @staticmethod
    def _field_label(parent, text, row, col):
        tk.Label(parent, text=text, bg=BG_SURFACE, fg=TEXT_2, font=(FONT, 9), anchor="w").grid(
            row=row, column=col, sticky="w", pady=(2, 4))

    def _set_src_mode(self, val):
        self.src_mode.set(val)
        if hasattr(self, "_file_row"):
            if val == "file":
                self._file_row.grid()
            else:
                self._file_row.grid_remove()
        for v, b in self._seg_buttons.items():
            on = v == val
            b.configure(bg=PURPLE if on else BG_INPUT, fg="#FFFFFF" if on else TEXT_MUTED)

    def _check_resolve(self):
        self.conn_pill.configure(text="●  Verificando DaVinci Resolve…", fg=TEXT_MUTED, highlightbackground=BORDER)

        def work():
            try:
                from .resolve_bridge import ResolveBridge

                br = self.bridge or ResolveBridge()
                name = br.project.GetName()
                self.bridge = br
                self.after(0, lambda: self.conn_pill.configure(
                    text=f"●  Resolve — {name[:14]}", fg=GREEN, highlightbackground=GREEN))
            except Exception:  # noqa: BLE001
                self.after(0, lambda: self.conn_pill.configure(
                    text="●  Resolve desconectado", fg=RED, highlightbackground=RED))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ erros
    def _report_error(self, exc: BaseException) -> None:
        """Mostra o erro na janela (seguro para chamar de qualquer thread) e grava no log."""
        import traceback

        msg = f"{type(exc).__name__}: {exc}"
        get_logger().error("%s\n%s", msg, "".join(traceback.format_exception(exc)))
        if isinstance(exc, TypeError) and "'NoneType' object is not callable" in str(exc):
            # A API do Resolve devolve None para funções que a versão instalada não tem.
            ver = self.bridge.versao() if getattr(self, "bridge", None) else "?"
            msg = (f"Sua versão do DaVinci Resolve ({ver}) não tem uma função que o Titan Match usa. "
                   "Atualize para o DaVinci Resolve Studio 21 ou mais novo.")

        def show(m=msg):
            if getattr(self, "_showing_error", False):
                return  # nunca empilha caixas de erro (evita loop se a própria caixa falhar)
            self._showing_error = True
            try:
                self.progress["value"] = 100
                self._set_progress_style("error")
                self.status.set("Erro: " + m)
                messagebox.showerror("Titan Match", f"{m}\n\nDetalhes no log: {log_dir()}")
            except Exception:  # noqa: BLE001
                get_logger().exception("falha ao mostrar a caixa de erro")
            finally:
                self._showing_error = False

        self.after(0, show)

    def report_callback_exception(self, exc, val, tb):  # erros dentro de callbacks do Tk
        if getattr(self, "_showing_error", False):
            get_logger().error("erro dentro da caixa de erro: %s", val)
            return
        self._report_error(val)

    # ------------------------------------------------------------
    def _on_brand(self, select: str | None = None):
        items = profiles_for_brand(self.brand_var.get())
        self._brand_profiles = {p.label: p.key for p in items}
        self.profile_cb.configure(values=list(self._brand_profiles))
        chosen = next((p for p in items if p.key == select), items[0])
        self.profile_var.set(chosen.label)
        self._on_profile()

    def _on_profile(self):
        p = PROFILES[self.profile_key]
        self.profile_note.set(f"Input CST: {p.label} → DaVinci Wide Gamut / Intermediate"
                              + (f"   ({p.note})" if p.note else ""))
        _save_config(profile=p.key)
        self.analysis = None
        self.apply_btn.configure(state="disabled") if hasattr(self, "apply_btn") else None

    @property
    def profile_key(self) -> str:
        return self._brand_profiles[self.profile_var.get()]

    def _get_source(self):
        if self.src_mode.get() == "resolve":
            from .resolve_bridge import ResolveBridge

            self.bridge = self.bridge or ResolveBridge()
            self.item = self.bridge.target_item()
            return self.bridge.source_frame(self.item)
        self.item = None
        return load_image(self.src_var.get())

    def _preview_cst(self):
        """Mostra o frame só com Input CST + Output CST, para conferir o log escolhido."""
        self.status.set("Pré-visualizando CST…")
        key = self.profile_key

        def work():
            try:
                from .profiles import get_profile, input_cst, output_cst

                src = self._get_source()
                disp = output_cst(input_cst(np.clip(src, 0, 1), get_profile(key)))
                self.after(0, self._show_cst, src, disp)
            except Exception as e:  # noqa: BLE001
                self._report_error(e)

        threading.Thread(target=work, daemon=True).start()

    def _show_cst(self, src, disp):
        self._photos = [_to_photo(disp), _to_photo(src)]
        self.prev_titles[0].set("Com Input CST (confira o log)")
        self.prev_titles[1].set("Original (log da câmera)")
        self.prev_titles[2].set("Referência")
        self.prev_labels[0].configure(image=self._photos[0])
        self.prev_labels[1].configure(image=self._photos[1])
        self.status.set("Se a imagem com CST ficar com contraste/cor naturais, o log está certo. "
                        "Lavada ou estourada = log errado.")

    def _pick_ref(self):
        p = filedialog.askopenfilename(filetypes=[("Imagens", "*.jpg *.jpeg *.png")])
        if p:
            self.ref_var.set(p)
            _save_config(reference=p)

    def _pick_src(self):
        p = filedialog.askopenfilename(filetypes=[("Imagens", "*.png *.jpg *.jpeg *.tif *.tiff")])
        if p:
            self.src_var.set(p)
            self.src_mode.set("file")


    # ------------------------------------------------------------ gerar
    def _match_options(self) -> MatchOptions:
        _save_config(strength=int(self.strength_var.get()), separate_skin=self.separate_var.get(),
                     protect_skin=self.protect_var.get(), film=self.film_var.get(),
                     haze=self.haze_names[self.haze_var.get()], haze_color=self.haze_color_var.get(),
                     skin_ambience=self.amb_names[self.amb_var.get()])
        return MatchOptions(
            film_emulation=self.film_var.get(),
            strength=float(self.strength_var.get()) / 100.0,
            protect_skin=self.protect_var.get(),
            separate_skin=self.separate_var.get(),
            template=self.tree_names[self.tree_var.get()],
            haze=self.haze_names[self.haze_var.get()],
            haze_color=self.haze_color_var.get(),
            skin_ambience=self.amb_names[self.amb_var.get()],
            progress=lambda p, m: self.after(0, self._set_progress, p, m),
        )

    def _set_progress(self, pct, msg):
        self.progress["value"] = pct
        self.status.set(msg)
        self._set_progress_style("done" if pct >= 100 else "busy")

    def _set_progress_style(self, state: str) -> None:
        """Roxo enquanto trabalha, verde quando termina, vermelho se der erro."""
        self.progress.configure(style={"busy": "Titan.Horizontal.TProgressbar",
                                       "done": "Titan.Done.Horizontal.TProgressbar",
                                       "error": "Titan.Error.Horizontal.TProgressbar"}[state])

    def _license_ok(self) -> bool:
        """Confere a licença na hora de usar (o teste grátis pode vencer com o plugin aberto)."""
        from . import licenca

        st = licenca.status(online=False)
        if st.valid:
            return True
        self._apply_license_state(st)
        return False

    def _generate(self):
        if not self._license_ok():
            return
        ref = self.ref_var.get().strip()
        if not Path(ref).is_file():
            messagebox.showerror("Titan Match", "Escolha uma imagem de referência válida.")
            return
        self.status.set("Analisando…")
        self.progress["value"] = 0
        self._set_progress_style("busy")
        self.apply_btn.configure(state="disabled")
        opts = self._match_options()
        threading.Thread(target=self._generate_worker, args=(ref, opts), daemon=True).start()

    def _generate_worker(self, ref, opts):
        try:
            ref_img = load_image(ref)
            src = self._get_source()
            a = analyze(ref_img, src, self.profile_key, options=opts, templates=self.templates)
            self.after(0, self._show, a)
        except Exception as e:  # noqa: BLE001
            self._report_error(e)

    def _show(self, a: Analysis):
        self.analysis = a
        v = a.plan.verification
        n_p = int(v.get("pessoas_footage", 0))
        if n_p:
            skin_on = a.plan.has("skin") and a.plan.node("skin").enabled
            self.people_lbl.configure(text=f"👤 {n_p} pessoa(s) — pele {'protegida' if skin_on else 'sem nó SKIN'}",
                                      fg=GREEN if skin_on else AMBER)
        elif v.get("pele_fracao_footage", 0) >= 0.03:
            self.people_lbl.configure(text="👤 pele detectada (sem rosto)", fg=AMBER)
        else:
            self.people_lbl.configure(text="👤 nenhuma pessoa", fg=TEXT_MUTED)
        get_logger().info("gerar: arvore=%s (%s) nos_ligados=%d verif=%s", a.plan.template_key, a.plan.template_reason,
                          sum(n.enabled for n in a.plan.nodes),
                          {k: a.plan.verification.get(k) for k in ("hist_dist_display_antes", "hist_dist_display_depois")})
        for t, name in zip(self.prev_titles, ["Antes (CST neutro)", "Depois (simulado)", "Referência"]):
            t.set(name)
        self._photos = [_to_photo(x) for x in (a.neutral_display, a.after_display, a.reference_display)]
        for lbl, ph in zip(self.prev_labels, self._photos):
            lbl.configure(image=ph)
        txt = format_dry_run(a.plan)
        if self.bridge and self.item is not None:
            from .resolve_bridge import check_block

            chk = check_block(self.bridge.inspect(self.item), [n.label for n in a.plan.nodes])
            txt += "\n\nSITUAÇÃO DO CLIPE NO RESOLVE:\n"
            txt += ("    árvore Titan já está no clipe: será preenchida\n" if chk.ok else
                    "    árvore Titan não está no clipe: Aplicar cria uma versão local nova com ela\n")
            for m in chk.warnings:
                txt += f"    - {m}\n"
        self.text.delete("1.0", "end")
        self.text.insert("1.0", txt)
        self.apply_btn.configure(state="normal" if self.item is not None else "disabled")
        self.status.set(f"Pronto: árvore '{a.plan.template_title}', "
                        f"{sum(n.enabled for n in a.plan.nodes)} nós ligados. Pronto para aplicar.")

    # ------------------------------------------------------------ aplicar / restaurar
    def _apply(self):
        a = self.analysis
        if not a or self.item is None:
            return
        if not self._license_ok():
            return
        from .resolve_bridge import ApprovalRequired, check_block

        labels = [n.label for n in a.plan.nodes]
        mode = self.mode_var.get()
        chk = check_block(self.bridge.inspect(self.item), labels)
        if mode == "auto":
            mode = "fill_block" if chk.ok else "new_version"
        if mode == "fill_block" and not chk.ok:
            messagebox.showerror("Titan Match", "; ".join(chk.blockers))
            return
        tpl = self.templates.get(a.plan.template_key)
        drx = tpl.drx if tpl else None
        if mode == "new_version" and drx is None:
            messagebox.showerror("Titan Match", f"A árvore '{a.plan.template_title}' não tem .drx instalado em "
                                                f"{TEMPLATES_DIR}. Escolha outra árvore ou crie o template.")
            return
        # Clicar em "Aplicar no Resolve" já é a aprovação (o dry-run foi mostrado no Gerar):
        # aplica direto. Os nós do usuário nunca são tocados (nova versão ou só nós Titan),
        # e "Restaurar" — que pede confirmação — desfaz.
        self._set_progress_style("busy")
        self.progress["value"] = 50
        self.status.set("Aplicando no DaVinci Resolve…")
        self.update_idletasks()
        try:
            if mode == "fill_block":
                rep = self.bridge.fill_block(self.item, a.plan, approved=True,
                                             overwrite_titan=bool(chk.titan_nodes_with_content),
                                             reference_display=a.reference_display)
            else:
                def frame(i: int, n: int) -> None:
                    self.progress["value"] = 50 + 40 * i // n
                    self.status.set(f"Montando a árvore… nó {i} de {n}")
                    self.update_idletasks()

                rep = self.bridge.apply_as_new_version(self.item, a.plan, drx, approved=True,
                                                       reference_display=a.reference_display,
                                                       animate=bool(_load_config().get("animar_arvore", True)),
                                                       on_frame=frame)
        except ApprovalRequired as e:
            self.progress["value"] = 0
            messagebox.showwarning("Titan Match", str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.progress["value"] = 0
            messagebox.showerror("Titan Match", str(e))
            return
        self.progress["value"] = 100
        self._set_progress_style("error" if rep.errors else "done")
        self.last_report = rep
        get_logger().info("aplicar: modo=%s clipe=%s versao=%s ok=%s erros=%s chamadas=%d",
                          rep.mode, rep.item_name, rep.version_created, rep.ok, rep.errors, len(rep.calls))
        self.restore_btn.configure(state="normal")
        out = "\n\nRESULTADO DA ESCRITA:\n" + "\n".join(f"    {c['call']}: {'ok' if c['ok'] else 'FALHOU'}" for c in rep.calls)
        out += "\n" + ("\n".join("    ERRO: " + e for e in rep.errors) if rep.errors else "    sem erros reportados")
        out += "\nConfira o resultado no viewer do Resolve (a API não devolve o frame graduado)."
        self.text.insert("end", out)
        if rep.skin_pending:
            self.skin_btn.configure(state="normal")
            self.people_lbl.configure(text="👆 marque a pele no nó SKIN", fg=AMBER)
            self.status.set("Aplicado. Para proteger a pele: no Resolve, selecione o nó SKIN, abra o Magic Mask, "
                            "clique no rosto (e nos braços, se quiser) e depois clique em Ativar pele.")
        else:
            self.status.set("Aplicado com erros — confira." if rep.errors else "Aplicado. Confira o resultado no Resolve.")

    def _enable_skin(self):
        if self.item is None or self.bridge is None:
            return
        try:
            ok, msg = self.bridge.enable_skin(self.item)
        except Exception as e:  # noqa: BLE001
            self._report_error(e)
            return
        get_logger().info("ativar pele: ok=%s %s", ok, msg)
        self.status.set(msg)
        if ok:
            self.skin_btn.configure(state="disabled")
            self.people_lbl.configure(text="👤 pele protegida", fg=GREEN)
            self._set_progress_style("done")
        else:
            messagebox.showinfo("Titan Match", msg)

    def _restore(self):
        rep = self.last_report
        if not rep or self.item is None:
            return
        what = ("voltar para a versão original do clipe" if rep.version_created
                else "neutralizar e desligar os nós Titan preenchidos")
        if not messagebox.askyesno("Restaurar original", f"Vou {what}. Continuar?"):
            return
        try:
            msg = self.bridge.restore(self.item, rep, approved=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Titan Match", str(e))
            return
        self.restore_btn.configure(state="disabled")
        self.status.set(msg)

    # ------------------------------------------------------------ template
    def _make_template(self):
        """Rotula os nós vazios do clipe atual conforme a árvore selecionada e exporta o .drx."""
        key = self.tree_names[self.tree_var.get()]
        if key == "auto":
            messagebox.showinfo("Titan Match", "Escolha uma árvore específica (não 'Automática') para criar o template.")
            return
        tpl = self.templates[key]
        try:
            from .resolve_bridge import ResolveBridge

            self.bridge = self.bridge or ResolveBridge()
            item = self.bridge.target_item()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Titan Match", str(e))
            return
        if not messagebox.askyesno(
            "Criar template",
            f"Clipe: '{item.GetName()}'.\nÁrvore: {tpl.title} — {len(tpl.nodes)} nós.\nTopologia: {tpl.topology}\n\n"
            "O clipe precisa ter exatamente esses nós, vazios, criados nessa ordem.\n\nVou rotular os nós, "
            "capturar um still na Gallery e salvar o .drx na pasta templates. Continuar?"):
            return
        try:
            p = self.bridge.prepare_template(item, TEMPLATES_DIR, approved=True, template=tpl)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Titan Match", str(e))
            return
        self.templates = load_templates()
        messagebox.showinfo("Titan Match", f"Template criado:\n{p}")

    def _save_json(self):
        if not self.analysis:
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if p:
            save_plan_json(self.analysis.plan, p)


def main():
    TitanMatchApp().mainloop()
