# Security Policy — Experimental

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest `rd-X.Y.Z` tag on `main` | Yes (R&D snapshot) |
| Hybrid `v1.3.*-industrial` tags | **Other repo** — [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) |

This repository is an **R&D sandbox** (libp2p / Long-Range / EVM depth). It is **not** a launched public mainnet, **not** the audit pin, and has **not** completed an independent external security audit.

## Reporting a vulnerability

1. **Do not** open a public issue with exploit details.
2. Prefer private reporting:
   - [Open a private vulnerability report](https://github.com/Gruver87/experimental/security/advisories/new)
   - Or contact the repository owner **Gruver87** via GitHub
3. Include: affected tag/commit, reproduction steps, impact, and whether a fix is proposed.
4. If the issue is in the industrial mesh / soak path, report it on **Hybrid** as well — do not assume Experimental is the pin.

CI “Security checks” = dependency / supply-chain gates — **not** an independent external audit.

## Secrets — what must never enter Git

- `data/wallet.json` — use `wallet.example.json`
- `.env` — API keys, JWT, bot tokens, RPC secrets
- `*.db`, `data/` — chain databases
- Private keys, seed phrases, passwords, TLS key material

## What is public in-repo

- `wallet.example.json`, `.env.example`
- Founder **public** address in `runtime/tokenomics.py` (not a private key)

## Cryptography

Transaction ECDSA uses **`cryptography`** (OpenSSL), not `python-ecdsa`.
Production-profile Hybrid requires Rust/PyO3 `abs_native`. Experimental libp2p is **opt-in** (`FEATURE_LIBP2P` / Cargo `libp2p`) and is **not** a drop-in for mesh mTLS.

## P2P

- Default industrial transport remains **TCP+TLS**.
- rust-libp2p labs must not disable TLS verification on the TCP+TLS path.
- Rate-limit inbound; semantic validation; soft-refuse (not hard bans as default).

## Pre-push check

```bash
python scripts/check_secrets.py
```

## Supply chain

- Dependabot: [`.github/dependabot.yml`](.github/dependabot.yml)
- SBOM artifact on GitHub Release: `sbom-on-release.yml`
- Release process: [docs/RELEASING.md](docs/RELEASING.md)
- **Never** publish Experimental `abs_native` wheels to PyPI (would collide with Hybrid).

## If a secret was committed

1. Rotate the secret immediately.
2. Purge from git history if it reached a remote.
3. Open a private report with the owner.
