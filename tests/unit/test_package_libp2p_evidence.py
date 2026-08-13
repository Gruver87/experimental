"""Evidence pack must track ADR 0019 hard-verify labs (not a truncated subset)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_PACK = ROOT / "scripts" / "package_libp2p_evidence.py"


def _load_pack():
    spec = importlib.util.spec_from_file_location("package_libp2p_evidence", _PACK)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_PACK}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_evidence_labs_are_hard_verify_list() -> None:
    pack = _load_pack()
    hard = pack.hard_verify_lab_paths()
    assert pack.LABS == hard
    assert len(pack.LABS) >= 68
    assert "scripts/libp2p_rust_ipv6_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_external_addrs_persist_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_external_addrs_atomic_persist_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_external_addrs_max_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_listen_derived_external_max_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_advertised_externals_shared_max_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_advertised_externals_all_paths_max_lab.py" in pack.LABS
    for rel in pack.LABS:
        assert (ROOT / rel).is_file(), rel
