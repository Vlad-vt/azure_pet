"""CPU-only INT8 ONNX sentence embedder for ``intfloat/multilingual-e5-small``.

E5 models expect a task prefix. Invoice lines and catalog names are short, similar-length
product descriptions, so we treat matching as a *symmetric* task and prefix both sides with
``"query: "`` (as recommended by the E5 authors for semantic-similarity use cases).
Embeddings are mean-pooled over the attention mask and L2-normalised, so cosine distance
equals ``1 - dot``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import onnxruntime as ort
from tokenizers import Tokenizer

PREFIX: Final = "query: "
MAX_LENGTH: Final = 64  # product lines are short; caps CPU cost per request


class OnnxEmbedder:
    def __init__(self, model_dir: Path, *, threads: int = 0, max_length: int = MAX_LENGTH) -> None:
        model_path = model_dir / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"
        if not model_path.exists() or not tokenizer_path.exists():
            raise FileNotFoundError(f"ONNX model or tokenizer missing in {model_dir}")

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_mem_pattern = True
        opts.enable_cpu_mem_arena = False  # keeps RSS low on a 1.5 GiB container
        if threads > 0:
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}

        tok = Tokenizer.from_file(str(tokenizer_path))
        tok.enable_truncation(max_length=max_length)
        tok.enable_padding(pad_id=tok.token_to_id("<pad>") or 1, pad_token="<pad>")  # noqa: S106
        self._tokenizer = tok
        self._lock = threading.Lock()
        self.dim = int(self._session.get_outputs()[0].shape[-1] or 384)

    @classmethod
    def from_env(cls, model_dir: Path, threads: int = 0) -> OnnxEmbedder:
        env_threads = int(os.environ.get("OMP_NUM_THREADS", "0") or 0)
        return cls(model_dir, threads=threads or env_threads)

    def embed(self, texts: list[str], batch_size: int = 64) -> npt.NDArray[np.float32]:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out: list[npt.NDArray[np.float32]] = []
        for start in range(0, len(texts), batch_size):
            out.append(self._embed_batch(texts[start : start + batch_size]))
        return np.vstack(out)

    def embed_one(self, text: str) -> npt.NDArray[np.float32]:
        row: npt.NDArray[np.float32] = self._embed_batch([text])[0]
        return row

    def _embed_batch(self, texts: list[str]) -> npt.NDArray[np.float32]:
        encodings = self._tokenizer.encode_batch([PREFIX + t for t in texts])
        input_ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
        attention = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
        feeds: dict[str, npt.NDArray[np.int64]] = {
            "input_ids": input_ids,
            "attention_mask": attention,
        }
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        with self._lock:  # ORT sessions are thread-safe, the lock bounds peak memory
            hidden = self._session.run(None, feeds)[0]
        mask = attention[..., None].astype(np.float32)
        pooled = (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        result: npt.NDArray[np.float32] = (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)
        return result
