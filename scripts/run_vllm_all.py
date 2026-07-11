#!/usr/bin/env python3
"""自动启动 vLLM 服务，并用本地 OpenAI-compatible 接口跑单轮/多轮评测。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_single_turn as base
import eval_multi_turn as multi_base


@dataclass
class GPUInfo:
    """一张 GPU 的基本显存状态。"""

    index: int
    used_mib: int
    total_mib: int

    @property
    def free_mib(self) -> int:
        return self.total_mib - self.used_mib


@dataclass
class JobResult:
    """一个模型评测任务的结果。"""

    preset: str
    success: bool
    message: str


def is_large_model(preset: str, args: argparse.Namespace) -> bool:
    """判断模型是否按大模型策略调度。"""
    meta = base.MODEL_PRESETS[preset]
    return float(meta.get("params_b") or 0) >= args.large_model_threshold_b


def parse_gpu_list(text: str | None) -> set[int] | None:
    """把 0,1,3 这样的 GPU 列表解析成集合。"""
    if not text:
        return None
    return {int(item.strip()) for item in text.split(",") if item.strip()}


def parse_args() -> argparse.Namespace:
    """解析调度脚本参数。"""
    parser = argparse.ArgumentParser(description="自动调度空闲 GPU，通过 vLLM 跑青少年内容安全评测。")
    parser.add_argument("--model-groups", nargs="*", help="默认使用 main，即全部内置模型。")
    parser.add_argument("--model-presets", nargs="*", help="只跑指定模型；优先级高于 --model-groups。")
    parser.add_argument("--tasks", choices=["single", "multi", "both"], default="both", help="运行单轮、多轮或两者都运行。")
    parser.add_argument("--model-root", type=Path, default=Path(os.environ.get("MODEL_ROOT", base.DEFAULT_MODEL_ROOT)))
    parser.add_argument("--python", default=sys.executable, help="运行评测脚本的 Python。默认使用当前环境。")
    parser.add_argument("--vllm-command", default=os.environ.get("VLLM_COMMAND", "vllm"), help="vLLM 命令名或完整路径。")
    parser.add_argument("--vllm-log-level", default=os.environ.get("VLLM_LOGGING_LEVEL", "WARNING"), help="vLLM 日志级别，例如 INFO、WARNING、ERROR。")
    parser.add_argument("--host", default="127.0.0.1", help="vLLM 服务监听地址。")
    parser.add_argument("--base-port", type=int, default=8100, help="第一个 vLLM 服务端口，后续模型依次递增。")
    parser.add_argument("--startup-timeout", type=int, default=900, help="等待 vLLM 服务启动的最长秒数。")
    parser.add_argument("--startup-stall-timeout", type=int, default=900, help="服务日志长时间没有增长时判定启动停滞。")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="轮询 GPU 和服务状态的间隔秒数。")
    parser.add_argument("--gpu-used-threshold-mib", type=int, default=2048, help="只使用当前显存占用不超过该值的 GPU。")
    parser.add_argument("--assume-gpus", help="跳过 nvidia-smi，直接假设这些 GPU 可用，例如 1,2,3；主要用于 dry-run。")
    parser.add_argument("--include-gpus", help="只允许使用这些 GPU，例如 1,2,3。")
    parser.add_argument("--exclude-gpus", help="排除这些 GPU，例如 0,4,5,6,7。")
    parser.add_argument("--small-model-gpus", type=int, default=1, help="小模型默认使用的 GPU 数量。")
    parser.add_argument("--large-model-gpus", type=int, default=2, help="大模型默认使用的 GPU 数量。")
    parser.add_argument("--large-model-threshold-b", type=float, default=30.0, help="参数量达到该阈值后视为大模型。")
    parser.add_argument("--allow-concurrent-large", action="store_true", help="GPU 足够时允许大模型与其他模型并行。")
    parser.add_argument("--skip-too-large", action="store_true", help="空闲 GPU 数量不足时跳过该模型，而不是直接退出。")
    parser.add_argument("--dtype", default="bfloat16", help="vLLM 加载模型时使用的数据类型。")
    parser.add_argument("--max-model-len", type=int, default=4096, help="vLLM 服务允许的最大上下文长度。")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90, help="vLLM 可使用的 GPU 显存比例。")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="每次回答最多生成的 token 数。")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度；0 表示确定性生成。")
    parser.add_argument("--top-p", type=float, default=0.9, help="核采样参数。")
    parser.add_argument("--repetition-penalty", type=float, default=1.05, help="重复惩罚参数。")
    parser.add_argument("--start", type=int, default=0, help="数据集起始下标。")
    parser.add_argument("--limit", type=int, default=0, help="0 表示跑完整数据集。")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=300.0, help="单次 API 请求超时时间。")
    parser.add_argument("--hf-endpoint", default=os.environ.get("HF_ENDPOINT"), help="Hugging Face 镜像地址。")
    parser.add_argument("--server-log-dir", type=Path, default=PROJECT_ROOT / "logs" / "vllm_servers", help="vLLM 服务日志目录。")
    parser.add_argument("--eval-log-dir", type=Path, default=PROJECT_ROOT / "logs" / "vllm_evals", help="评测脚本日志目录。")
    parser.add_argument("--dry-run", action="store_true", help="只打印调度计划，不启动服务。")
    return parser.parse_args()


def query_gpus() -> list[GPUInfo]:
    """读取 nvidia-smi，返回每张 GPU 的显存占用。"""
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as exc:
        raise SystemExit(f"无法读取 nvidia-smi：{exc}") from exc

    gpus: list[GPUInfo] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        gpus.append(GPUInfo(index=int(parts[0]), used_mib=int(parts[1]), total_mib=int(parts[2])))
    if not gpus:
        raise SystemExit("nvidia-smi 没有返回可用 GPU。")
    return gpus


def available_gpu_indices(args: argparse.Namespace) -> list[int]:
    """根据显存阈值和 include/exclude 规则选择可用 GPU。"""
    assumed = parse_gpu_list(args.assume_gpus)
    if assumed is not None:
        return sorted(assumed)

    include = parse_gpu_list(args.include_gpus)
    exclude = parse_gpu_list(args.exclude_gpus) or set()
    candidates: list[GPUInfo] = []
    for gpu in query_gpus():
        if include is not None and gpu.index not in include:
            continue
        if gpu.index in exclude:
            continue
        if gpu.used_mib <= args.gpu_used_threshold_mib:
            candidates.append(gpu)
    candidates.sort(key=lambda item: (-item.free_mib, item.index))
    return [gpu.index for gpu in candidates]


def required_gpus_for_preset(preset: str, args: argparse.Namespace) -> int:
    """根据模型规模估计需要几张 GPU。"""
    meta = base.MODEL_PRESETS[preset]
    params_b = float(meta.get("params_b") or 0)
    if params_b >= args.large_model_threshold_b:
        return args.large_model_gpus
    return args.small_model_gpus


def model_source_for_preset(preset: str, args: argparse.Namespace) -> str:
    """确定 vLLM 加载的模型来源：优先本地目录，缺失时用 Hugging Face ID。"""
    meta = base.MODEL_PRESETS[preset]
    local_dir = base.model_dir(args.model_root, meta["model_id"])
    return str(local_dir) if has_local_model(preset, args) else str(meta["model_id"])


def expected_weight_files(local_dir: Path) -> list[str]:
    """从权重索引里读取分片列表；没有索引时返回空列表。"""
    for index_name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        index_path = local_dir / index_name
        if not index_path.exists():
            continue
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        weight_map = data.get("weight_map")
        if isinstance(weight_map, dict):
            return sorted({str(name) for name in weight_map.values()})
    return []


def has_tokenizer_files(local_dir: Path) -> bool:
    """确认本地目录至少包含一种常见 tokenizer 资产。"""
    names = (
        "tokenizer.json",
        "tokenizer.model",
        "spiece.model",
        "vocab.json",
        "merges.txt",
        "tiktoken.model",
    )
    return any((local_dir / name).is_file() for name in names) or any(local_dir.glob("*.tiktoken"))


def has_local_model(preset: str, args: argparse.Namespace) -> bool:
    """判断模型权重是否已经完整放在 MODEL_ROOT 下。"""
    meta = base.MODEL_PRESETS[preset]
    local_dir = base.model_dir(args.model_root, meta["model_id"])
    if not local_dir.is_dir() or not (local_dir / "config.json").is_file() or not has_tokenizer_files(local_dir):
        return False

    expected_files = expected_weight_files(local_dir)
    if expected_files:
        return all((local_dir / name).is_file() and (local_dir / name).stat().st_size > 0 for name in expected_files)

    weight_patterns = ("*.safetensors", "pytorch_model*.bin", "*.bin")
    return any(
        path.is_file() and path.stat().st_size > 0
        for pattern in weight_patterns
        for path in local_dir.glob(pattern)
    )


def configure_hf_env(args: argparse.Namespace) -> None:
    """统一 Hugging Face 下载环境，避免 Xet/CAS 在服务器镜像环境下卡住或报 401。"""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint


def download_missing_model(preset: str, args: argparse.Namespace) -> None:
    """启动 vLLM 前下载缺失模型，避免服务启动阶段静默下载到超时。"""
    if has_local_model(preset, args):
        print(f"[model-ready] {preset} local={model_source_for_preset(preset, args)}", flush=True)
        return

    meta = base.MODEL_PRESETS[preset]
    local_dir = base.model_dir(args.model_root, meta["model_id"])
    print(f"[download-start] {preset} repo={meta['model_id']} local={local_dir}", flush=True)
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("缺少 huggingface_hub 依赖，请在服务器环境里安装：pip install huggingface_hub") from exc

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            snapshot_download(
                repo_id=str(meta["model_id"]),
                local_dir=str(local_dir),
                ignore_patterns=["*.gguf", "*.h5", "*.msgpack", "*.onnx", "*.ot", "*.tflite"],
                max_workers=4,
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            print(f"[download-retry] {preset} attempt={attempt}/3 error={type(exc).__name__}: {exc}", flush=True)
            if attempt < 3:
                time.sleep(30 * attempt)
    if last_error is not None:
        raise RuntimeError(f"下载模型失败：{preset} repo={meta['model_id']} local={local_dir}，原因：{last_error}") from last_error

    if not has_local_model(preset, args):
        raise RuntimeError(f"模型下载后仍不完整：{preset} local={local_dir}")
    print(f"[download-done] {preset} local={local_dir}", flush=True)


def prepare_models(presets: list[str], args: argparse.Namespace) -> tuple[list[str], list[JobResult]]:
    """逐个确认模型已在本地，下载失败的模型记录为失败，其他模型继续跑。"""
    configure_hf_env(args)
    ready: list[str] = []
    failures: list[JobResult] = []
    for preset in presets:
        try:
            download_missing_model(preset, args)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[download-failed] {preset} {message}", flush=True)
            failures.append(JobResult(preset=preset, success=False, message=message))
            continue
        ready.append(preset)
    return ready, failures


def output_file_for_task(task: str, preset: str, args: argparse.Namespace) -> Path:
    """按评测脚本的默认规则推导输出文件路径。"""
    if task == "single":
        return base.DEFAULT_OUTPUT_DIR / f"{preset}_start{args.start}_limit{args.limit or 'all'}.jsonl"
    return multi_base.DEFAULT_OUTPUT_DIR / f"{preset}_multiturn_start{args.start}_limit{args.limit or 'all'}.jsonl"


def task_sample_count(task: str, args: argparse.Namespace) -> int:
    """读取当前 start/limit 下的样本数，用于判断断点续跑是否完整。"""
    if task == "single":
        _, samples = base.load_dataset(base.DEFAULT_DATASET, args.start, args.limit)
        return len(samples)
    _, samples = multi_base.load_dataset(multi_base.DEFAULT_DATASET, args.start, args.limit)
    return len(samples)


def task_output_done(task: str, preset: str, args: argparse.Namespace) -> bool:
    """判断某个模型某个任务是否已经完整输出。"""
    if args.overwrite:
        return False
    out = output_file_for_task(task, preset, args)
    sample_count = task_sample_count(task, args)
    if task == "single":
        return len(base.completed_sample_ids(out)) >= sample_count
    return len(multi_base.completed_sample_ids(out)) >= sample_count


def model_outputs_done(preset: str, args: argparse.Namespace) -> bool:
    """判断当前要跑的任务是否都已经完成，完成则无需启动 vLLM。"""
    tasks: list[str] = []
    if args.tasks in ("single", "both"):
        tasks.append("single")
    if args.tasks in ("multi", "both"):
        tasks.append("multi")
    return all(task_output_done(task, preset, args) for task in tasks)


def startup_timeout_for_preset(preset: str, args: argparse.Namespace) -> int:
    """远程模型和大模型需要更长的下载/加载等待时间。"""
    timeout = args.startup_timeout
    if is_large_model(preset, args):
        timeout = max(timeout, 7200)
    elif not has_local_model(preset, args):
        timeout = max(timeout, 3600)
    return timeout


def wait_for_vllm(
    host: str,
    port: int,
    proc: subprocess.Popen[Any],
    timeout: int,
    poll_interval: float,
    server_log: Path,
    stall_timeout: int,
) -> None:
    """等待 vLLM OpenAI-compatible 服务就绪。"""
    url = f"http://{host}:{port}/v1/models"
    deadline = time.time() + timeout
    last_log_size = -1
    last_log_change = time.time()
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"vLLM 服务提前退出，returncode={proc.returncode}")
        if server_log.exists():
            current_size = server_log.stat().st_size
            if current_size != last_log_size:
                last_log_size = current_size
                last_log_change = time.time()
            elif current_size > 0 and time.time() - last_log_change > stall_timeout:
                raise TimeoutError(f"等待 vLLM 服务停滞：{url}，日志 {stall_timeout}s 没有新输出：{server_log}")
        try:
            request = Request(url, headers={"Authorization": "Bearer EMPTY"})
            with urlopen(request, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except URLError:
            pass
        time.sleep(poll_interval)
    raise TimeoutError(f"等待 vLLM 服务超时：{url}")


def start_vllm_server(
    preset: str,
    gpus: list[int],
    port: int,
    args: argparse.Namespace,
    server_log: Path,
) -> subprocess.Popen[Any]:
    """启动一个 vLLM 服务进程。"""
    meta = base.MODEL_PRESETS[preset]
    cmd = [
        args.vllm_command,
        "serve",
        model_source_for_preset(preset, args),
        "--served-model-name",
        preset,
        "--host",
        args.host,
        "--port",
        str(port),
        "--dtype",
        args.dtype,
        "--max-model-len",
        str(args.max_model_len),
        "--gpu-memory-utilization",
        str(args.gpu_memory_utilization),
        "--generation-config",
        "vllm",
        "--max-num-seqs",
        "1",
        "--max-num-batched-tokens",
        str(args.max_model_len),
    ]
    if len(gpus) > 1:
        cmd.extend([
            "--tensor-parallel-size",
            str(len(gpus)),
            "--distributed-executor-backend",
            "mp",
            "--disable-custom-all-reduce",
        ])
    if meta.get("trust_remote_code"):
        cmd.append("--trust-remote-code")
    cmd.append("--enforce-eager")

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ",".join(str(gpu) for gpu in gpus)
    env["VLLM_LOGGING_LEVEL"] = args.vllm_log_level
    # 避免额外采样/JIT路径；保持启动参数简单，减少版本兼容问题。
    env["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
    env["VLLM_MLA_DISABLE"] = "1"
    env["VLLM_USE_DEEP_GEMM"] = "0"
    env["VLLM_MOE_USE_DEEP_GEMM"] = "0"
    env["OMP_NUM_THREADS"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    if len(gpus) > 1:
        env["NCCL_P2P_DISABLE"] = "1"
        env["NCCL_IB_DISABLE"] = "1"
        env["NCCL_ASYNC_ERROR_HANDLING"] = "1"
        env["TORCH_NCCL_BLOCKING_WAIT"] = "1"
    # Xet/CAS 下载通道在未登录或镜像环境下容易 401；评测统一走普通下载链路。
    env["HF_HUB_DISABLE_XET"] = "1"
    if args.hf_endpoint:
        env["HF_ENDPOINT"] = args.hf_endpoint

    server_log.parent.mkdir(parents=True, exist_ok=True)
    log_file = server_log.open("w", encoding="utf-8")
    print(
        f"[vllm-start] {preset} gpus={env['CUDA_VISIBLE_DEVICES']} "
        f"max_len={args.max_model_len} port={port} log={server_log}",
        flush=True,
    )
    log_file.write("[cmd] " + " ".join(shlex.quote(str(item)) for item in cmd) + "\n")
    log_file.flush()
    return subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env, cwd=PROJECT_ROOT)


def terminate_process(proc: subprocess.Popen[Any]) -> None:
    """优雅停止 vLLM 服务；超时后强制结束。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=30)


def eval_command(script: str, preset: str, port: int, args: argparse.Namespace) -> list[str]:
    """构造 vLLM-only 单轮或多轮评测命令。"""
    cmd = [
        args.python,
        str(SCRIPT_DIR / script),
        "--api-base",
        f"http://{args.host}:{port}/v1",
        "--api-key",
        "EMPTY",
        "--api-model",
        preset,
        "--model-presets",
        preset,
        "--model-root",
        str(args.model_root),
        "--start",
        str(args.start),
        "--max-new-tokens",
        str(args.max_new_tokens),
        "--temperature",
        str(args.temperature),
        "--top-p",
        str(args.top_p),
        "--repetition-penalty",
        str(args.repetition_penalty),
        "--request-timeout",
        str(args.request_timeout),
    ]
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    if args.overwrite:
        cmd.append("--overwrite")
    return cmd


def run_eval_step(name: str, cmd: list[str], log_path: Path) -> None:
    """运行一个评测脚本，并把输出写入日志。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[eval-start] {name} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=log_file, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed, returncode={result.returncode}, log={log_path}")
    print(f"[eval-done] {name}", flush=True)


def run_one_job(preset: str, gpus: list[int], port: int, args: argparse.Namespace, run_id: str) -> JobResult:
    """启动一个 vLLM 服务，跑完指定模型的评测，然后关闭服务。"""
    server_log = args.server_log_dir / f"{run_id}_{preset}_server.log"
    proc: subprocess.Popen[Any] | None = None
    try:
        proc = start_vllm_server(preset, gpus, port, args, server_log)
        wait_for_vllm(
            args.host,
            port,
            proc,
            startup_timeout_for_preset(preset, args),
            args.poll_interval,
            server_log,
            args.startup_stall_timeout,
        )
        print(f"[vllm-ready] {preset} port={port}", flush=True)

        if args.tasks in ("single", "both"):
            single_log = args.eval_log_dir / f"{run_id}_{preset}_single.log"
            run_eval_step(f"{preset} single", eval_command("eval_single_turn.py", preset, port, args), single_log)
        if args.tasks in ("multi", "both"):
            multi_log = args.eval_log_dir / f"{run_id}_{preset}_multi.log"
            run_eval_step(f"{preset} multi", eval_command("eval_multi_turn.py", preset, port, args), multi_log)
        return JobResult(preset=preset, success=True, message="ok")
    except Exception as exc:
        return JobResult(preset=preset, success=False, message=f"{type(exc).__name__}: {exc}")
    finally:
        if proc is not None:
            terminate_process(proc)
            print(f"[vllm-stop] {preset}", flush=True)


def print_plan(presets: list[str], free_gpus: list[int], args: argparse.Namespace) -> None:
    """打印本次调度计划。"""
    print("===== vLLM auto schedule plan =====")
    print(f"tasks={args.tasks}")
    print(f"model_root={args.model_root}")
    print("execution_mode=eager_vllm")
    print("download_policy=prepare_before_start")
    print(f"large_model_policy={'concurrent' if args.allow_concurrent_large else 'exclusive'}")
    print(f"startup_stall_timeout={args.startup_stall_timeout}s")
    print(f"free_gpus={','.join(map(str, free_gpus)) or '<none>'}")
    for preset in presets:
        meta = base.MODEL_PRESETS[preset]
        print(
            f"- {preset}: params={meta.get('params_b')}B "
            f"need_gpus={required_gpus_for_preset(preset, args)} "
            f"wait_timeout={startup_timeout_for_preset(preset, args)}s "
            f"source={model_source_for_preset(preset, args)}"
        )


def main() -> int:
    """程序入口。"""
    args = parse_args()
    groups = args.model_groups if (args.model_groups or args.model_presets) else ["main"]
    presets = base.parse_presets(args.model_presets, groups)
    free_gpus = available_gpu_indices(args)
    print_plan(presets, free_gpus, args)

    if args.dry_run:
        return 0
    if not free_gpus:
        raise SystemExit("没有满足阈值的空闲 GPU；可以调大 --gpu-used-threshold-mib 或指定 --include-gpus。")
    too_large = [preset for preset in presets if required_gpus_for_preset(preset, args) > len(free_gpus)]
    if too_large and not args.skip_too_large:
        detail = ", ".join(f"{preset}(need={required_gpus_for_preset(preset, args)})" for preset in too_large)
        raise SystemExit(
            f"当前空闲 GPU 数量为 {len(free_gpus)}，以下模型默认资源不足：{detail}。\n"
            "可选做法：释放更多 GPU；或加 --large-model-gpus 1 强制单卡试跑；或加 --skip-too-large 跳过。"
        )
    if too_large and args.skip_too_large:
        presets = [preset for preset in presets if preset not in set(too_large)]
        print(f"[skip-too-large] {','.join(too_large)}", flush=True)

    completed_results: list[JobResult] = []
    if not args.overwrite:
        completed = [preset for preset in presets if model_outputs_done(preset, args)]
        if completed:
            print(f"[skip-completed] {','.join(completed)}", flush=True)
            completed_results = [JobResult(preset=preset, success=True, message="already done") for preset in completed]
            presets = [preset for preset in presets if preset not in set(completed)]
    if not presets:
        print("===== vLLM schedule done =====")
        for result in sorted(completed_results, key=lambda item: item.preset):
            print(f"{result.preset}: ok {result.message}")
        return 0

    presets, preparation_results = prepare_models(presets, args)
    if not presets:
        print("===== vLLM schedule done =====")
        for result in sorted(completed_results + preparation_results, key=lambda item: item.preset):
            status = "ok" if result.success else "failed"
            print(f"{result.preset}: {status} {result.message}")
        return 0 if all(result.success for result in completed_results + preparation_results) else 1

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    gpu_lock = threading.Lock()
    result_lock = threading.Lock()
    available = list(free_gpus)
    pending = list(enumerate(presets))
    running: list[tuple[threading.Thread, str]] = []
    results: list[JobResult] = completed_results + preparation_results

    def launch(preset: str, gpus: list[int], port: int) -> None:
        result = run_one_job(preset, gpus, port, args, run_id)
        with result_lock:
            results.append(result)
        with gpu_lock:
            available.extend(gpus)
            available.sort()

    while pending or running:
        running = [(thread, preset) for thread, preset in running if thread.is_alive()]
        scheduled_any = False
        with gpu_lock:
            large_running = any(is_large_model(preset, args) for _, preset in running)
            for item in list(pending):
                job_index, preset = item
                need = required_gpus_for_preset(preset, args)
                large_job = is_large_model(preset, args)
                if not args.allow_concurrent_large and (large_running or (large_job and running)):
                    continue
                if len(available) < need:
                    continue
                gpus = available[:need]
                del available[:need]
                pending.remove(item)
                port = args.base_port + job_index
                thread = threading.Thread(target=launch, args=(preset, gpus, port), daemon=False)
                thread.start()
                running.append((thread, preset))
                scheduled_any = True
                if large_job:
                    break
        if not scheduled_any:
            time.sleep(args.poll_interval)

    print("===== vLLM schedule done =====")
    for result in sorted(results, key=lambda item: item.preset):
        status = "ok" if result.success else "failed"
        print(f"{result.preset}: {status} {result.message}")
    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
