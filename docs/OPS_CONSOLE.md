# Absolute Ops Console

Same-origin industrial UI for Experimental nodes.

## URLs

| Path | What |
|------|------|
| `/` or `/console` | Ops console (default) |
| `/console/assets/*` | CSP-bound JS/CSS |
| `/explorer` | Legacy feature explorer |

## Security

- `Content-Security-Policy`: `default-src 'self'` (no CDN)
- Path resolve via realpath allowlist under `web/console` + `web/explorer` only
- No private-key forms that POST to the node
- EIP-1193 connect + sessionStorage watchlist only
- CORS still allow-list only

## Operator check

```powershell
python -m pytest -q tests/unit/test_web_console_static.py --tb=line
# with a node up:
# open http://127.0.0.1:<http_port>/
```

Not soak evidence. Not mainnet.
