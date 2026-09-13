# Absolute Ops Console

Same-origin industrial UI for Experimental nodes.

## URLs

| Path | What |
|------|------|
| `/` or `/console` | Ops console (default) |
| `/console/assets/*` | CSP-bound JS/CSS |
| `/explorer` | Legacy feature explorer |

## Security

- `Content-Security-Policy`: `default-src 'self'` (no CDN, no inline scripts)
- Path resolve via realpath allowlist under `web/console` + `web/explorer` only
- No private-key forms that POST to the node
- EIP-1193 connect + `wallet_switchEthereumChain` / `wallet_addEthereumChain` + `eth_sendTransaction`
- Session watchlist is sessionStorage only; theme in localStorage
- CORS still allow-list only
- Council panel is **watch-only** (staging `778889`); no genesis mint from console

## Wallets

1. Set REST base (http_port) and JSON-RPC (rpc_port, auto-derived from `/status`).
2. Connect injected wallet → **Switch to Absolute** (uses node `chain_id`).
3. Send ABS via wallet-signed `eth_sendTransaction` (wei, 18 decimals).

## Markets

`GET /market/snapshot` and `GET /market/fx` are **ops orientation only** (not consensus / not Absolute oracle).

- Exchange clocks: NYSE, LSE, TSE, HKEX, SSE, CME, MOEX, ASX, Binance, Coinbase, Bybit, OKX, Kraken
- Crypto: CoinGecko simple price
- FX: Frankfurter (ECB) + converter
- Macro: Yahoo chart basket (gold/silver/oil/gas/copper, indices, mega-caps)

Server-side allowlist + TLS verify; browser CSP stays `connect-src 'self'`.

## Operator check

```powershell
python -m pytest -q tests/unit/test_web_console_static.py tests/unit/test_console_wallets_council.py --tb=line
# with a node up:
# open http://127.0.0.1:<http_port>/
```

Not soak evidence. Not mainnet.
