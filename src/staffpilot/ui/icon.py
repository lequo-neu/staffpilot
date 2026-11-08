"""The StaffPilot mark, drawn once for the sidebar and the browser tab.

The mark is a staffing curve: a tall January team that settles to what demand needs,
in white on a deep teal tile. The sidebar shows it as inline SVG; the browser tab gets
a PNG drawn from the same points, because some browsers still ignore SVG tab icons.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch


TILE = "#0f6e75"
LINE = "#ffffff"
# Points of the curve in an 18 by 18 box, y measured downwards as in SVG.
CURVE = ((2, 3), (5, 12), (9, 12), (12, 11), (16, 9))
TILE_SIZE, TILE_RADIUS, INSET = 28, 8, 5  # the curve box sits 5 units inside the 28 unit tile


def curve_svg(size: int = 18, stroke: float = 2.0) -> str:
    points = " ".join(f"{x},{y}" for x, y in CURVE)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 18 18" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{LINE}" stroke-width="{stroke}" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def write_png(path: Path, pixels: int = 64) -> Path:
    """Draw the tile and curve as a square PNG for the browser tab."""
    fig = Figure(figsize=(1, 1), dpi=pixels)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, TILE_SIZE)
    ax.set_ylim(TILE_SIZE, 0)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            TILE_SIZE,
            TILE_SIZE,
            boxstyle=f"round,pad=0,rounding_size={TILE_RADIUS}",
            color=TILE,
            lw=0,
        )
    )
    xs = [x + INSET for x, _ in CURVE]
    ys = [y + INSET for _, y in CURVE]
    # Two SVG units of stroke on a 28 unit tile, expressed in points for this figure size.
    ax.plot(xs, ys, color=LINE, linewidth=2 / TILE_SIZE * 72, solid_capstyle="round", solid_joinstyle="round")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=pixels, transparent=True)
    return path


# Line icons for the sidebar, drawn on a 24 unit grid with a 2 unit stroke. They are used as
# CSS masks, so each one takes the colour of its menu item.
NAV_ICONS = {
    "This year": '<rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>',
    "Data": '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13'
    'M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "Plan": '<path d="M3 21h18M6 17V11M11 17V5M16 17v-8M21 17v-4"/>',
    "Scenario": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/>'
    '<circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "Memo": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/>'
    '<path d="M14 3v5h5M8.5 13h7M8.5 17h5"/>',
    "Monthly update": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/><path d="M12 8v4l3 2"/>',
    "Decision log": '<path d="M10 6h11M10 12h11M10 18h11"/><path d="M3 6l1.5 1.5L7 4.5M3 12l1.5 1.5L7 10.5'
    'M3 18l1.5 1.5L7 16.5"/>',
    "Assistant": '<path d="M20.5 11.5a8 8 0 0 1-11.8 7L3.5 20l1.4-4.6A8 8 0 1 1 20.5 11.5z"/>'
    '<path d="M8.5 11.5h.01M12.5 11.5h.01M16.5 11.5h.01"/>',
    "Evaluation": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.5 9"/>',
    "Country inputs": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "Compare policies": '<path d="M12 3v18M7 21h10M5 7h14"/><path d="M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>',
}


def nav_css(groups: list[tuple[str, list[str]]]) -> str:
    """CSS that puts each page's icon before its sidebar item; each group's radio has its index in a class."""
    rules = []
    for index, (_, names) in enumerate(groups):
        for position, name in enumerate(names, start=1):
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" '
                f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{NAV_ICONS.get(name, "")}</svg>'
            )
            data = quote(svg)
            rules.append(
                f'.sp-nav-{index} label:nth-of-type({position}) {{ --sp-icon: url("data:image/svg+xml,{data}"); }}'
            )
    return "\n".join(rules)
