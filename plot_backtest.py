#!/usr/bin/env python3
"""讀取 breakout_backtest.py 輸出的 trades.csv,畫出權益曲線、回落與年度損益。
用法: python3 plot_backtest.py trades.csv out.png [標題]"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"

plt.rcParams.update({
    "font.family": ["WenQuanYi Zen Hei", "DejaVu Sans"], "axes.unicode_minus": False,
    "figure.facecolor": SURF, "axes.facecolor": SURF, "text.color": INK,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
})


def style(ax):
    for k in ("top", "right", "left"):
        ax.spines[k].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))


def main():
    src, out = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else "價格突破策略回測"
    t = pd.read_csv(src, parse_dates=["date"]).sort_values(["date", "entry_time"])
    eq = t.set_index("date")["pnl"].cumsum()   # 每筆交易後的權益,與回測程式的最大回落一致
    dd = eq - eq.cummax()
    yr = t.groupby(t["date"].dt.year)["pnl"].sum()

    wins, loss = t[t.pnl > 0].pnl.sum(), -t[t.pnl <= 0].pnl.sum()
    stats = (f"{t.date.min():%Y-%m-%d} ~ {t.date.max():%Y-%m-%d}  |  交易 {len(t)} 筆  |  "
             f"淨損益 {t.pnl.sum():,.0f} 元  |  勝率 {(t.pnl > 0).mean():.1%}  |  "
             f"獲利因子 {wins / loss:.2f}  |  最大回落 {-dd.min():,.0f} 元  |  成本 {t.cost.sum():,.0f} 元")

    fig, axs = plt.subplots(3, 1, figsize=(11, 10.5), gridspec_kw={"height_ratios": [3, 1.5, 1.8]})
    fig.suptitle(title, x=0.06, ha="left", fontsize=16, fontweight="bold", y=0.985)
    fig.text(0.06, 0.945, stats, fontsize=9.5, color=INK2, ha="left")

    ax = axs[0]
    ax.plot(eq.index, eq.values, color=BLUE, lw=1.6)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_title("累積淨損益(元,已扣成本)", loc="left", fontsize=11, color=INK)
    ax.annotate(f"{eq.iloc[-1]:,.0f}", (eq.index[-1], eq.iloc[-1]), xytext=(6, 0),
                textcoords="offset points", color=INK, fontsize=10, va="center")
    style(ax)

    ax = axs[1]
    ax.fill_between(dd.index, dd.values, 0, color=ORANGE, alpha=0.35, lw=0)
    ax.plot(dd.index, dd.values, color=ORANGE, lw=1)
    ax.set_title("自高點回落(元)", loc="left", fontsize=11, color=INK)
    i = dd.idxmin()
    ax.annotate(f"最大回落 {dd.min():,.0f}", (i, dd.min()), xytext=(-8, 8),
                textcoords="offset points", color=INK, fontsize=9.5, ha="right")
    style(ax)
    for a in axs[:2]:
        a.sharex = None
    axs[1].set_xlim(axs[0].get_xlim())

    ax = axs[2]
    cols = [BLUE if v >= 0 else ORANGE for v in yr.values]
    ax.bar(yr.index.astype(str), yr.values, color=cols, width=0.62)
    ax.axhline(0, color=INK2, lw=0.8)
    for x, v in zip(yr.index.astype(str), yr.values):
        ax.annotate(f"{v:,.0f}", (x, v), xytext=(0, 4 if v >= 0 else -4), textcoords="offset points",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5, color=INK)
    ax.set_title("年度淨損益(元;藍=獲利,橘=虧損)", loc="left", fontsize=11, color=INK)
    ax.margins(y=0.18)
    style(ax)

    fig.tight_layout(rect=(0.02, 0, 0.98, 0.93))
    fig.savefig(out, dpi=140)
    print("saved", out)


if __name__ == "__main__":
    main()
