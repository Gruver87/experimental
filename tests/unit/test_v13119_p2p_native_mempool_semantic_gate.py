#!/usr/bin/env python3
"""v1.3.119: native mempool batch signature semantic gate on message-loop shell."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from crypto.wallet import Wallet
from network.p2p_node import P2PNode
from runtime.config import Config

CHAIN = 778888


def _wire(msg_type: str, data: dict) -> bytes:
    return (
        json.dumps(
            {"type": msg_type, "data": data},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _signed_tx(*, chain_id: int = CHAIN, to: str = "0x" + ("22" * 20)) -> dict:
    w = Wallet.create_new()
    return w.sign_transaction(to=to, value=1, nonce=0, chain_id=chain_id)


def test_needles_v13119():
    transport = (ROOT / "native" / "abs_native" / "src" / "p2p_transport.rs").read_text(
        encoding="utf-8"
    )
    wire = (ROOT / "native" / "abs_native" / "src" / "p2p_wire.rs").read_text(
        encoding="utf-8"
    )
    assert "check_mempool_batch_semantics" in transport
    assert "verify_mempool_batch_signatures_inner" in wire
    assert "v1.3.119" in transport
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "native_mempool_semantic_gate" in p2p
    notes = (ROOT / "RELEASE_NOTES_v1.3.119.md").read_text(encoding="utf-8")
    assert "1.3.119-industrial" in notes
    # Live Config().node_version advances with later waves; pin notes not config.
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_semantic_gate" in metrics


def _loop_once(
    payload: bytes,
    *,
    chain_id: int,
    require_sigs: bool,
    mempool_solicit_armed: bool = True,
) -> dict:
    listener = native.P2PNativeListener("127.0.0.1", 0, 1024 * 1024, 5000)
    addr = listener.local_addr
    host, port_s = addr.rsplit(":", 1)
    port = int(port_s)
    host = host.strip("[]")
    got = {}

    def server():
        deadline = time.time() + 8.0
        while time.time() < deadline:
            out = listener.accept()
            if out.get("ok") and out.get("conn") is not None:
                c = out["conn"]
                # v1.3.144 default armed=False; semantic tests arm solicit.
                got["out"] = c.read_message_loop_events(
                    8,
                    65536,
                    ["mempool", "status"],
                    False,
                    chain_id,
                    require_sigs,
                    mempool_solicit_armed,
                )
                c.close()
                return

    t = threading.Thread(target=server, daemon=True)
    t.start()
    time.sleep(0.05)
    conn = native.p2p_native_connect(host, port, 1024 * 1024, 8000)
    conn.write(payload)
    conn.close()
    t.join(timeout=5)
    return got.get("out") or {}


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_native_loop_dispatches_valid_mempool_batch():
    batch = {"transactions": [_signed_tx(), _signed_tx(to="0x" + ("33" * 20))]}
    out = _loop_once(_wire("mempool", batch), chain_id=CHAIN, require_sigs=True)
    assert out.get("ok") is True
    events = list(out.get("events") or [])
    assert any(e.get("action") == "dispatch" and e.get("type") == "mempool" for e in events)


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_native_loop_strikes_tampered_batch_tx():
    good = _signed_tx()
    bad = _signed_tx(to="0x" + ("44" * 20))
    bad["value"] = 999999
    batch = {"transactions": [good, bad]}
    out = _loop_once(_wire("mempool", batch), chain_id=CHAIN, require_sigs=True)
    events = list(out.get("events") or [])
    assert any(
        e.get("action") == "strike" and e.get("reason") == "bad_tx_signature"
        for e in events
    )


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_native_loop_strikes_missing_sig_in_batch():
    unsigned = {
        "from": "0x" + ("11" * 20),
        "to": "0x" + ("22" * 20),
        "value": 1,
        "nonce": 0,
    }
    batch = {"transactions": [unsigned]}
    out = _loop_once(_wire("mempool", batch), chain_id=CHAIN, require_sigs=True)
    events = list(out.get("events") or [])
    assert any(
        e.get("action") == "strike" and e.get("reason") == "missing_tx_signature"
        for e in events
    )


def test_status_exposes_mempool_semantic_gate():
    cfg = Config()
    cfg.p2p_native_transport = True
    cfg.p2p_tls_enabled = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.bootstrap_peers = []
    node = P2PNode(cfg, MagicMock(), MagicMock())
    node._native_message_loop_shell = True
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_semantic_gate") is True
