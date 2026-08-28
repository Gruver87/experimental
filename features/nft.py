#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NFT Marketplace — встроен в Absolute Blockchain.
Перенесён из nft_core.py и расширен поддержкой БД и EventBus.
"""

import json
import time
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from crypto import native


@dataclass
class NFTToken:
    token_id: str
    name: str
    description: str
    image_url: str
    owner: str
    creator: str
    price: float = 0.0
    for_sale: bool = False
    created_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "token_id": self.token_id,
            "name": self.name,
            "description": self.description,
            "image_url": self.image_url,
            "owner": self.owner,
            "creator": self.creator,
            "price": self.price,
            "for_sale": self.for_sale,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class NFTMarketplace:
    """
    NFT маркетплейс, интегрированный с балансами блокчейна.
    При покупке/продаже ABS-балансы обновляются через db.
    """

    MINT_FEE = 1.0   # стоимость создания NFT в ABS
    ROYALTY = 0.05   # 5% роялти создателю при каждой продаже

    def __init__(self, db=None, bus=None):
        self.db = db
        self.bus = bus
        self.tokens: Dict[str, NFTToken] = {}
        self.offers: Dict[str, Dict] = {}
        self.auctions: Dict[str, Dict] = {}
        self.sales_history: List[Dict] = []
        self.lock = threading.RLock()
        self._load_from_db()
        if not self.tokens:
            self._load_genesis_collection()
            self._persist_all()
        print(f"[NFT] Marketplace initialized ({len(self.tokens)} tokens, "
              f"persisted={bool(self.db and hasattr(self.db, 'get_nft_tokens'))})")

    def _token_from_dict(self, d: Dict) -> NFTToken:
        return NFTToken(
            token_id=d["token_id"],
            name=d.get("name", ""),
            description=d.get("description", ""),
            image_url=d.get("image_url", ""),
            owner=d.get("owner", ""),
            creator=d.get("creator", ""),
            price=float(d.get("price", 0)),
            for_sale=bool(d.get("for_sale")),
            created_at=float(d.get("created_at", time.time())),
            metadata=d.get("metadata") or {},
        )

    def _load_from_db(self) -> None:
        if not self.db or not hasattr(self.db, "get_nft_tokens"):
            return
        for row in self.db.get_nft_tokens():
            self.tokens[row["token_id"]] = self._token_from_dict(row)
        if hasattr(self.db, "get_nft_offers"):
            for o in self.db.get_nft_offers():
                oid = o.get("offer_id")
                if oid:
                    self.offers[oid] = o
        if hasattr(self.db, "get_nft_auctions"):
            for a in self.db.get_nft_auctions():
                aid = a.get("auction_id")
                if aid:
                    self.auctions[aid] = a
        if hasattr(self.db, "get_nft_sales"):
            self.sales_history = self.db.get_nft_sales(limit=500)

    def _persist_token(self, token_id: str) -> None:
        if not self.db or not hasattr(self.db, "save_nft_token"):
            return
        t = self.tokens.get(token_id)
        if t:
            self.db.save_nft_token(t.to_dict())

    def _persist_offer(self, offer_id: str) -> None:
        if not self.db or not hasattr(self.db, "save_nft_offer"):
            return
        o = self.offers.get(offer_id)
        if o:
            self.db.save_nft_offer(o)

    def _persist_auction(self, auction_id: str) -> None:
        if not self.db or not hasattr(self.db, "save_nft_auction"):
            return
        a = self.auctions.get(auction_id)
        if a:
            self.db.save_nft_auction(a)

    def _record_sale(self, sale: Dict) -> None:
        self.sales_history.append(sale)
        if self.db and hasattr(self.db, "save_nft_sale"):
            self.db.save_nft_sale(sale)

    def _persist_all(self) -> None:
        for tid in list(self.tokens.keys()):
            self._persist_token(tid)
        for oid in list(self.offers.keys()):
            self._persist_offer(oid)
        for aid in list(self.auctions.keys()):
            self._persist_auction(aid)

    def _has_balance_backend(self) -> bool:
        return bool(
            self.db
            and hasattr(self.db, "get_balance")
            and hasattr(self.db, "update_balance")
        )

    def _has_atomic_uow(self) -> bool:
        """True when store exposes ``atomic()`` (ADR 0016 NFT UoW path)."""
        return bool(self.db and callable(getattr(self.db, "atomic", None)))

    def _uow(self):
        """Storage unit-of-work for balance + NFT persist; null if unavailable."""
        if self._has_atomic_uow():
            return self.db.atomic()
        from contextlib import nullcontext

        return nullcontext()

    def _balance(self, addr: str) -> float:
        if not self._has_balance_backend():
            return 0.0
        return float(self.db.get_balance(addr))

    def _debit(self, addr: str, amount: float) -> bool:
        if amount <= 0 or not self._has_balance_backend():
            return False
        if self._balance(addr) < amount:
            return False
        self.db.update_balance(addr, -amount)
        return True

    def _credit(self, addr: str, amount: float) -> bool:
        if amount <= 0 or not self._has_balance_backend():
            return False
        self.db.update_balance(addr, amount)
        return True

    def _settle_sale(self, buyer: str, seller: str, creator: str, price: float) -> bool:
        if price <= 0 or not self._has_balance_backend():
            return False
        if self._balance(buyer) < price:
            return False
        royalty = price * self.ROYALTY
        seller_amount = price - royalty
        self.db.update_balance(buyer, -price)
        self.db.update_balance(seller, seller_amount)
        if creator != seller and royalty > 0:
            self.db.update_balance(creator, royalty)
        return True

    def _load_genesis_collection(self):
        """Начальная коллекция Genesis."""
        genesis = [
            ("abs_genesis_crown",    "Absolute Crown",    "The ultimate crown of the Absolute Kingdom", "crown",    100.0),
            ("abs_quantum_guardian", "Quantum Guardian",  "Guardian of the quantum realm",              "guardian", 200.0),
            ("abs_genesis_block",    "Genesis Block",     "The very first block of Absolute chain",     "block",    500.0),
            ("abs_elemental_master", "Elemental Master",  "Master of all four elements",                "master",   300.0),
            ("abs_wisdom_relic",     "Wisdom Relic",      "Ancient artifact of wisdom",                 "relic",    150.0),
        ]
        for tid, name, desc, img, price in genesis:
            self._mint_internal(tid, name, desc, img, "0xgenesis", price)

    def _mint_internal(self, token_id, name, description, image_url, creator, price):
        if token_id not in self.tokens:
            self.tokens[token_id] = NFTToken(
                token_id=token_id, name=name, description=description,
                image_url=image_url, owner=creator, creator=creator,
                price=price, for_sale=(price > 0),
            )

    # ── Создание NFT ─────────────────────────────────────────────────────────

    def mint(self, token_id: str, name: str, description: str,
             image_url: str, creator: str, price: float = 0.0) -> Dict:
        """Создать новый NFT. Списывает MINT_FEE с создателя (atomic UoW when available)."""
        with self.lock:
            if token_id in self.tokens:
                return {"success": False, "error": "token_id already exists"}

            try:
                with self._uow():
                    if not self._debit(creator, self.MINT_FEE):
                        return {
                            "success": False,
                            "error": f"Need {self.MINT_FEE} ABS to mint",
                        }

                    self.tokens[token_id] = NFTToken(
                        token_id=token_id, name=name, description=description,
                        image_url=image_url, owner=creator, creator=creator,
                        price=price, for_sale=(price > 0),
                    )
                    self._persist_token(token_id)
            except Exception as exc:
                self.tokens.pop(token_id, None)
                return {"success": False, "error": f"nft_uow_failed: {exc}"}

            if self.bus:
                self.bus.emit("nft.minted", {"token_id": token_id, "creator": creator})

            return {
                "success": True,
                "token_id": token_id,
                "uow_atomic": self._has_atomic_uow(),
            }

    # ── Торговля ─────────────────────────────────────────────────────────────

    def list_for_sale(self, token_id: str, owner: str, price: float) -> Dict:
        with self.lock:
            if price <= 0:
                return {"success": False, "error": "price must be > 0"}
            if token_id not in self.tokens:
                return {"success": False, "error": "not found"}
            t = self.tokens[token_id]
            if t.owner != owner:
                return {"success": False, "error": "not owner"}
            t.price = price
            t.for_sale = True
            self._persist_token(token_id)
            return {"success": True, "token_id": token_id, "price": price}

    def buy(self, token_id: str, buyer: str) -> Dict:
        """Покупка NFT. ABS переводится продавцу и создателю (роялти) в одном UoW."""
        with self.lock:
            if token_id not in self.tokens:
                return {"success": False, "error": "not found"}
            t = self.tokens[token_id]
            if not t.for_sale:
                return {"success": False, "error": "not for sale"}
            if buyer == t.owner:
                return {"success": False, "error": "already owner"}

            price = t.price
            old_owner = t.owner
            old_for_sale = t.for_sale

            try:
                with self._uow():
                    if not self._settle_sale(buyer, t.owner, t.creator, price):
                        return {
                            "success": False,
                            "error": "insufficient balance or balance backend unavailable",
                        }

                    t.owner = buyer
                    t.for_sale = False
                    self._persist_token(token_id)
                    self._record_sale({
                        "token_id": token_id, "from": old_owner,
                        "to": buyer, "price": price,
                        "type": "buy", "timestamp": int(time.time()),
                    })
            except Exception as exc:
                t.owner = old_owner
                t.for_sale = old_for_sale
                return {"success": False, "error": f"nft_uow_failed: {exc}"}

            if self.bus:
                self.bus.emit("nft.sold", {
                    "token_id": token_id, "buyer": buyer,
                    "seller": old_owner, "price": price,
                })

            return {
                "success": True,
                "token_id": token_id,
                "buyer": buyer,
                "price": price,
                "uow_atomic": self._has_atomic_uow(),
            }

    def transfer(self, token_id: str, from_addr: str, to_addr: str) -> Dict:
        with self.lock:
            if not to_addr:
                return {"success": False, "error": "recipient required"}
            if token_id not in self.tokens:
                return {"success": False, "error": "not found"}
            t = self.tokens[token_id]
            if t.owner != from_addr:
                return {"success": False, "error": "not owner"}
            try:
                from features.council_nft import council_transfer_refuse

                refuse = council_transfer_refuse(t)
                if refuse:
                    return {"success": False, "error": refuse}
            except ImportError:
                pass
            t.owner = to_addr
            t.for_sale = False
            self._persist_token(token_id)
            return {"success": True}

    # ── Геттеры ──────────────────────────────────────────────────────────────

    def get_token(self, token_id: str) -> Optional[Dict]:
        with self.lock:
            t = self.tokens.get(token_id)
            return t.to_dict() if t else None

    def get_by_owner(self, owner: str) -> List[Dict]:
        with self.lock:
            return [t.to_dict() for t in self.tokens.values() if t.owner == owner]

    def get_on_sale(self) -> List[Dict]:
        with self.lock:
            return [t.to_dict() for t in self.tokens.values() if t.for_sale]

    def get_all(self) -> List[Dict]:
        with self.lock:
            return [t.to_dict() for t in self.tokens.values()]

    def get_stats(self) -> Dict:
        with self.lock:
            persisted = bool(self.db and hasattr(self.db, "get_nft_tokens"))
            balance_bound = self._has_balance_backend()
            return {
                "total_tokens": len(self.tokens),
                "on_sale": sum(1 for t in self.tokens.values() if t.for_sale),
                "unique_owners": len({t.owner for t in self.tokens.values()}),
                "total_value": sum(t.price for t in self.tokens.values() if t.for_sale),
                "mint_fee": self.MINT_FEE,
                "royalty_pct": self.ROYALTY * 100,
                "total_sales": len(self.sales_history),
                "total_offers": len(self.offers),
                "active_auctions": sum(1 for a in self.auctions.values() if a.get("status") == "active"),
                "persisted": persisted,
                "balance_backend": balance_bound,
                # Balance mutations + persist share db.atomic() when available (ADR 0016).
                "execution_bound": balance_bound,
                "uow_atomic": self._has_atomic_uow(),
                "on_chain_standard": False,
                "enabled": True,
                "tier": "app-profile",
                "adr": "0016",
            }

    # ── Offers ────────────────────────────────────────────────────────────────

    def make_offer(self, token_id: str, bidder: str, price: float,
                   hours: int = 24) -> Optional[str]:
        """Create a purchase offer for any NFT (not just for-sale ones)."""
        with self.lock:
            if price <= 0:
                return None
            if token_id not in self.tokens:
                return None
            if not self._has_balance_backend() or self._balance(bidder) < price:
                return None
            offer_id = native.sha256_hex(
                f"{token_id}{bidder}{price}{time.time()}".encode()
            )[:16]
            self.offers[offer_id] = {
                "offer_id": offer_id,
                "token_id": token_id,
                "bidder": bidder,
                "price": price,
                "expires_at": int(time.time()) + hours * 3600,
                "status": "pending",
                "created_at": int(time.time()),
            }
            self._persist_offer(offer_id)
            return offer_id

    def accept_offer(self, offer_id: str, seller: str) -> Dict:
        """Accept an offer — transfer NFT to bidder."""
        with self.lock:
            offer = self.offers.get(offer_id)
            if not offer or offer["status"] != "pending":
                return {"success": False, "error": "Offer not found or expired"}
            token_id = offer["token_id"]
            t = self.tokens.get(token_id)
            if not t or t.owner != seller:
                return {"success": False, "error": "Not token owner"}
            # Transfer
            price = offer["price"]
            if not self._settle_sale(offer["bidder"], seller, t.creator, price):
                return {"success": False, "error": "Bidder has insufficient balance or balance backend unavailable"}
            old_owner = t.owner
            t.owner = offer["bidder"]
            t.for_sale = False
            self._persist_token(token_id)
            offer["status"] = "accepted"
            self._persist_offer(offer_id)
            self._record_sale({
                "token_id": token_id, "from": old_owner,
                "to": offer["bidder"], "price": price,
                "type": "offer", "timestamp": int(time.time()),
            })
            if self.bus:
                self.bus.emit("nft.offer_accepted", {"offer_id": offer_id, "token_id": token_id})
            return {"success": True, "offer_id": offer_id, "token_id": token_id, "price": price}

    def get_offers(self, token_id: str = None) -> List[Dict]:
        with self.lock:
            now = int(time.time())
            offers = [o for o in self.offers.values()
                      if (token_id is None or o["token_id"] == token_id)
                      and o["expires_at"] > now]
            return offers

    # ── Auctions ──────────────────────────────────────────────────────────────

    def create_auction(self, token_id: str, seller: str, start_price: float,
                       reserve_price: float = 0.0, hours: int = 24,
                       auction_type: str = "english") -> Optional[str]:
        """Create an English auction for an NFT."""
        with self.lock:
            if start_price <= 0 or reserve_price < 0 or hours <= 0:
                return None
            t = self.tokens.get(token_id)
            if not t or t.owner != seller:
                return None
            auction_id = native.sha256_hex(
                f"{token_id}{seller}{time.time()}".encode()
            )[:16]
            self.auctions[auction_id] = {
                "auction_id": auction_id,
                "token_id": token_id,
                "seller": seller,
                "start_price": start_price,
                "reserve_price": reserve_price,
                "current_bid": start_price,
                "current_bidder": None,
                "auction_type": auction_type,
                "ends_at": int(time.time()) + hours * 3600,
                "status": "active",
                "bids": [],
                "created_at": int(time.time()),
            }
            self._persist_auction(auction_id)
            return auction_id

    def place_bid(self, auction_id: str, bidder: str, amount: float) -> Dict:
        with self.lock:
            auction = self.auctions.get(auction_id)
            if not auction or auction["status"] != "active":
                return {"success": False, "error": "Auction not found or ended"}
            if int(time.time()) > auction["ends_at"]:
                auction["status"] = "ended"
                self._persist_auction(auction_id)
                return {"success": False, "error": "Auction has ended"}
            if amount <= auction["current_bid"]:
                return {"success": False, "error": f"Bid must be > {auction['current_bid']}"}
            if not self._has_balance_backend() or self._balance(bidder) < amount:
                return {"success": False, "error": "insufficient balance or balance backend unavailable"}
            auction["bids"].append({"bidder": bidder, "amount": amount, "ts": int(time.time())})
            auction["current_bid"] = amount
            auction["current_bidder"] = bidder
            self._persist_auction(auction_id)
            return {"success": True, "auction_id": auction_id,
                    "current_bid": amount, "bidder": bidder}

    def finalize_auction(self, auction_id: str) -> Dict:
        with self.lock:
            auction = self.auctions.get(auction_id)
            if not auction:
                return {"success": False, "error": "Auction not found"}
            if auction["status"] != "active":
                return {"success": False, "error": "Auction already finalized"}
            auction["status"] = "finalized"
            self._persist_auction(auction_id)
            winner = auction["current_bidder"]
            price = auction["current_bid"]
            if winner and price >= auction.get("reserve_price", 0):
                token_id = auction["token_id"]
                t = self.tokens.get(token_id)
                if not t:
                    auction["status"] = "settlement_failed"
                    self._persist_auction(auction_id)
                    return {"success": False, "error": "Auction token not found"}
                old_owner = t.owner
                if not self._settle_sale(winner, old_owner, t.creator, price):
                    auction["status"] = "settlement_failed"
                    self._persist_auction(auction_id)
                    return {"success": False, "error": "insufficient balance or balance backend unavailable"}
                t.owner = winner
                t.for_sale = False
                self._persist_token(token_id)
                self._record_sale({
                    "token_id": token_id, "from": old_owner, "to": winner,
                    "price": price, "type": "auction", "timestamp": int(time.time()),
                })
                return {"success": True, "auction_id": auction_id,
                        "winner": winner, "price": price}
            return {"success": True, "auction_id": auction_id,
                    "message": "Reserve price not met — no sale"}

    def get_auctions(self, active_only: bool = False) -> List[Dict]:
        with self.lock:
            auctions = list(self.auctions.values())
            if active_only:
                auctions = [a for a in auctions if a["status"] == "active"]
            return auctions

    def get_sales_history(self, token_id: str = None, limit: int = 50) -> List[Dict]:
        with self.lock:
            sales = self.sales_history
            if token_id:
                sales = [s for s in sales if s["token_id"] == token_id]
            return sales[-limit:][::-1]
