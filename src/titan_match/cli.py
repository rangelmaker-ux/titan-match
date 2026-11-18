"""Linha de comando do Titan Match."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import analyze, export_luts, load_image
from .matching import MatchOptions
from .profiles import PROFILES
from .report import format_dry_run, save_plan_json


def _confirm(prompt: str) -> bool:
    print(prompt)
    return input('Digite APLICAR para confirmar: ').strip() == "APLICAR"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="titan_match", description="Titan Match â€” color matching por referÃªncia")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="dry-run offline: referÃªncia + frame log em arquivo")
    a.add_argument("--reference", required=True)
    a.add_argument("--frame", required=True)
    a.add_argument("--profile", required=True, choices=list(PROFILES))
    a.add_argument("--film", action="store_true")
    a.add_argument("--json")

    sub.add_parser("profiles", help="lista os profiles")
    l = sub.add_parser("export-luts", help="gera os .cube de CST")
    l.add_argument("--profile", required=True, choices=list(PROFILES))
    l.add_argument("--out", required=True)

    sub.add_parser("resolve-inspect", help="lista os nÃ³s do clipe alvo (somente leitura)")

    r = sub.add_parser("resolve-match", help="dry-run com o frame do Resolve; aplica sÃ³ apÃ³s confirmaÃ§Ã£o")
    r.add_argument("--reference", required=True)
    r.add_argument("--profile", required=True, choices=list(PROFILES))
    r.add_argument("--film", action="store_true")
    r.add_argument("--json")
    r.add_argument("--apply", choices=["fill_block", "new_version"])
    r.add_argument("--template", help=".drx para --apply new_version")
    r.add_argument("--overwrite-titan", action="store_true", help="permite sobrescrever nÃ³s Titan com conteÃºdo")

    t = sub.add_parser("prepare-template", help="rotula 10 nÃ³s vazios do clipe e exporta template .drx")
    t.add_argument("--out", required=True)

    sub.add_parser("ui", help="abre a interface")
    args = ap.parse_args(argv)

    if args.cmd == "profiles":
        for k, p in PROFILES.items():
            print(f"{k:20s} {p.brand} — {p.label}")
        return 0
    if args.cmd == "export-luts":
        for role, p in export_luts(args.profile, args.out).items():
            print(role, p)
        return 0
    if args.cmd == "ui":
        from .ui import main as ui_main

        ui_main()
        return 0
    if args.cmd == "analyze":
        res = analyze(load_image(args.reference), load_image(args.frame), args.profile,
                      options=MatchOptions(film_emulation=args.film))
        print(format_dry_run(res.plan))
        if args.json:
            save_plan_json(res.plan, args.json)
        return 0

    from .resolve_bridge import ResolveBridge, check_block

    br = ResolveBridge()
    item = br.target_item()
    if args.cmd == "resolve-inspect":
        nodes = br.inspect(item)
        print(f"Clipe: {item.GetName()}  ({len(nodes)} nÃ³s)")
        for n in nodes:
            print(f"  {n.index:3d}  {n.label!r:32s} tools={n.tools} lut={n.lut!r}")
        chk = check_block(nodes)
        print("Bloco Titan:", chk.start)
        for m in chk.blockers + chk.warnings:
            print("  -", m)
        return 0
    if args.cmd == "prepare-template":
        if not _confirm(f"Rotular os nÃ³s do clipe '{item.GetName()}', capturar still e exportar .drx em {args.out}?"):
            print("Cancelado.")
            return 1
        print(br.prepare_template(item, args.out, approved=True))
        return 0
    if args.cmd == "resolve-match":
        ref = load_image(args.reference)
        res = analyze(ref, br.source_frame(item), args.profile, options=MatchOptions(film_emulation=args.film))
        print(format_dry_run(res.plan))
        chk = check_block(br.inspect(item))
        print("\nBloco Titan:", chk.start)
        for m in chk.blockers + chk.warnings:
            print("  -", m)
        if args.json:
            save_plan_json(res.plan, args.json)
        if not args.apply:
            print("\nDry-run apenas. Use --apply fill_block|new_version para escrever.")
            return 0
        if not _confirm(f"\nEscrever o plano acima no clipe '{item.GetName()}' (modo {args.apply})?"):
            print("Cancelado: nada foi escrito.")
            return 1
        if args.apply == "fill_block":
            rep = br.fill_block(item, res.plan, approved=True, overwrite_titan=args.overwrite_titan,
                                reference_display=ref)
        else:
            if not args.template:
                print("--template Ã© obrigatÃ³rio para new_version", file=sys.stderr)
                return 2
            rep = br.apply_as_new_version(item, res.plan, args.template, approved=True, reference_display=ref)
        print(json.dumps({"ok": rep.ok, "errors": rep.errors, "calls": rep.calls,
                          "verification": rep.verification, "version": rep.version_created}, indent=2,
                         ensure_ascii=False))
        return 0 if rep.ok else 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
