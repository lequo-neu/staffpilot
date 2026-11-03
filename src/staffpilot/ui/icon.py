"""The StaffPilot mark, drawn once for the sidebar and the browser tab.

The mark is a staffing curve: a tall January team that settles to what demand needs,
in white on a deep teal tile. The sidebar shows it as inline SVG; the browser tab gets
a PNG drawn from the same points, because some browsers still ignore SVG tab icons.
"""

from __future__ import annotations

from pathlib import Path

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
