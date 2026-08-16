#!/usr/bin/env python3
"""将单轮和多轮评分结果生成为图表、汇总数据和论文式表格。"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from textwrap import fill
from typing import Any, Iterable


# Matplotlib 在服务器上常无法写入默认缓存目录，因此将缓存放到项目外的临时目录。
os.environ.setdefault("MPLCONFIGDIR", "/tmp/qh-bench-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/qh-bench-cache")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch, Rectangle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_SCORES = tuple(range(-2, 3))


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
    parser.add_argument(
        "--single-human-labels",
        type=Path,
        default=PROJECT_ROOT / "results" / "scores" / "human_agreement" / "单轮人工一致性标注_100.json",
    )
    parser.add_argument(
        "--multi-human-labels",
        type=Path,
        default=PROJECT_ROOT / "results" / "scores" / "human_agreement" / "多轮人工一致性标注_50.json",
    )
    parser.add_argument(
        "--human-judge-reference",
        type=Path,
        default=PROJECT_ROOT / "results" / "scores" / "human_agreement" / "自动裁判评分对照_150.json",
    )
    parser.add_argument("--agreement-bootstrap-reps", type=int, default=20_000)
    parser.add_argument("--agreement-bootstrap-seed", type=int, default=20_260_721)
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


def load_human_judge_rows(
    single_path: Path,
    multi_path: Path,
    reference_path: Path,
) -> list[dict[str, Any]]:
    """读取人工复核与自动裁判对照；仅纳入非空的真实人工评分。"""
    reference = read_json(reference_path)
    rows: list[dict[str, Any]] = []
    for task, path in (("单轮", single_path), ("多轮", multi_path)):
        document = read_json(path)
        items = document.get("样本", [])
        ref_items = reference.get(task, [])
        ref_ids = [str(item.get("标注序号", "")) for item in ref_items]
        if len(ref_ids) != len(set(ref_ids)):
            raise ValueError(f"{task}自动裁判对照存在重复标注序号。")
        ref_map = {str(item["标注序号"]): item for item in ref_items}
        item_ids = [str(item.get("标注序号", "")) for item in items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError(f"{task}人工标注文件存在重复标注序号。")
        if set(item_ids) != set(ref_ids):
            raise ValueError(f"{task}人工标注与自动裁判对照的样本集不一致。")
        for item in items:
            human_score = item.get("人类评分")
            if human_score is None:
                continue
            if isinstance(human_score, bool) or not isinstance(human_score, int) or human_score not in VALID_SCORES:
                raise ValueError(
                    f"{task} {item.get('标注序号')} 人类评分必须是 -2 至 2 的整数。"
                )
            annotation_id = str(item["标注序号"])
            ref_item = ref_map[annotation_id]
            judge_score = ref_item.get("自动裁判评分")
            if isinstance(judge_score, bool) or not isinstance(judge_score, int) or judge_score not in VALID_SCORES:
                raise ValueError(f"{task} {annotation_id} 自动裁判评分无效。")
            locator = item.get("定位信息", {})
            if str(locator.get("模型", "")) != str(ref_item.get("模型", "")):
                raise ValueError(f"{task} {annotation_id} 模型定位与对照文件不一致。")
            if str(locator.get("样本编号", "")) != str(ref_item.get("样本编号", "")):
                raise ValueError(f"{task} {annotation_id} 样本定位与对照文件不一致。")
            rows.append({
                "task": task,
                "annotation_id": annotation_id,
                "model": str(locator.get("模型", "")),
                "sample_id": str(locator.get("样本编号", "")),
                "human_score": human_score,
                "judge_score": judge_score,
                "difference": judge_score - human_score,
            })
    if not rows:
        raise ValueError("没有找到非空人工评分。")
    return rows


def weighted_cohen_kappa(human: list[int], judge: list[int], weighting: str) -> float | None:
    """计算五档有序评分的 Cohen's kappa；weighting 为 unweighted/linear/quadratic。"""
    if len(human) != len(judge) or not human:
        raise ValueError("Cohen's kappa 需要非空的成对评分。")
    count = len(human)
    matrix = [[0 for _ in VALID_SCORES] for _ in VALID_SCORES]
    for human_score, judge_score in zip(human, judge):
        matrix[human_score + 2][judge_score + 2] += 1
    human_marginal = [sum(row) / count for row in matrix]
    judge_marginal = [sum(matrix[row][col] for row in range(5)) / count for col in range(5)]

    def disagreement_weight(row: int, col: int) -> float:
        distance = abs(row - col)
        if weighting == "unweighted":
            return float(row != col)
        if weighting == "linear":
            return distance / 4
        if weighting == "quadratic":
            return (distance / 4) ** 2
        raise ValueError(f"不支持的 kappa 权重：{weighting}")

    observed = sum(
        disagreement_weight(row, col) * matrix[row][col] / count
        for row in range(5)
        for col in range(5)
    )
    expected = sum(
        disagreement_weight(row, col) * human_marginal[row] * judge_marginal[col]
        for row in range(5)
        for col in range(5)
    )
    return None if math.isclose(expected, 0.0) else 1 - observed / expected


def average_ranks(values: list[int]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for position in range(start, end):
            ranks[order[position]] = average_rank
        start = end
    return ranks


def pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    denominator = left_scale * right_scale
    return None if math.isclose(denominator, 0.0) else numerator / denominator


def exact_sign_test_two_sided(lower_count: int, higher_count: int) -> float | None:
    disagreement_count = lower_count + higher_count
    if disagreement_count == 0:
        return None
    tail = min(lower_count, higher_count)
    probability = sum(math.comb(disagreement_count, value) for value in range(tail + 1)) / (2 ** disagreement_count)
    return min(1.0, 2 * probability)


def agreement_core(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("一致性统计不能使用空样本。")
    human = [int(row["human_score"]) for row in rows]
    judge = [int(row["judge_score"]) for row in rows]
    differences = [judge_score - human_score for human_score, judge_score in zip(human, judge)]
    exact_count = sum(value == 0 for value in differences)
    within_one_count = sum(abs(value) <= 1 for value in differences)
    lower_count = sum(value < 0 for value in differences)
    higher_count = sum(value > 0 for value in differences)
    confusion = [
        [sum(h == human_score and j == judge_score for h, j in zip(human, judge)) for judge_score in VALID_SCORES]
        for human_score in VALID_SCORES
    ]
    return {
        "n": len(rows),
        "task_counts": dict(Counter(str(row["task"]) for row in rows)),
        "human_mean": mean(human),
        "judge_mean": mean(judge),
        "mean_difference": mean(differences),
        "exact_count": exact_count,
        "exact_rate": exact_count / len(rows),
        "within_one_count": within_one_count,
        "within_one_rate": within_one_count / len(rows),
        "mae": mean(abs(value) for value in differences),
        "kappa_unweighted": weighted_cohen_kappa(human, judge, "unweighted"),
        "kappa_linear": weighted_cohen_kappa(human, judge, "linear"),
        "kappa_quadratic": weighted_cohen_kappa(human, judge, "quadratic"),
        "spearman": pearson_correlation(average_ranks(human), average_ranks(judge)),
        "disagreement_count": lower_count + higher_count,
        "judge_lower_count": lower_count,
        "judge_higher_count": higher_count,
        "sign_test_two_sided_p": exact_sign_test_two_sided(lower_count, higher_count),
        "difference_distribution": {value: differences.count(value) for value in range(-4, 5)},
        "confusion_matrix": confusion,
    }


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("不能对空列表计算分位数。")
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def agreement_with_bootstrap(
    rows: list[dict[str, Any]],
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("bootstrap 重复次数必须为正整数。")
    result = agreement_core(rows)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["task"])].append(row)
    rng = random.Random(seed)
    bootstrap_values: dict[str, list[float]] = {
        "exact_rate": [],
        "within_one_rate": [],
        "mae": [],
        "mean_difference": [],
        "kappa_quadratic": [],
        "spearman": [],
    }
    for _ in range(repetitions):
        resampled: list[dict[str, Any]] = []
        for group in groups.values():
            resampled.extend(rng.choice(group) for _ in range(len(group)))
        replicate = agreement_core(resampled)
        for key in bootstrap_values:
            value = replicate[key]
            if value is not None and math.isfinite(float(value)):
                bootstrap_values[key].append(float(value))
    result["bootstrap_repetitions"] = repetitions
    result["bootstrap_seed"] = seed
    result["ci95"] = {
        key: (percentile(values, 0.025), percentile(values, 0.975))
        for key, values in bootstrap_values.items()
    }
    return result


def compute_agreement_summaries(
    rows: list[dict[str, Any]],
    repetitions: int,
    seed: int,
) -> dict[str, dict[str, Any]]:
    single_rows = [row for row in rows if row["task"] == "单轮"]
    multi_rows = [row for row in rows if row["task"] == "多轮"]
    if not single_rows or not multi_rows:
        raise ValueError("人工一致性实验必须同时包含单轮和多轮非空评分。")
    return {
        "single": agreement_with_bootstrap(single_rows, repetitions, seed + 1),
        "multi": agreement_with_bootstrap(multi_rows, repetitions, seed + 2),
        "pooled": agreement_with_bootstrap(rows, repetitions, seed + 3),
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


def plot_human_judge_agreement(
    summary: dict[str, Any],
    output: Path,
    dpi: int,
) -> None:
    """展示真实人工评分与自动裁判的混淆矩阵及差值分布。"""
    confusion = summary["confusion_matrix"]
    differences = summary["difference_distribution"]
    fig, (matrix_ax, delta_ax) = plt.subplots(
        1,
        2,
        figsize=(15.5, 7.6),
        gridspec_kw={"width_ratios": [1.08, 1]},
    )

    agreement_cmap = LinearSegmentedColormap.from_list(
        "agreement_blue",
        ["#F5F8FA", "#A9C7DB", "#2C6FA3", "#214B63"],
    )
    image = matrix_ax.imshow(confusion, cmap=agreement_cmap, aspect="equal", vmin=0)
    matrix_ax.set_xticks(range(5), [f"{value:+d}" if value else "0" for value in VALID_SCORES])
    matrix_ax.set_yticks(range(5), [f"{value:+d}" if value else "0" for value in VALID_SCORES])
    matrix_ax.set_xlabel("自动裁判评分")
    matrix_ax.set_ylabel("人工评分")
    matrix_ax.set_title("五档评分混淆矩阵", pad=22)
    matrix_ax.text(
        0.5,
        1.015,
        "对角线为完全一致；单元格数字为样本数",
        transform=matrix_ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
        color="#5B6470",
    )
    maximum = max(max(row) for row in confusion)
    for row_index, row in enumerate(confusion):
        for col_index, value in enumerate(row):
            text_color = "white" if maximum and value >= maximum * 0.42 else "#20242A"
            matrix_ax.text(
                col_index,
                row_index,
                str(value),
                ha="center",
                va="center",
                fontsize=12,
                fontweight="bold" if row_index == col_index else "normal",
                color=text_color,
            )
        matrix_ax.add_patch(
            Rectangle(
                (row_index - 0.5, row_index - 0.5),
                1,
                1,
                fill=False,
                edgecolor="#D98C33",
                linewidth=1.5,
            )
        )
    matrix_ax.set_xticks([value - 0.5 for value in range(1, 5)], minor=True)
    matrix_ax.set_yticks([value - 0.5 for value in range(1, 5)], minor=True)
    matrix_ax.grid(which="minor", color="white", linewidth=1.2)
    matrix_ax.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(image, ax=matrix_ax, fraction=0.046, pad=0.04)
    colorbar.set_label("样本数")

    delta_values = list(range(-4, 5))
    counts = [int(differences.get(value, 0)) for value in delta_values]
    colors = ["#D98C33" if value < 0 else "#A7ADB5" if value == 0 else "#2C6FA3" for value in delta_values]
    bars = delta_ax.bar(delta_values, counts, width=0.72, color=colors, edgecolor="#4C5159", linewidth=0.7)
    delta_ax.axvline(0, color="#60656F", linewidth=1.1)
    delta_ax.set_xticks(delta_values, [f"{value:+d}" if value else "0" for value in delta_values])
    delta_ax.set_xlabel("评分差（自动裁判 - 人工）")
    delta_ax.set_ylabel("样本数")
    delta_ax.set_title("成对评分差值分布", pad=22)
    delta_ax.text(
        0.5,
        1.015,
        "负值表示自动裁判评分更低",
        transform=delta_ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
        color="#5B6470",
    )
    delta_ax.grid(axis="y")
    delta_ax.set_axisbelow(True)
    delta_ax.spines[["top", "right"]].set_visible(False)
    delta_ax.set_ylim(0, max(counts) * 1.17 if max(counts) else 1)
    for bar, count in zip(bars, counts):
        if count:
            delta_ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(counts) * 0.025,
                str(count),
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    sign_p = summary["sign_test_two_sided_p"]
    fig.suptitle("人类标注者—自动裁判一致性", fontsize=18, fontweight="bold", y=0.985)
    fig.text(
        0.5,
        0.925,
        (
            f'n={summary["n"]}（单轮{summary["task_counts"].get("单轮", 0)}，'
            f'多轮{summary["task_counts"].get("多轮", 0)}）；仅统计非空的真实人工评分'
        ),
        ha="center",
        va="center",
        fontsize=11,
        color="#5B6470",
    )
    fig.text(
        0.5,
        0.052,
        (
            f'完全一致 {summary["exact_rate"]:.1%}  |  '
            f'二次加权 Cohen\'s κ={summary["kappa_quadratic"]:.3f}'
        ),
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        color="#214B63",
    )
    fig.text(
        0.5,
        0.019,
        (
            f'{summary["disagreement_count"]}条不一致样本中：自动裁判更低 {summary["judge_lower_count"]}条，'
            f'更高 {summary["judge_higher_count"]}条；双侧精确符号检验 p={sign_p:.2e}'
        ),
        ha="center",
        va="center",
        fontsize=10.2,
        color="#4C5159",
    )
    fig.tight_layout(rect=(0.02, 0.10, 0.98, 0.90), w_pad=3.0)
    save_figure(fig, output / "09_human_judge_agreement.png", dpi)


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
    human_judge_rows = load_human_judge_rows(
        args.single_human_labels,
        args.multi_human_labels,
        args.human_judge_reference,
    )
    agreement = compute_agreement_summaries(
        human_judge_rows,
        args.agreement_bootstrap_reps,
        args.agreement_bootstrap_seed,
    )

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
        plot_human_judge_agreement(agreement["pooled"], args.output_dir, args.dpi)

    print(f"分析完成：{args.output_dir}")
    print(f"论文表产物：{len(table_paths)} 个文件")
    for label, key in (("单轮", "single"), ("多轮", "multi"), ("汇总", "pooled")):
        current = agreement[key]
        kappa = current["kappa_quadratic"]
        spearman = current["spearman"]
        print(
            f"{label}人工—自动裁判：n={current['n']}，"
            f"完全一致={current['exact_rate']:.1%}，"
            f"相差不超1分={current['within_one_rate']:.1%}，"
            f"MAE={current['mae']:.3f}，"
            f"二次加权κ={kappa:.3f}，"
            f"Spearman ρ={spearman:.3f}，"
            f"人工均分={current['human_mean']:.3f}，"
            f"自动裁判均分={current['judge_mean']:.3f}"
        )
    pooled = agreement["pooled"]
    print(
        f"不一致方向：自动裁判更低 {pooled['judge_lower_count']} 条，"
        f"更高 {pooled['judge_higher_count']} 条；"
        f"双侧精确符号检验 p={pooled['sign_test_two_sided_p']:.2e}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
