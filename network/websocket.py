"""
WebSocket server — broadcasts blockchain events in real-time to browser clients.
Port 8766  (ws://localhost:8766)

Supports:
  - Legacy ping/pong + NEW_BLOCK / NEW_TX events
  - Ethereum JSON-RPC: eth_subscribe / eth_unsubscribe (newHeads, logs, newPendingTransactions)
"""
import asyncio
import json
import logging
import time

logger = logging.getLogger("WebSocket")

try:
    from websockets.asyncio.server import serve as ws_serve
    _WS_AVAILABLE = True
except ImportError:
    try:
        from websockets import serve as ws_serve
        _WS_AVAILABLE = True
    except ImportError:
        ws_serve = None
        _WS_AVAILABLE = False
        logger.warning("[WebSocket] 'websockets' package not found — WS disabled. Run: pip install websockets")

from network.ws_events import normalize_block_event, normalize_tx_event


class WebSocketServer:
    """Asyncio WebSocket server that broadcasts chain events to browser clients."""

    def __init__(
        self,
        event_bus=None,
        host: str = "0.0.0.0",
        port: int = 8546,
        blockchain=None,
        config=None,
    ):
        self.host = host
        self.port = port
        self._clients: set = set()
        self._conn_ids: dict = {}
        self._next_conn_id = 1
        self._running = False
        self._send_failures = 0
        self._handler_errors = 0
        self._loop = None
        self.blockchain = blockchain
        self.config = config

        try:
            from api.eth_ws_subscriptions import EthWsSubscriptionManager
            self._eth_subs = EthWsSubscriptionManager()
        except ImportError:
            self._eth_subs = None

        if event_bus:
            reg = getattr(event_bus, "subscribe", None) or getattr(event_bus, "on", None)
            if reg:
                reg("block.new", self._on_block)
                reg("tx.new", self._on_tx)
                reg("tx.applied", self._on_tx)
                reg("consensus.attestation", self._on_attestation)

    def set_runtime_refs(self, blockchain=None, config=None) -> None:
        if blockchain is not None:
            self.blockchain = blockchain
        if config is not None:
            self.config = config

    # ── Event handlers (called from other threads) ────────────────────────────

    def _on_block(self, block):
        data = normalize_block_event(block)
        msg = {
            "type": "event",
            "event": "NEW_BLOCK",
            "data": data,
            "ts": time.time(),
        }
        self._schedule(msg)
        if self._eth_subs and self._loop and self._loop.is_running() and isinstance(block, dict):
            try:
                from api.eth_format import format_block, handle_eth_get_logs

                query = getattr(self.blockchain, "query_facade", None)

                def _format_head(b, full_tx=False):
                    return format_block(b, full_tx, query=query)

                self._eth_subs.on_new_block(
                    block,
                    _format_head,
                    handle_eth_get_logs,
                    self.blockchain,
                    self._schedule_eth_notification,
                )
            except Exception as exc:
                logger.debug("[WS] eth subscription block notify: %s", exc)

    def _on_tx(self, tx):
        data = normalize_tx_event(tx)
        msg = {
            "type": "event",
            "event": "NEW_TX",
            "data": data,
            "ts": time.time(),
        }
        self._schedule(msg)
        if self._eth_subs and data.get("block") == "pending":
            self._eth_subs.on_new_tx(data, self._schedule_eth_notification)

    def _on_attestation(self, att):
        if not isinstance(att, dict):
            return
        msg = {
            "type": "event",
            "event": "ATTESTATION",
            "data": {
                "validator": att.get("validator", ""),
                "block_hash": att.get("block_hash", ""),
                "slot": att.get("slot", 0),
            },
            "ts": time.time(),
        }
        self._schedule(msg)

    def _ws_for_conn(self, conn_id: int):
        for ws, cid in self._conn_ids.items():
            if cid == conn_id:
                return ws
        return None

    def _schedule_eth_notification(self, sub_id: int, payload: dict) -> None:
        if not self._eth_subs or not self._loop or not self._loop.is_running():
            return
        row = self._eth_subs.get_subscription(sub_id)
        if not row:
            return
        ws = self._ws_for_conn(row.get("conn_id"))
        if ws is None:
            return
        asyncio.run_coroutine_threadsafe(self._send_json(ws, payload), self._loop)

    def _schedule(self, msg: dict):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast(self, msg: dict):
        if not self._clients:
            return
        data = json.dumps(msg, default=str)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except Exception as exc:
                self._send_failures += 1
                logger.warning("[WS] broadcast send failed: %s", exc)
                dead.add(ws)
        self._clients -= dead

    def get_stats(self) -> dict:
        return {
            "clients": len(self._clients),
            "running": bool(self._running),
            "send_failures": int(self._send_failures),
            "handler_errors": int(self._handler_errors),
        }

    async def _send_json(self, websocket, payload: dict):
        try:
            await websocket.send(json.dumps(payload, default=str))
        except Exception as exc:
            self._send_failures += 1
            logger.warning("[WS] send failed: %s", exc)

    async def _handle_json_rpc(self, websocket, conn_id: int, data: dict):
        method = data.get("method", "")
        if method not in ("eth_subscribe", "eth_unsubscribe", "eth_chainId"):
            return False
        if not self._eth_subs:
            await self._send_json(
                websocket,
                {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {"code": -32601, "message": "eth subscriptions unavailable"},
                },
            )
            return True
        try:
            from api.eth_format import format_block, handle_eth_get_logs
            result = self._eth_subs.handle_rpc(
                conn_id,
                method,
                data.get("params") or [],
                format_block,
                handle_eth_get_logs,
                self.blockchain,
            )
            await self._send_json(
                websocket,
                {"jsonrpc": "2.0", "id": data.get("id"), "result": result},
            )
        except ValueError as exc:
            await self._send_json(
                websocket,
                {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {"code": -32602, "message": str(exc)},
                },
            )
        except Exception as exc:
            await self._send_json(
                websocket,
                {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {"code": -32000, "message": str(exc)},
                },
            )
        return True

    # ── Connection handler ────────────────────────────────────────────────────

    async def _handler(self, websocket):
        self._clients.add(websocket)
        conn_id = self._next_conn_id
        self._next_conn_id += 1
        self._conn_ids[websocket] = conn_id
        logger.info(f"[WS] client connected ({len(self._clients)} total)")
        try:
            await websocket.send(json.dumps({
                "type": "connected",
                "message": "Absolute Blockchain WebSocket API v1 (eth_subscribe supported)",
                "ts": time.time(),
            }))
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong", "ts": time.time()}))
                        continue
                    if await self._handle_json_rpc(websocket, conn_id, data):
                        continue
                except json.JSONDecodeError as exc:
                    self._handler_errors += 1
                    logger.debug("[WS] invalid JSON frame: %s", exc)
                except Exception as exc:
                    self._handler_errors += 1
                    logger.warning("[WS] handler error: %s", exc)
        except Exception as exc:
            logger.debug("[WS] connection closed: %s", exc)
        finally:
            self._clients.discard(websocket)
            self._conn_ids.pop(websocket, None)
            if self._eth_subs:
                self._eth_subs.drop_connection(conn_id)
            logger.debug(f"[WS] client disconnected ({len(self._clients)} remaining)")

    # ── Start / Stop ──────────────────────────────────────────────────────────

    async def start(self):
        if not _WS_AVAILABLE:
            logger.warning("[WebSocket] disabled (install websockets>=12.0)")
            return

        self._loop = asyncio.get_running_loop()
        self._running = True
        try:
            async with ws_serve(self._handler, self.host, self.port):
                logger.info(f"[WebSocket] server running on {self.host}:{self.port}")
                while self._running:
                    await asyncio.sleep(1)
        except OSError as e:
            if getattr(e, "winerror", None) == 10048 or getattr(e, "errno", None) in (48, 98):
                logger.error(
                    f"[WebSocket] could not bind port {self.port}: {e} "
                    "(stop other node: .\\scripts\\stop_node.ps1)"
                )
            else:
                logger.error(f"[WebSocket] error: {e}")
        except Exception as e:
            logger.error(f"[WebSocket] error: {e}")
        finally:
            # Fail-closed: bind/runtime failure must not leave a live flag.
            self._running = False

    def stop(self):
        self._running = False
