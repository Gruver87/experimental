"""Integration tests for Lightning HTLC, Plasma Merkle, Oracle quorum, L2 crypto."""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_lightning_htlc_settle_and_refund():
    from features.lightning import LightningNetwork
    from features.l2_crypto import payment_hash
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "htlc.db"))
    db.initialize()
    alice = "0x" + "a" * 40
    bob = "0x" + "b" * 40
    db.set_balance(alice, 100.0)

    ln_a = LightningNetwork(node_address=alice, db=db)
    cid = ln_a.open_channel(bob, 20.0)
    assert cid

    preimage = "secret-route-key"
    ph = payment_hash(preimage)
    htlc_id = ln_a.add_htlc(cid, bob, 5.0, ph, expiry=int(time.time()) + 3600)
    assert htlc_id

    ln_b = LightningNetwork(node_address=bob, db=db)
    ch = ln_b.channels[cid]
    assert ch.balance1 == 15.0 - (5.0 * ch.fee_rate)

    assert ln_b.settle_htlc(htlc_id, preimage)
    assert ln_b.htlcs[htlc_id].status == "settled"
    assert ch.balance2 >= 5.0


def test_lightning_htlc_refund_after_expiry():
    from features.lightning import LightningNetwork
    from features.l2_crypto import payment_hash
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "refund.db"))
    db.initialize()
    alice = "0x" + "c" * 40
    bob = "0x" + "d" * 40
    db.set_balance(alice, 50.0)

    ln = LightningNetwork(node_address=alice, db=db)
    cid = ln.open_channel(bob, 10.0)
    ph = payment_hash("expired")
    htlc_id = ln.add_htlc(cid, bob, 2.0, ph, expiry=int(time.time()) - 1)
    assert htlc_id
    after_lock = ln.channels[cid].balance1
    assert ln.refund_htlc(htlc_id)
    assert ln.htlcs[htlc_id].status == "refunded"
    assert ln.channels[cid].balance1 == after_lock + 2.0


def test_plasma_merkle_proof_roundtrip():
    from crypto.keys import KeyGenerator
    from features.plasma import PlasmaChain
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "merkle.db"))
    db.initialize()
    user = "0x" + "1" * 40
    recipient = "0x" + "2" * 40
    db.set_balance(user, 100.0)
    kp = KeyGenerator.generate_keypair()

    pl = PlasmaChain(chain_id="merkle", db=db)
    pl.deposit(user, 30.0)
    txh = pl.submit_transaction(
        user, recipient, 7.0, private_key=kp.private_key, public_key=kp.public_key.hex()
    )
    assert txh
    blk = pl.submit_block()
    assert blk

    block_id = pl.blocks[-1].block_id
    full_hash = pl.blocks[-1].tx_hashes[0]
    proof_doc = pl.merkle_proof(block_id, full_hash)
    assert proof_doc
    assert pl.verify_inclusion(block_id, full_hash, proof_doc["proof"])


def test_oracle_quorum_median():
    from features.oracle_registry import OracleFeedRegistry
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "oracle.db"))
    db.initialize()
    reg = OracleFeedRegistry(db, secret="")

    now = int(__import__("time").time())
    for reporter, value in (("rep1", 100.0), ("rep2", 102.0), ("rep3", 101.0)):
        out = reg.submit_report(
            "btc",
            value,
            reporter,
            payload={
                "symbol": "btc",
                "value": float(value),
                "reporter": reporter,
                "ts": now,
            },
        )
        assert out.get("ok") is True, out

    agg = reg.aggregate_symbol("btc", quorum=2, max_age_sec=3600)
    assert agg is not None
    assert agg["value"] == 101.0
    assert agg["quorum"] == 3


def test_l2_state_sign_and_verify():
    from crypto.keys import KeyGenerator
    from features.l2_crypto import sign_state, verify_state

    kp = KeyGenerator.generate_keypair()
    payload = {"channel_id": "abc", "version": 1, "balance1": 10.0, "balance2": 0.0}
    sig = sign_state(payload, kp.private_key)
    assert verify_state(payload, sig, kp.public_key)
    payload["balance1"] = 9.0
    assert not verify_state(payload, sig, kp.public_key)
