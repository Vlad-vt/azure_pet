from __future__ import annotations

import json

import pytest

from skumatch import __version__
from skumatch.config import Settings
from skumatch.logging import configure_logging, get_logger


def test_version() -> None:
    assert __version__


def test_settings_defaults_are_budget_safe() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.db_pool_size == 5
    assert s.db_max_overflow == 5
    assert s.rrf_k == 60
    assert s.embedding_dim == 384


def test_logging_redacts_sensitive_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    get_logger("t").info("match", query="MILCH 1L", vector=[0.1, 0.2], n=1)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["query"] == "[redacted]"
    assert record["vector"] == "[redacted]"
    assert record["n"] == 1
