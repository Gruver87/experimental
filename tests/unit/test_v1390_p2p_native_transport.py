#!/usr/bin/env python3
"""v1.3.90: native plain-TCP P2P transport (listener + framed conn)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import abs_native

from crypto import native
from network.p2p_node import P2PNode
from runtime.config import Config


def test_needles_v1390():
    transport = (ROOT / "native" / "abs_native" / "src" / "p2p_transport.rs").read_text(
        encoding="utf-8"
    )
    assert "P2PNativeListener" in transport
    assert "P2PNativeConn" in transport
    assert "v1.3.90" in transport
    lib = (ROOT / "native" / "abs_native" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "mod p2p_transport" in lib
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "_native_accept_loop" in p2p
    assert "_handle_native_incoming" in p2p
    assert "p2p_native_transport" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_native_transport" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.90.md").read_text(encoding="utf-8")
    assert "1.3.90-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    assert hasattr(abs_native, "P2PNativeListener")
    assert hasattr(abs_native, "P2PNativeConn")
    assert hasattr(native, "p2p_native_connect")
    assert hasattr(native, "p2p_native_transport_available")


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_native_listener_accept_and_framed_read():
    listener = native.P2PNativeListener("127.0.0.1", 0, 1024 * 1024, 3000)
    addr = listener.local_addr
    host, port_s = addr.rsplit(":", 1)
    port = int(port_s)
    host = host.strip("[]")

    ready = threading.Event()

    def client():
        ready.wait(timeout=2)
        time.sleep(0.05)
        conn = native.p2p_native_connect(host, port, 1024 * 1024, 3000)
        conn.write(b'{"type":"ping","data":null}\n')
        conn.close()

    t = threading.Thread(target=client, daemon=True)
    t.start()
    ready.set()
    deadline = time.time() + 5.0
    conn = None
    while time.time() < deadline:
        out = listener.accept()
        assert out.get("ok") is True
        if out.get("conn") is not None:
            conn = out["conn"]
            break
    assert conn is not None, "accept never returned a connection"
    line_out = conn.read_line()
    assert line_out.get("ok") is True, line_out
    assert b"ping" in bytes(line_out.get("line") or b"")
    conn.close()
    listener.close()
    t.join(timeout=2)


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_native_connect_helper():
    listener = native.P2PNativeListener("127.0.0.1", 0, 1024 * 1024, 3000)
    addr = listener.local_addr
    host, port_s = addr.rsplit(":", 1)
    port = int(port_s)
    host = host.strip("[]")

    def server():
        deadline = time.time() + 5.0
        while time.time() < deadline:
            out = listener.accept()
            if out.get("ok") and out.get("conn") is not None:
                c = out["conn"]
                c.write(b'{"type":"pong","data":null}\n')
                c.close()
                return

    t = threading.Thread(target=server, daemon=True)
    t.start()
    time.sleep(0.1)
    conn = native.p2p_native_connect(host, port, 1024 * 1024, 5000)
    out = conn.read_line()
    assert out.get("ok") is True, out
    assert b"pong" in bytes(out.get("line") or b"")
    conn.close()
    listener.close()
    t.join(timeout=2)


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_p2p_node_native_transport_flag():
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_native_transport = True
    cfg.p2p_tls_enabled = False
    node = P2PNode(cfg, MagicMock(), MagicMock())
    assert node._use_native_transport is True
    status = node.get_p2p_security_status()
    assert status.get("native_p2p_transport") is True

    cfg2 = Config()
    cfg2.require_native_crypto = False
    cfg2.deployment_mode = "dev"
    cfg2.p2p_native_transport = True
    cfg2.p2p_tls_enabled = True
    node2 = P2PNode(cfg2, MagicMock(), MagicMock())
    assert node2._use_native_transport is False


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_native_capability_probe_chains_cause(monkeypatch, caplog):
    import logging
    import sys
    import types

    import abs_native

    class _Wrap(types.ModuleType):
        def __init__(self, real):
            super().__init__(real.__name__)
            self._real = real

        def __getattr__(self, name):
            if name == "P2PNativeConn":
                raise OSError("cap boom")
            return getattr(self._real, name)

    monkeypatch.setitem(sys.modules, "abs_native", _Wrap(abs_native))
    cfg = Config()
    cfg.require_native_crypto = True
    cfg.deployment_mode = "dev"
    cfg.p2p_native_transport = True
    cfg.p2p_tls_enabled = False
    with caplog.at_level(logging.WARNING, logger="P2P"):
        with pytest.raises(RuntimeError, match="native capability probe failed") as ei:
            P2PNode(cfg, MagicMock(), MagicMock())
    assert "cap boom" in caplog.text
    assert isinstance(ei.value.__cause__, OSError)
