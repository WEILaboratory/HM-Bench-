#!/usr/bin/env python3
"""运行本任务：单轮重评分，并行执行多轮重测评后重评分。"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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

import eval_multi_turn as multi_eval
import eval_single_turn as model_catalog


DEFAULT_SINGLE_INPUT_DIR = PROJECT_ROOT / "results" / "model_outputs" / "single"
DEFAULT_MULTI_INPUT_DIR = PROJECT_ROOT / "results" / "model_outputs" / "multi"


@dataclass(frozen=True)
class GPUInfo:
    index: int
    used_mib: int
    total_mib: int

    @property
    def free_mib(self) -> int:
        return self.total_mib - self.used_mib


@dataclass(frozen=True)
class ModelResult:
    preset: str
    success: bool
    message: str


@dataclass(frozen=True)
class StageResult:
    name: str
    returncode: int
    log_path: Path

    @property
    def success(self) -> bool:
        return self.returncode == 0


class ProcessRegistry:
    """集中记录评分、评测和 vLLM 进程，确保中断时不会遗留服务。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[Any]] = {}

    def add(self, name: str, process: subprocess.Popen[Any]) -> None:
        with self._lock:
            self._processes[name] = process

    def remove(self, name: str) -> None:
        with self._lock:
            self._processes.pop(name, None)

    def terminate_all(self) -> None:
        with self._lock:
            processes = list(self._processes.items())
        for name, process in processes:
            if process.poll() is None:
                print(f"[stop] {name} pid={process.pid}", flush=True)
                terminate_process_group(process, timeout=10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="并行运行单轮重新评分，以及多轮重新测评→多轮重新评分。"
    )
    models = parser.add_mutually_exclusive_group()
    models.add_argument("--model-groups", nargs="+", default=["main"], help="默认 main，即全部 13 个模型。")
    models.add_argument("--model-presets", nargs="+", help="只运行指定模型。")
    parser.add_argument("--model-root", type=Path, default=Path(os.environ.get("MODEL_ROOT", "/data/jinxiang")))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--vllm-command", default=os.environ.get("VLLM_COMMAND", "vllm"))
    parser.add_argument("--vllm-log-level", default=os.environ.get("VLLM_LOGGING_LEVEL", "WARNING"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--base-port", type=int, default=8100)
    parser.add_argument("--include-gpus", help="只使用这些 GPU，例如 0,1,2,3。")
    parser.add_argument("--exclude-gpus", help="排除这些 GPU，例如 4,5。")
    parser.add_argument("--gpu-used-threshold-mib", type=int, default=2048)
    parser.add_argument("--small-model-gpus", type=int, default=1)
    parser.add_argument("--large-model-gpus", type=int, default=2)
    parser.add_argument("--large-model-threshold-b", type=float, default=30.0)
    parser.add_argument("--disable-concurrent-large", action="store_true", help="大模型运行时独占全部调度。")
    parser.add_argument("--skip-too-large", action="store_true", help="GPU 数量不足时跳过放不下的模型。")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    parser.add_argument("--startup-timeout", type=int, default=900)
    parser.add_argument("--startup-stall-timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--hf-endpoint", default=os.environ.get("HF_ENDPOINT"))

    parser.add_argument("--single-input-glob", default="*_start0_limitall.jsonl")
    parser.add_argument("--judge-model", default=None, help="留空时由 JUDGE_MODEL 或评分脚本默认值决定。")
    parser.add_argument("--judge-base-url", default=None, help="留空时读取 JUDGE_API_BASE/PACKY_BASE_URL。")
    parser.add_argument("--judge-timeout", type=float, default=180.0)
    parser.add_argument("--judge-max-retries", type=int, default=3)
    parser.add_argument("--judge-max-tokens", type=int, default=32)
    parser.add_argument("--judge-sleep", type=float, default=0.2)
    parser.add_argument("--resume", action="store_true", help="断点续跑；默认覆盖多轮输出和两类评分。")
    parser.add_argument("--log-dir", type=Path, help="本次运行日志目录。")
    parser.add_argument("--dry-run", action="store_true", help="只检查并打印计划，不启动进程。")
    args = parser.parse_args()

    positive = {
        "small-model-gpus": args.small_model_gpus,
        "large-model-gpus": args.large_model_gpus,
        "max-model-len": args.max_model_len,
        "max-new-tokens": args.max_new_tokens,
        "startup-timeout": args.startup_timeout,
        "startup-stall-timeout": args.startup_stall_timeout,
        "judge-max-retries": args.judge_max_retries,
        "judge-max-tokens": args.judge_max_tokens,
    }
    for name, value in positive.items():
        if value < 1:
            parser.error(f"{name} 必须大于 0。")
    if not 0 < args.gpu_memory_utilization <= 1:
        parser.error("gpu-memory-utilization 必须位于 (0, 1]。")
    if args.poll_interval <= 0 or args.request_timeout <= 0 or args.judge_timeout <= 0:
        parser.error("轮询和请求超时必须大于 0。")
    if args.judge_sleep < 0:
        parser.error("judge-sleep 不能为负数。")
    if not args.dry_run and not (os.environ.get("JUDGE_API_KEY") or os.environ.get("PACKY_API_KEY")):
        parser.error("评分需要设置 JUDGE_API_KEY 或 PACKY_API_KEY。")
    return args


def parse_gpu_list(text: str | None) -> set[int] | None:
    if not text:
        return None
    try:
        return {int(item.strip()) for item in text.split(",") if item.strip()}
    except ValueError as exc:
        raise SystemExit(f"GPU 列表格式错误：{text}") from exc


def query_gpus() -> list[GPUInfo]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as exc:
        raise RuntimeError(f"无法读取 nvidia-smi：{exc}") from exc
    gpus: list[GPUInfo] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3:
            gpus.append(GPUInfo(int(parts[0]), int(parts[1]), int(parts[2])))
    if not gpus:
        raise RuntimeError("nvidia-smi 没有返回 GPU。")
    return gpus


def available_gpus(args: argparse.Namespace) -> list[int]:
    include = parse_gpu_list(args.include_gpus)
    exclude = parse_gpu_list(args.exclude_gpus) or set()
    candidates = [
        gpu
        for gpu in query_gpus()
        if (include is None or gpu.index in include)
        and gpu.index not in exclude
        and gpu.used_mib <= args.gpu_used_threshold_mib
    ]
    candidates.sort(key=lambda gpu: (-gpu.free_mib, gpu.index))
    return [gpu.index for gpu in candidates]


def is_large(preset: str, args: argparse.Namespace) -> bool:
    return float(model_catalog.MODEL_PRESETS[preset].get("params_b") or 0) >= args.large_model_threshold_b


def required_gpus(preset: str, args: argparse.Namespace) -> int:
    return args.large_model_gpus if is_large(preset, args) else args.small_model_gpus


def expected_weight_files(local_dir: Path) -> list[str]:
    for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        index_path = local_dir / name
        if not index_path.is_file():
            continue
        try:
            weight_map = json.loads(index_path.read_text(encoding="utf-8")).get("weight_map")
        except json.JSONDecodeError:
            return []
        if isinstance(weight_map, dict):
            return sorted({str(value) for value in weight_map.values()})
    return []


def has_local_model(preset: str, args: argparse.Namespace) -> bool:
    meta = model_catalog.MODEL_PRESETS[preset]
    local_dir = model_catalog.model_dir(args.model_root, str(meta["model_id"]))
    if not local_dir.is_dir() or not (local_dir / "config.json").is_file():
        return False
    tokenizer_names = ("tokenizer.json", "tokenizer.model", "spiece.model", "vocab.json", "tiktoken.model")
    if not any((local_dir / name).is_file() for name in tokenizer_names) and not any(local_dir.glob("*.tiktoken")):
        return False
    expected = expected_weight_files(local_dir)
    if expected:
        return all((local_dir / name).is_file() and (local_dir / name).stat().st_size > 0 for name in expected)
    return any(
        path.is_file() and path.stat().st_size > 0
        for pattern in ("*.safetensors", "pytorch_model*.bin", "*.bin")
        for path in local_dir.glob(pattern)
    )


def model_source(preset: str, args: argparse.Namespace) -> str:
    meta = model_catalog.MODEL_PRESETS[preset]
    local_dir = model_catalog.model_dir(args.model_root, str(meta["model_id"]))
    return str(local_dir) if has_local_model(preset, args) else str(meta["model_id"])


def prepare_models(presets: list[str], args: argparse.Namespace) -> tuple[list[str], list[ModelResult]]:
    """在启动 GPU 服务前把缺失模型完整下载到 model-root。"""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint

    ready: list[str] = []
    failures: list[ModelResult] = []
    for preset in presets:
        if has_local_model(preset, args):
            print(f"[model-ready] {preset} source={model_source(preset, args)}", flush=True)
            ready.append(preset)
            continue
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError("缺少 huggingface_hub，请先安装 scripts/requirements.txt。") from exc

        meta = model_catalog.MODEL_PRESETS[preset]
        local_dir = model_catalog.model_dir(args.model_root, str(meta["model_id"]))
        local_dir.mkdir(parents=True, exist_ok=True)
        print(f"[download-start] {preset} repo={meta['model_id']} local={local_dir}", flush=True)
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
                print(f"[download-retry] {preset} attempt={attempt}/3 error={exc}", flush=True)
                if attempt < 3:
                    time.sleep(30 * attempt)
        if last_error is not None or not has_local_model(preset, args):
            message = f"模型下载失败或文件不完整：{last_error or local_dir}"
            print(f"[download-failed] {preset} {message}", flush=True)
            failures.append(ModelResult(preset, False, message))
            continue
        print(f"[download-done] {preset} local={local_dir}", flush=True)
        ready.append(preset)
    return ready, failures


def startup_timeout(preset: str, args: argparse.Namespace) -> int:
    if is_large(preset, args):
        return max(args.startup_timeout, 7200)
    if not has_local_model(preset, args):
        return max(args.startup_timeout, 3600)
    return args.startup_timeout


def terminate_process_group(process: subprocess.Popen[Any], timeout: int = 30) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=timeout)


def wait_for_server(
    process: subprocess.Popen[Any],
    host: str,
    port: int,
    timeout: int,
    poll_interval: float,
    log_path: Path,
    stall_timeout: int,
) -> None:
    url = f"http://{host}:{port}/v1/models"
    deadline = time.time() + timeout
    last_size = -1
    last_change = time.time()
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM 提前退出，returncode={process.returncode}")
        if log_path.exists():
            size = log_path.stat().st_size
            if size != last_size:
                last_size = size
                last_change = time.time()
            elif size > 0 and time.time() - last_change > stall_timeout:
                raise TimeoutError(f"vLLM 日志 {stall_timeout}s 没有增长：{log_path}")
        try:
            request = Request(url, headers={"Authorization": "Bearer EMPTY"})
            with urlopen(request, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(poll_interval)
    raise TimeoutError(f"等待 vLLM 超时：{url}")


def start_vllm(
    preset: str,
    gpus: list[int],
    port: int,
    args: argparse.Namespace,
    log_path: Path,
    registry: ProcessRegistry,
) -> subprocess.Popen[Any]:
    meta = model_catalog.MODEL_PRESETS[preset]
    command = [
        args.vllm_command,
        "serve",
        model_source(preset, args),
        "--served-model-name", preset,
        "--host", args.host,
        "--port", str(port),
        "--dtype", args.dtype,
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--generation-config", "vllm",
        "--max-num-seqs", "1",
        "--max-num-batched-tokens", str(args.max_model_len),
        "--enforce-eager",
    ]
    if len(gpus) > 1:
        command.extend([
            "--tensor-parallel-size", str(len(gpus)),
            "--distributed-executor-backend", "mp",
            "--disable-custom-all-reduce",
        ])
    if meta.get("trust_remote_code"):
        command.append("--trust-remote-code")

    env = os.environ.copy()
    env.update({
        "CUDA_VISIBLE_DEVICES": ",".join(str(gpu) for gpu in gpus),
        "VLLM_LOGGING_LEVEL": args.vllm_log_level,
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
        "VLLM_MLA_DISABLE": "1",
        "VLLM_USE_DEEP_GEMM": "0",
        "VLLM_MOE_USE_DEEP_GEMM": "0",
        "OMP_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HUB_DISABLE_XET": "1",
    })
    if len(gpus) > 1:
        env.update({
            "NCCL_P2P_DISABLE": "1",
            "NCCL_IB_DISABLE": "1",
            "NCCL_ASYNC_ERROR_HANDLING": "1",
            "TORCH_NCCL_BLOCKING_WAIT": "1",
        })
    if args.hf_endpoint:
        env["HF_ENDPOINT"] = args.hf_endpoint

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    log_handle.write("$ " + shlex.join(command) + "\n\n")
    log_handle.flush()
    print(f"[vllm-start] {preset} gpus={gpus} port={port} log={log_path}", flush=True)
    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    registry.add(f"vllm:{preset}", process)
    return process


def multi_output_path(preset: str) -> Path:
    return DEFAULT_MULTI_INPUT_DIR / f"{preset}_multiturn_start0_limitall.jsonl"


def multi_output_complete(preset: str) -> bool:
    _, samples = multi_eval.load_dataset(multi_eval.DEFAULT_DATASET, 0, 0)
    return len(multi_eval.completed_sample_ids(multi_output_path(preset))) >= len(samples)


def evaluation_command(preset: str, port: int, args: argparse.Namespace) -> list[str]:
    command = [
        args.python,
        str(SCRIPT_DIR / "eval_multi_turn.py"),
        "--api-base", f"http://{args.host}:{port}/v1",
        "--api-key", "EMPTY",
        "--api-model", preset,
        "--model-presets", preset,
        "--model-root", str(args.model_root),
        "--max-new-tokens", str(args.max_new_tokens),
        "--temperature", str(args.temperature),
        "--top-p", str(args.top_p),
        "--repetition-penalty", str(args.repetition_penalty),
        "--request-timeout", str(args.request_timeout),
    ]
    if not args.resume:
        command.append("--overwrite")
    return command


def run_evaluation(
    preset: str,
    port: int,
    args: argparse.Namespace,
    log_path: Path,
    registry: ProcessRegistry,
) -> None:
    command = evaluation_command(preset, port, args)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[eval-start] {preset} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + shlex.join(command) + "\n\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        registry.add(f"eval:{preset}", process)
        try:
            returncode = process.wait()
        finally:
            registry.remove(f"eval:{preset}")
    if returncode != 0:
        raise RuntimeError(f"多轮测评失败，returncode={returncode}，log={log_path}")
    if not multi_output_complete(preset):
        raise RuntimeError(f"多轮测评退出但结果不完整：{multi_output_path(preset)}")
    print(f"[eval-done] {preset}", flush=True)


def run_model(
    preset: str,
    gpus: list[int],
    port: int,
    args: argparse.Namespace,
    run_id: str,
    log_dir: Path,
    registry: ProcessRegistry,
) -> ModelResult:
    server_log = log_dir / f"{run_id}_{preset}_server.log"
    eval_log = log_dir / f"{run_id}_{preset}_multi.log"
    process: subprocess.Popen[Any] | None = None
    try:
        process = start_vllm(preset, gpus, port, args, server_log, registry)
        wait_for_server(
            process,
            args.host,
            port,
            startup_timeout(preset, args),
            args.poll_interval,
            server_log,
            args.startup_stall_timeout,
        )
        print(f"[vllm-ready] {preset}", flush=True)
        run_evaluation(preset, port, args, eval_log, registry)
        return ModelResult(preset, True, "ok")
    except Exception as exc:
        return ModelResult(preset, False, f"{type(exc).__name__}: {exc}")
    finally:
        if process is not None:
            terminate_process_group(process)
            registry.remove(f"vllm:{preset}")
            print(f"[vllm-stop] {preset}", flush=True)


def run_multi_evaluation(
    presets: list[str],
    args: argparse.Namespace,
    log_dir: Path,
    registry: ProcessRegistry,
) -> tuple[bool, list[str]]:
    free_gpus = available_gpus(args)
    if not free_gpus:
        print("[multi-eval-failed] 没有满足阈值的空闲 GPU。", flush=True)
        return False, []

    completed: list[str] = []
    if args.resume:
        completed = [preset for preset in presets if multi_output_complete(preset)]
        if completed:
            print(f"[skip-completed] {','.join(completed)}", flush=True)
    pending_presets = [preset for preset in presets if preset not in set(completed)]
    too_large = [preset for preset in pending_presets if required_gpus(preset, args) > len(free_gpus)]
    if too_large and not args.skip_too_large:
        print(f"[multi-eval-failed] GPU 数量不足：{','.join(too_large)}", flush=True)
        return False, completed
    if too_large:
        print(f"[skip-too-large] {','.join(too_large)}", flush=True)
        pending_presets = [preset for preset in pending_presets if preset not in set(too_large)]

    if not pending_presets:
        return bool(completed), completed

    pending_presets, preparation_failures = prepare_models(pending_presets, args)
    if not pending_presets:
        return False, completed

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    gpu_lock = threading.Lock()
    result_lock = threading.Lock()
    available = list(free_gpus)
    pending = list(enumerate(pending_presets))
    running: list[tuple[threading.Thread, str]] = []
    results: list[ModelResult] = []

    def launch(preset: str, gpus: list[int], port: int) -> None:
        result = run_model(preset, gpus, port, args, run_id, log_dir, registry)
        with result_lock:
            results.append(result)
        with gpu_lock:
            available.extend(gpus)
            available.sort()

    while pending or running:
        running = [(thread, preset) for thread, preset in running if thread.is_alive()]
        scheduled = False
        with gpu_lock:
            large_running = any(is_large(preset, args) for _, preset in running)
            for item in list(pending):
                index, preset = item
                need = required_gpus(preset, args)
                large_job = is_large(preset, args)
                if args.disable_concurrent_large and (large_running or (large_job and running)):
                    continue
                if len(available) < need:
                    continue
                gpus = available[:need]
                del available[:need]
                pending.remove(item)
                thread = threading.Thread(
                    target=launch,
                    args=(preset, gpus, args.base_port + index),
                    daemon=False,
                )
                thread.start()
                running.append((thread, preset))
                scheduled = True
                if args.disable_concurrent_large and large_job:
                    break
        if not scheduled:
            time.sleep(args.poll_interval)

    for result in sorted(results, key=lambda item: item.preset):
        print(f"[model-{'done' if result.success else 'failed'}] {result.preset} {result.message}", flush=True)
    succeeded = completed + [result.preset for result in results if result.success]
    return not preparation_failures and all(result.success for result in results), succeeded


def append_option(command: list[str], flag: str, value: object | None) -> None:
    if value is not None and str(value) != "":
        command.extend([flag, str(value)])


def scoring_command(args: argparse.Namespace, task: str, input_files: list[Path] | None = None) -> list[str]:
    is_single = task == "single"
    command = [
        args.python,
        str(SCRIPT_DIR / ("score_single_turn.py" if is_single else "score_multi_turn.py")),
        "--timeout", str(args.judge_timeout),
        "--max-retries", str(args.judge_max_retries),
        "--judge-max-tokens", str(args.judge_max_tokens),
        "--sleep", str(args.judge_sleep),
    ]
    if input_files:
        command.extend(str(path) for path in input_files)
    elif is_single:
        command.extend([
            "--input-dir", str(DEFAULT_SINGLE_INPUT_DIR),
            "--input-glob", args.single_input_glob,
        ])
    append_option(command, "--judge-model", args.judge_model)
    append_option(command, "--base-url", args.judge_base_url)
    if not args.resume:
        command.append("--overwrite")
    return command


def run_scoring_stage(
    name: str,
    command: list[str],
    log_path: Path,
    registry: ProcessRegistry,
) -> StageResult:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[start] {name} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + shlex.join(command) + "\n\n")
        log.flush()
        try:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            log.write(f"启动失败：{type(exc).__name__}: {exc}\n")
            return StageResult(name, 127, log_path)
        registry.add(name, process)
        try:
            returncode = process.wait()
        finally:
            registry.remove(name)
    print(f"[{'done' if returncode == 0 else 'failed'}] {name} exit={returncode} log={log_path}", flush=True)
    return StageResult(name, returncode, log_path)


def require_single_inputs(args: argparse.Namespace) -> None:
    pattern = str(DEFAULT_SINGLE_INPUT_DIR / args.single_input_glob)
    if not any(Path(path).is_file() for path in glob.glob(pattern)):
        raise SystemExit(f"没有找到单轮待评分文件：{pattern}")


def print_dry_run(presets: list[str], args: argparse.Namespace, log_dir: Path) -> None:
    print("===== risk refresh dry-run =====")
    print("workflow: single_score || (multi_eval -> multi_score)")
    print(f"mode={'resume' if args.resume else 'overwrite'}")
    print(f"log_dir={log_dir}")
    print(f"gpus={args.include_gpus or '<auto>'}")
    print("single_score:", shlex.join(scoring_command(args, "single")))
    print("multi_eval:")
    for index, preset in enumerate(presets):
        print(
            f"- {preset}: need_gpus={required_gpus(preset, args)} port={args.base_port + index} "
            f"source={model_source(preset, args)}"
        )
    print("multi_score:", shlex.join(scoring_command(args, "multi", [multi_output_path(p) for p in presets])))


def main() -> int:
    args = parse_args()
    presets = model_catalog.parse_presets(
        args.model_presets,
        [] if args.model_presets else args.model_groups,
    )
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = args.log_dir or PROJECT_ROOT / "logs" / "risk_refresh" / run_id
    if args.dry_run:
        print_dry_run(presets, args, log_dir)
        return 0

    require_single_inputs(args)
    log_dir.mkdir(parents=True, exist_ok=True)
    registry = ProcessRegistry()

    def single_branch() -> StageResult:
        return run_scoring_stage(
            "single_score",
            scoring_command(args, "single"),
            log_dir / "single_score.log",
            registry,
        )

    def multi_branch() -> tuple[StageResult, StageResult | None]:
        try:
            success, succeeded_presets = run_multi_evaluation(
                presets,
                args,
                log_dir / "multi_eval",
                registry,
            )
        except Exception as exc:
            print(f"[multi-eval-failed] {type(exc).__name__}: {exc}", flush=True)
            return StageResult("multi_eval", 1, log_dir / "multi_eval"), None
        evaluation = StageResult("multi_eval", 0 if success else 1, log_dir / "multi_eval")
        if not evaluation.success:
            print("[blocked] multi_score 未启动，因为 multi_eval 失败。", flush=True)
            return evaluation, None
        outputs = [multi_output_path(preset) for preset in succeeded_presets]
        missing = [path for path in outputs if not path.is_file()]
        if not outputs or missing:
            print(f"[blocked] multi_score 缺少结果：{','.join(path.name for path in missing)}", flush=True)
            return evaluation, StageResult("multi_score", 1, log_dir / "multi_eval")
        scoring = run_scoring_stage(
            "multi_score",
            scoring_command(args, "multi", outputs),
            log_dir / "multi_score.log",
            registry,
        )
        return evaluation, scoring

    print("===== risk refresh =====", flush=True)
    print("workflow=single_score || (multi_eval -> multi_score)", flush=True)
    print(f"models={','.join(presets)} mode={'resume' if args.resume else 'overwrite'} log_dir={log_dir}", flush=True)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        single_future = pool.submit(single_branch)
        multi_future = pool.submit(multi_branch)
        single_result = single_future.result()
        multi_eval_result, multi_score_result = multi_future.result()
    except KeyboardInterrupt:
        print("\n[interrupt] 正在停止所有子进程……", flush=True)
        registry.terminate_all()
        pool.shutdown(wait=True, cancel_futures=True)
        return 130
    pool.shutdown(wait=True)

    print("===== summary =====", flush=True)
    print(f"single_score: {'ok' if single_result.success else 'failed'} log={single_result.log_path}")
    print(f"multi_eval: {'ok' if multi_eval_result.success else 'failed'} log={multi_eval_result.log_path}")
    if multi_score_result is None:
        print("multi_score: blocked by multi_eval")
    else:
        print(f"multi_score: {'ok' if multi_score_result.success else 'failed'} log={multi_score_result.log_path}")
    return 0 if single_result.success and multi_score_result is not None and multi_score_result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
