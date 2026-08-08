#!/usr/bin/env python3
"""HARD local gate for ADR 0019 rust-libp2p (Experimental only).

Fail-closed checklist (exit 1 on first FAIL unless --keep-going):

  1) repo / honesty markers
  2) cargo fmt --check (abs_native)
  3) cargo test --features libp2p --lib
  4) cargo audit (native lockfile; uses .cargo/audit.toml)
  5) abs_native libp2p deep capability (protocols + block_peer + metrics keys)
  6) industrial freeze: prod JSON feature_libp2p=false + Config prod OFF
  7) bridge OFF audit gate
  8) pytest unit suite (libp2p + dual_stack + prod freeze)
  9) all Slice A–J labs (must print OK:/PASS)
 10) optional --rebuild (maturin + pip install)
 11) optional --evidence pack

Usage (from Experimental repo root):
  python scripts/verify_adr0019_libp2p_hard.py
  python scripts/verify_adr0019_libp2p_hard.py --keep-going
  python scripts/verify_adr0019_libp2p_hard.py --rebuild
  python scripts/verify_adr0019_libp2p_hard.py --evidence
  powershell -ExecutionPolicy Bypass -File scripts\\verify_adr0019_libp2p_hard.ps1

Honesty: PASS here ≠ tip proof ≠ prod libp2p mesh. TCP+TLS remains default.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "abs_native"

REQUIRED_METRIC_KEYS = (
    "libp2p_peers",
    "libp2p_dial_ok",
    "libp2p_dial_fail",
    "libp2p_wire_sent",
    "libp2p_wire_recv",
    "libp2p_dial_refused_budget",
    "libp2p_gossip_pub",
    "libp2p_gossip_recv",
    "libp2p_mdns_discovered",
    "libp2p_kad_peers",
    "libp2p_kad_queries",
    "libp2p_relay_reservations",
    "libp2p_relay_circuits",
    "libp2p_conn_limit_denied",
    "libp2p_block_denied",
    "libp2p_blocked_peers",
    "libp2p_identify_peers",
    "libp2p_abs_wire_v1_sent",
    "libp2p_abs_wire_v2_sent",
    "libp2p_abs_wire_v1_recv",
    "libp2p_abs_wire_v2_recv",
    "libp2p_autonat_probes",
    "libp2p_autonat_status_changes",
    "libp2p_dcutr_upgrade_success",
    "libp2p_dcutr_upgrade_fail",
    "libp2p_bootstrap_peers",
    "libp2p_bootstrap_dials_ok",
    "libp2p_bootstrap_dials_fail",
    "libp2p_bootstrap_dials_timeout",
    "libp2p_bootstrap_dials_attempted",
    "libp2p_reconnect_scheduled",
    "libp2p_reconnect_ok",
    "libp2p_reconnect_fail",
    "libp2p_reconnect_give_up",
    "libp2p_gossip_validation_accept",
    "libp2p_gossip_validation_reject",
    "libp2p_gossip_app_score_sets",
    "libp2p_gossip_not_supported",
    "libp2p_gossip_peer_score",
)

UNIT_TESTS = [
    "tests/unit/test_libp2p_adapter.py",
    "tests/unit/test_libp2p_wire_bridge.py",
    "tests/unit/test_libp2p_status_metrics.py",
    "tests/unit/test_libp2p_swarm_lab.py",
    "tests/unit/test_dual_stack.py",
    "tests/unit/test_prod_mesh_feature_freeze.py",
]

LABS = [
    ("A", "scripts/libp2p_rust_two_node_lab.py"),
    ("B", "scripts/libp2p_rust_wire_lab.py"),
    ("B", "scripts/libp2p_rust_three_node_lab.py"),
    ("C", "scripts/libp2p_rust_soak_lab.py"),
    ("D", "scripts/libp2p_mixed_dual_stack_lab.py"),
    ("E", "scripts/libp2p_rust_gossip_lab.py"),
    ("F", "scripts/libp2p_rust_identity_mdns_lab.py"),
    ("G", "scripts/libp2p_rust_kad_lab.py"),
    ("G", "scripts/libp2p_rust_abs_announce_lab.py"),
    ("H", "scripts/libp2p_rust_relay_limits_lab.py"),
    ("I", "scripts/libp2p_rust_blocklist_lab.py"),
    ("J", "scripts/libp2p_rust_status_surface_lab.py"),
    ("K", "scripts/libp2p_rust_mdns_toggle_lab.py"),
    ("L", "scripts/libp2p_rust_wire_timeout_lab.py"),
    ("M", "scripts/libp2p_rust_abs_wire_lab.py"),
    ("N", "scripts/libp2p_rust_autonat_dcutr_lab.py"),
    ("O", "scripts/libp2p_rust_bootstrap_lab.py"),
    ("P", "scripts/libp2p_rust_reconnect_lab.py"),
    ("Q", "scripts/libp2p_rust_peer_score_lab.py"),
]

PROD_JSONS = (
    "docker/node.prod.json",
    "docker/node.prod.mesh1.json",
    "docker/node.prod.mesh2.json",
    "docker/node.prod.mesh3.json",
)


def _print(text: str) -> None:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
    sys.stdout.flush()


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 300,
    env: dict[str, str] | None = None,
) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return False, float(timeout), f"TIMEOUT: {exc}"
    except OSError as exc:
        return False, 0.0, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, time.perf_counter() - t0, out


def _tail(out: str, n: int = 1200) -> str:
    out = (out or "").strip()
    return out[-n:] if len(out) > n else out


class HardGate:
    def __init__(self, *, keep_going: bool, quiet: bool) -> None:
        self.keep_going = keep_going
        self.quiet = quiet
        self.rows: list[tuple[str, bool, float, str]] = []

    def step(self, name: str, fn: Callable[[], tuple[bool, str]], *, elapsed: float = 0.0) -> bool:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"exception: {exc}"
        self.rows.append((name, ok, elapsed, detail))
        _print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        if not ok and not self.keep_going:
            return False
        return True

    def step_cmd(
        self,
        name: str,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 300,
        env: dict[str, str] | None = None,
        require_substr: str | None = None,
    ) -> bool:
        ok, elapsed, out = _run(cmd, cwd=cwd, timeout=timeout, env=env)
        detail = ""
        for ln in (out or "").splitlines()[::-1]:
            if ln.strip():
                detail = ln.strip()
                break
        if ok and require_substr and require_substr not in (out or ""):
            ok = False
            detail = f"missing required text {require_substr!r}"
        self.rows.append((name, ok, elapsed, detail))
        _print(f"[{'PASS' if ok else 'FAIL'}] {name} ({elapsed:.1f}s) {detail}")
        if not ok and not self.quiet:
            _print(_tail(out))
        if not ok and not self.keep_going:
            return False
        return True


def check_repo_honesty() -> tuple[bool, str]:
    adr = ROOT / "docs" / "adr" / "0019-rust-libp2p-industrial.md"
    if not adr.is_file():
        return False, "missing ADR 0019"
    text = adr.read_text(encoding="utf-8", errors="replace")
    need = (
        "TCP+TLS",
        "tip proof",
        "Gruver87/experimental",
        "Slice Q",
        "FEATURE_LIBP2P",
        "## Honesty",
    )
    missing = [m for m in need if m not in text]
    if "experimental" not in text.lower():
        missing.append("experimental")
    if missing:
        return False, f"ADR honesty markers missing: {missing}"
    # Refuse running from Ultimate Hybrid audit pin by path heuristic
    root_name = ROOT.name.lower()
    if "ultimate_hybrid" in root_name and "experimental" not in root_name:
        return False, f"refusing audit-pin tree: {ROOT}"
    return True, f"repo={ROOT.name}"


def check_native_deep() -> tuple[bool, str]:
    try:
        import abs_native  # type: ignore
    except Exception as exc:
        return False, f"import failed: {exc}"
    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        return False, "libp2p_available() False — rebuild with maturin --features libp2p"
    wire = str(getattr(abs_native, "ABS_WIRE_PROTOCOL", ""))
    gossip = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", ""))
    kad = str(getattr(abs_native, "ABS_KAD_PROTOCOL", ""))
    if wire != "/abs/wire/1.0.0":
        return False, f"bad ABS_WIRE_PROTOCOL={wire!r}"
    if gossip != "abs/blocks/1.0.0":
        return False, f"bad ABS_GOSSIP_BLOCKS_TOPIC={gossip!r}"
    if kad != "/absolute/kad/1.0.0":
        return False, f"bad ABS_KAD_PROTOCOL={kad!r}"

    a = abs_native.libp2p_node_new()
    b = abs_native.libp2p_node_new()
    try:
        addrs = a.listen("/ip4/127.0.0.1/tcp/0")
        if not addrs:
            return False, "listen returned empty"
        remote = b.dial(addrs[0])
        if not remote:
            return False, "dial returned empty peer id"
        time.sleep(0.25)
        m = dict(b.metrics())
        missing = [k for k in REQUIRED_METRIC_KEYS if k not in m]
        if missing:
            return False, f"metrics missing keys: {missing}"
        cap = dict(a.capability_status())
        if cap.get("default_mesh") is not False:
            return False, "capability_status.default_mesh must be False"
        if int(cap.get("phase") or 0) < 8:
            return False, f"capability phase too low: {cap.get('phase')}"
        # Slice I API must exist
        a.block_peer(b.peer_id)
        if b.peer_id not in list(a.blocked_peers()):
            return False, "block_peer did not stick"
        a.unblock_peer(b.peer_id)
        if b.peer_id in list(a.blocked_peers()):
            return False, "unblock_peer failed"
        # honesty string
        if "ADR0019" not in str(cap.get("honesty", "")):
            return False, "capability honesty marker missing"
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass
    return True, f"wire={wire} kad={kad} phase_ok metrics={len(REQUIRED_METRIC_KEYS)}"


def check_industrial_freeze() -> tuple[bool, str]:
    bad: list[str] = []
    for rel in PROD_JSONS:
        path = ROOT / rel
        if not path.is_file():
            bad.append(f"missing {rel}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if bool(data.get("feature_libp2p", False)):
            bad.append(f"{path.name}: feature_libp2p true")
        if bool(data.get("feature_long_range", False)):
            bad.append(f"{path.name}: feature_long_range true")
    # Config prod path
    env = os.environ.copy()
    env["DEPLOYMENT_MODE"] = "prod"
    env["FEATURE_LIBP2P"] = "true"
    env["FEATURE_LONG_RANGE"] = "true"
    code = (
        "from runtime.config import Config\n"
        "c=Config(); c.deployment_mode='prod'; c.apply_env()\n"
        "assert c.feature_libp2p is False\n"
        "assert c.feature_long_range is False\n"
        "print('prod_freeze_ok')\n"
    )
    ok, _, out = _run([sys.executable, "-c", code], env=env, timeout=60)
    if not ok or "prod_freeze_ok" not in out:
        bad.append("Config prod freeze failed")
    if bad:
        return False, "; ".join(bad)
    return True, "prod JSON + Config freeze OK"


def do_rebuild() -> tuple[bool, str]:
    ok, elapsed, out = _run(
        [
            "maturin",
            "build",
            "--release",
            "--features",
            "pyo3/extension-module,libp2p",
        ],
        cwd=NATIVE,
        timeout=900,
    )
    if not ok:
        return False, f"maturin failed ({elapsed:.0f}s): {_tail(out, 400)}"
    wheels = sorted(
        NATIVE.joinpath("target", "wheels").glob("abs_native-*.whl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not wheels:
        # sandbox / alternate target dir
        wheels = sorted(
            ROOT.rglob("abs_native-*.whl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not wheels:
        return False, "no wheel found after maturin build"
    whl = wheels[0]
    ok2, _, out2 = _run(
        [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(whl)],
        timeout=120,
    )
    if not ok2:
        return False, f"pip install failed: {_tail(out2, 400)}"
    return True, f"installed {whl.name}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep-going", action="store_true", help="run all steps even after FAIL")
    ap.add_argument("--rebuild", action="store_true", help="maturin build + pip install first")
    ap.add_argument("--evidence", action="store_true", help="package evidence after green path")
    ap.add_argument("--skip-cargo", action="store_true", help="skip fmt/test/audit (not hard)")
    ap.add_argument("--skip-labs", action="store_true")
    ap.add_argument("--skip-units", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    g = HardGate(keep_going=args.keep_going, quiet=args.quiet)
    _print("=== ADR 0019 HARD VERIFY (Experimental) ===")
    _print(f"root: {ROOT}")
    _print("fail-closed: any FAIL => exit 1 (unless --keep-going)")
    _print("honesty: not tip proof / not prod libp2p mesh")

    if not g.step("repo_honesty", check_repo_honesty):
        return 1

    if args.rebuild:
        if not g.step("rebuild_wheel", do_rebuild):
            return 1

    if not args.skip_cargo:
        if not g.step_cmd(
            "cargo_fmt",
            ["cargo", "fmt", "--manifest-path", str(NATIVE / "Cargo.toml"), "--all", "--", "--check"],
            timeout=120,
        ):
            return 1
        if not g.step_cmd(
            "cargo_test_libp2p",
            ["cargo", "test", "--features", "libp2p", "--lib"],
            cwd=NATIVE,
            timeout=600,
        ):
            return 1
        # audit: prefer project config; also pass known ignores for CI parity
        audit_cmd = [
            "cargo",
            "audit",
            "--file",
            str(NATIVE / "Cargo.lock"),
        ]
        if not g.step_cmd("cargo_audit", audit_cmd, timeout=180):
            # cargo-audit may be missing
            if "no such command" in (g.rows[-1][3] or "").lower() or "audit" in g.rows[-1][3]:
                _print("HINT: cargo install cargo-audit --locked")
            return 1

    if not g.step("native_libp2p_deep", check_native_deep):
        return 1

    if not g.step("industrial_freeze", check_industrial_freeze):
        return 1

    if not g.step_cmd(
        "bridge_off_gate",
        [sys.executable, str(ROOT / "scripts" / "bridge_off_audit_gate.py")],
        timeout=60,
    ):
        return 1

    if not args.skip_units:
        if not g.step_cmd(
            "unit_tests",
            [sys.executable, "-m", "pytest", "-q", *UNIT_TESTS],
            timeout=300,
        ):
            return 1

    if not args.skip_labs:
        for slice_id, rel in LABS:
            label = f"lab_{slice_id}:{Path(rel).stem}"
            ok = g.step_cmd(
                label,
                [sys.executable, str(ROOT / rel)],
                timeout=180,
                require_substr="PASS",
            )
            if not ok:
                return 1

    if args.evidence:
        # only if everything so far passed
        if all(ok for _, ok, _, _ in g.rows):
            if not g.step_cmd(
                "evidence_pack",
                [sys.executable, str(ROOT / "scripts" / "package_libp2p_evidence.py")],
                timeout=600,
            ):
                return 1
        else:
            g.rows.append(("evidence_pack", False, 0.0, "skipped: prior FAIL"))
            _print("[FAIL] evidence_pack — skipped: prior FAIL")

    passed = sum(1 for _, ok, _, _ in g.rows if ok)
    failed = sum(1 for _, ok, _, _ in g.rows if not ok)
    _print("---")
    _print(f"HARD summary: {passed} PASS, {failed} FAIL / {len(g.rows)} steps")
    if failed:
        _print("FAILED steps:")
        for name, ok, _, detail in g.rows:
            if not ok:
                _print(f"  - {name}: {detail}")
    _print("honesty: lab/R&D only — TCP+TLS remains default industrial mesh")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
