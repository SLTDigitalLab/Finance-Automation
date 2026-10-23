"""
Monthly trend charts for the report (PNG, for embedding in Word).

One single-series column chart per measure, one slot per month, so a month
whose trial balance is not loaded shows as a gap rather than being skipped.
"""
import io
from typing import List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from services.financial_analysis.pl_engine import MonthFigures  # noqa: E402

SERIES = "#2a78d6"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"

MIN_MONTHS = 2   # fewer loaded months than this: no chart


def _label(m: MonthFigures) -> str:
    return f"{m.period.label[:3]}’{m.period.year % 100:02d}"


def trend_chart(months: List[MonthFigures], field: str, title: str) -> Optional[io.BytesIO]:
    values = [getattr(m, field) for m in months]
    if sum(v is not None for v in values) < MIN_MONTHS:
        return None

    fig, ax = plt.subplots(figsize=(7.2, 2.7), dpi=200)
    x = range(len(months))
    heights = [v if v is not None else 0 for v in values]
    bars = ax.bar(x, heights, width=0.55, color=SERIES, zorder=2)

    top = max(v for v in values if v is not None)
    for bar, value in zip(bars, values):
        cx = bar.get_x() + bar.get_width() / 2
        if value is None:
            ax.text(cx, top * 0.02, "n/a", ha="center", va="bottom", fontsize=6.5, color=MUTED)
            bar.set_visible(False)
        else:
            ax.text(cx, value + top * 0.015, f"{value:,.0f}", ha="center", va="bottom",
                    fontsize=6.5, color=INK_SECONDARY)

    ax.set_xticks(list(x))
    ax.set_xticklabels([_label(m) for m in months], fontsize=7, color=MUTED)
    ax.tick_params(axis="y", labelsize=7, colors=MUTED, length=0)
    ax.tick_params(axis="x", length=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylim(0, top * 1.15)
    ax.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.set_title(title, loc="left", fontsize=8.5, color=INK, fontweight="bold", pad=8)

    fig.tight_layout()
    out = io.BytesIO()
    fig.savefig(out, format="png", facecolor="white")
    plt.close(fig)
    out.seek(0)
    return out
