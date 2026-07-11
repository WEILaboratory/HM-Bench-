#!/usr/bin/env bash
set -eo pipefail

# 为 vLLM 评测重新配置一个干净环境。
#
# 典型用法：
#   cd /home/jinxiang/safety
#   source ~/miniconda3/etc/profile.d/conda.sh
#   bash scripts/setup_vllm_env.sh
#
# 这个脚本会删除 OLD_ENVS 里的旧 conda 环境，然后创建 ENV_NAME。
# 默认固定 CUDA 12.8 + vLLM 0.10.2，避免最新版 vLLM 拉入 CUDA 13 依赖。


# ----------------------------- 可调整参数 -----------------------------

ENV_NAME="${ENV_NAME:-vllm_eval}"
OLD_ENVS="${OLD_ENVS:-vllm_eval_clean vllm_eval_010}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
PYTORCH_CUDA_TAG="${PYTORCH_CUDA_TAG:-cu128}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/${PYTORCH_CUDA_TAG}}"

# 注意：不要直接使用名为 VLLM_VERSION 的环境变量。
# 之前的 shell 里可能残留 VLLM_VERSION=0.24.0，会把脚本带回 CUDA 13 依赖链。
# 如需手动改版本，请显式传 VLLM_PIN_VERSION=0.x.y。
VLLM_PIN_VERSION="${VLLM_PIN_VERSION:-0.10.2}"
TRANSFORMERS_PIN_VERSION="${TRANSFORMERS_PIN_VERSION:-4.56.2}"

# 注意：不要直接使用名为 CUDA_VERSION 的环境变量。
# vLLM 官方 wheel 命令常把 CUDA_VERSION=128 表示 cu128，但 conda 需要的是 12.8。
# 这里单独使用 CUDA_TOOLKIT_VERSION，避免被上一次安装命令残留的 CUDA_VERSION=128 污染。
CUDA_TOOLKIT_VERSION="${CUDA_TOOLKIT_VERSION:-12.8}"
case "${CUDA_TOOLKIT_VERSION}" in
  12.*|13.*) ;;
  128) CUDA_TOOLKIT_VERSION="12.8" ;;
  126) CUDA_TOOLKIT_VERSION="12.6" ;;
  *)
    echo "ERROR: CUDA_TOOLKIT_VERSION 应该类似 12.8 或 12.6，当前为：${CUDA_TOOLKIT_VERSION}" >&2
    exit 1
    ;;
esac


# ----------------------------- Conda 准备 -----------------------------

if ! command -v conda >/dev/null 2>&1; then
  if [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/miniconda3/etc/profile.d/conda.sh"
  else
    echo "ERROR: 没有找到 conda，请先安装或 source conda.sh。" >&2
    exit 1
  fi
fi

CONDA_BASE="$(conda info --base)"
# shellcheck source=/dev/null
source "${CONDA_BASE}/etc/profile.d/conda.sh"

# 如果用户正好在旧环境里运行脚本，先退回 base，避免删除当前环境失败。
while [[ "${CONDA_DEFAULT_ENV:-base}" != "base" && "${CONDA_SHLVL:-0}" -gt 1 ]]; do
  conda deactivate
done

echo "===== 清理旧环境 ====="
for old_env in ${OLD_ENVS}; do
  if conda env list | awk '{print $1}' | grep -qx "${old_env}"; then
    echo "[remove] ${old_env}"
    conda env remove -n "${old_env}" -y
  else
    echo "[skip] ${old_env} 不存在"
  fi
done

if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "[remove] ${ENV_NAME}"
  conda env remove -n "${ENV_NAME}" -y
fi

echo "===== 创建新环境：${ENV_NAME} ====="
conda create -n "${ENV_NAME}" "python=${PYTHON_VERSION}" -y
conda activate "${ENV_NAME}"


# ----------------------------- CUDA 工具链 -----------------------------

echo "===== 安装 CUDA ${CUDA_TOOLKIT_VERSION} 编译工具链 ====="
conda install -c nvidia \
  cuda-nvcc \
  cuda-cudart-dev \
  cuda-libraries-dev \
  "cuda-version=${CUDA_TOOLKIT_VERSION}" \
  -y

mkdir -p "${CONDA_PREFIX}/etc/conda/activate.d" "${CONDA_PREFIX}/etc/conda/deactivate.d"
cat > "${CONDA_PREFIX}/etc/conda/activate.d/youth_vllm_cuda.sh" <<EOF
export CUDA_HOME="${CONDA_PREFIX}"
export PATH="${CONDA_PREFIX}/bin:\${PATH}"
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${CONDA_PREFIX}/lib64:\${LD_LIBRARY_PATH:-}"
export HF_HUB_DISABLE_XET=1
export TOKENIZERS_PARALLELISM=false
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_MLA_DISABLE=1
export VLLM_USE_DEEP_GEMM=0
export VLLM_MOE_USE_DEEP_GEMM=0
EOF

cat > "${CONDA_PREFIX}/etc/conda/deactivate.d/youth_vllm_cuda.sh" <<'EOF'
unset CUDA_HOME
unset HF_HUB_DISABLE_XET
unset TOKENIZERS_PARALLELISM
unset VLLM_USE_FLASHINFER_SAMPLER
unset VLLM_MLA_DISABLE
unset VLLM_USE_DEEP_GEMM
unset VLLM_MOE_USE_DEEP_GEMM
EOF

# 让当前 shell 立即拿到上面的变量。
# shellcheck source=/dev/null
source "${CONDA_PREFIX}/etc/conda/activate.d/youth_vllm_cuda.sh"


# ----------------------------- Python 依赖 -----------------------------

echo "===== 安装 vLLM 和评测依赖 ====="
echo "vLLM 固定版本：${VLLM_PIN_VERSION}"
echo "Transformers 固定版本：${TRANSFORMERS_PIN_VERSION}"
echo "PyTorch CUDA wheel 源：${PYTORCH_INDEX_URL}"
python -m pip install -i "${PIP_INDEX_URL}" -U pip setuptools wheel packaging psutil ninja

# 固定 vLLM 版本，避免最新版依赖链拉入 CUDA 13 kernel 包。
# 同时固定 transformers 4.x；transformers 5.x 移除了 vLLM 0.10.2 仍会访问的 tokenizer 属性。
python -m pip install -i "${PIP_INDEX_URL}" \
  --extra-index-url "${PYTORCH_INDEX_URL}" \
  "vllm==${VLLM_PIN_VERSION}" \
  "transformers==${TRANSFORMERS_PIN_VERSION}" \
  "huggingface_hub[cli]<1.0"

python -m pip install -i "${PIP_INDEX_URL}" \
  openai \
  "huggingface_hub[cli]<1.0" \
  accelerate \
  sentencepiece \
  protobuf \
  tiktoken \
  einops \
  safetensors


# ----------------------------- 环境校验 -----------------------------

echo "===== 校验环境 ====="
EXPECTED_VLLM_VERSION="${VLLM_PIN_VERSION}" python - <<'PY'
import importlib.metadata as md
import subprocess
import sys

bad = []
for dist in md.distributions():
    name = dist.metadata["Name"].lower()
    if "cu13" in name or name in {"humming-kernels", "nvidia-cutlass-dsl"}:
        bad.append(f"{name}=={dist.version}")
if bad:
    print("ERROR: 检测到 CUDA 13 或高风险 kernel 依赖：")
    for item in sorted(bad):
        print("  " + item)
    raise SystemExit(1)

import os
import torch
import transformers
import vllm

expected_vllm = os.environ["EXPECTED_VLLM_VERSION"]
print("python:", sys.version.split()[0])
print("torch:", torch.__version__)
print("torch cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("vllm:", vllm.__version__)
print("transformers:", transformers.__version__)
if vllm.__version__ != expected_vllm:
    raise SystemExit(f"ERROR: vLLM 版本不符合预期，应为 {expected_vllm}，实际为 {vllm.__version__}")
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))

subprocess.run(["nvcc", "--version"], check=True)
if not torch.cuda.is_available():
    raise SystemExit("ERROR: PyTorch 看不到 CUDA，请检查驱动和 CUDA_VISIBLE_DEVICES。")
PY

echo "===== 校验评测脚本可导入 ====="
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"
python scripts/eval_single_turn.py --list-models >/dev/null
python scripts/eval_multi_turn.py --list-models >/dev/null
python scripts/run_vllm_all.py --dry-run --assume-gpus 0 --model-presets qwen2.5-7b-instruct --tasks single >/dev/null

echo
echo "环境配置完成：${ENV_NAME}"
echo "以后运行前使用：conda activate ${ENV_NAME}"
echo "建议先小样本测试："
echo "  MODEL_ROOT=/data/jinxiang python scripts/run_vllm_all.py --model-presets qwen2.5-7b-instruct --tasks single --limit 2 --overwrite"
