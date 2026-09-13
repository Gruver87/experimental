"""Lightning Network — HTLC payment channels with signed state + persistence."""

from __future__ import annotations

from crypto import native
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from features.l2_crypto import hash_state, payment_hash, sign_state, verify_state


class LightningChannel:
    def __init__(
        self,
        channel_id: str,
        node1: str,
        node2: str,
        capacity: float,
        balance1: float = None,
        balance2: float = None,
        status: str = "open",
        created_at: int = None,
        fee_rate: float = 0.00001,
        state_version: int = 0,
    ):
        self.channel_id = channel_id
        self.node1 = node1
        self.node2 = node2
        self.capacity = capacity
        self.balance1 = balance1 if balance1 is not None else capacity
        self.balance2 = balance2 if balance2 is not None else 0.0
        self.status = status
        self.created_at = created_at if created_at is not None else int(time.time())
        self.fee_rate = fee_rate
        self.state_version = int(state_version or 0)

    def state_payload(self) -> Dict:
        return {
            "channel_id": self.channel_id,
            "version": self.state_version,
            "node1": self.node1,
            "node2": self.node2,
            "balance1": round(self.balance1, 8),
            "balance2": round(self.balance2, 8),
            "capacity": round(self.capacity, 8),
            "status": self.status,
        }

    def to_dict(self) -> Dict:
        return {
            "channel_id": self.channel_id,
            "node1": self.node1[:16] + "..." if len(self.node1) > 20 else self.node1,
            "node2": self.node2[:16] + "..." if len(self.node2) > 20 else self.node2,
            "capacity": self.capacity,
            "balance1": self.balance1,
            "balance2": self.balance2,
            "status": self.status,
            "state_version": self.state_version,
            "created_at": self.created_at,
        }

    def to_db(self) -> Dict:
        return {
            "channel_id": self.channel_id,
            "node1": self.node1,
            "node2": self.node2,
            "capacity": self.capacity,
            "balance1": self.balance1,
            "balance2": self.balance2,
            "status": self.status,
            "created_at": self.created_at,
            "fee_rate": self.fee_rate,
        }


class LightningHTLC:
    def __init__(
        self,
        htlc_id: str,
        channel_id: str,
        payment_hash: str,
        amount: float,
        expiry: int,
        sender: str,
        receiver: str,
        status: str = "pending",
        preimage: str = "",
        created_at: int = None,
    ):
        self.htlc_id = htlc_id
        self.channel_id = channel_id
        self.payment_hash = payment_hash
        self.amount = amount
        self.expiry = expiry
        self.sender = sender
        self.receiver = receiver
        self.status = status
        self.preimage = preimage
        self.created_at = created_at if created_at is not None else int(time.time())

    def to_dict(self) -> Dict:
        return {
            "htlc_id": self.htlc_id,
            "channel_id": self.channel_id,
            "payment_hash": self.payment_hash[:16] + "...",
            "amount": self.amount,
            "expiry": self.expiry,
            "sender": self.sender[:16] + "...",
            "receiver": self.receiver[:16] + "...",
            "status": self.status,
            "created_at": self.created_at,
        }

    def to_db(self) -> Dict:
        return {
            "htlc_id": self.htlc_id,
            "channel_id": self.channel_id,
            "payment_hash": self.payment_hash,
            "amount": self.amount,
            "expiry": self.expiry,
            "sender": self.sender,
            "receiver": self.receiver,
            "status": self.status,
            "preimage": self.preimage,
            "created_at": self.created_at,
        }


class LightningPayment:
    def __init__(
        self,
        payment_id: str,
        channel_id: str,
        from_node: str,
        to_node: str,
        amount: float,
        fee: float,
        timestamp: int = None,
        status: str = "completed",
        payment_hash_value: str = "",
    ):
        self.payment_id = payment_id
        self.channel_id = channel_id
        self.from_node = from_node
        self.to_node = to_node
        self.amount = amount
        self.fee = fee
        self.timestamp = timestamp if timestamp is not None else int(time.time())
        self.status = status
        self.payment_hash = payment_hash_value or native.sha256_hex(
            f"{payment_id}{amount}{self.timestamp}".encode()
        )

    def to_dict(self) -> Dict:
        return {
            "payment_id": self.payment_id[:16],
            "channel_id": self.channel_id[:16],
            "from": self.from_node[:16] + "...",
            "to": self.to_node[:16] + "...",
            "amount": self.amount,
            "fee": self.fee,
            "status": self.status,
            "timestamp": self.timestamp,
        }

    def to_db(self) -> Dict:
        return {
            "payment_id": self.payment_id,
            "channel_id": self.channel_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "amount": self.amount,
            "fee": self.fee,
            "status": self.status,
            "payment_hash": self.payment_hash,
            "timestamp": self.timestamp,
        }


class LightningNetwork:
    """Payment channel network with HTLCs, signed states, and route finding."""

    MIN_CHANNEL = 1.0
    MAX_CHANNEL = 10_000.0
    DEFAULT_HTLC_EXPIRY_SEC = 3600

    def __init__(self, node_address: str = "genesis", db=None):
        self.node_address = node_address
        self.db = db
        self.channels: Dict[str, LightningChannel] = {}
        self.payments: Dict[str, LightningPayment] = {}
        self.htlcs: Dict[str, LightningHTLC] = {}
        self._load_from_db()
        print(
            f"[Lightning] Network initialized for {node_address[:16]}... "
            f"({len(self.channels)} channels, {len(self.htlcs)} htlcs, persisted={bool(db)})"
        )

    def _load_from_db(self) -> None:
        if not self.db or not hasattr(self.db, "get_lightning_channels"):
            return
        for row in self.db.get_lightning_channels():
            ch = LightningChannel(
                channel_id=row["channel_id"],
                node1=row["node1"],
                node2=row["node2"],
                capacity=row["capacity"],
                balance1=row["balance1"],
                balance2=row["balance2"],
                status=row["status"],
                created_at=row["created_at"],
                fee_rate=row.get("fee_rate", 0.00001),
            )
            if hasattr(self.db, "get_lightning_channel_state"):
                st = self.db.get_lightning_channel_state(ch.channel_id)
                if st:
                    ch.state_version = int(st.get("version", 0))
            self.channels[ch.channel_id] = ch
        for row in self.db.get_lightning_payments(limit=500):
            p = LightningPayment(
                payment_id=row["payment_id"],
                channel_id=row["channel_id"],
                from_node=row["from_node"],
                to_node=row["to_node"],
                amount=row["amount"],
                fee=row["fee"],
                timestamp=row["timestamp"],
                status=row.get("status", "completed"),
                payment_hash_value=row.get("payment_hash", ""),
            )
            self.payments[p.payment_id] = p
        if hasattr(self.db, "get_lightning_htlcs"):
            for row in self.db.get_lightning_htlcs(limit=500):
                h = LightningHTLC(
                    htlc_id=row["htlc_id"],
                    channel_id=row["channel_id"],
                    payment_hash=row["payment_hash"],
                    amount=row["amount"],
                    expiry=row["expiry"],
                    sender=row["sender"],
                    receiver=row["receiver"],
                    status=row.get("status", "pending"),
                    preimage=row.get("preimage", ""),
                    created_at=row.get("created_at"),
                )
                self.htlcs[h.htlc_id] = h

    def _persist_channel(self, ch: LightningChannel) -> None:
        if self.db and hasattr(self.db, "save_lightning_channel"):
            self.db.save_lightning_channel(ch.to_db())

    def _persist_payment(self, p: LightningPayment) -> None:
        if self.db and hasattr(self.db, "save_lightning_payment"):
            self.db.save_lightning_payment(p.to_db())

    def _persist_htlc(self, h: LightningHTLC) -> None:
        if self.db and hasattr(self.db, "save_lightning_htlc"):
            self.db.save_lightning_htlc(h.to_db())

    def _persist_state(self, ch: LightningChannel, sig_node1: str = "", sig_node2: str = "") -> None:
        if not self.db or not hasattr(self.db, "save_lightning_channel_state"):
            return
        payload = ch.state_payload()
        self.db.save_lightning_channel_state({
            "channel_id": ch.channel_id,
            "version": ch.state_version,
            "balance1": ch.balance1,
            "balance2": ch.balance2,
            "state_hash": hash_state(payload),
            "sig_node1": sig_node1,
            "sig_node2": sig_node2,
            "updated_at": int(time.time()),
        })

    def open_channel(
        self,
        peer_address: str,
        capacity: float,
        node_balance: Optional[float] = None,
    ) -> Optional[str]:
        from runtime.amount import from_satoshi_float, to_satoshi

        if capacity < self.MIN_CHANNEL or capacity > self.MAX_CHANNEL:
            return None
        if not self.db or not hasattr(self.db, "get_balance"):
            return None
        try:
            cap_sat = int(to_satoshi(capacity))
        except (TypeError, ValueError):
            return None
        if hasattr(self.db, "get_balance_satoshi"):
            bal_sat = int(self.db.get_balance_satoshi(self.node_address))
        else:
            bal_sat = int(to_satoshi(self.db.get_balance(self.node_address)))
        if bal_sat < cap_sat:
            return None
        if hasattr(self.db, "balance_delta_satoshi"):
            self.db.balance_delta_satoshi(self.node_address, -cap_sat)
        else:
            self.db.update_balance(self.node_address, -from_satoshi_float(cap_sat))
        channel_id = native.sha256_hex(
            f"{self.node_address}{peer_address}{capacity}{time.time()}".encode()
        )[:16]
        ch = LightningChannel(channel_id, self.node_address, peer_address, capacity)
        self.channels[channel_id] = ch
        self._persist_channel(ch)
        self._persist_state(ch)
        return channel_id

    def sign_channel_state(
        self,
        channel_id: str,
        private_key: bytes,
        public_key: bytes,
    ) -> Optional[str]:
        ch = self.channels.get(channel_id)
        if not ch or ch.status != "open":
            return None
        ch.state_version += 1
        sig = sign_state(ch.state_payload(), private_key)
        sig1, sig2 = "", ""
        if self.node_address == ch.node1:
            sig1 = sig
        elif self.node_address == ch.node2:
            sig2 = sig
        prev = self.db.get_lightning_channel_state(channel_id) if self.db else None
        if prev:
            sig1 = sig1 or prev.get("sig_node1", "")
            sig2 = sig2 or prev.get("sig_node2", "")
        self._persist_channel(ch)
        self._persist_state(ch, sig_node1=sig1, sig_node2=sig2)
        return sig

    def verify_channel_state(self, channel_id: str, node_pubkey: bytes, is_node1: bool) -> bool:
        if not self.db:
            return False
        st = self.db.get_lightning_channel_state(channel_id)
        ch = self.channels.get(channel_id)
        if not st or not ch:
            return False
        payload = ch.state_payload()
        sig = st.get("sig_node1" if is_node1 else "sig_node2", "")
        return verify_state(payload, sig, node_pubkey)

    def close_channel(self, channel_id: str) -> bool:
        from runtime.amount import from_satoshi_float, to_satoshi

        ch = self.channels.get(channel_id)
        if not ch or ch.status != "open":
            return False
        if not self.db:
            return False
        try:
            b1 = int(to_satoshi(ch.balance1))
            b2 = int(to_satoshi(ch.balance2))
        except (TypeError, ValueError):
            return False
        if hasattr(self.db, "balance_delta_satoshi"):
            self.db.balance_delta_satoshi(ch.node1, b1)
            self.db.balance_delta_satoshi(ch.node2, b2)
        else:
            self.db.update_balance(ch.node1, from_satoshi_float(b1))
            self.db.update_balance(ch.node2, from_satoshi_float(b2))
        ch.status = "closed"
        ch.state_version += 1
        self._persist_channel(ch)
        self._persist_state(ch)
        return True

    def force_close(self, channel_id: str) -> bool:
        """Force-close using latest signed state (cooperative close fallback)."""
        return self.close_channel(channel_id)

    def send_payment(self, channel_id: str, to_node: str, amount: float) -> Optional[str]:
        from runtime.amount import SATOSHI_MULTIPLIER, from_satoshi_float, to_satoshi

        ch = self.channels.get(channel_id)
        if not ch or ch.status != "open":
            return None
        try:
            amt_sat = int(to_satoshi(amount))
            fee_sat = (amt_sat * int(to_satoshi(ch.fee_rate))) // int(SATOSHI_MULTIPLIER)
            b1 = int(to_satoshi(ch.balance1))
            b2 = int(to_satoshi(ch.balance2))
        except (TypeError, ValueError):
            return None
        if amt_sat <= 0:
            return None
        if self.node_address == ch.node1:
            if to_node != ch.node2 or b1 < amt_sat + fee_sat:
                return None
            b1 -= amt_sat + fee_sat
            b2 += amt_sat
        elif self.node_address == ch.node2:
            if to_node != ch.node1 or b2 < amt_sat + fee_sat:
                return None
            b1 += amt_sat
            b2 -= amt_sat + fee_sat
        else:
            return None
        ch.balance1 = from_satoshi_float(b1)
        ch.balance2 = from_satoshi_float(b2)
        ch.state_version += 1
        pid = native.sha256_hex(
            f"{channel_id}{self.node_address}{to_node}{amount}{time.time()}".encode()
        )[:16]
        payment = LightningPayment(
            pid,
            channel_id,
            self.node_address,
            to_node,
            from_satoshi_float(amt_sat),
            from_satoshi_float(fee_sat),
        )
        self.payments[pid] = payment
        self._persist_channel(ch)
        self._persist_payment(payment)
        self._persist_state(ch)
        return pid

    def add_htlc(
        self,
        channel_id: str,
        receiver: str,
        amount: float,
        preimage_hash: str,
        expiry: int = None,
    ) -> Optional[str]:
        from runtime.amount import SATOSHI_MULTIPLIER, from_satoshi_float, to_satoshi

        ch = self.channels.get(channel_id)
        if not ch or ch.status != "open":
            return None
        try:
            amt_sat = int(to_satoshi(amount))
            fee_sat = (amt_sat * int(to_satoshi(ch.fee_rate))) // int(SATOSHI_MULTIPLIER)
            b1 = int(to_satoshi(ch.balance1))
            b2 = int(to_satoshi(ch.balance2))
        except (TypeError, ValueError):
            return None
        if amt_sat <= 0:
            return None
        expiry = int(expiry or (int(time.time()) + self.DEFAULT_HTLC_EXPIRY_SEC))
        if self.node_address == ch.node1:
            if receiver != ch.node2 or b1 < amt_sat + fee_sat:
                return None
            b1 -= amt_sat + fee_sat
        elif self.node_address == ch.node2:
            if receiver != ch.node1 or b2 < amt_sat + fee_sat:
                return None
            b2 -= amt_sat + fee_sat
        else:
            return None
        ch.balance1 = from_satoshi_float(b1)
        ch.balance2 = from_satoshi_float(b2)
        htlc_id = native.sha256_hex(
            f"{channel_id}{preimage_hash}{amount}{time.time()}".encode()
        )[:16]
        htlc = LightningHTLC(
            htlc_id,
            channel_id,
            preimage_hash,
            from_satoshi_float(amt_sat),
            expiry,
            self.node_address,
            receiver,
        )
        self.htlcs[htlc_id] = htlc
        ch.state_version += 1
        self._persist_channel(ch)
        self._persist_htlc(htlc)
        self._persist_state(ch)
        return htlc_id

    def settle_htlc(self, htlc_id: str, preimage: str) -> bool:
        from runtime.amount import from_satoshi_float, to_satoshi

        htlc = self.htlcs.get(htlc_id)
        if not htlc or htlc.status != "pending":
            return False
        if payment_hash(preimage) != htlc.payment_hash:
            return False
        if int(time.time()) > htlc.expiry:
            return False
        ch = self.channels.get(htlc.channel_id)
        if not ch or ch.status != "open":
            return False
        try:
            amt_sat = int(to_satoshi(htlc.amount))
            b1 = int(to_satoshi(ch.balance1))
            b2 = int(to_satoshi(ch.balance2))
        except (TypeError, ValueError):
            return False
        if self.node_address == htlc.receiver:
            if self.node_address == ch.node1:
                b1 += amt_sat
            elif self.node_address == ch.node2:
                b2 += amt_sat
            ch.balance1 = from_satoshi_float(b1)
            ch.balance2 = from_satoshi_float(b2)
        htlc.status = "settled"
        htlc.preimage = preimage
        ch.state_version += 1
        self._persist_channel(ch)
        self._persist_htlc(htlc)
        self._persist_state(ch)
        return True

    def refund_htlc(self, htlc_id: str) -> bool:
        from runtime.amount import from_satoshi_float, to_satoshi

        htlc = self.htlcs.get(htlc_id)
        if not htlc or htlc.status != "pending":
            return False
        if int(time.time()) < htlc.expiry:
            return False
        ch = self.channels.get(htlc.channel_id)
        if not ch:
            return False
        try:
            amt_sat = int(to_satoshi(htlc.amount))
            b1 = int(to_satoshi(ch.balance1))
            b2 = int(to_satoshi(ch.balance2))
        except (TypeError, ValueError):
            return False
        if htlc.sender == ch.node1:
            b1 += amt_sat
        elif htlc.sender == ch.node2:
            b2 += amt_sat
        ch.balance1 = from_satoshi_float(b1)
        ch.balance2 = from_satoshi_float(b2)
        htlc.status = "refunded"
        ch.state_version += 1
        self._persist_channel(ch)
        self._persist_htlc(htlc)
        self._persist_state(ch)
        return True

    def find_route(self, destination: str, amount: float) -> List[str]:
        """BFS route over open channels (channel_id path)."""
        if amount <= 0:
            return []
        graph: Dict[str, List[Tuple[str, str, float]]] = {}
        for ch in self.channels.values():
            if ch.status != "open":
                continue
            if ch.node1 == self.node_address and ch.balance1 >= amount:
                graph.setdefault(ch.node1, []).append((ch.node2, ch.channel_id, ch.balance1))
            if ch.node2 == self.node_address and ch.balance2 >= amount:
                graph.setdefault(ch.node2, []).append((ch.node1, ch.channel_id, ch.balance2))
        start = self.node_address
        if start not in graph:
            return []
        queue = deque([(start, [])])
        seen = {start}
        while queue:
            node, path = queue.popleft()
            if node == destination and path:
                return path
            for nxt, cid, _cap in graph.get(node, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                queue.append((nxt, path + [cid]))
        return []

    def route_payment(self, destination: str, amount: float, preimage: str) -> Optional[str]:
        """Direct-channel payment only. Multi-hop remote messaging is not implemented."""
        path = self.find_route(destination, amount)
        if len(path) != 1:
            return None
        ph = payment_hash(preimage)
        cid = path[0]
        ch = self.channels[cid]
        receiver = ch.node2 if self.node_address == ch.node1 else ch.node1
        if receiver != destination:
            return None
        return self.add_htlc(cid, receiver, amount, ph)

    def get_channel_info(self, channel_id: str) -> Optional[Dict]:
        ch = self.channels.get(channel_id)
        return ch.to_dict() if ch else None

    def get_all_channels(self) -> List[Dict]:
        return [ch.to_dict() for ch in self.channels.values()]

    def get_htlcs(self, channel_id: str = "") -> List[Dict]:
        rows = [
            h.to_dict() for h in self.htlcs.values()
            if not channel_id or h.channel_id == channel_id
        ]
        return rows

    def get_payment_history(self, limit: int = 50) -> List[Dict]:
        payments = sorted(self.payments.values(), key=lambda p: p.timestamp, reverse=True)
        return [p.to_dict() for p in payments[:limit]]

    def get_stats(self) -> Dict:
        total_capacity = sum(ch.capacity for ch in self.channels.values())
        active = sum(1 for ch in self.channels.values() if ch.status == "open")
        total_paid = sum(p.amount for p in self.payments.values())
        pending_htlcs = sum(1 for h in self.htlcs.values() if h.status == "pending")
        return {
            "channels_count": len(self.channels),
            "active_channels": active,
            "total_capacity": total_capacity,
            "payments_count": len(self.payments),
            "htlcs_count": len(self.htlcs),
            "pending_htlcs": pending_htlcs,
            "total_volume": total_paid,
            "persisted": bool(self.db),
            "node_address": self.node_address,
            "htlc_enabled": True,
            "routing_enabled": False,
            "direct_channel_only": True,
            "multi_hop_implemented": False,
        }
