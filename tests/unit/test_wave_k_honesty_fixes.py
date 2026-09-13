"""Wave K: P2P value satoshi, plasma signed, shard satoshi, pre-soak label, recovery auth."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_p2p_value_gates_use_satoshi():
    src = (Path(__file__).resolve().parents[2] / "network" / "p2p_node.py").read_text(
        encoding="utf-8"
    )
    assert "float(value) < 0.0" not in src
    assert "float(value) > max_value" not in src
    assert "to_satoshi(value)" in src


def test_plasma_unsigned_refused():
    from features.plasma import PlasmaChain
    from storage.database import Database
    import os
    import tempfile

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "pu.db"))
    db.initialize()
    user = "0x" + "1" * 40
    db.set_balance(user, 100.0)
    pl = PlasmaChain(chain_id="u", db=db)
    pl.deposit(user, 10.0)
    assert pl.submit_transaction(user, "0x" + "2" * 40, 1.0) is None


def test_plasma_signed_ok():
    from crypto.keys import KeyGenerator
    from features.plasma import PlasmaChain
    from storage.database import Database
    import os
    import tempfile

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ps.db"))
    db.initialize()
    user = "0x" + "1" * 40
    db.set_balance(user, 100.0)
    kp = KeyGenerator.generate_keypair()
    pl = PlasmaChain(chain_id="s", db=db)
    pl.deposit(user, 10.0)
    assert pl.submit_transaction(
        user,
        "0x" + "2" * 40,
        1.0,
        private_key=kp.private_key,
        public_key=kp.public_key.hex(),
    )


def test_pre_soak_skipmesh_not_pre_soak_pass():
    src = (
        Path(__file__).resolve().parents[2] / "scripts" / "verify_pre_soak.ps1"
    ).read_text(encoding="utf-8")
    assert "PASS static-only" in src
    assert "NOT pre-soak ready" in src


def test_recovery_unsigned_refused():
    from features.smart_accounts import SmartAccount

    a = SmartAccount("0x" + "c" * 40, "0x" + "a" * 40)
    g = "0x" + "1" * 40
    a.add_guardian(g, "g")
    a.approve_guardian(g, a.owner)
    rid = a.request_recovery(g)
    assert a.approve_recovery(rid, g) is False
