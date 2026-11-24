"""Download the INT8-quantised ONNX export of intfloat/multilingual-e5-small.

The model is baked into the Docker image at build time so cold starts never hit the network.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # plain HTTPS download, proxy-friendly

from huggingface_hub import hf_hub_download

REPO_ID = "Xenova/multilingual-e5-small"
# Pinned for reproducibility (ONNX export of intfloat/multilingual-e5-small).
REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
FILES = {
    "onnx/model_quantized.onnx": "model.onnx",
    "tokenizer.json": "tokenizer.json",
    "config.json": "config.json",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("models/multilingual-e5-small"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for remote, local in FILES.items():
        target = args.out / local
        if target.exists():
            print(f"exists: {target}")
            continue
        path = hf_hub_download(REPO_ID, remote, revision=REVISION)
        shutil.copyfile(path, target)
        print(f"downloaded: {remote} -> {target} ({target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
