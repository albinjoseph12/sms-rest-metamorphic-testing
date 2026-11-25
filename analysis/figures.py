#!/usr/bin/env python3
"""Figures for the manuscript. Every value is read from paper/numbers.json."""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
N = json.load(open(f"{SMS_HOME}/paper/numbers.json"))
OUT = f"{SMS_HOME}/paper/figs"
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5})


# --------------------------------------------------------------- Fig 1: architecture
def fig_architecture():
    fig, ax = plt.subplots(figsize=(7.1, 3.6))
    ax.set_xlim(0, 104); ax.set_ylim(0, 52); ax.axis("off")

    def box(x, y, w, h, title, body, fc="#eef3fa", ec="#33506e"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.5,rounding_size=1.1",
                                    fc=fc, ec=ec, lw=1.0))
        ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontweight="bold", fontsize=7.6)
        ax.text(x + w / 2, y + h - 6.0, body, ha="center", va="top", fontsize=6.6, linespacing=1.4)

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=8,
                                     lw=1.0, color="#33506e"))

    W, G = 23.0, 3.0
    xs = [1 + i * (W + G) for i in range(4)]
    box(xs[0], 30, W, 19, "1  Target acquisition",
        "published frame\nmechanical criteria\nseeded permutation\nharness synthesis",
        fc="#f3f0e7", ec="#6e5c33")
    box(xs[1], 30, W, 19, "2  Contract analysis",
        "resource model\n$ref and allOf resolution\ninvariant witnesses:\ntemporal, quantity,\nreference, ownership")
    box(xs[2], 30, W, 19, "3  Instantiation",
        "relation catalogue\n(P, T, R_resp, R_state)\napplicability check\nfollow-up synthesis")
    box(xs[3], 30, W, 19, "4  Execution",
        "source, then follow-up\nsame credential,\none controlled\ndifference")

    box(xs[0], 5, W, 19, "Target under test",
        "application process\nand its own\nrelational database", fc="#f7eaea", ec="#6e3333")
    box(xs[1], 5, W, 19, "5  State oracle",
        "snapshot before\nsnapshot after\nrow-level delta")
    box(xs[2], 5, W, 19, "6  Verdict",
        "R_resp on the status\nR_state on the delta\nviolation kind")
    box(xs[3], 5, W, 19, "7  Triage",
        "failing tests\nto signatures\nto root causes")

    for i in range(3):
        arrow(xs[i] + W, 39.5, xs[i + 1], 39.5)
    arrow(xs[3] + W / 2, 30, xs[3] + W / 2, 24)
    for i in (3, 2):
        arrow(xs[i], 14.5, xs[i - 1] + W, 14.5)
    arrow(xs[0] + W / 2, 24, xs[0] + W / 2, 30)

    ax.text(xs[3] + W / 2 + 1.2, 27, "responses", ha="left", va="center", fontsize=6.4, color="#33506e")
    ax.text(xs[2] - G / 2, 26.0, "delta", ha="center", fontsize=6.4, color="#33506e")
    ax.text(xs[1] - G / 2, 26.0, "requests", ha="center", fontsize=6.4, color="#33506e")
    ax.text(xs[0] + W / 2 + 1.2, 27, "OpenAPI\ndocument", ha="left", va="center", fontsize=6.4,
            color="#33506e", linespacing=1.2)
    ax.text(52, 0.6, "the harness never reads or edits target source code; only deployment "
                     "configuration is synthesised",
            ha="center", fontsize=6.6, style="italic", color="#444")
    fig.savefig(f"{OUT}/fig1_architecture.png", dpi=400, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------- Fig 2: three-level counts
def fig_counts():
    main = N["main"]; base = N["baseline"]
    ts = ["realworld", "cloudrun", "booking", "any-auto-register", "dispatch"]
    labels = [t if t != "any-auto-register" else "any-auto-reg." for t in ts]
    ft = [main[t]["per_seed"][0]["failing_tests"] for t in ts]
    sg = [main[t]["per_seed"][0]["signatures"] for t in ts]
    rc = [main[t]["per_seed"][0]["causes"] for t in ts]
    bft = [base[t]["failing_tests"] for t in ts]
    brc = [base[t]["causes"] for t in ts]
    bbe = [base[t]["behavioural_causes"] for t in ts]

    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.7))
    x = range(len(ts)); w = 0.26
    ax = axes[0]
    ax.bar([i - w for i in x], ft, w, label="failing tests", color="#33506e")
    ax.bar(list(x), sg, w, label="signatures", color="#6f8fb5")
    ax.bar([i + w for i in x], rc, w, label="root causes", color="#c2a15a")
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=7)
    ax.set_title("SMS", fontsize=9); ax.legend(fontsize=6.6, frameon=False)
    ax.set_ylabel("count (symlog)")

    ax = axes[1]
    ax.bar([i - w for i in x], bft, w, label="failing tests", color="#33506e")
    ax.bar(list(x), brc, w, label="root causes", color="#6f8fb5")
    ax.bar([i + w for i in x], bbe, w, label="behavioural causes", color="#c2a15a")
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=7)
    ax.set_title("Schemathesis baseline", fontsize=9); ax.legend(fontsize=6.6, frameon=False)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig2_counts.png", dpi=400, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------- Fig 3: ablation
def fig_ablation():
    main = N["main"]; abl = N["ablations"]
    ts = [t for t in ["realworld", "cloudrun", "booking", "any-auto-register", "dispatch"]
          if t in abl.get("no-contract", {})]
    labels = [t if t != "any-auto-register" else "any-auto-reg." for t in ts]
    full = [main[t]["failing_mean_ci"][0] for t in ts]
    nost = [abl["no-state"][t]["failing_mean_ci"][0] for t in ts]
    noct = [abl["no-contract"][t]["failing_mean_ci"][0] for t in ts]
    spur = [abl["no-contract"][t]["not_in_full_mean_ci"][0] for t in ts]
    fig, ax = plt.subplots(figsize=(4.6, 2.7))
    x = range(len(ts)); w = 0.26
    ax.bar([i - w for i in x], full, w, label="full", color="#33506e")
    ax.bar(list(x), nost, w, label="no persistence oracle", color="#6f8fb5")
    ax.bar([i + w for i in x], noct, w, label="no contract witnesses", color="#c2a15a")
    ax.bar([i + w for i in x], spur, w, label="  of which absent from full",
           color="#8c3b3b", alpha=0.85)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=7)
    ax.set_ylabel("failing tests (mean of 3 seeds)")
    ax.legend(fontsize=6.4, frameon=False)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig3_ablation.png", dpi=400, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_architecture(); fig_counts(); fig_ablation()
    print(os.listdir(OUT))
