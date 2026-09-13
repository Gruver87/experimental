"""Mempool.get_for_block: fee-ranked pool → contiguous executable nonces."""

from __future__ import annotations

from blockchain.mempool import Mempool, MempoolTransaction


def _tx(nonce: int, *, fee: float = 0.001, data: str = "") -> MempoolTransaction:
    return MempoolTransaction(
        tx_hash=f"tx-{nonce:04d}-{data or 's'}",
        from_addr="0x" + "a1" * 20,
        to_addr="0x" + ("0" * 40 if data else "b2" * 20),
        amount=0.0 if data else 0.01,
        fee=fee,
        nonce=nonce,
        timestamp=1.0,
        data=data,
        gas=500_000 if data else 21_000,
    )


def test_get_for_block_skips_gapped_evm_nonces_until_prefix():
    mp = Mempool(max_size=1000, min_fee=0.0)
    # Equal fees: fee-only get may surface 2,5,8 before 0.
    for n in (2, 5, 0, 1, 8, 3):
        assert mp.add(_tx(n, data="6000" if n % 3 == 2 else ""))

    nonces = {("0x" + "a1" * 20): 0}

    def lookup(addr: str) -> int:
        return int(nonces.get(addr, 0))

    packed = mp.get_for_block(limit=8, nonce_lookup=lookup)
    assert [int(t.nonce) for t in packed] == [0, 1, 2, 3]


def test_get_for_block_empty_when_only_future_nonces():
    mp = Mempool(max_size=100, min_fee=0.0)
    assert mp.add(_tx(5))
    assert mp.add(_tx(6))
    packed = mp.get_for_block(limit=4, nonce_lookup=lambda _a: 0)
    assert packed == []


def test_get_for_block_respects_limit_across_senders():
    mp = Mempool(max_size=1000, min_fee=0.0)
    a = "0x" + "a1" * 20
    b = "0x" + "b2" * 20
    for n in range(5):
        t = _tx(n)
        t.from_addr = a
        t.tx_hash = f"a-{n}"
        assert mp.add(t)
    for n in range(5):
        t = _tx(n, fee=0.002)
        t.from_addr = b
        t.to_addr = "0x" + "c3" * 20
        t.tx_hash = f"b-{n}"
        assert mp.add(t)

    packed = mp.get_for_block(limit=3, nonce_lookup=lambda _a: 0)
    assert len(packed) == 3
    # Higher fee sender b preferred when both at nonce 0.
    assert all(t.from_addr == b for t in packed)
    assert [int(t.nonce) for t in packed] == [0, 1, 2]
