"""Wave 42 — WASM VM SQLite persistence + bridge relayer status API."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_wasm_deploy_persists_and_charges_fee():
    from features.wasm_vm import WASMVirtualMachine
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "w.db"))
    db.initialize()
    owner = "0x" + "a" * 40
    db.set_balance(owner, 1.0)

    vm1 = WASMVirtualMachine(db=db)
    addr = vm1.deploy("fn hello() {}", owner, "TestContract")
    assert addr
    assert addr.startswith("wasm_")
    assert db.get_balance(owner) == 1.0 - vm1.DEPLOY_FEE

    vm2 = WASMVirtualMachine(db=db)
    assert addr in vm2.contracts
    assert vm2.get_stats()["persisted"] is True


def test_wasm_call_persists_storage():
    from features.wasm_vm import WASMVirtualMachine
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "c.db"))
    db.initialize()
    owner = "0x" + "b" * 40
    db.set_balance(owner, 10.0)

    vm = WASMVirtualMachine(db=db)
    addr = vm.deploy("token", owner, "Tok", {"initialSupply": 1000})
    out = vm.call(addr, "transfer", {"to": "0x" + "c" * 40, "amount": 100}, owner)
    assert out["success"] is False
    assert out.get("error") == "wasm_pseudo_token_host_refused"
    assert vm.get_stats().get("enabled") is bool(
        __import__("features.wasm_engine", fromlist=["WASMEngine"]).WASMEngine.available()
    )


def test_wasm_deploy_rejects_low_balance():
    from features.wasm_vm import WASMVirtualMachine
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "r.db"))
    db.initialize()
    owner = "0x" + "d" * 40
    db.set_balance(owner, 0.001)

    vm = WASMVirtualMachine(db=db)
    assert vm.deploy("code", owner) is None


def test_wasm_deploy_requires_balance_backend():
    from features.wasm_vm import WASMVirtualMachine

    owner = "0x" + "e" * 40
    vm = WASMVirtualMachine(db=None)
    assert vm.deploy("fn hello() {}", owner, "NoBackend") is None


def test_wasm_custom_function_fails_without_execution_backend():
    from features.wasm_vm import WASMVirtualMachine
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "custom.db"))
    db.initialize()
    owner = "0x" + "f" * 40
    db.set_balance(owner, 1.0)

    vm = WASMVirtualMachine(db=db)
    addr = vm.deploy("fn hello() {}", owner, "CustomContract")
    out = vm.call(addr, "hello", {}, owner)

    assert out["success"] is False
    assert out["error"] == "Custom WASM execution backend not available"


def test_wasm_constructor_cannot_be_called_after_deploy():
    from features.wasm_vm import WASMVirtualMachine
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ctor.db"))
    db.initialize()
    owner = "0x" + "a" * 40
    attacker = "0x" + "b" * 40
    db.set_balance(owner, 1.0)

    vm = WASMVirtualMachine(db=db)
    addr = vm.deploy("token", owner, "Token", {"initialSupply": 1000})
    out = vm.call(addr, "constructor", {"initialSupply": 999999}, attacker)

    assert out["success"] is False
    assert out["error"] == "Constructor cannot be called after deployment"
    assert vm.call(addr, "balanceOf", {"account": owner}, owner)["result"] == 1000
    assert vm.call(addr, "balanceOf", {"account": attacker}, attacker)["result"] == 0


def test_wasm_set_storage_requires_contract_owner():
    from features.wasm_vm import WASMVirtualMachine
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "storage_acl.db"))
    db.initialize()
    owner = "0x" + "a" * 40
    attacker = "0x" + "b" * 40
    db.set_balance(owner, 1.0)

    vm = WASMVirtualMachine(db=db)
    addr = vm.deploy("token", owner, "Token")

    denied = vm.call(addr, "setStorage", {"key": "admin", "value": attacker}, attacker)
    assert denied["success"] is False
    assert denied["error"] == "Only contract owner can set storage"
    assert vm.call(addr, "getStorage", {"key": "admin"}, owner)["result"] is None

    allowed = vm.call(addr, "setStorage", {"key": "admin", "value": owner}, owner)
    assert allowed["success"] is True
    assert vm.call(addr, "getStorage", {"key": "admin"}, owner)["result"] == owner


def test_bridge_relayer_status_helper():
    from api.http import _build_bridge_relayer_status
    from runtime.config import Config
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "br.db"))
    db.initialize()
    cfg = Config(db_path=db.db_path)
    st = _build_bridge_relayer_status(cfg, db)
    assert "pending_locks" in st
    assert "relayer_script" in st
    assert "require_l1_proof" in st
    assert "readiness" in st
    assert "l1_outbound" in st
