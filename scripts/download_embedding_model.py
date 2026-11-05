"""本地 Embedding 模型下载脚本（仅在有网环境执行）。

用法（在项目根目录）：
    python scripts/download_embedding_model.py
    python scripts/download_embedding_model.py --repo BAAI/bge-small-zh-v1.5
    python scripts/download_embedding_model.py --endpoint https://hf-mirror.com

已知坑（Windows）：huggingface_hub 新版默认启用 hf_xet 下载后端，在 Windows
上拉取大权重文件会报 ``xet_get ... failed with error: os error 5 拒绝访问``，
换镜像源也无效（走的仍是同一个后端）。本脚本在导入 huggingface_hub 之前
显式关闭 hf_xet 与 hf_transfer，改走普通 HTTP 下载；同时把 HF 缓存目录
固定为项目内 ``.hf-cache``，避免写入用户主目录下的系统缓存。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 必须在导入 huggingface_hub 之前设置，否则后端选择已经定型。
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ.setdefault("HF_HOME", str(PROJECT_ROOT / ".hf-cache"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from huggingface_hub import snapshot_download  # noqa: E402

DEFAULT_REPO = "BAAI/bge-small-zh-v1.5"

# 下载完成后校验的最小文件集，缺任何一个都视为下载失败。
REQUIRED_FILES = [
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "vocab.txt",
    "1_Pooling/config.json",
]

# sentence-transformers 只需 safetensors；同一份权重若连其他格式一起拉，
# 会多占一倍磁盘（bin 约 91 MB），默认跳过。
DEFAULT_IGNORE_PATTERNS = [
    "*.bin",
    "*.h5",
    "*.msgpack",
    "*.onnx",
    "openvino/*",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载本地 Embedding 模型到 models/ 目录（已规避 hf_xet 报错）"
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Hugging Face 仓库 ID")
    parser.add_argument(
        "--local-dir",
        default=None,
        help="模型保存目录，默认 models/<仓库名小写>",
    )
    parser.add_argument(
        "--with-other-weights",
        action="store_true",
        help="同时下载 bin/onnx 等其他权重格式（默认跳过，省一倍磁盘）",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="可选镜像源，例如 https://hf-mirror.com，默认直连 huggingface.co",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint.rstrip("/")

    local_dir = (
        Path(args.local_dir)
        if args.local_dir
        else PROJECT_ROOT / "models" / args.repo.split("/")[-1].lower()
    )
    if not local_dir.is_absolute():
        local_dir = PROJECT_ROOT / local_dir

    ignore = [] if args.with_other_weights else DEFAULT_IGNORE_PATTERNS
    print(f"仓库      : {args.repo}")
    print(f"下载后端  : 普通 HTTP（hf_xet 已关闭）")
    print(f"跳过格式  : {'（无，全部下载）' if not ignore else ', '.join(ignore)}")
    print(f"缓存目录  : {os.environ['HF_HOME']}")
    print(f"保存目录  : {local_dir}")

    snapshot_download(args.repo, local_dir=str(local_dir), ignore_patterns=ignore)

    missing = [name for name in REQUIRED_FILES if not (local_dir / name).is_file()]
    if missing:
        print("下载不完整，缺少: " + ", ".join(missing), file=sys.stderr)
        return 1

    size_mb = (local_dir / "model.safetensors").stat().st_size / 1024 / 1024
    print(f"完成，model.safetensors = {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
