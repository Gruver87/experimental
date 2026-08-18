"""NFT marketplace port (ADR 0016 Profile C — app staging).

Industrial L1 must not call Rocks NFT helpers from transport without this port.
Balance/fee mutations belong on the same apply / Storage UoW path as L1 txs;
``NullNftMarketplacePort`` is the fail-closed default when FEATURE_NFT is off.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from runtime.amount import money_abs


@runtime_checkable
class NftMarketplacePort(Protocol):
    """Port for NFT marketplace operations (staging / app profile)."""

    def mint(
        self,
        creator: str,
        name: str,
        description: str = "",
        image_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Mint a token; fee debit must be UoW-safe on the bound store."""
        ...

    def list_for_sale(self, token_id: str, owner: str, price: float) -> Dict[str, Any]:
        ...

    def buy(self, token_id: str, buyer: str) -> Dict[str, Any]:
        """Purchase; ABS transfers must not bypass tip apply when on L1 balances."""
        ...

    def get_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        ...

    def list_tokens(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        ...

    def get_stats(self) -> Dict[str, Any]:
        ...


class NullNftMarketplacePort:
    """Fail-closed NFT port when the sprout is disabled (prod mesh)."""

    def mint(
        self,
        creator: str,
        name: str,
        description: str = "",
        image_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {"ok": False, "error": "nft_disabled", "adr": "0016"}

    def list_for_sale(self, token_id: str, owner: str, price: float) -> Dict[str, Any]:
        return {"ok": False, "error": "nft_disabled", "adr": "0016"}

    def buy(self, token_id: str, buyer: str) -> Dict[str, Any]:
        return {"ok": False, "error": "nft_disabled", "adr": "0016"}

    def get_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        return None

    def list_tokens(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        return []

    def get_stats(self) -> Dict[str, Any]:
        return {"enabled": False, "tier": "app-profile", "adr": "0016"}


class NftMarketplaceAdapter:
    """Adapt legacy ``NFTMarketplace`` to ``NftMarketplacePort``."""

    def __init__(self, marketplace: Any) -> None:
        if marketplace is None:
            raise ValueError("marketplace is required")
        self._m = marketplace

    def mint(
        self,
        creator: str,
        name: str,
        description: str = "",
        image_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        fn = getattr(self._m, "mint", None) or getattr(self._m, "create_nft", None)
        if not callable(fn):
            return {"ok": False, "error": "mint_unsupported"}
        try:
            result = fn(
                creator=creator,
                name=name,
                description=description,
                image_url=image_url,
                metadata=metadata or {},
            )
        except TypeError:
            result = fn(creator, name, description, image_url, metadata or {})
        if isinstance(result, dict):
            return result
        return {"ok": True, "token": getattr(result, "to_dict", lambda: result)()}

    def list_for_sale(self, token_id: str, owner: str, price: float) -> Dict[str, Any]:
        fn = getattr(self._m, "list_for_sale", None) or getattr(self._m, "sell", None)
        if not callable(fn):
            return {"ok": False, "error": "list_unsupported"}
        result = fn(token_id, owner, money_abs(price, field="price"))
        return result if isinstance(result, dict) else {"ok": True, "result": result}

    def buy(self, token_id: str, buyer: str) -> Dict[str, Any]:
        fn = getattr(self._m, "buy", None) or getattr(self._m, "purchase", None)
        if not callable(fn):
            return {"ok": False, "error": "buy_unsupported"}
        result = fn(token_id, buyer)
        return result if isinstance(result, dict) else {"ok": True, "result": result}

    def get_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        fn = getattr(self._m, "get_token", None)
        if not callable(fn):
            tok = getattr(self._m, "tokens", {}).get(token_id)
            if tok is None:
                return None
            return tok.to_dict() if hasattr(tok, "to_dict") else dict(tok)
        result = fn(token_id)
        if result is None:
            return None
        return result if isinstance(result, dict) else result.to_dict()

    def list_tokens(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        fn = getattr(self._m, "list_tokens", None) or getattr(self._m, "get_tokens", None)
        if callable(fn):
            raw = fn(owner) if owner is not None else fn()
        else:
            raw = list(getattr(self._m, "tokens", {}).values())
        out: List[Dict[str, Any]] = []
        for item in raw or []:
            if hasattr(item, "to_dict"):
                d = item.to_dict()
            elif isinstance(item, dict):
                d = item
            else:
                continue
            if owner and d.get("owner") != owner:
                continue
            out.append(d)
        return out

    def get_stats(self) -> Dict[str, Any]:
        fn = getattr(self._m, "get_stats", None)
        if callable(fn):
            stats = fn()
            if isinstance(stats, dict):
                stats = dict(stats)
                stats.setdefault("enabled", True)
                stats.setdefault("tier", "app-profile")
                stats.setdefault("adr", "0016")
                return stats
        return {
            "enabled": True,
            "tier": "app-profile",
            "adr": "0016",
            "token_count": len(getattr(self._m, "tokens", {}) or {}),
        }
