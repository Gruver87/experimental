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
    assert "scripts/libp2p_rust_identify_listen_addrs_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_mdns_listen_addrs_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_kad_listen_addrs_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_autonat_listen_addrs_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_upnp_listen_addrs_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_advertised_externals_libp2p_book_max_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_dcutr_candidates_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identify_candidates_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_external_addrs_replace_no_unlink_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_atomic_persist_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_persist_parent_dir_fsync_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_key_mode_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_key_windows_dacl_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_persist_mkdir_fsync_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_create_exclusive_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_tmp_dacl_at_create_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_existing_acl_refuse_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_null_dacl_refuse_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_callback_ace_refuse_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_protected_dacl_refuse_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_persist_json_acl_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_parent_dir_refuse_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_parent_mkdir_recheck_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_identity_parent_unattested_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_persist_tmp_per_thread_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_persist_tmp_stale_tid_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_circuit_excluded_from_external_book_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_relay_client_circuit_external_book_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_behaviour_external_confirmed_capped_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_observed_external_charge_key_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_behaviour_external_expired_canonical_lab.py" in pack.LABS
    assert "scripts/libp2p_rust_persist_external_charge_key_lab.py" in pack.LABS
    for rel in pack.LABS:
        assert (ROOT / rel).is_file(), rel
