"""Fail-closed: abs_native cargo test must link CPython, not extension-module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_HELPER = ROOT / "scripts" / "cargo_test_abs_native.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("cargo_test_abs_native", _HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_HELPER}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_helper = _load_helper()


def test_cargo_test_disables_extension_module() -> None:
    argv = _helper.cargo_test_argv(extra_features=["libp2p"], extra_args=["--lib"])
    assert "--no-default-features" in argv
    joined = " ".join(argv)
    assert "extension-module" not in joined
    feat = argv[argv.index("--features") + 1]
    assert _helper.AUTO_INIT in feat.split(",")
    assert "libp2p" in feat.split(",")
    assert argv[-1] == "--lib"


def test_cargo_test_refuses_extension_module_feature() -> None:
    with pytest.raises(_helper.CargoTestAbsNativeError, match="skips linking libpython"):
        _helper.cargo_test_argv(extra_features=["extension-module"])
