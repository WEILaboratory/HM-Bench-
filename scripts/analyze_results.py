#!/usr/bin/env python3
"""将单轮和多轮评分结果生成为图表、汇总数据和论文式表格。"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from textwrap import fill
from typing import Any, Iterable


# Matplotlib 在服务器上常无法写入默认缓存目录，因此将缓存放到项目外的临时目录。
os.environ.setdefault("MPLCONFIGDIR", "/tmp/hm-bench-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/hm-bench-cache")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将完整评分结果生成为 PNG 图表和 LaTeX 论文表。")
    parser.add_argument(
        "--single-dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "青少年内容安全单轮场景.json",
    )
    parser.add_argument(
        "--multi-dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "青少年内容安全多轮场景.json",
    )
    parser.add_argument("--single-scores", type=Path, default=PROJECT_ROOT / "results" / "scores" / "single")
    parser.add_argument("--multi-scores", type=Path, default=PROJECT_ROOT / "results" / "scores" / "multi")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "results" / "analysis")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument(
        "--tables-only",
        action="store_true",
        help="只刷新 LaTeX 和 PNG 论文表，不重新生成原有 8 张分析图。",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def configure_plotting() -> str:
    """选择可用的中文字体并设定统一图表样式。"""
    available = {font.name for font in font_manager.fontManager.ttflist}
    candidates = (
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Microsoft YaHei",
        "PingFang SC",
        "Songti SC",
        "Arial Unicode MS",
        "SimHei",
        "DejaVu Sans",
    )
    selected = next((name for name in candidates if name in available), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [selected, "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#9AA0A6",
        "axes.labelcolor": "#30343B",
        "text.color": "#20242A",
        "xtick.color": "#454A52",
        "ytick.color": "#454A52",
        "grid.color": "#DDE1E6",
        "grid.alpha": 0.7,
        "axes.titleweight": "bold",
    })
    return selected


def model_series(model: str) -> str:
    if model.startswith("qwen2.5"):
        return "Qwen2.5"
    if model.startswith("internlm2.5"):
        return "InternLM2.5"
    if model.startswith("glm-z1"):
        return "GLM-Z1"
    if model.startswith("glm4"):
        return "GLM-4"
    if model.startswith("deepseek"):
        return "DeepSeek"
    return model


def load_reports(path: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for file in sorted(path.glob("*_scores.json")):
        report = read_json(file)
        source = report.get("source_metadata", {})
        model = str(source.get("model_preset") or source.get("api_model") or file.stem)
        if model in reports:
            raise ValueError(f"重复模型结果：{model}")
        reports[model] = report
    if not reports:
        raise ValueError(f"没有找到评分结果：{path}")
    return reports


def validate_reports(
    single_reports: dict[str, dict[str, Any]],
    multi_reports: dict[str, dict[str, Any]],
    single_count: int,
    multi_count: int,
) -> None:
    if set(single_reports) != set(multi_reports):
        raise ValueError("单轮和多轮的模型集合不一致。")
    for model, report in single_reports.items():
        items = report.get("items", [])
        if len(items) != single_count or any("score" not in item or "error" in item for item in items):
            raise ValueError(f"单轮结果不完整：{model}")
    for model, report in multi_reports.items():
        items = report.get("items", [])
        if len(items) != multi_count or any("score" not in item or "error" in item for item in items):
            raise ValueError(f"多轮结果不完整：{model}")


def mean(values: Iterable[int | float]) -> float:
    return float(statistics.fmean(values))


def summary_stats(scores: list[int]) -> dict[str, Any]:
    """计算论文表使用的描述统计量；均值区间采用正态近似。"""
    count = len(scores)
    if not count:
        raise ValueError("不能汇总空分数序列。")
    score_mean = mean(scores)
    score_sd = float(statistics.stdev(scores)) if count > 1 else 0.0
    margin = 1.96 * score_sd / math.sqrt(count) if count > 1 else 0.0
    distribution = {str(score): scores.count(score) for score in range(-2, 3)}
    return {
        "n": count,
        "mean": score_mean,
        "sd": score_sd,
        "ci95_low": max(-2.0, score_mean - margin),
        "ci95_high": min(2.0, score_mean + margin),
        "unsafe_count": sum(score < 0 for score in scores),
        "unsafe_rate": sum(score < 0 for score in scores) / count,
        "score_distribution": distribution,
    }


def aggregate(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for row in rows:
        grouped[tuple(str(row[field]) for field in fields)].append(int(row["score"]))
    return [
        {**dict(zip(fields, key)), **summary_stats(scores)}
        for key, scores in grouped.items()
    ]


def add_rank(rows: list[dict[str, Any]], metric: str, output_field: str) -> None:
    """按降序添加稳定排名；相同数值使用相同名次。"""
    ordered = sorted(rows, key=lambda row: (-float(row[metric]), str(row.get("model", ""))))
    previous: float | None = None
    rank = 0
    for position, row in enumerate(ordered, 1):
        value = float(row[metric])
        if previous is None or not math.isclose(value, previous, abs_tol=1e-12):
            rank = position
            previous = value
        row[output_field] = rank


def latex_escape(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def latex_tabular(headers: list[str], rows: list[list[str]], alignment: str | None = None) -> str:
    columns = alignment or ("l" + "r" * (len(headers) - 1))
    body = [
        f"\\begin{{tabular}}{{{columns}}}",
        "\\toprule",
        " & ".join(latex_escape(value) for value in headers) + r" \\",
        "\\midrule",
    ]
    body.extend(" & ".join(latex_escape(value) for value in row) + r" \\" for row in rows)
    body.extend(["\\bottomrule", "\\end{tabular}"])
    return "\n".join(body)


def prepare_output_dir(path: Path) -> None:
    """只确保输出目录存在，不删除任何已有分析产物。"""
    path.mkdir(parents=True, exist_ok=True)


def save_figure(fig: Any, path: Path, dpi: int) -> None:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def add_score_axis(ax: Any) -> None:
    ax.axvline(0, color="#60656F", linewidth=1)
    ax.set_xlim(-2.05, 2.05)
    ax.set_xlabel("平均得分（-2 至 +2）")
    ax.grid(axis="x")


def plot_model_overview(overview: list[dict[str, Any]], output: Path, dpi: int) -> None:
    rows = sorted(overview, key=lambda row: row["balanced_mean"])
    y = list(range(len(rows)))
    fig, ax = plt.subplots(figsize=(13, 8))
    height = 0.36
    ax.barh([value - height / 2 for value in y], [row["single_mean"] for row in rows], height,
            label="单轮均分", color="#3274A1")
    ax.barh([value + height / 2 for value in y], [row["multi_mean"] for row in rows], height,
            label="多轮样本均分", color="#E1812C")
    ax.set_yticks(y, [row["model"] for row in rows])
    ax.set_title("各模型单轮与多轮评分对比", pad=14)
    add_score_axis(ax)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    save_figure(fig, output / "01_model_overview.png", dpi)


def plot_scale_comparison(overview: list[dict[str, Any]], output: Path, dpi: int) -> None:
    series_names = [name for name in ("Qwen2.5", "InternLM2.5", "GLM-4", "GLM-Z1")
                    if sum(row["series"] == name for row in overview) >= 2]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharey=True)
    for ax, series in zip(axes.flat, series_names):
        rows = sorted((row for row in overview if row["series"] == series), key=lambda row: row["params_b"])
        sizes = [row["params_b"] for row in rows]
        ax.plot(sizes, [row["single_mean"] for row in rows], "o-", linewidth=2.2,
                color="#3274A1", label="单轮")
        ax.plot(sizes, [row["multi_mean"] for row in rows], "s--", linewidth=2.2,
                color="#E1812C", label="多轮")
        ax.axhline(0, color="#60656F", linewidth=1)
        ax.set_title(series)
        ax.set_xticks(sizes, [f"{size:g}B" for size in sizes])
        ax.set_ylim(-2.05, 2.05)
        ax.grid(axis="y")
        ax.set_xlabel("参数规模")
    axes[0, 0].set_ylabel("平均得分")
    axes[1, 0].set_ylabel("平均得分")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.98))
    fig.suptitle("同系列不同参数规模的评分对比", y=1.03, fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save_figure(fig, output / "02_scale_comparison.png", dpi)


def plot_same_size(overview: list[dict[str, Any]], output: Path, dpi: int) -> None:
    grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in overview:
        grouped[row["params_b"]].append(row)
    groups = [(size, rows) for size, rows in sorted(grouped.items()) if len(rows) >= 2]
    fig, axes = plt.subplots(1, len(groups), figsize=(15, 5.8), sharey=True)
    if len(groups) == 1:
        axes = [axes]
    for ax, (size, rows) in zip(axes, groups):
        rows = sorted(rows, key=lambda row: row["balanced_mean"], reverse=True)
        x = list(range(len(rows)))
        width = 0.36
        ax.bar([value - width / 2 for value in x], [row["single_mean"] for row in rows], width,
               color="#3274A1", label="单轮")
        ax.bar([value + width / 2 for value in x], [row["multi_mean"] for row in rows], width,
               color="#E1812C", label="多轮")
        ax.axhline(0, color="#60656F", linewidth=1)
        ax.set_xticks(x, [fill(row["model"], 16) for row in rows], rotation=18, ha="right")
        ax.set_title(f"{size:g}B")
        ax.set_ylim(-2.05, 2.05)
        ax.grid(axis="y")
    axes[0].set_ylabel("平均得分（-2 至 +2）")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.98))
    fig.suptitle("相同参数规模下的不同模型对比", y=1.04, fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save_figure(fig, output / "03_same_size_comparison.png", dpi)


def plot_l1_dimensions(l1_rows: list[dict[str, Any]], output: Path, dpi: int) -> None:
    rows = sorted(l1_rows, key=lambda row: row["mean"])
    labels = [fill(row["一级分类"], 18) for row in rows]
    y = list(range(len(rows)))
    fig, (score_ax, risk_ax) = plt.subplots(1, 2, figsize=(16, 8), gridspec_kw={"width_ratios": [1.2, 1]})
    colors = ["#C03D3E" if row["mean"] < 0 else "#3274A1" for row in rows]
    score_ax.barh(y, [row["mean"] for row in rows], color=colors)
    score_ax.set_yticks(y, labels)
    score_ax.set_title("平均得分")
    add_score_axis(score_ax)
    risk_ax.barh(y, [row["unsafe_rate"] * 100 for row in rows], color="#D98C33")
    risk_ax.set_yticks(y, [""] * len(rows))
    risk_ax.set_xlim(0, 100)
    risk_ax.set_xlabel("负分率（%）")
    risk_ax.set_title("负分率")
    risk_ax.grid(axis="x")
    fig.suptitle("单轮一级风险维度表现", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    save_figure(fig, output / "04_single_l1_dimensions.png", dpi)


def plot_l2_dimensions(l2_rows: list[dict[str, Any]], output: Path, dpi: int) -> None:
    rows = sorted(l2_rows, key=lambda row: row["mean"], reverse=True)
    labels = [fill(row["二级分类"], 24) for row in rows]
    categories = sorted({row["一级分类"] for row in rows})
    category_colors = {category: plt.get_cmap("tab10")(index) for index, category in enumerate(categories)}
    colors = [category_colors[row["一级分类"]] for row in rows]
    fig, ax = plt.subplots(figsize=(15, 20))
    y = list(range(len(rows)))
    ax.barh(y, [row["mean"] for row in rows], color=colors, height=0.72)
    ax.set_yticks(y, labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_title("单轮二级风险维度平均得分", pad=16)
    add_score_axis(ax)
    legend = [Patch(facecolor=category_colors[category], label=fill(category, 16)) for category in categories]
    ax.legend(handles=legend, title="一级风险维度", frameon=False, fontsize=8,
              loc="lower right", bbox_to_anchor=(1.0, 0.0))
    fig.tight_layout()
    save_figure(fig, output / "05_single_l2_dimensions.png", dpi)


def plot_model_l1_heatmap(
    model_l1_rows: list[dict[str, Any]],
    model_order: list[str],
    l1_order: list[str],
    output: Path,
    dpi: int,
) -> None:
    lookup = {(row["model"], row["一级分类"]): row["mean"] for row in model_l1_rows}
    matrix = [[lookup[(model, category)] for category in l1_order] for model in model_order]
    cmap = LinearSegmentedColormap.from_list("safety", ["#B2182B", "#F7F7F7", "#2166AC"])
    fig, ax = plt.subplots(figsize=(17, 9))
    image = ax.imshow(matrix, cmap=cmap, vmin=-2, vmax=2, aspect="auto")
    ax.set_xticks(range(len(l1_order)), [fill(label, 10) for label in l1_order], rotation=32, ha="right")
    ax.set_yticks(range(len(model_order)), model_order)
    for row_index, row in enumerate(matrix):
        for col_index, value in enumerate(row):
            ax.text(col_index, row_index, f"{value:.2f}", ha="center", va="center",
                    fontsize=8, color="white" if abs(value) > 1.05 else "#20242A")
    ax.set_title("模型在单轮一级风险维度上的平均得分", pad=16)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    colorbar.set_label("平均得分（-2 至 +2）")
    fig.tight_layout()
    save_figure(fig, output / "06_model_l1_heatmap.png", dpi)


def plot_multi_mechanisms(mechanisms: list[dict[str, Any]], output: Path, dpi: int) -> None:
    rows = sorted(mechanisms, key=lambda row: row["mean"])
    labels = [f'{row["机制编号"]}  {fill(row["机制名称"], 18)}' for row in rows]
    y = list(range(len(rows)))
    fig, (score_ax, risk_ax) = plt.subplots(1, 2, figsize=(16, 8), gridspec_kw={"width_ratios": [1.2, 1]})
    score_ax.barh(y, [row["mean"] for row in rows], color="#8C6BB1")
    score_ax.set_yticks(y, labels)
    score_ax.set_title("样本平均得分")
    add_score_axis(score_ax)
    risk_ax.barh(y, [row["unsafe_rate"] * 100 for row in rows], color="#D98C33")
    risk_ax.set_yticks(y, [""] * len(rows))
    risk_ax.set_xlim(0, 100)
    risk_ax.set_xlabel("负分率（%）")
    risk_ax.set_title("负分率")
    risk_ax.grid(axis="x")
    fig.suptitle("多轮对话风险机制表现", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    save_figure(fig, output / "07_multi_mechanisms.png", dpi)


def plot_model_multi_heatmap(
    model_mechanism_rows: list[dict[str, Any]],
    model_order: list[str],
    mechanism_order: list[tuple[str, str]],
    output: Path,
    dpi: int,
) -> None:
    lookup = {
        (row["model"], row["机制编号"]): row["mean"]
        for row in model_mechanism_rows
    }
    matrix = [
        [lookup[(model, mechanism_id)] for mechanism_id, _ in mechanism_order]
        for model in model_order
    ]
    cmap = LinearSegmentedColormap.from_list("safety", ["#B2182B", "#F7F7F7", "#2166AC"])
    fig, ax = plt.subplots(figsize=(18, 9))
    image = ax.imshow(matrix, cmap=cmap, vmin=-2, vmax=2, aspect="auto")
    labels = [f"{mechanism_id}\n{fill(name, 9)}" for mechanism_id, name in mechanism_order]
    ax.set_xticks(range(len(mechanism_order)), labels, rotation=28, ha="right")
    ax.set_yticks(range(len(model_order)), model_order)
    for row_index, row in enumerate(matrix):
        for col_index, value in enumerate(row):
            ax.text(col_index, row_index, f"{value:.2f}", ha="center", va="center",
                    fontsize=8, color="white" if abs(value) > 1.05 else "#20242A")
    ax.set_title("模型在多轮风险机制上的整体得分", pad=16)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    colorbar.set_label("平均得分（-2 至 +2）")
    fig.tight_layout()
    save_figure(fig, output / "08_model_multi_mechanism_heatmap.png", dpi)


def compact_model_rows(overview: list[dict[str, Any]]) -> list[dict[str, Any]]:
    add_rank(overview, "balanced_mean", "balanced_rank")
    return sorted(overview, key=lambda row: int(row["balanced_rank"]))


def paper_table_rows(overview: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            str(row["balanced_rank"]),
            str(row["model"]),
            f"{float(row['params_b']):g}",
            f"{float(row['single_mean']):.3f}",
            f"{float(row['multi_mean']):.3f}",
            f"{float(row['multi_minus_single']):+.3f}",
            f"{float(row['balanced_mean']):.3f}",
        ]
        for row in compact_model_rows(overview)
    ]


def write_paper_table_latex(path: Path, overview: list[dict[str, Any]]) -> None:
    headers = ["排名", "模型", "参数量(B)", "单轮均分", "多轮均分", "差值", "综合均分"]
    tabular = latex_tabular(headers, paper_table_rows(overview), alignment="rlrrrrr")
    content = "\n".join([
        "% Requires booktabs; compile Chinese with XeLaTeX or LuaLaTeX.",
        "\\begin{table*}[htbp]",
        "\\centering",
        "\\caption{各模型单轮与多轮风险测评结果}",
        "\\label{tab:model-risk-results}",
        tabular,
        "\\parbox{0.96\\textwidth}{\\footnotesize 注：得分范围为 $[-2,2]$；差值为多轮均分减单轮均分；综合均分为单轮和多轮均分的等权平均。}",
        "\\end{table*}",
        "",
    ])
    path.write_text(content, encoding="utf-8")


def write_paper_table_image(path: Path, overview: list[dict[str, Any]], dpi: int) -> None:
    headers = ["排名", "模型", "参数量(B)", "单轮均分", "多轮均分", "差值", "综合均分"]
    rows = paper_table_rows(overview)
    fig, ax = plt.subplots(figsize=(14, 8.2))
    ax.axis("off")
    ax.set_title("各模型单轮与多轮风险测评结果", fontsize=18, pad=22, loc="left")
    ax.text(
        0,
        0.965,
        "得分范围：-2 至 +2；差值 = 多轮均分 - 单轮均分；综合均分为两者等权平均",
        transform=ax.transAxes,
        fontsize=10.5,
        color="#5B6470",
        va="top",
    )
    table = ax.table(
        cellText=rows,
        colLabels=headers,
        cellLoc="center",
        colLoc="center",
        colWidths=[0.07, 0.30, 0.11, 0.12, 0.12, 0.12, 0.13],
        bbox=[0, 0.04, 1, 0.86],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10.5)
    table.scale(1, 1.35)
    for (row_index, column_index), cell in table.get_celld().items():
        cell.set_edgecolor("#D7DCE2")
        cell.set_linewidth(0.7)
        if row_index == 0:
            cell.set_facecolor("#315A7D")
            cell.set_text_props(color="white", weight="bold")
        else:
            cell.set_facecolor("#F5F7F9" if row_index % 2 == 0 else "white")
            if column_index == 1:
                cell.set_text_props(ha="left")
    save_figure(fig, path, dpi)


def export_paper_table_outputs(
    output: Path,
    overview: list[dict[str, Any]],
    dpi: int,
) -> list[Path]:
    paths = [output / "paper_table.tex", output / "paper_table.png"]
    write_paper_table_latex(paths[0], overview)
    write_paper_table_image(paths[1], overview, dpi)
    return paths


def main() -> int:
    args = parse_args()
    font = configure_plotting()
    single_data = read_json(args.single_dataset)
    multi_data = read_json(args.multi_dataset)
    single_samples = {sample["样本ID"]: sample for sample in single_data["样本"]}
    multi_samples = {sample["样本编号"]: sample for sample in multi_data["样本"]}
    single_reports = load_reports(args.single_scores)
    multi_reports = load_reports(args.multi_scores)
    validate_reports(single_reports, multi_reports, len(single_samples), len(multi_samples))

    single_rows: list[dict[str, Any]] = []
    multi_rows: list[dict[str, Any]] = []
    overview: list[dict[str, Any]] = []
    for model, report in single_reports.items():
        source = report.get("source_metadata", {})
        params_b = float(source.get("model_params_b") or 0)
        single_scores = [int(item["score"]) for item in report["items"]]
        multi_scores = [int(item["score"]) for item in multi_reports[model]["items"]]
        for item in report["items"]:
            sample = single_samples[item["sample_id"]]
            single_rows.append({
                "model": model,
                "sample_id": item["sample_id"],
                "score": int(item["score"]),
                "一级分类": sample["一级分类"],
                "二级分类": sample["二级分类"],
            })
        for item in multi_reports[model]["items"]:
            sample = multi_samples[item["sample_id"]]
            multi_rows.append({
                "model": model,
                "sample_id": item["sample_id"],
                "score": int(item["score"]),
                "机制编号": sample["机制编号"],
                "机制名称": sample["机制名称"],
            })
        single_stats = summary_stats(single_scores)
        multi_stats = summary_stats(multi_scores)
        single_mean = float(single_stats["mean"])
        multi_mean = float(multi_stats["mean"])
        overview.append({
            "model": model,
            "series": model_series(model),
            "params_b": params_b,
            **{f"single_{key}": value for key, value in single_stats.items()},
            **{f"multi_{key}": value for key, value in multi_stats.items()},
            "multi_minus_single": multi_mean - single_mean,
            "balanced_mean": (single_mean + multi_mean) / 2,
        })

    overview.sort(key=lambda row: row["balanced_mean"], reverse=True)
    l1_rows = aggregate(single_rows, ("一级分类",))
    l2_rows = aggregate(single_rows, ("一级分类", "二级分类"))
    model_l1_rows = aggregate(single_rows, ("model", "一级分类"))
    mechanisms = aggregate(multi_rows, ("机制编号", "机制名称"))
    model_mechanisms = aggregate(multi_rows, ("model", "机制编号", "机制名称"))
    model_order = [row["model"] for row in overview]
    l1_order = [row["一级分类"] for row in sorted(l1_rows, key=lambda row: row["mean"])]
    mechanism_order = [
        (row["机制编号"], row["机制名称"])
        for row in sorted(mechanisms, key=lambda row: row["机制编号"])
    ]

    prepare_output_dir(args.output_dir)
    table_paths = export_paper_table_outputs(args.output_dir, overview, args.dpi)
    if not args.tables_only:
        plot_model_overview(overview, args.output_dir, args.dpi)
        plot_scale_comparison(overview, args.output_dir, args.dpi)
        plot_same_size(overview, args.output_dir, args.dpi)
        plot_l1_dimensions(l1_rows, args.output_dir, args.dpi)
        plot_l2_dimensions(l2_rows, args.output_dir, args.dpi)
        plot_model_l1_heatmap(model_l1_rows, model_order, l1_order, args.output_dir, args.dpi)
        plot_multi_mechanisms(mechanisms, args.output_dir, args.dpi)
        plot_model_multi_heatmap(model_mechanisms, model_order, mechanism_order, args.output_dir, args.dpi)

    print(f"分析完成：{args.output_dir}")
    print(f"论文表产物：{len(table_paths)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
