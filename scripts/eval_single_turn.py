#!/usr/bin/env python3
"""通过 vLLM/OpenAI-compatible 接口评测青少年内容安全单轮数据集。"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# 路径和模型配置。MODEL_ROOT 只用于记录本地模型目录，不在本脚本中加载权重。

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "datasets" / "青少年内容安全单轮场景.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results" / "model_outputs" / "single"
DEFAULT_MODEL_ROOT = Path("/data/jinxiang")

MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "qwen2.5-1.5b-instruct": {"model_id": "Qwen/Qwen2.5-1.5B-Instruct", "family": "Qwen", "params_b": 1.5},
    "qwen2.5-7b-instruct": {"model_id": "Qwen/Qwen2.5-7B-Instruct", "family": "Qwen", "params_b": 7},
    "qwen2.5-14b-instruct": {"model_id": "Qwen/Qwen2.5-14B-Instruct", "family": "Qwen", "params_b": 14},
    "qwen2.5-32b-instruct": {"model_id": "Qwen/Qwen2.5-32B-Instruct", "family": "Qwen", "params_b": 32},
    "deepseek-llm-7b-chat": {"model_id": "deepseek-ai/deepseek-llm-7b-chat", "family": "DeepSeek", "params_b": 7},
    "deepseek-v2-lite-chat": {
        "model_id": "deepseek-ai/DeepSeek-V2-Lite-Chat",
        "family": "DeepSeek",
        "params_b": 16,
        "active_params_b": 2.4,
        "trust_remote_code": True,
    },
    "internlm2.5-1.8b-chat": {
        "model_id": "internlm/internlm2_5-1_8b-chat",
        "family": "InternLM",
        "params_b": 1.8,
        "trust_remote_code": True,
    },
    "internlm2.5-7b-chat": {
        "model_id": "internlm/internlm2_5-7b-chat",
        "family": "InternLM",
        "params_b": 7,
        "trust_remote_code": True,
    },
    "internlm2.5-20b-chat": {
        "model_id": "internlm/internlm2_5-20b-chat",
        "family": "InternLM",
        "params_b": 20,
        "trust_remote_code": True,
    },
    "glm4-9b-0414": {"model_id": "zai-org/GLM-4-9B-0414", "family": "GLM", "params_b": 9},
    "glm4-32b-0414": {"model_id": "zai-org/GLM-4-32B-0414", "family": "GLM", "params_b": 32},
    "glm-z1-9b-0414": {
        "model_id": "zai-org/GLM-Z1-9B-0414",
        "family": "GLM",
        "params_b": 9,
        "is_reasoning_model": True,
    },
    "glm-z1-32b-0414": {
        "model_id": "zai-org/GLM-Z1-32B-0414",
        "family": "GLM",
        "params_b": 32,
        "is_reasoning_model": True,
    },
}

MODEL_GROUPS: dict[str, list[str]] = {
    "default": ["qwen2.5-7b-instruct", "deepseek-v2-lite-chat", "internlm2.5-7b-chat", "glm4-9b-0414"],
    "qwen-scale": ["qwen2.5-1.5b-instruct", "qwen2.5-7b-instruct", "qwen2.5-14b-instruct", "qwen2.5-32b-instruct"],
    "deepseek-native": ["deepseek-llm-7b-chat", "deepseek-v2-lite-chat"],
    "internlm-scale": ["internlm2.5-1.8b-chat", "internlm2.5-7b-chat", "internlm2.5-20b-chat"],
    "glm-scale": ["glm4-9b-0414", "glm4-32b-0414", "glm-z1-9b-0414", "glm-z1-32b-0414"],
}
MODEL_GROUPS["main"] = [
    preset
    for group in ("qwen-scale", "deepseek-native", "internlm-scale", "glm-scale")
    for preset in MODEL_GROUPS[group]
]


@dataclass
class EvalArgs:
    """单轮评测参数。"""

    dataset: Path
    output_dir: Path
    model_root: Path
    model_presets: list[str]
    start: int
    limit: int
    max_new_tokens: int
    temperature: float
    top_p: float
    repetition_penalty: float
    overwrite: bool
    max_consecutive_errors: int
    api_base: str
    api_key: str
    api_model: str | None
    request_timeout: float


def env_int(name: str, default: int) -> int:
    """读取整数环境变量。"""
    value = os.environ.get(name)
    return default if value in (None, "") else int(value)


def env_float(name: str, default: float) -> float:
    """读取浮点数环境变量。"""
    value = os.environ.get(name)
    return default if value in (None, "") else float(value)


def env_flag(name: str, default: bool = False) -> bool:
    """读取布尔环境变量。"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def model_dir(model_root: Path, model_id: str) -> Path:
    """把 Hugging Face 模型名转换成本地目录名。"""
    return model_root / model_id.replace("/", "_")


def dedupe_presets(presets: list[str]) -> list[str]:
    """按原顺序去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for preset in presets:
        if preset not in seen:
            seen.add(preset)
            result.append(preset)
    return result


def parse_presets(model_presets: list[str] | None, model_groups: list[str] | None) -> list[str]:
    """把模型组和模型名解析成最终运行列表。"""
    presets: list[str] = []
    for group in model_groups or []:
        if group not in MODEL_GROUPS:
            raise SystemExit(f"未知模型组：{group}\n可用模型组：{', '.join(MODEL_GROUPS)}")
        presets.extend(MODEL_GROUPS[group])
    presets.extend(model_presets or [])
    if not presets:
        presets = MODEL_GROUPS["default"]

    presets = dedupe_presets(presets)
    unknown = [preset for preset in presets if preset not in MODEL_PRESETS]
    if unknown:
        raise SystemExit(f"未知模型名称：{', '.join(unknown)}\n可用模型名称：{', '.join(MODEL_PRESETS)}")
    return presets


def print_model_catalog() -> None:
    """打印内置模型组和模型名。"""
    print("Model groups:")
    for name, presets in MODEL_GROUPS.items():
        print(f"  {name}: {', '.join(presets)}")
    print("\nModel presets:")
    for name, meta in MODEL_PRESETS.items():
        tags = [str(meta["family"]), f"{meta['params_b']}B"]
        if meta.get("active_params_b"):
            tags.append(f"{meta['active_params_b']}B active")
        if meta.get("trust_remote_code"):
            tags.append("trust_remote_code")
        if meta.get("is_reasoning_model"):
            tags.append("reasoning")
        print(f"  {name}: {meta['model_id']} [{', '.join(tags)}]")


def parse_args() -> EvalArgs:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="通过 vLLM/OpenAI-compatible 接口评测单轮数据集。")
    parser.add_argument("--list-models", action="store_true", help="列出内置模型组和模型名后退出。")
    parser.add_argument("--model-groups", nargs="*", help="要运行的模型组，例如 default、main。")
    parser.add_argument("--model-presets", nargs="*", help="要运行的具体模型名。")
    parser.add_argument("--dataset", type=Path, default=Path(os.environ.get("DATASET", DEFAULT_DATASET)))
    parser.add_argument("--output-dir", type=Path, default=Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--model-root", type=Path, default=Path(os.environ.get("MODEL_ROOT", DEFAULT_MODEL_ROOT)))
    parser.add_argument("--start", type=int, default=env_int("START", 0))
    parser.add_argument("--limit", type=int, default=env_int("LIMIT", 0), help="0 表示从 start 跑到末尾。")
    parser.add_argument("--max-new-tokens", type=int, default=env_int("MAX_NEW_TOKENS", 512))
    parser.add_argument("--temperature", type=float, default=env_float("TEMPERATURE", 0.0))
    parser.add_argument("--top-p", type=float, default=env_float("TOP_P", 0.9))
    parser.add_argument("--repetition-penalty", type=float, default=env_float("REPETITION_PENALTY", 1.05))
    parser.add_argument("--overwrite", action="store_true", default=env_flag("OVERWRITE", False))
    parser.add_argument("--max-consecutive-errors", type=int, default=env_int("MAX_CONSECUTIVE_ERRORS", 3))
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", "EMPTY"))
    parser.add_argument("--api-model", default=os.environ.get("API_MODEL"))
    parser.add_argument("--request-timeout", type=float, default=env_float("REQUEST_TIMEOUT", 300.0))
    parsed = parser.parse_args()

    if parsed.list_models:
        print_model_catalog()
        raise SystemExit(0)

    return EvalArgs(
        dataset=parsed.dataset,
        output_dir=parsed.output_dir,
        model_root=parsed.model_root,
        model_presets=parse_presets(parsed.model_presets, parsed.model_groups),
        start=parsed.start,
        limit=parsed.limit,
        max_new_tokens=parsed.max_new_tokens,
        temperature=parsed.temperature,
        top_p=parsed.top_p,
        repetition_penalty=parsed.repetition_penalty,
        overwrite=parsed.overwrite,
        max_consecutive_errors=parsed.max_consecutive_errors,
        api_base=parsed.api_base,
        api_key=parsed.api_key,
        api_model=parsed.api_model,
        request_timeout=parsed.request_timeout,
    )


def load_dataset(path: Path, start: int, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """读取并校验单轮数据集。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("样本")
    if not isinstance(rows, list):
        raise SystemExit("单轮数据集缺少顶层字段：样本")
    if not isinstance(data.get("评分标准"), dict):
        raise SystemExit("单轮数据集缺少顶层字段：评分标准")
    if start < 0 or limit < 0:
        raise SystemExit("start 和 limit 不能为负数。")

    sample_ids = [str(row.get("样本ID", "")).strip() for row in rows if isinstance(row, dict)]
    if len(sample_ids) != len(rows) or any(not sample_id for sample_id in sample_ids):
        raise SystemExit("单轮数据集存在缺失样本ID的样本。")
    if len(set(sample_ids)) != len(sample_ids):
        raise SystemExit("单轮数据集存在重复样本ID。")

    end = None if limit == 0 else start + limit
    selected = rows[start:end]
    required = ["样本ID", "一级分类", "二级分类", "三级维度", "情景背景", "用户输入"]
    for row in selected:
        missing = [key for key in required if not str(row.get(key, "")).strip()]
        if missing:
            raise SystemExit(f"样本 {row.get('样本ID', '<unknown>')} 缺少字段：{missing}")
    metadata = {key: value for key, value in data.items() if key != "样本"}
    return metadata, selected


def build_prompt(sample: dict[str, Any]) -> str:
    """把情景背景和用户输入直接拼成单轮请求。"""
    background = str(sample["情景背景"]).strip()
    user_input = str(sample["用户输入"]).strip()
    return f"{background}{user_input}"


def create_client(args: EvalArgs) -> Any:
    """创建 OpenAI-compatible 客户端；vLLM 也使用这个接口格式。"""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("缺少 openai 依赖，请先运行：pip install openai") from exc
    return OpenAI(api_key=args.api_key, base_url=args.api_base, timeout=args.request_timeout)


def served_model_name(args: EvalArgs, preset: str) -> str:
    """确定 vLLM 服务中使用的模型名。"""
    return args.api_model or preset


def request_chat(client: Any, model: str, messages: list[dict[str, str]], args: EvalArgs) -> tuple[str, float]:
    """向 vLLM/OpenAI-compatible 服务发送一次 chat 请求。"""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_new_tokens,
    }
    if args.repetition_penalty != 1.0:
        payload["extra_body"] = {"repetition_penalty": args.repetition_penalty}

    start = time.time()
    try:
        response = client.chat.completions.create(**payload)
    except TypeError:
        # 兼容较旧 openai 包：不支持 extra_body 时去掉重复惩罚参数重试。
        payload.pop("extra_body", None)
        response = client.chat.completions.create(**payload)
    elapsed = time.time() - start
    return (response.choices[0].message.content or "").strip(), elapsed


def smoke_test(client: Any, model: str, args: EvalArgs, preset: str) -> None:
    """正式评测前确认本地 vLLM 服务可用。"""
    smoke_args = EvalArgs(**{**args.__dict__, "max_new_tokens": min(args.max_new_tokens, 48)})
    try:
        output, _ = request_chat(client, model, [{"role": "user", "content": "你好，请用一句中文介绍你自己。"}], smoke_args)
    except Exception as exc:
        raise SystemExit(f"[smoke-test-error] {preset}: {type(exc).__name__}: {exc}") from exc
    if not output:
        raise SystemExit(f"[smoke-test-error] {preset}: vLLM 服务返回了空回复。")
    print(f"[smoke-test] {preset} ok: {output.replace(chr(10), ' ')[:80]}", flush=True)


def output_path(args: EvalArgs, preset: str) -> Path:
    """生成稳定的 jsonl 输出路径。"""
    return args.output_dir / f"{preset}_start{args.start}_limit{args.limit or 'all'}.jsonl"


def completed_sample_ids(path: Path) -> set[str]:
    """读取已经完成的样本 ID，支持断点续跑。"""
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("record_type") == "sample" and row.get("sample_id") and row.get("output"):
            done.add(str(row["sample_id"]))
    return done


def write_metadata(
    f: Any,
    args: EvalArgs,
    dataset_metadata: dict[str, Any],
    preset: str,
    samples: list[dict[str, Any]],
) -> None:
    """新输出文件首行写入评测元数据。"""
    meta = MODEL_PRESETS[preset]
    row = {
        "record_type": "metadata",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "dataset_metadata": dataset_metadata,
        "sample_count": len(samples),
        "start": args.start,
        "limit": args.limit,
        "backend": "vllm",
        "api_base": args.api_base,
        "api_model": served_model_name(args, preset),
        "model_preset": preset,
        "model_id": meta["model_id"],
        "model_family": meta["family"],
        "model_params_b": meta.get("params_b"),
        "model_active_params_b": meta.get("active_params_b"),
        "model_dir": str(model_dir(args.model_root, meta["model_id"])),
        "prompt_template": "{情景背景}{用户输入}",
        "generation": {
            "max_new_tokens": args.max_new_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
        },
    }
    f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_output_row(index: int, sample: dict[str, Any], output: str, elapsed: float) -> dict[str, Any]:
    """构造单条样本输出。"""
    return {
        "record_type": "sample",
        "index": index,
        "sample_id": sample["样本ID"],
        "category_l1": sample["一级分类"],
        "category_l2": sample["二级分类"],
        "scenario": sample["三级维度"],
        "background": sample["情景背景"],
        "user_input": sample["用户输入"],
        "output": output,
        "elapsed_sec": round(elapsed, 3),
    }


def run_one_model(
    args: EvalArgs,
    dataset_metadata: dict[str, Any],
    preset: str,
    samples: list[dict[str, Any]],
) -> None:
    """请求一个 vLLM 模型服务，并跑完所选单轮样本。"""
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = output_path(args, preset)
    finished = set() if args.overwrite else completed_sample_ids(out)
    if len(finished) >= len(samples):
        print(f"[skip-model] preset={preset} output={out} resume_done={len(finished)}/{len(samples)}", flush=True)
        return

    client = create_client(args)
    api_model = served_model_name(args, preset)
    smoke_test(client, api_model, args, preset)

    mode = "w" if args.overwrite or not out.exists() else "a"
    if mode == "w":
        finished = set()
    print(
        f"[run] preset={preset} api_base={args.api_base} api_model={api_model} "
        f"samples={len(samples)} output={out} resume_done={len(finished)}",
        flush=True,
    )

    consecutive_errors = 0
    with out.open(mode, encoding="utf-8") as f:
        if mode == "w":
            write_metadata(f, args, dataset_metadata, preset, samples)
        for offset, sample in enumerate(samples):
            sample_id = sample["样本ID"]
            if sample_id in finished:
                print(f"[skip] {sample_id}", flush=True)
                continue

            index = args.start + offset
            try:
                output, elapsed = request_chat(client, api_model, [{"role": "user", "content": build_prompt(sample)}], args)
                row = sample_output_row(index, sample, output, elapsed)
                consecutive_errors = 0
                status = "ok"
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                consecutive_errors += 1
                row = {"record_type": "sample", "index": index, "sample_id": sample_id, "error": f"{type(exc).__name__}: {exc}"}
                status = "error"
                print(f"[error] {sample_id}: {row['error']}", flush=True)
                if args.max_consecutive_errors and consecutive_errors >= args.max_consecutive_errors:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    raise SystemExit(f"[stop] {preset} reached {consecutive_errors} consecutive API errors.")

            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{offset + 1}/{len(samples)}] {sample_id} {status}", flush=True)


def main() -> int:
    """程序入口。"""
    args = parse_args()
    dataset_metadata, samples = load_dataset(args.dataset, args.start, args.limit)

    print("===== eval_single_turn_vllm =====", flush=True)
    print(f"dataset={args.dataset}", flush=True)
    print(f"samples={len(samples)} start={args.start} limit={args.limit or 'all'}", flush=True)
    print(f"model_presets={','.join(args.model_presets)}", flush=True)
    print(f"api_base={args.api_base}", flush=True)

    for preset in args.model_presets:
        print(f"\n===== model: {preset} =====", flush=True)
        run_one_model(args, dataset_metadata, preset, samples)
    print("===== done =====", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
