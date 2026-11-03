"""Light and dark chart themes. The same hues, stepped for each background.

Light charts go in the README; dark charts match the dashboard, map and diagram.
"""

LIGHT = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "line": "#2a78d6",       # single-series lines
    "bar": "#52514e",        # neutral bars
    "band_alpha": 0.12,      # shaded ranges
    "signal": "#d03b3b",     # control-chart signals (status color, the same in both themes)
    "series": {"kuiper": "#2a78d6", "starlink": "#eb6834"},
}

DARK = {
    "surface": "#0e1420",
    "ink": "#f0efec",
    "ink_2": "#c3c2b7",
    "muted": "#8d93a0",
    "grid": "#222b3a",
    "axis": "#3a4558",
    "line": "#3987e5",
    "bar": "#8d93a0",
    "band_alpha": 0.2,
    "signal": "#d03b3b",
    "series": {"kuiper": "#3987e5", "starlink": "#d95926"},
}

def style_axes(ax, theme: dict) -> None:
    """Shared look: light grid, recessive axes, theme background."""
    ax.set_facecolor(theme["surface"])
    ax.grid(True, axis="y", color=theme["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["axis"])
    ax.tick_params(colors=theme["muted"], labelsize=10)
