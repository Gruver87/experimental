#!/usr/bin/env python3
"""v1.3.144: native shell skips ECDSA on unsolicited MSG_MEMPOOL (solicit-armed)."""

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
from network.p2p_node import MSG_MEMPOOL, P2PNode, PeerConnection
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


def _signed_tx() -> dict:
    w = Wallet.create_new()
    return w.sign_transaction(to="0x" + ("22" * 20), value=1, nonce=0, chain_id=CHAIN)


def test_needles_v13144():
    transport = (ROOT / "native" / "abs_native" / "src" / "p2p_transport.rs").read_text(
        encoding="utf-8"
    )
    assert "mempool_solicit_armed" in transport
    assert "unsolicited_mempool" in transport
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "_mempool_solicit_armed_for" in p2p
    assert "native_mempool_solicit_armed_shell" in p2p
    notes = (ROOT / "RELEASE_NOTES_v1.3.144.md").read_text(encoding="utf-8")
    assert "1.3.144-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_solicit_armed_shell" in metrics


def _loop_once(payload: bytes, *, armed: bool, require_sigs: bool = True) -> dict:
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
                c.set_session_established(True)
                got["out"] = c.read_message_loop_events(
                    8, 65536, ["mempool", "status"], False, CHAIN, require_sigs, armed
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
def test_unarmed_mempool_strikes_without_sig_gate():
    """Large valid-looking batch must strike unsolicited_mempool (no ECDSA path)."""
    # Many signed txs — if ECDSA ran, this would be expensive; unarmed refuses first.
    batch = {"transactions": [_signed_tx() for _ in range(8)]}
    out = _loop_once(_wire("mempool", batch), armed=False)
    events = list(out.get("events") or [])
    assert any(
        e.get("action") == "strike" and e.get("reason") == "unsolicited_mempool"
        for e in events
    )
    assert not any(e.get("action") == "dispatch" for e in events)


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_armed_mempool_still_dispatches_valid_batch():
    batch = {"transactions": [_signed_tx()]}
    out = _loop_once(_wire("mempool", batch), armed=True)
    events = list(out.get("events") or [])
    assert any(e.get("action") == "dispatch" and e.get("type") == "mempool" for e in events)


def test_mempool_solicit_armed_for_waiter():
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.bootstrap_peers = []
    node = P2PNode(cfg, MagicMock(), MagicMock())

    class _W:
        def get_extra_info(self, _name, default=None):
            return ("127.0.0.1", 5001)

        def is_closing(self):
            return False

        def close(self):
            return None

        def write(self, _data):
            return None

        async def drain(self):
            return None

    class _R:
        async def read(self, _n):
            await __import__("asyncio").sleep(0)
            return b""

    peer = PeerConnection(_R(), _W())
    peer.peer_id = "peer-a"
    assert node._mempool_solicit_armed_for(peer) is False
    node._sync_waiters["peer-a"] = ((MSG_MEMPOOL,), MagicMock(), {"kind": "mempool"})
    assert node._mempool_solicit_armed_for(peer) is True
    node._sync_waiters["peer-a"] = ((MSG_MEMPOOL,), MagicMock(), {"kind": "blocks"})
    assert node._mempool_solicit_armed_for(peer) is False
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_solicit_armed_shell") is True
