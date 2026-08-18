# -*- coding: utf-8 -*-
"""P2P message router for the legacy peer-manager stack.

The async runtime uses ``network.p2p_node`` directly. This handler keeps the
older ``network.p2p`` package functional for tests and small embedded nodes.
"""

from typing import Any, Dict, Optional
import logging

from .messages import Message, MessageType, create_block_request, create_block_response, create_sync_response

logger = logging.getLogger("P2P.MessageHandler")


class MessageHandler:
    def __init__(self, peer_manager, p2p_server, storage, chain, sync_manager):
        self.peer_manager = peer_manager
        self.p2p_server = p2p_server
        self.storage = storage
        self.chain = chain
        self.sync_manager = sync_manager
        self.seen_inventory = set()
        self._send_failures = 0
        self._send_unbound = 0

    def handle(self, peer_id: str, raw_message: Any) -> Optional[Dict[str, Any]]:
        """Validate and route one peer message, returning the response payload."""
        message = self._coerce_message(raw_message)
        if message is None:
            self._score(peer_id, "malicious")
            return {"type": "error", "error": "invalid_message"}

        peer = self.peer_manager.get_peer(peer_id) if self.peer_manager else None
        if peer is not None and getattr(peer, "is_banned", False):
            return {"type": "error", "error": "peer_banned"}

        if self.peer_manager and hasattr(self.peer_manager, "check_rate_limit"):
            if not self.peer_manager.check_rate_limit(peer_id, message.type.value):
                self._score(peer_id, "malicious")
                return {"type": "error", "error": "rate_limited"}

        response = self._route(peer_id, message)
        if response is not None:
            self._send(peer_id, response)
        return response

    def handle_message(self, peer_id: str, raw_message: Any) -> Optional[Dict[str, Any]]:
        """Compatibility alias used by older callers."""
        return self.handle(peer_id, raw_message)

    def _coerce_message(self, raw_message: Any) -> Optional[Message]:
        if isinstance(raw_message, Message):
            return raw_message
        if isinstance(raw_message, str):
            try:
                return Message.from_json(raw_message)
            except Exception:
                return None
        if isinstance(raw_message, dict):
            msg_type = raw_message.get("type")
            data = raw_message.get("data")
            if data is None:
                data = {k: v for k, v in raw_message.items() if k != "type"}
            try:
                return Message(MessageType(msg_type), data)
            except Exception:
                return None
        return None

    def _route(self, peer_id: str, message: Message) -> Optional[Dict[str, Any]]:
        handlers = {
            MessageType.PING: self._handle_ping,
            MessageType.PONG: self._handle_pong,
            MessageType.INV_BLOCK: self._handle_inv_block,
            MessageType.INV_TX: self._handle_inv_tx,
            MessageType.BLOCK_ANNOUNCE: self._handle_block_announce,
            MessageType.BLOCK_REQUEST: self._handle_block_request,
            MessageType.BLOCK_RESPONSE: self._handle_block_response,
            MessageType.SYNC_REQUEST: self._handle_sync_request,
            MessageType.SYNC_RESPONSE: self._handle_sync_response,
        }
        handler = handlers.get(message.type)
        if handler is None:
            self._score(peer_id, "malicious")
            return {"type": "error", "error": "unsupported_message_type"}
        return handler(peer_id, message.data)

    def _handle_ping(self, _peer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": MessageType.PONG.value, "data": {"time": data.get("time")}}

    def _handle_pong(self, _peer_id: str, _data: Dict[str, Any]) -> None:
        return None

    def _handle_inv_block(self, _peer_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block_hash = str(data.get("hash", ""))
        if not block_hash:
            return {"type": "error", "error": "missing_block_hash"}
        self.seen_inventory.add(("block", block_hash))
        if self._get_block(block_hash):
            return None
        return create_block_request(block_hash)

    def _handle_inv_tx(self, _peer_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tx_hash = str(data.get("hash", ""))
        if not tx_hash:
            return {"type": "error", "error": "missing_tx_hash"}
        self.seen_inventory.add(("tx", tx_hash))
        return None

    def _handle_block_announce(self, _peer_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block_hash = str(data.get("hash", ""))
        if not block_hash:
            return {"type": "error", "error": "missing_block_hash"}
        if self._get_block(block_hash):
            return None
        return create_block_request(block_hash)

    def _handle_block_request(self, _peer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        block_hash = str(data.get("hash", ""))
        block = self._get_block(block_hash)
        if not block:
            return {"type": "error", "error": "block_not_found", "hash": block_hash}
        return create_block_response(block)

    def _handle_block_response(self, peer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        block = data.get("block")
        if not isinstance(block, dict) or not block.get("hash"):
            self._score(peer_id, "invalid_block")
            return {"type": "error", "error": "invalid_block"}
        if self._import_block(block):
            self._score(peer_id, "valid_block")
            return {"type": "block_accepted", "hash": block.get("hash")}
        self._score(peer_id, "invalid_block")
        return {"type": "error", "error": "block_rejected", "hash": block.get("hash")}

    def _handle_sync_request(self, _peer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        from_height = int(data.get("from_height", 0) or 0)
        return create_sync_response(self._headers_from(from_height))

    def _handle_sync_response(self, _peer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = data.get("headers", [])
        if self.sync_manager and hasattr(self.sync_manager, "handle_headers"):
            self.sync_manager.handle_headers(headers)
        return {"type": "sync_headers_received", "count": len(headers)}

    def _get_block(self, block_hash: str) -> Optional[Dict[str, Any]]:
        for owner in (self.chain, self.storage):
            if not owner:
                continue
            for method in ("get_block_by_hash", "get_block"):
                if hasattr(owner, method):
                    block = getattr(owner, method)(block_hash)
                    if block:
                        return block
        return None

    def _import_block(self, block: Dict[str, Any]) -> bool:
        for owner, methods in (
            (self.chain, ("import_block", "add_block")),
            (self.storage, ("save_block",)),
        ):
            if not owner:
                continue
            for method in methods:
                if hasattr(owner, method):
                    result = getattr(owner, method)(block)
                    if result is None:
                        return True
                    if result is True or result is False:
                        return result
                    if isinstance(result, dict):
                        return result.get("success") is True
                    return False
        return False

    def _headers_from(self, from_height: int) -> list:
        if self.chain and hasattr(self.chain, "get_headers_from"):
            return list(self.chain.get_headers_from(from_height))
        if self.storage and hasattr(self.storage, "get_headers_from"):
            return list(self.storage.get_headers_from(from_height))
        headers = []
        height = from_height + 1
        while self.chain and hasattr(self.chain, "get_block"):
            block = self.chain.get_block(height)
            if not block:
                break
            headers.append({
                "hash": block.get("hash", ""),
                "height": block.get("height", block.get("number", height)),
                "parent_hash": block.get("parent_hash", block.get("parent", "")),
            })
            height += 1
            if len(headers) >= 512:
                break
        return headers

    def _send(self, peer_id: str, payload: Dict[str, Any]) -> bool:
        if not self.p2p_server:
            self._send_unbound += 1
            return False
        for method in ("send_message", "send"):
            if hasattr(self.p2p_server, method):
                try:
                    getattr(self.p2p_server, method)(peer_id, payload)
                    return True
                except Exception as exc:
                    self._send_failures += 1
                    logger.warning(
                        "[MessageHandler] %s failed peer=%s: %s",
                        method,
                        peer_id,
                        exc,
                    )
                    return False
        self._send_failures += 1
        return False

    def _score(self, peer_id: str, event: str) -> None:
        if self.peer_manager and hasattr(self.peer_manager, "update_score"):
            self.peer_manager.update_score(peer_id, event)
