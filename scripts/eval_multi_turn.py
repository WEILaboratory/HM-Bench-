#!/usr/bin/env python3
"""通过 vLLM/OpenAI-compatible 接口评测青少年内容安全多轮数据集。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_single_turn as base


# 多轮默认输出与单轮分开，避免新旧实验结果混在一起。

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "青少年内容安全多轮场景.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval_outputs_multiturn_vllm"
DEFAULT_MODEL_ROOT = Path("/data/jinxiang")


@dataclass
class MultiTurnArgs:
    """多轮评测参数。"""

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


def parse_args() -> MultiTurnArgs:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="通过 vLLM/OpenAI-compatible 接口评测多轮数据集。")
    parser.add_argument("--list-models", action="store_true", help="列出内置模型组和模型名后退出。")
    parser.add_argument("--model-groups", nargs="*", help="要运行的模型组，例如 default、main。")
    parser.add_argument("--model-presets", nargs="*", help="要运行的具体模型名。")
    parser.add_argument("--dataset", type=Path, default=Path(os.environ.get("DATASET", DEFAULT_DATASET)))
    parser.add_argument("--output-dir", type=Path, default=Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--model-root", type=Path, default=Path(os.environ.get("MODEL_ROOT", DEFAULT_MODEL_ROOT)))
    parser.add_argument("--start", type=int, default=base.env_int("START", 0))
    parser.add_argument("--limit", type=int, default=base.env_int("LIMIT", 0), help="0 表示从 start 跑到末尾。")
    parser.add_argument("--max-new-tokens", type=int, default=base.env_int("MAX_NEW_TOKENS", 512))
    parser.add_argument("--temperature", type=float, default=base.env_float("TEMPERATURE", 0.0))
    parser.add_argument("--top-p", type=float, default=base.env_float("TOP_P", 0.9))
    parser.add_argument("--repetition-penalty", type=float, default=base.env_float("REPETITION_PENALTY", 1.05))
    parser.add_argument("--overwrite", action="store_true", default=base.env_flag("OVERWRITE", False))
    parser.add_argument("--max-consecutive-errors", type=int, default=base.env_int("MAX_CONSECUTIVE_ERRORS", 3))
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", "EMPTY"))
    parser.add_argument("--api-model", default=os.environ.get("API_MODEL"))
    parser.add_argument("--request-timeout", type=float, default=base.env_float("REQUEST_TIMEOUT", 300.0))
    parsed = parser.parse_args()

    if parsed.list_models:
        base.print_model_catalog()
        raise SystemExit(0)

    return MultiTurnArgs(
        dataset=parsed.dataset,
        output_dir=parsed.output_dir,
        model_root=parsed.model_root,
        model_presets=base.parse_presets(parsed.model_presets, parsed.model_groups),
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
    """读取并校验多轮数据集。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("样本")
    if not isinstance(rows, list):
        raise SystemExit("多轮数据集缺少顶层字段：样本。")
    if not isinstance(data.get("评分标准"), dict):
        raise SystemExit("多轮数据集缺少顶层字段：评分标准。")
    if start < 0 or limit < 0:
        raise SystemExit("start 和 limit 不能为负数。")

    mechanisms = data.get("机制")
    if not isinstance(mechanisms, list) or not mechanisms:
        raise SystemExit("多轮数据集缺少非空顶层字段：机制。")
    mechanism_ids = {str(item.get("机制编号")) for item in mechanisms if isinstance(item, dict) and item.get("机制编号")}
    metadata = {key: value for key, value in data.items() if key != "样本"}

    sample_ids = [str(row.get("样本编号", "")).strip() for row in rows if isinstance(row, dict)]
    if len(sample_ids) != len(rows) or any(not sample_id for sample_id in sample_ids):
        raise SystemExit("多轮数据集存在缺失样本编号的样本。")
    if len(set(sample_ids)) != len(sample_ids):
        raise SystemExit("多轮数据集存在重复样本编号。")

    end = None if limit == 0 else start + limit
    selected = rows[start:end]
    required = ["样本编号", "机制编号", "机制名称", "场景", "情景背景", "对话"]
    for row in selected:
        missing = [key for key in required if not row.get(key)]
        if missing:
            raise SystemExit(f"样本 {row.get('样本编号', '<unknown>')} 缺少字段：{missing}")
        if str(row["机制编号"]) not in mechanism_ids:
            raise SystemExit(f"样本 {row['样本编号']} 使用了未知机制编号：{row['机制编号']}")
        if not isinstance(row["对话"], list) or not row["对话"]:
            raise SystemExit(f"样本 {row['样本编号']} 缺少对话轮次。")
        expected_turn = 1
        for turn in row["对话"]:
            if not turn.get("轮次") or not str(turn.get("用户输入", "")).strip():
                raise SystemExit(f"样本 {row['样本编号']} 存在无效轮次：{turn}")
            if int(turn["轮次"]) != expected_turn:
                raise SystemExit(f"样本 {row['样本编号']} 的轮次必须从 1 连续递增。")
            expected_turn += 1
    return metadata, selected


def build_user_message(sample: dict[str, Any], turn: dict[str, Any], is_first_turn: bool) -> str:
    """第一轮直接拼接情景背景，后续轮次只追加新的用户输入。"""
    user_input = str(turn["用户输入"]).strip()
    if is_first_turn:
        background = str(sample["情景背景"]).strip()
        return f"{background}{user_input}"
    return user_input


def request_chat(client: Any, model: str, messages: list[dict[str, str]], args: MultiTurnArgs) -> tuple[str, float]:
    """向 vLLM/OpenAI-compatible 服务发送一次多轮 chat 请求。"""
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


def smoke_test(client: Any, model: str, args: MultiTurnArgs, preset: str) -> None:
    """正式评测前确认本地 vLLM 服务支持多轮 chat。"""
    smoke_args = MultiTurnArgs(**{**args.__dict__, "max_new_tokens": min(args.max_new_tokens, 48)})
    messages = [{"role": "user", "content": "你好，请用一句中文介绍你自己。"}]
    try:
        first, _ = request_chat(client, model, messages, smoke_args)
        messages.append({"role": "assistant", "content": first})
        messages.append({"role": "user", "content": "请用一句话概括你刚才说了什么。"})
        second, _ = request_chat(client, model, messages, smoke_args)
    except Exception as exc:
        raise SystemExit(f"[smoke-test-error] {preset}: {type(exc).__name__}: {exc}") from exc
    if not first or not second:
        raise SystemExit(f"[smoke-test-error] {preset}: vLLM 服务返回了空回复。")
    print(f"[smoke-test] {preset} ok: {second.replace(chr(10), ' ')[:80]}", flush=True)


def run_sample_conversation(client: Any, model: str, sample: dict[str, Any], args: MultiTurnArgs) -> list[dict[str, Any]]:
    """跑完一个样本的全部轮次；样本内保留历史，样本间不共享历史。"""
    messages: list[dict[str, str]] = []
    evaluated_turns: list[dict[str, Any]] = []

    for idx, turn in enumerate(sample["对话"]):
        user_content = build_user_message(sample, turn, is_first_turn=(idx == 0))
        messages.append({"role": "user", "content": user_content})
        output, elapsed = request_chat(client, model, messages, args)
        messages.append({"role": "assistant", "content": output})
        evaluated_turns.append({
            "turn_id": turn["轮次"],
            "user_input": turn["用户输入"],
            "model_input": user_content,
            "assistant_output": output,
            "elapsed_sec": round(elapsed, 3),
            "history_messages_after_turn": len(messages),
        })
    return evaluated_turns


def output_path(args: MultiTurnArgs, preset: str) -> Path:
    """生成稳定的 jsonl 输出路径。"""
    return args.output_dir / f"{preset}_multiturn_start{args.start}_limit{args.limit or 'all'}.jsonl"


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
        if row.get("record_type") == "sample" and row.get("sample_id") and row.get("status") == "ok":
            done.add(str(row["sample_id"]))
    return done


def write_metadata(
    f: Any,
    args: MultiTurnArgs,
    dataset_metadata: dict[str, Any],
    preset: str,
    samples: list[dict[str, Any]],
) -> None:
    """新输出文件首行写入评测元数据。"""
    meta = base.MODEL_PRESETS[preset]
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
        "api_model": base.served_model_name(args, preset),
        "model_preset": preset,
        "model_id": meta["model_id"],
        "model_family": meta["family"],
        "model_params_b": meta.get("params_b"),
        "model_active_params_b": meta.get("active_params_b"),
        "model_dir": str(base.model_dir(args.model_root, meta["model_id"])),
        "conversation_memory": "每条样本内部保留此前用户和助手轮次；不同样本之间清空历史。",
        "first_turn_template": "{background}{turn_1_user_input}",
        "later_turn_template": "{turn_n_user_input}",
        "generation": {
            "max_new_tokens": args.max_new_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
        },
    }
    f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_output_row(index: int, sample: dict[str, Any], turns: list[dict[str, Any]]) -> dict[str, Any]:
    """构造一个多轮样本输出。"""
    return {
        "record_type": "sample",
        "status": "ok",
        "index": index,
        "sample_id": sample["样本编号"],
        "mechanism_id": sample["机制编号"],
        "mechanism_name": sample["机制名称"],
        "scenario": sample["场景"],
        "background": sample["情景背景"],
        "turn_count": len(turns),
        "turns": turns,
    }


def run_one_model(args: MultiTurnArgs, dataset_metadata: dict[str, Any], preset: str, samples: list[dict[str, Any]]) -> None:
    """请求一个 vLLM 模型服务，并跑完所选多轮样本。"""
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = output_path(args, preset)
    finished = set() if args.overwrite else completed_sample_ids(out)
    if len(finished) >= len(samples):
        print(f"[skip-model] preset={preset} output={out} resume_done={len(finished)}/{len(samples)}", flush=True)
        return

    client = base.create_client(args)
    api_model = base.served_model_name(args, preset)
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
            sample_id = sample["样本编号"]
            if sample_id in finished:
                print(f"[skip] {sample_id}", flush=True)
                continue

            index = args.start + offset
            try:
                turns = run_sample_conversation(client, api_model, sample, args)
                row = sample_output_row(index, sample, turns)
                consecutive_errors = 0
                status = "ok"
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                consecutive_errors += 1
                row = {
                    "record_type": "sample",
                    "status": "error",
                    "index": index,
                    "sample_id": sample_id,
                    "mechanism_id": sample.get("机制编号"),
                    "mechanism_name": sample.get("机制名称"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
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

    print("===== eval_multi_turn_vllm =====", flush=True)
    print(f"dataset={args.dataset}", flush=True)
    print(f"samples={len(samples)} start={args.start} limit={args.limit or 'all'}", flush=True)
    print(f"model_presets={','.join(args.model_presets)}", flush=True)
    print(f"api_base={args.api_base}", flush=True)
    print("conversation_memory=样本内保留历史，样本间清空", flush=True)

    for preset in args.model_presets:
        print(f"\n===== model: {preset} =====", flush=True)
        run_one_model(args, dataset_metadata, preset, samples)
    print("===== done =====", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
