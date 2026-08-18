#!/usr/bin/env python3
"""Legacy P2P message handler routes real network messages."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from network.p2p.message_handler import MessageHandler
from network.p2p.messages import InventoryMessage, Message, MessageType
from network.p2p.peer_manager import PeerManager


class _Server:
    def __init__(self):
        self.sent = []

    def send_message(self, peer_id, payload):
        self.sent.append((peer_id, payload))


class _Chain:
    def __init__(self):
        self.blocks = {
            "0x01": {"hash": "0x01", "height": 1, "parent_hash": "0x00"},
            "0x02": {"hash": "0x02", "height": 2, "parent_hash": "0x01"},
        }
        self.imported = []

    def get_block_by_hash(self, block_hash):
        return self.blocks.get(block_hash)

    def get_block(self, height):
        for block in self.blocks.values():
            if block["height"] == height:
                return block
        return None

    def import_block(self, block):
        self.imported.append(block)
        return True


def _handler():
    peers = PeerManager("node-a")
    peers.add_peer("peer-1", "127.0.0.1", 9001)
    server = _Server()
    chain = _Chain()
    return MessageHandler(peers, server, None, chain, None), peers, server, chain


def test_ping_returns_and_sends_pong():
    handler, _, server, _ = _handler()

    response = handler.handle("peer-1", Message(MessageType.PING, {"time": 123}))

    assert response == {"type": "pong", "data": {"time": 123}}
    assert server.sent == [("peer-1", response)]


def test_unknown_block_inventory_requests_block():
    handler, _, _, _ = _handler()

    response = handler.handle("peer-1", InventoryMessage.for_block("0xdead"))

    assert response == {"type": "block_request", "hash": "0xdead"}
    assert ("block", "0xdead") in handler.seen_inventory


def test_block_response_imports_and_scores_peer():
    handler, peers, _, chain = _handler()
    block = {"hash": "0x03", "height": 3, "parent_hash": "0x02"}

    response = handler.handle(
        "peer-1", {"type": "block_response", "block": block}
    )

    assert response == {"type": "block_accepted", "hash": "0x03"}
    assert chain.imported == [block]
    assert peers.get_peer("peer-1").score > 100


def test_sync_request_returns_headers_after_height():
    handler, _, _, _ = _handler()

    response = handler.handle("peer-1", {"type": "sync_request", "from_height": 1})

    assert response["type"] == "sync_response"
    assert response["headers"] == [
        {"hash": "0x02", "height": 2, "parent_hash": "0x01"}
    ]


def test_invalid_block_response_penalizes_peer():
    handler, peers, _, _ = _handler()

    response = handler.handle("peer-1", {"type": "block_response", "block": {}})

    assert response["error"] == "invalid_block"
    assert peers.get_peer("peer-1").score < 100


def test_send_failure_is_logged_and_counted(caplog):
    import logging

    class _BoomServer:
        def send_message(self, peer_id, payload):
            raise RuntimeError("send boom")

    handler, _, _, _ = _handler()
    handler.p2p_server = _BoomServer()
    with caplog.at_level(logging.WARNING, logger="P2P.MessageHandler"):
        ok = handler._send("peer-1", {"type": "pong"})
    assert ok is False
    assert handler._send_failures == 1
    assert "send_message failed" in caplog.text
