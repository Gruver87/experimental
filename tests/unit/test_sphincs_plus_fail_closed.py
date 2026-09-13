import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.http import RESTHandler, ThreadedHTTPServer, configure_rate_limiter
from crypto.sphincs_plus import SPHINCSPLUS, QuantumWallet
from features.postquantum import PostQuantumManager
from runtime.config import Config
from storage.database import Database


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _post(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


@pytest.fixture
def sphincs_server(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "sphincs.db")
    cfg.http_port = _free_port()
    cfg.rate_limit_rpm = 0
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    RESTHandler.config = cfg
    RESTHandler.db = db
    RESTHandler.blockchain = None
    RESTHandler.mempool = None
    RESTHandler.sphincs = SPHINCSPLUS()
    RESTHandler.pq_manager = PostQuantumManager()
    configure_rate_limiter(cfg)
    server = ThreadedHTTPServer(("127.0.0.1", cfg.http_port), RESTHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        yield f"http://127.0.0.1:{cfg.http_port}"
    finally:
        server.shutdown()
        db.close()


def test_sphincs_backend_fails_closed_without_real_backend():
    sphincs = SPHINCSPLUS()
    with pytest.raises(NotImplementedError):
        sphincs.generate_keypair()
    with pytest.raises(NotImplementedError):
        sphincs.sign(b"message", b"private")
    with pytest.raises(NotImplementedError):
        sphincs.verify(b"message", b"a" * 32, b"public")


def test_quantum_wallet_does_not_create_fake_sphincs_keypair():
    with pytest.raises(NotImplementedError):
        QuantumWallet().create()


def test_sphincs_rest_keygen_and_sign_fail_closed(sphincs_server):
    status, body = _get(f"{sphincs_server}/pq/sphincs/keygen")
    assert status == 501
    assert "backend not available" in body["error"]

    status, body = _post(
        f"{sphincs_server}/pq/sphincs/sign",
        {"message": "hello", "private_key": "00" * 32},
    )
    assert status == 501
    assert "backend not available" in body["error"]


def test_sphincs_rest_verify_fails_closed_without_backend(sphincs_server):
    status, body = _post(
        f"{sphincs_server}/pq/sphincs/verify",
        {"message": "hello", "signature": "00" * 32, "public_key": "11" * 32},
    )
    assert status == 501
    assert "backend not available" in body["error"]


def test_pq_keygen_returns_backend_error_for_all_algorithms(sphincs_server):
    """Wave I: Dilithium educational hash-demo removed — all PQ keygen → 501."""
    status, body = _post(
        f"{sphincs_server}/pq/keygen",
        {"algorithm": "kyber"},
    )
    assert status == 501
    assert "Kyber key generation backend not available" in body["error"]

    status, body = _post(
        f"{sphincs_server}/pq/keygen",
        {"algorithm": "dilithium"},
    )
    assert status == 501
    assert "Dilithium" in body["error"] and "not available" in body["error"]


def test_pq_hybrid_encrypt_fails_closed_without_backend(sphincs_server):
    status, body = _post(
        f"{sphincs_server}/pq/hybrid-encrypt",
        {"message": "hello", "public_key": "00" * 32},
    )
    assert status == 501
    assert "hybrid_encrypt not available" in body["error"]
