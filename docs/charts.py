from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

IMAGES = Path(__file__).parent / "images"
TARGET_RPS = [1000, 2000, 3000, 4000, 5000]
ACTUAL_RPS = [967, 1695, 2181, 2208, 2236]
CHECK_MS = [17, 33, 68, 115, 161]
REDIS_MS = [16, 15, 25, 27, 27]
CEILING_RPS = 2200

INK = "#0F172A"
MUTED = "#64748B"
GRID = "#E2E8F0"
BLUE = "#2563EB"
RED = "#DC2626"
SKY = "#BFDBFE"
SLATE = "#CBD5E1"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 12,
        "axes.edgecolor": SLATE,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def styled_axes(title: str, ylabel: str) -> tuple[plt.Figure, plt.Axes]:
    figure, axes = plt.subplots(figsize=(10, 5.2), dpi=200)
    axes.set_title(title, loc="left", fontsize=16, fontweight="bold", color=INK, pad=16)
    axes.set_xlabel("Целевая нагрузка, RPS")
    axes.set_ylabel(ylabel)
    axes.grid(axis="y", color=GRID, linewidth=1)
    axes.set_axisbelow(True)
    return figure, axes


def throughput_chart() -> None:
    figure, axes = styled_axes("Пропускная способность", "RPS")
    positions = range(len(TARGET_RPS))
    labels = [f"{value:,}".replace(",", " ") for value in TARGET_RPS]
    axes.bar(positions, TARGET_RPS, width=0.6, color=SLATE, label="цель")
    axes.plot(
        positions, ACTUAL_RPS, color=BLUE, linewidth=3, marker="o", markersize=9, label="факт"
    )
    for position, value in zip(positions, ACTUAL_RPS, strict=True):
        axes.annotate(
            f"{value:,}".replace(",", " "),
            (position, value),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=12,
            fontweight="bold",
            color=BLUE,
        )
    axes.axhline(CEILING_RPS, color=RED, linestyle="--", linewidth=1.5)
    axes.text(
        -0.35,
        CEILING_RPS + 140,
        f"потолок ≈ {CEILING_RPS:,} RPS".replace(",", " "),
        ha="left",
        color=RED,
        fontsize=12,
        fontweight="bold",
    )
    axes.set_xticks(list(positions), labels)
    axes.set_ylim(0, 5600)
    axes.legend(frameon=False, loc="upper left")
    figure.tight_layout()
    figure.savefig(IMAGES / "throughput.png", facecolor="white")


def latency_chart() -> None:
    figure, axes = styled_axes("Из чего складывается время проверки", "мс, в среднем")
    positions = range(len(TARGET_RPS))
    labels = [f"{value:,}".replace(",", " ") for value in TARGET_RPS]
    queue_ms = [check - redis for check, redis in zip(CHECK_MS, REDIS_MS, strict=True)]
    axes.bar(positions, REDIS_MS, width=0.6, color=RED, label="вызов Redis")
    axes.bar(
        positions,
        queue_ms,
        width=0.6,
        bottom=REDIS_MS,
        color=SKY,
        label="очередь и обработка в приложении",
    )
    for position, total in zip(positions, CHECK_MS, strict=True):
        axes.annotate(
            f"{total} мс",
            (position, total),
            textcoords="offset points",
            xytext=(0, 6),
            ha="center",
            fontsize=12,
            fontweight="bold",
            color=INK,
        )
    axes.set_xticks(list(positions), labels)
    axes.set_ylim(0, max(CHECK_MS) * 1.2)
    axes.legend(frameon=False, loc="upper left")
    figure.tight_layout()
    figure.savefig(IMAGES / "latency.png", facecolor="white")


if __name__ == "__main__":
    throughput_chart()
    latency_chart()
