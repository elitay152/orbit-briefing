"""Architecture diagram for orbit-briefing, styled to match the satellite map.

The content is static, so it's drawn at site-build time. Keep each box in step with the code.
"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

SPACE = "#0e1420"
BOX = "#1b2331"
BOX_EDGE = "#3a4558"
STORE = "#16263d"
STORE_EDGE = "#3987e5"
INK = "#f0efec"
INK_2 = "#c3c2b7"
MUTED = "#8d93a0"
ARROW = "#8d93a0"
BAND = "#141b27"


def box(ax, x, y, w, h, title, lines, face=BOX, edge=BOX_EDGE) -> None:
    """Rounded box with a bold title and a few lines of detail."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12",
                                facecolor=face, edgecolor=edge, linewidth=1.4, zorder=2))
    ax.text(x + 0.18, y + h - 0.2, title, fontsize=12.5, fontweight="bold", color=INK,
            va="top", zorder=3)
    ax.text(x + 0.18, y + h - 0.6, "\n".join(lines), fontsize=10, color=INK_2,
            va="top", linespacing=1.45, zorder=3)


def arrow(ax, start, end) -> None:
    """Arrow from start to end, in data coordinates."""
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14,
                                 color=ARROW, linewidth=1.4, zorder=1,
                                 shrinkA=2, shrinkB=2))


def draw_diagram(out_path: Path) -> Path:
    """Draw the pipeline diagram and save it."""
    fig = plt.figure(figsize=(12, 7))
    fig.patch.set_facecolor(SPACE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9.33)
    ax.axis("off")

    ax.text(0.45, 8.85, "How my satellite data pipeline works", fontsize=20, fontweight="bold",
            color=INK, va="top")
    ax.text(0.45, 8.22, "orbit-briefing: tracking Amazon Leo and Starlink from public orbit data",
            fontsize=12, color=INK_2, va="top")

    # GitHub Actions band around the steps it runs
    ax.add_patch(FancyBboxPatch((2.6, 2.6), 7.45, 3.85, boxstyle="round,pad=0,rounding_size=0.15",
                                facecolor=BAND, edgecolor=BOX_EDGE, linewidth=1, linestyle=(0, (4, 3)),
                                zorder=0))
    ax.text(2.8, 6.27, "GitHub Actions  ·  daily schedule, tests on every push",
            fontsize=10, color=MUTED, va="top")

    row_y, row_h = 3.15, 2.4
    mid = row_y + row_h / 2

    # source and ingest path
    box(ax, 0.45, row_y, 1.75, row_h, "CelesTrak", ["Public orbit", "data API"])
    box(ax, 2.85, row_y, 2.1, row_h, "Extract", ["Raw JSON", "snapshots,", "cached, with", "retries"])
    box(ax, 5.35, row_y, 2.1, row_h, "Validate", ["Required fields,", "mean motion > 0,", "valid epoch;", "logs rejections"])
    box(ax, 7.85, row_y, 1.95, row_h, "Parquet lake", ["Partitioned by", "constellation", "and snapshot;", "idempotent"],
        face=STORE, edge=STORE_EDGE)
    for x0, x1 in ((2.2, 2.85), (4.95, 5.35), (7.45, 7.85)):
        arrow(ax, (x0, mid), (x1, mid))

    # query layer
    box(ax, 10.5, row_y, 1.6, row_h, "DuckDB", ["SQL over", "the full", "history"], face=STORE, edge=STORE_EDGE)
    arrow(ax, (9.8, mid), (10.5, mid))

    # outputs
    outputs = [
        (6.3, "Spoken briefing", ["Satellites passing over", "a location, read aloud"]),
        (4.8, "Prediction error", ["SGP4 error as data ages,", "altitude changes"]),
        (3.3, "Control charts (SPC)", ["Altitude changes and", "data freshness"]),
        (1.8, "AI analyst", ["Local LLM writes read-only", "SQL, with guardrails"]),
        (0.3, "Dashboard", ["GitHub Pages, rebuilt", "after each snapshot"]),
    ]
    box_h = 1.3
    for y, title, lines in outputs:
        box(ax, 12.75, y, 2.95, box_h, title, lines)
        arrow(ax, (12.1, mid), (12.75, y + box_h / 2))

    # footer: stack
    ax.text(0.45, 0.85, "Python  ·  DuckDB  ·  Parquet  ·  GitHub Actions  ·  skyfield / SGP4  ·  "
            "pytest  ·  Ollama  ·  Streamlit", fontsize=11, color=INK_2, va="center")
    ax.text(0.45, 0.4, "github.com/elitay152/orbit-briefing", fontsize=10, color=MUTED, va="center")

    fig.savefig(out_path, dpi=150, facecolor=SPACE)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print(draw_diagram(Path("demo") / "pipeline_diagram.png"))
