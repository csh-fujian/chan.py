# -*- coding: utf-8 -*-
"""
绘制「三买A / 三买B 区别」说明示意图。

图是**示意图**，不是真实行情：坐标只为表达结构关系，不代表真实价位。
真实样例（已由 Debug 脚本在本地 DuckDB 日线上打桩核实）写在图注里。

结构依据（与内核判定同源）：
- T3A: ChanAnalyse/BuySellPoint/BSPointList.py:treat_bsp3_after
       中枢取 seg.next 里的「第一个多笔中枢」→ 离开笔突破 → 回抽笔不回中枢
- T3B: ChanAnalyse/BuySellPoint/BSPointList.py:treat_bsp3_before
       中枢取锚点所在 seg 里的「最后一个多笔中枢」→ 离开笔突破（锚点即离开笔终点）
       → 紧接的回抽笔不回中枢
两处方向都由 check_breakout(中枢离开笔) 决定，不由线段方向决定。

输出：Document/images/bsp3a_bsp3b_explain.png
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

C_UP = "#F6465D"       # 红涨
C_DOWN = "#2EBD85"     # 绿跌
C_BI = "#4A5568"       # 笔
C_ZS_FILL = "#FFD400"  # 中枢
C_ZS_EDGE = "#C7A500"
C_BSP = "#FF3B30"      # 三买标记
C_ANCHOR = "#7A5AF8"   # 第一类点（锚点）
C_SEG = "#94A3B8"      # 线段主脊


def draw_bi(ax, pts, label=None, label_pos=None, bold=False):
    """按点序列画一条折线（笔），逐段着色。"""
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        ax.plot([x0, x1], [y0, y1],
                color=C_BI, lw=2.2 if bold else 1.8,
                solid_capstyle="round", zorder=5)
    if label:
        lx, ly = label_pos or pts[len(pts) // 2]
        ax.annotate(label, xy=(lx, ly), xytext=(0, 14), textcoords="offset points",
                    fontsize=9, color="#334155", ha="center", zorder=9)


def draw_zs(ax, x, y, w, h, tag=True):
    """画中枢矩形 + 上下沿虚线。"""
    ax.add_patch(Rectangle((x, y), w, h, facecolor=C_ZS_FILL, alpha=0.28,
                           edgecolor=C_ZS_EDGE, lw=1.4, zorder=2))
    ax.axhline(y + h, color=C_ZS_EDGE, ls="--", lw=0.9, alpha=0.9, zorder=3)
    ax.axhline(y, color=C_ZS_EDGE, ls="--", lw=0.9, alpha=0.9, zorder=3)
    if tag:
        ax.text(x + w / 2, y + h / 2, "中枢", fontsize=11, fontweight="bold",
                color="#7A6400", ha="center", va="center", zorder=8)


def mark(ax, x, y, text, color, marker="^", offset=(8, -22), size=170):
    ax.scatter([x], [y], marker=marker, s=size, color=color,
               edgecolor="white", linewidth=1.4, zorder=12)
    ax.annotate(text, xy=(x, y), xytext=offset, textcoords="offset points",
                fontsize=10.5, fontweight="bold", color=color, zorder=13,
                arrowprops=dict(arrowstyle="->", color=color, lw=1.2))


def panel_a(ax):
    """三买A：中枢在「锚点之后的下一条线段」里。"""
    ax.set_title("三买A（3a）· 中枢在锚点的下一条线段里", fontsize=13,
                 fontweight="bold", pad=12)

    # 下跌线段，终点 = 第一类买点（锚点）
    draw_bi(ax, [(0.2, 9.4), (2.2, 7.0), (3.0, 7.9), (4.6, 4.2)])
    ax.plot([0.2, 4.6], [9.4, 4.2], color=C_SEG, lw=5, alpha=0.30, zorder=1)
    ax.text(1.4, 9.9, "线段①（下跌）", fontsize=9.5, color="#64748B")
    mark(ax, 4.6, 4.2, "一买（锚点）", C_ANCHOR, marker="o", offset=(-18, -30), size=110)

    # 下一条线段（向上）内部形成中枢
    pts = [(4.6, 4.2), (6.0, 7.2), (7.1, 5.7), (8.3, 7.5), (9.1, 6.0)]
    draw_bi(ax, pts)
    ax.plot([4.6, 9.1], [4.2, 6.0], color=C_SEG, lw=5, alpha=0.30, zorder=1)
    ax.text(5.6, 3.5, "线段②（向上）", fontsize=9.5, color="#64748B")
    draw_zs(ax, 6.0, 6.0, 3.1, 1.2)   # zs = [6.0, 7.2]

    # 离开笔：向上突破中枢上沿
    ax.plot([9.1, 10.8], [6.0, 9.2], color=C_BI, lw=2.6, zorder=6)
    ax.annotate("离开笔\n突破中枢上沿", xy=(9.95, 7.6), xytext=(-6, 26),
                textcoords="offset points", fontsize=9, color="#0F766E",
                ha="center", zorder=10,
                arrowprops=dict(arrowstyle="->", color="#0F766E", lw=1.0))

    # 回抽笔：低点仍在中枢上沿之上
    ax.plot([10.8, 12.2], [9.2, 7.55], color=C_BI, lw=2.6, zorder=6)
    ax.annotate("回抽笔 · 低点 7.55 > 上沿 7.20\n没有回到中枢", xy=(12.2, 7.55),
                xytext=(10.4, 9.5), textcoords="data", fontsize=9,
                color="#B91C1C", ha="center", va="bottom", zorder=10,
                arrowprops=dict(arrowstyle="->", color="#B91C1C", lw=1.0))
    mark(ax, 12.2, 7.55, "三买A", C_BSP, offset=(12, -20))

    ax.axhline(7.2, color=C_ZS_EDGE, ls="--", lw=0.9, alpha=0.9, zorder=3)
    ax.text(-0.1, 7.28, "中枢上沿", fontsize=8.5, color="#8A6D00", va="bottom")
    ax.text(-0.1, 5.92, "中枢下沿", fontsize=8.5, color="#8A6D00", va="top")

    ax.set_xlim(0, 13.6)
    ax.set_ylim(3.2, 10.6)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.grid(alpha=0.10, ls=":")
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)

    ax.text(0.02, 0.03,
            "要点：一买之后新走出一条线段，中枢在这条新线段内部形成；\n"
            "      离开笔冲破中枢上沿、回抽笔低点仍在上沿之上 → 三买A。\n"
            "      中枢位置 = 锚点（一买）的下一条线段。",
            transform=ax.transAxes, fontsize=9.5, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.55", facecolor="#FEFCE8",
                      edgecolor="#E5D98A", alpha=0.96), zorder=14)


def panel_b(ax):
    """三买B：中枢与锚点在「同一条线段」里，锚点就是中枢的离开笔终点。"""
    ax.set_title("三买B（3b）· 中枢在锚点所在的那条线段里", fontsize=13,
                 fontweight="bold", pad=12)

    # 向上线段，中枢就在这条线段内部
    pts = [(0.4, 4.4), (1.9, 6.6), (3.0, 5.5), (4.2, 6.9), (5.2, 5.7)]
    draw_bi(ax, pts)
    ax.plot([0.4, 5.2], [4.4, 5.7], color=C_SEG, lw=5, alpha=0.30, zorder=1)
    ax.text(0.8, 3.9, "线段①（向上）", fontsize=9.5, color="#64748B")
    draw_zs(ax, 1.9, 5.7, 3.3, 0.9)   # zs = [5.7, 6.6]

    # 离开笔：线段末端的向上笔冲破中枢上沿 —— 它的终点同时就是「锚点」转折处
    ax.plot([5.2, 6.8], [5.7, 8.6], color=C_BI, lw=2.6, zorder=6)
    ax.annotate("离开笔\n终点 8.60 > 上沿 6.60", xy=(6.5, 8.15),
                xytext=(3.9, 9.55), textcoords="data", fontsize=9,
                color="#0F766E", ha="center", va="bottom", zorder=10,
                arrowprops=dict(arrowstyle="->", color="#0F766E", lw=1.0))
    mark(ax, 6.8, 8.6, "第一类点（锚点）", C_ANCHOR, marker="o",
         offset=(28, 8), size=110)

    # 回抽笔：紧接锚点之后，低点仍在中枢上沿之上
    ax.plot([6.8, 9.4], [8.6, 6.9], color=C_BI, lw=2.6, zorder=6)
    ax.plot([9.4, 10.2], [6.9, 7.7], color=C_BI, lw=1.8, zorder=5, alpha=0.5)
    ax.annotate("回抽笔 · 低点 6.90 > 上沿 6.60\n没有回到中枢", xy=(9.4, 6.9),
                xytext=(10.3, 8.15), textcoords="data", fontsize=9,
                color="#B91C1C", ha="left", va="bottom", zorder=10,
                arrowprops=dict(arrowstyle="->", color="#B91C1C", lw=1.0))
    mark(ax, 9.4, 6.9, "三买B", C_BSP, offset=(-4, -30))

    ax.axhline(6.6, color=C_ZS_EDGE, ls="--", lw=0.9, alpha=0.9, zorder=3)
    ax.text(-0.1, 6.68, "中枢上沿", fontsize=8.5, color="#8A6D00", va="bottom")
    ax.text(-0.1, 5.62, "中枢下沿", fontsize=8.5, color="#8A6D00", va="top")

    ax.set_xlim(0, 13.6)
    ax.set_ylim(3.2, 10.6)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.grid(alpha=0.10, ls=":")
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)

    ax.text(0.02, 0.03,
            "要点：中枢与锚点在同一条线段内，锚点就是这条线段里中枢的离开笔终点；\n"
            "      锚点之后的第一笔回抽不回到中枢上沿 → 三买B。\n"
            "      中枢位置 = 锚点（第一类点）所在的这条线段。",
            transform=ax.transAxes, fontsize=9.5, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.55", facecolor="#EFF6FF",
                      edgecolor="#9DB8E0", alpha=0.96), zorder=14)


def main():
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 6.6), dpi=140)
    panel_a(axes[0])
    panel_b(axes[1])
    fig.suptitle("第三类买点：三买A 与 三买B 的区别（结构示意）",
                 fontsize=15, fontweight="bold", y=0.975)
    fig.text(0.5, 0.012,
             "示意图形状只表达结构关系，不代表真实价位区间。"
             "灰带 = 线段；深灰折线 = 笔；黄框 = 中枢；紫色圆 = 第一类点（锚点）；红三角 = 三买",
             ha="center", fontsize=9.5, color="#555555")
    fig.tight_layout(rect=[0, 0.035, 1, 0.945])

    out = "Document/images/bsp3a_bsp3b_explain.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print("saved:", out)


if __name__ == "__main__":
    main()