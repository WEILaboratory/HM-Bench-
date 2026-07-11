#!/usr/bin/env python3
"""先并行评测全部模型，再并行评分当前数据集的结果。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import eval_multi_turn as multi
import eval_single_turn as single


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SCORE_OUTPUT_DIR = PROJECT_ROOT / "results" / "scores"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行全部模型的生成与评分实验。")
    parser.add_argument("--model-root", default=os.environ.get("MODEL_ROOT", "/data/jinxiang"))
    parser.add_argument("--gpus", default=os.environ.get("EVAL_GPUS", ""), help="例如 0,1,2,3；留空则自动选空闲 GPU。")
    parser.add_argument("--small-model-gpus", type=int, default=1)
    parser.add_argument("--large-model-gpus", type=int, default=2)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.85)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--score-workers", type=int, default=8, help="同时评分的结果文件数。")
    parser.add_argument("--disable-concurrent-large", action="store_true", help="大模型运行时不再并行其他模型。")
    parser.add_argument("--overwrite-generation", action="store_true")
    parser.add_argument("--overwrite-scoring", action="store_true")
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--skip-scoring", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.score_workers < 1:
        parser.error("score-workers 必须大于 0。")
    if not args.dry_run and not args.skip_scoring and not (os.environ.get("JUDGE_API_KEY") or os.environ.get("PACKY_API_KEY")):
        parser.error("评分需要设置 JUDGE_API_KEY。")
    return args


def generation_command(args: argparse.Namespace) -> list[str]:
    """构造全模型 vLLM 调度命令。"""
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_vllm_all.py"),
        "--model-groups", "main",
        "--tasks", "both",
        "--model-root", args.model_root,
        "--small-model-gpus", str(args.small_model_gpus),
        "--large-model-gpus", str(args.large_model_gpus),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--max-new-tokens", str(args.max_new_tokens),
        "--temperature", "0",
    ]
    if args.gpus:
        cmd.extend(["--include-gpus", args.gpus])
    if not args.disable_concurrent_large:
        cmd.append("--allow-concurrent-large")
    if args.overwrite_generation:
        cmd.append("--overwrite")
    return cmd


def current_result_files() -> tuple[list[tuple[str, Path]], list[str]]:
    """选择全部模型的完整单轮和多轮结果。"""
    _, single_samples = single.load_dataset(single.DEFAULT_DATASET, 0, 0)
    _, multi_samples = multi.load_dataset(multi.DEFAULT_DATASET, 0, 0)
    jobs: list[tuple[str, Path]] = []
    missing: list[str] = []
    for preset in single.MODEL_GROUPS["main"]:
        single_path = single.DEFAULT_OUTPUT_DIR / f"{preset}_start0_limitall.jsonl"
        multi_path = multi.DEFAULT_OUTPUT_DIR / f"{preset}_multiturn_start0_limitall.jsonl"
        if len(single.completed_sample_ids(single_path)) >= len(single_samples):
            jobs.append(("single", single_path))
        else:
            missing.append(f"single:{preset}")
        if len(multi.completed_sample_ids(multi_path)) >= len(multi_samples):
            jobs.append(("multi", multi_path))
        else:
            missing.append(f"multi:{preset}")
    return jobs, missing


def score_complete(task: str, source: Path) -> bool:
    """确认评分报告中没有遗留失败样本。"""
    report_path = SCORE_OUTPUT_DIR / task / f"{source.stem}_scores.json"
    if not report_path.exists():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    items = report.get("items", [])
    score_key = "score" if task == "single" else "sample_score"
    expected = int(report.get("source_sample_count", 0))
    return len(items) == expected and all(score_key in item and "error" not in item for item in items)


def score_one(task: str, source: Path, args: argparse.Namespace, log_dir: Path) -> tuple[str, bool, str]:
    """每个结果文件由独立进程评分，方便并发和断点续跑。"""
    name = f"{task}:{source.stem}"
    log_path = log_dir / f"{task}_{source.stem}.log"
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "score_outputs.py"),
        "--task", task,
        "--sleep", "0",
        str(source),
    ]
    if args.overwrite_scoring:
        cmd.append("--overwrite")
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    success = result.returncode == 0 and score_complete(task, source)
    return name, success, str(log_path)


def main() -> int:
    args = parse_args()
    generation = generation_command(args)
    print("===== full experiment =====", flush=True)
    print("generation:", " ".join(generation), flush=True)
    print(f"score_workers={args.score_workers}", flush=True)
    if args.dry_run:
        dry_command = generation + ["--dry-run"]
        if args.gpus:
            dry_command.extend(["--assume-gpus", args.gpus])
        return subprocess.run(dry_command, cwd=PROJECT_ROOT).returncode

    generation_ok = True
    if not args.skip_generation:
        generation_ok = subprocess.run(generation, cwd=PROJECT_ROOT).returncode == 0
    if args.skip_scoring:
        return 0 if generation_ok else 1

    jobs, missing = current_result_files()
    if missing:
        print(f"[missing-results] {','.join(missing)}", flush=True)
    if not jobs:
        print("没有可评分的当前数据集结果。", flush=True)
        return 1

    log_dir = PROJECT_ROOT / "logs" / "scores" / datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(args.score_workers, len(jobs))) as pool:
        futures = [pool.submit(score_one, task, source, args, log_dir) for task, source in jobs]
        for future in as_completed(futures):
            name, success, log = future.result()
            print(f"[score-{'done' if success else 'failed'}] {name} log={log}", flush=True)
            if not success:
                failures.append(name)

    print(f"===== finished generation={generation_ok} scored={len(jobs) - len(failures)}/{len(jobs)} =====", flush=True)
    return 0 if generation_ok and not missing and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
