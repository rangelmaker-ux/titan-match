"""Gera o ícone e o logo do Titan Match no estilo da família Titan (Obsidian Frosted Glass).

Saída em assets/:
  titan_match_icon.png (512), titan_match.ico (16–256), titan_match_symbol_64.png,
  titan_match_logo.png (cabeçalho da janela)
"""
from __future__ import annotations

import colorsys
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"
S = 2048  # desenha grande e reduz (antialias)
TITAN = [(0.0, (192, 132, 252)), (0.30, (136, 85, 247)), (0.70, (39, 139, 255)), (1.0, (64, 201, 255))]
OBSIDIAN = [(0.0, (26, 29, 54)), (0.5, (19, 21, 37)), (1.0, (11, 13, 24))]


def _lerp(stops, t):
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            k = (t - t0) / max(t1 - t0, 1e-9)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
    return stops[-1][1]


def diag_gradient(size, stops):
    w, h = size
    small = Image.new("RGB", (256, 256))
    px = small.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = _lerp(stops, (x + y) / 510)
    return small.resize((w, h), Image.BICUBIC)


def vert_gradient(size, stops):
    w, h = size
    col = Image.new("RGB", (1, 256))
    for y in range(256):
        col.putpixel((0, y), _lerp(stops, 1 - y / 255))
    return col.resize((w, h), Image.BICUBIC)


def shape_mask(draw_fn):
    m = Image.new("L", (S, S), 0)
    draw_fn(ImageDraw.Draw(m))
    return m


def symbol(size: int = 512) -> Image.Image:
    u = S / 128  # coordenadas no mesmo grid 128×128 do símbolo do Titan Editor
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Base de vidro obsidiana
    base = shape_mask(lambda d: d.rounded_rectangle([4 * u, 4 * u, 124 * u, 124 * u], radius=26 * u, fill=255))
    img.paste(diag_gradient((S, S), OBSIDIAN), (0, 0), base)
    border = shape_mask(lambda d: d.rounded_rectangle([4 * u, 4 * u, 124 * u, 124 * u], radius=26 * u,
                                                      outline=255, width=int(1.6 * u)))
    bgrad = diag_gradient((S, S), [(0.0, (164, 95, 255)), (0.45, (64, 201, 255)), (1.0, (40, 44, 70))])
    img.paste(bgrad, (0, 0), border)
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.arc([12 * u, 12 * u, 44 * u, 44 * u], 180, 270, fill=(255, 255, 255, 60), width=int(1.0 * u))
    d.line([28 * u, 12 * u, 100 * u, 12 * u], fill=(255, 255, 255, 60), width=int(1.0 * u))
    d.arc([84 * u, 12 * u, 116 * u, 44 * u], 270, 360, fill=(255, 255, 255, 60), width=int(1.0 * u))
    img = Image.alpha_composite(img, ov)

    # Barras laterais: quente (esquerda) × fria (direita) = o "match" laranja/azul
    warm = [(0.0, (180, 70, 30)), (0.6, (255, 140, 60)), (1.0, (255, 200, 120))]
    cool = [(0.0, (20, 80, 160)), (0.6, (39, 139, 255)), (1.0, (64, 220, 255))]
    for (x, y, h, op), stops in [((14, 56, 16, .65), warm), ((21, 44, 40, .9), warm), ((28, 50, 28, .75), warm),
                                 ((96, 50, 28, .75), cool), ((103, 44, 40, .9), cool), ((110, 56, 16, .65), cool)]:
        m = shape_mask(lambda dd: dd.rounded_rectangle([x * u, y * u, (x + 3.5) * u, (y + h) * u],
                                                       radius=1.75 * u, fill=int(255 * op)))
        img.paste(vert_gradient((S, S), stops), (0, 0), m)

    # Letra T no gradiente Titan, com brilho roxo
    def t_shape(dd):
        dd.rounded_rectangle([33 * u, 28 * u, 95 * u, 45 * u], radius=3 * u, fill=255)
        dd.rounded_rectangle([55 * u, 40 * u, 73 * u, 103 * u], radius=4 * u, fill=255)

    tmask = shape_mask(t_shape)
    glow = Image.new("RGBA", (S, S), (136, 85, 247, 0))
    glow.putalpha(tmask.filter(ImageFilter.GaussianBlur(7 * u)).point(lambda v: int(v * 0.55)))
    img = Image.alpha_composite(img, glow)
    img.paste(diag_gradient((S, S), TITAN), (0, 0), tmask)
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ov).line([37 * u, 30.5 * u, 91 * u, 30.5 * u], fill=(255, 255, 255, 150), width=int(1.0 * u))
    img = Image.alpha_composite(img, ov)

    # Roda de cor (color wheel de grading) sobre a haste do T
    cx, cy, r_out, r_in = 64 * u, 70 * u, 15 * u, 10.5 * u
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rp = ring.load()
    x0, x1, y0, y1 = int(cx - r_out - 2), int(cx + r_out + 2), int(cy - r_out - 2), int(cy + r_out + 2)
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            dx, dy = xx - cx, yy - cy
            rr = math.hypot(dx, dy)
            if r_in <= rr <= r_out:
                hue = (math.degrees(math.atan2(-dy, dx)) % 360) / 360
                rgb = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
                rp[xx, yy] = (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), 255)
    halo = Image.new("RGBA", (S, S), (64, 201, 255, 0))
    hm = shape_mask(lambda dd: dd.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], fill=255))
    halo.putalpha(hm.filter(ImageFilter.GaussianBlur(4 * u)).point(lambda v: int(v * 0.6)))
    img = Image.alpha_composite(img, halo)
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=(19, 21, 37, 255))
    img = Image.alpha_composite(img, ring)
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline=(255, 255, 255, 200),
                               width=int(0.9 * u))
    img = Image.alpha_composite(img, ov)
    d = ImageDraw.Draw(img)
    # ponto de balanço deslocado (o "puck" da roda) + centro
    px_, py_ = cx + 3.5 * u, cy - 3 * u
    d.ellipse([px_ - 2.4 * u, py_ - 2.4 * u, px_ + 2.4 * u, py_ + 2.4 * u], fill=(255, 255, 255, 255))
    d.ellipse([cx - 1.4 * u, cy - 1.4 * u, cx + 1.4 * u, cy + 1.4 * u], fill=(164, 95, 255, 255))
    d.line([cx, cy, px_, py_], fill=(255, 255, 255, 255), width=int(0.8 * u))
    return img.resize((size, size), Image.LANCZOS)


def logo(height: int = 44) -> Image.Image:
    """Símbolo + 'TITAN' branco + 'MATCH' no gradiente Titan (como o cabeçalho do Titan Editor)."""
    k = 4
    hh = height * k
    sym = symbol(512).resize((hh, hh), Image.LANCZOS)
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", int(hh * 0.46))
    t1, t2 = "TITAN ", "MATCH"
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w1 = tmp.textlength(t1, font=font)
    w2 = tmp.textlength(t2, font=font)
    gap = int(hh * 0.28)
    W = int(hh + gap + w1 + w2 + hh * 0.1)
    img = Image.new("RGBA", (W, hh), (0, 0, 0, 0))
    img.paste(sym, (0, 0), sym)
    d = ImageDraw.Draw(img)
    ty = int(hh * 0.22)
    d.text((hh + gap, ty), t1, font=font, fill=(241, 245, 249, 255))
    m = Image.new("L", (W, hh), 0)
    ImageDraw.Draw(m).text((hh + gap + w1, ty), t2, font=font, fill=255)
    grad = Image.new("RGB", (W, hh))
    gx0 = int(hh + gap + w1)
    for x in range(W):
        c = _lerp(TITAN, (x - gx0) / max(w2, 1))
        ImageDraw.Draw(grad).line([x, 0, x, hh], fill=c)
    img.paste(grad, (0, 0), m)
    return img.resize((W // k, height), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    big = symbol(512)
    big.save(OUT / "titan_match_icon.png")
    big.save(OUT / "titan_match.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    symbol(64).save(OUT / "titan_match_symbol_64.png")
    logo(40).save(OUT / "titan_match_logo.png")
    print("ok:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
