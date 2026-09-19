#!/usr/bin/env python3
"""Generate the ICOC-Students 2026 email artwork.

Writes SVG sources to ``static/brand/icoc/svg/`` and renders each to a PNG in
``static/brand/icoc/`` at twice its display size.

Why both: SVG is the right format to *author* in — the molecular network is
generated geometry, and a colour or a node position is one edit away. SVG is the
wrong format to *send*: Gmail, Outlook and every mobile client strip inline
``<svg>``, and none of them will load an ``.svg`` from an ``<img src>`` either.
So the vectors live in the repo and the raster goes in the mail.

Run it from the repository root:

    python3 scripts/build_icoc_art.py
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys

SVG_DIR = "static/brand/icoc/svg"
PNG_DIR = "static/brand/icoc"

# Sampled from the conference banner the organisers supplied, so the email and
# the poster are recognisably the same event.
DEEP = "#0f5a49"
DEEPER = "#0a4438"
MID = "#12654f"
LEAF = "#559347"
SPROUT = "#7fbf6a"
TEAL = "#1d6f7e"
TEAL_DEEP = "#155563"
TEAL_MID = "#22808f"
TEAL_LIGHT = "#7ed3dd"
PAPER = "#eef2f0"


# ---------------------------------------------------------------- geometry


def hexagon(cx: float, cy: float, r: float) -> str:
    """Points for a pointy-top hexagon — a benzene ring, near enough."""
    return " ".join(
        f"{cx + r * math.cos(math.radians(a)):.1f},"
        f"{cy + r * math.sin(math.radians(a)):.1f}"
        for a in range(30, 390, 60)
    )


def star(cx: float, cy: float, r: float, points: int = 4) -> str:
    out = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * 0.38
        angle = math.radians(i * 180 / points - 90)
        out.append(f"{cx + radius * math.cos(angle):.1f},"
                   f"{cy + radius * math.sin(angle):.1f}")
    return " ".join(out)


# A hand-placed molecular network. Laid out by eye rather than at random: a
# random graph reads as noise, and the point is for it to look like chemistry.
NODES = {
    "a": (70, 196), "b": (152, 92), "c": (196, 232), "d": (268, 150),
    "e": (300, 268), "f": (392, 208), "g": (404, 84), "h": (498, 146),
    "i": (556, 252), "j": (620, 108), "k": (676, 208), "l": (742, 74),
    "m": (790, 186), "n": (858, 268), "o": (892, 128), "p": (968, 214),
    "q": (1030, 96), "r": (1088, 236), "s": (1150, 140), "t": (1224, 214),
}
BONDS = [
    ("a", "b"), ("a", "c"), ("b", "d"), ("c", "e"), ("d", "e"), ("d", "g"),
    ("e", "f"), ("f", "h"), ("g", "h"), ("f", "i"), ("h", "j"), ("i", "k"),
    ("j", "k"), ("j", "l"), ("k", "m"), ("l", "m"), ("m", "n"), ("m", "o"),
    ("n", "p"), ("o", "p"), ("o", "q"), ("p", "r"), ("q", "s"), ("r", "s"),
    ("r", "t"), ("s", "t"),
]
BIG = {"d", "h", "k", "m", "p", "s"}


def masthead(deep: str = DEEP, deeper: str = DEEPER, mid: str = MID,
             light: str = SPROUT, leaf: str = LEAF) -> str:
    """The header band: a molecular network dissolving into flat colour.

    The bottom edge is exactly ``deep`` so the image can butt straight up
    against the solid-colour cell below it and read as one continuous header — a
    seam there is the sort of thing that looks broken rather than deliberate,
    which is why the dinner variant exists at all.
    """
    bonds = "\n".join(
        f'    <line x1="{NODES[a][0]}" y1="{NODES[a][1]}" '
        f'x2="{NODES[b][0]}" y2="{NODES[b][1]}"/>'
        for a, b in BONDS
    )
    nodes = "\n".join(
        f'    <circle cx="{x}" cy="{y}" r="{9 if k in BIG else 5.5}" '
        f'fill="{light if k in BIG else leaf}" opacity="{0.9 if k in BIG else 0.7}"/>'
        for k, (x, y) in NODES.items()
    )
    rings = "\n".join(
        f'    <polygon points="{hexagon(cx, cy, r)}"/>'
        for cx, cy, r in ((236, 70, 34), (610, 244, 26), (1126, 62, 30))
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="320"
     viewBox="0 0 1280 320" role="presentation">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0"   stop-color="{deeper}"/>
      <stop offset="0.5" stop-color="{mid}"/>
      <stop offset="1"   stop-color="{deep}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.1" r="0.8">
      <stop offset="0" stop-color="{light}" stop-opacity="0.22"/>
      <stop offset="1" stop-color="{light}" stop-opacity="0"/>
    </radialGradient>
    <!-- The network is brightest at the top and gone by the bottom edge, so it
         hands over to the flat green underneath without a visible join. -->
    <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0"    stop-color="#ffffff" stop-opacity="1"/>
      <stop offset="0.55" stop-color="#ffffff" stop-opacity="0.75"/>
      <stop offset="1"    stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <mask id="dissolve">
      <rect width="1280" height="320" fill="url(#fade)"/>
    </mask>
  </defs>

  <rect width="1280" height="320" fill="url(#sky)"/>
  <rect width="1280" height="320" fill="url(#glow)"/>

  <g mask="url(#dissolve)">
    <!-- catalytic cycle: the arrow that makes it chemistry rather than dots -->
    <g fill="none" stroke="{light}" stroke-opacity="0.30" stroke-width="3">
      <circle cx="640" cy="150" r="118" stroke-dasharray="26 18"/>
      <circle cx="640" cy="150" r="150" stroke-opacity="0.13" stroke-dasharray="4 20"/>
    </g>
    <polygon points="758,150 742,138 742,162" fill="{light}" opacity="0.36"/>
    <polygon points="522,150 538,162 538,138" fill="{light}" opacity="0.36"/>

    <g stroke="{light}" stroke-opacity="0.42" stroke-width="2" stroke-linecap="round">
{bonds}
    </g>
    <g fill="none" stroke="{light}" stroke-opacity="0.34" stroke-width="2.5">
{rings}
    </g>
{nodes}
  </g>
</svg>
"""


def divider(colour: str, dot: str, width: int = 1200) -> str:
    """A hairline with a small ring at its centre — a section break."""
    mid = width / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="48"
     viewBox="0 0 {width} 48" role="presentation">
  <g stroke="{colour}" stroke-width="2" stroke-linecap="round" fill="none">
    <line x1="30" y1="24" x2="{mid - 70:.0f}" y2="24" opacity="0.5"/>
    <line x1="{mid + 70:.0f}" y1="24" x2="{width - 30}" y2="24" opacity="0.5"/>
    <polygon points="{hexagon(mid, 24, 17)}" stroke-width="2.4"/>
    <line x1="{mid - 52:.0f}" y1="24" x2="{mid - 17:.0f}" y2="24"/>
    <line x1="{mid + 17:.0f}" y1="24" x2="{mid + 52:.0f}" y2="24"/>
  </g>
  <circle cx="{mid - 52:.0f}" cy="24" r="5.5" fill="{dot}"/>
  <circle cx="{mid + 52:.0f}" cy="24" r="5.5" fill="{dot}"/>
</svg>
"""


def meal_badge(night: bool) -> str:
    """A cloche, with the sun over lunch and a moon over dinner.

    White line art, because it sits on the card's coloured header bar. Strokes
    are deliberately heavy: this is displayed at 26px next to the sitting name,
    and a delicate icon at that size is just a grey smudge. The two have to read
    apart on a phone, which is the only size that matters.
    """
    if night:
        # A crescent is one disc with a second swept out of it: the outer arc
        # goes one way round, the inner arc comes back the other.
        sky = (
            '  <path d="M44 7.5a10.5 10.5 0 1 0 0 21 13 13 0 0 1 0-21z" '
            'fill="#ffffff"/>\n'
            f'  <polygon points="{star(23, 13, 5.5)}" fill="#ffffff" opacity="0.85"/>\n'
            f'  <polygon points="{star(63, 25, 4)}" fill="#ffffff" opacity="0.65"/>\n'
        )
    else:
        rays = "".join(
            f'  <line x1="{44 + 11 * math.cos(math.radians(a)):.1f}"'
            f' y1="{18 + 11 * math.sin(math.radians(a)):.1f}"'
            f' x2="{44 + 14.5 * math.cos(math.radians(a)):.1f}"'
            f' y2="{18 + 14.5 * math.sin(math.radians(a)):.1f}"'
            f' stroke="#ffffff" stroke-width="4" stroke-linecap="round"/>\n'
            for a in range(0, 360, 45)
        )
        sky = f'  <circle cx="44" cy="18" r="7.5" fill="#ffffff"/>\n{rays}'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="88" height="88"
     viewBox="0 0 88 88" role="presentation">
{sky}  <circle cx="44" cy="36" r="3.6" fill="#ffffff"/>
  <g stroke="#ffffff" stroke-width="4.6" fill="none" stroke-linecap="round">
    <path d="M16 70a28 28 0 0 1 56 0"/>
    <line x1="9" y1="70" x2="79" y2="70"/>
  </g>
</svg>
"""


# --------------------------------------------------------------- rendering

ASSETS = {
    # name: (svg source, rendered PNG width)
    "icoc-masthead": (masthead, 1280),
    "icoc-masthead-teal": (
        lambda: masthead(TEAL, TEAL_DEEP, TEAL_MID, TEAL_LIGHT, "#4aa8b4"), 1280),
    "icoc-divider": (lambda: divider("#bcd6cb", LEAF), 1200),
    "icoc-divider-light": (lambda: divider("#4f8f7c", SPROUT), 1200),
    "icoc-badge-lunch": (lambda: meal_badge(False), 88),
    "icoc-badge-dinner": (lambda: meal_badge(True), 88),
}


def main() -> int:
    if not shutil.which("rsvg-convert"):
        print("rsvg-convert is not installed; cannot rasterise.", file=sys.stderr)
        return 1
    os.makedirs(SVG_DIR, exist_ok=True)
    os.makedirs(PNG_DIR, exist_ok=True)

    for name, (build, width) in ASSETS.items():
        svg_path = os.path.join(SVG_DIR, f"{name}.svg")
        png_path = os.path.join(PNG_DIR, f"{name}.png")
        with open(svg_path, "w", encoding="utf-8") as handle:
            handle.write(build())
        subprocess.run(
            ["rsvg-convert", "-w", str(width), "-o", png_path, svg_path],
            check=True,
        )
        # Quantise: these are flat-colour illustrations, so a 128-colour palette
        # is lossless to the eye and a fraction of the bytes on the wire.
        if shutil.which("magick"):
            subprocess.run(
                ["magick", png_path, "-colors", "128", "-strip",
                 "-define", "png:compression-level=9", png_path],
                check=True,
            )
        print(f"  {name:22} {os.path.getsize(png_path) / 1024:6.1f} KB  {width}px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
