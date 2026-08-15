# GitHub repository profile — Gruver87/experimental

Apply with:

```powershell
gh repo edit Gruver87/experimental --description "Absolute Blockchain Experimental — R&D sandbox (libp2p ADR 0019, Long-Range, EVM). Not the audit pin. Default mesh = TCP+TLS."
gh repo edit Gruver87/experimental --homepage "https://github.com/Gruver87/experimental#start-in-60-seconds"
gh repo edit Gruver87/experimental --enable-wiki=false
@(
  "absolute-blockchain","blockchain","blockchain-node","layer1","python","rust","pyo3",
  "p2p","libp2p","evm","experimental","research","devnet","cryptography","web3",
  "json-rpc","rest-api","rocksdb","hybrid-blockchain","noise-protocol"
) | ForEach-Object { gh repo edit Gruver87/experimental --add-topic $_ }
```

Or paste into **Settings → General → About**.

| Field | Value |
|-------|-------|
| **Description** | Absolute Blockchain Experimental — R&D sandbox (libp2p ADR 0019, Long-Range, EVM). Not the audit pin. Default mesh = TCP+TLS. |
| **Website** | https://github.com/Gruver87/experimental#start-in-60-seconds |
| **Social preview** | Upload evergreen `docs/assets/repo-banner.svg` (export PNG 1280×640) in **Settings → General → Social preview** |
| **Skimmer card** | [docs/AT_A_GLANCE.md](../docs/AT_A_GLANCE.md) |
| **Issue chooser** | Bug · Feature · Ops/verify · private vulnerability report · Hybrid pin (other repo) |

## Topics

```
absolute-blockchain
blockchain
blockchain-node
layer1
python
rust
pyo3
p2p
libp2p
evm
experimental
research
devnet
cryptography
web3
json-rpc
rest-api
rocksdb
hybrid-blockchain
noise-protocol
```

> Cap = 20 topics. Prefer searchable stack terms. Keep `experimental` / `libp2p` / `research` so this repo is not confused with the Hybrid pin.

## Branches

| Branch | Role |
|--------|------|
| **`main`** | **Default** — R&D landing |
| `rd/*` | Slice work before merge |

## Current release

| Field | Value |
|-------|-------|
| **Tag** | `rd-1.0.0` — first R&D GitHub Release (prerelease); `main` through Slice CZ phase 103 |
| **ADR stack** | Hybrid 0001–0016 inherited · **0017–0019** Experimental |
| **Hard gate** | 115 steps with `--rebuild` |
| **Notes** | [CHANGELOG](../CHANGELOG.md) · [RELEASING](../docs/RELEASING.md) |
| **Industrial sibling** | [`Absolute_Blockchain_Ultimate_Hybrid`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) — **not** this freeze |
| **Self-check** | `python scripts/verify_experimental_rd.py` · `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |
| **CI** | `experimental-rd.yml`, `test.yml`, `security-audit.yml` |

### Not yet proven (do not claim in About)

- External security audit
- Prod libp2p cutover
- 48h soak on this tree
- Public VPS testnet / launched mainnet / listed ABS
- GPG-signed release tags (annotated tags in use when signing key absent)

## Honest positioning (release / About)

- **Is:** R&D sandbox; rust-libp2p labs through Slice CZ; fail-closed advertised cap
- **Is not:** Hybrid audit pin; live public mainnet; prod libp2p mesh
- **Banner:** evergreen `docs/assets/repo-banner.svg` (no Hybrid version chip)
