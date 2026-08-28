"""Wire message type constants for the application dispatcher (Step D).

Mirrored from ``network.p2p_node`` string values. A unit test asserts parity so
handlers never import ``P2PNode`` (avoids package cycles).
"""

from __future__ import annotations

MSG_HANDSHAKE = "handshake"
MSG_HANDSHAKE_ACK = "handshake_ack"
MSG_PING = "ping"
MSG_PONG = "pong"
MSG_IDLE = "__idle__"
MSG_NEW_BLOCK = "new_block"
MSG_GET_BLOCK = "get_block"
MSG_GET_BLOCK_BY_HASH = "get_block_by_hash"
MSG_BLOCK = "block"
MSG_GET_BLOCKS = "get_blocks"
MSG_BLOCKS = "blocks"
MSG_NEW_TX = "new_tx"
MSG_GET_MEMPOOL = "get_mempool"
MSG_MEMPOOL = "mempool"
MSG_GET_PEERS = "get_peers"
MSG_PEERS = "peers"
MSG_STATUS = "status"
MSG_ATTESTATION = "attestation"
MSG_STATE_ROOT_REQUEST = "state_root_request"
MSG_STATE_ROOT_RESPONSE = "state_root_response"
MSG_VALIDATOR_REGISTER = "validator_register"
MSG_CROSS_SHARD_TX = "cross_shard_tx"
MSG_CROSS_SHARD_ACK = "cross_shard_ack"
MSG_SHARD_MIGRATION = "shard_migration"
MSG_WS_CHECKPOINT = "ws_checkpoint"

DISPATCHABLE_TYPES = frozenset(
    {
        MSG_PING,
        MSG_PONG,
        MSG_NEW_BLOCK,
        MSG_GET_BLOCK,
        MSG_GET_BLOCK_BY_HASH,
        MSG_GET_BLOCKS,
        MSG_NEW_TX,
        MSG_GET_MEMPOOL,
        MSG_MEMPOOL,
        MSG_BLOCKS,
        MSG_BLOCK,
        MSG_GET_PEERS,
        MSG_PEERS,
        MSG_STATUS,
        MSG_ATTESTATION,
        MSG_VALIDATOR_REGISTER,
        MSG_STATE_ROOT_REQUEST,
        MSG_STATE_ROOT_RESPONSE,
        MSG_CROSS_SHARD_TX,
        MSG_CROSS_SHARD_ACK,
        MSG_SHARD_MIGRATION,
        MSG_WS_CHECKPOINT,
    }
)
