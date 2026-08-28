# GitHub repository profile — Gruver87/experimental

Apply with:

```powershell
gh repo edit Gruver87/experimental --description "Absolute Blockchain Experimental — evidence-first R&D (libp2p ADR 0019, Long-Range, EVM). Not the audit pin. libp2p 48h not PASS (B1)."
gh repo edit Gruver87/experimental --homepage "https://github.com/Gruver87/experimental/blob/main/docs/AT_A_GLANCE.md"
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
| **Description** | Absolute Blockchain Experimental — evidence-first R&D (libp2p ADR 0019, Long-Range, EVM). Not the audit pin. libp2p 48h not PASS (B1). |
| **Website** | https://github.com/Gruver87/experimental/blob/main/docs/AT_A_GLANCE.md |
| **Social preview** | Upload evergreen `docs/assets/repo-banner.svg` (export PNG 1280×640) in **Settings → General · Social preview** |
| **Skimmer card** | [docs/AT_A_GLANCE.md](../docs/AT_A_GLANCE.md) |
| **Execution order** | [docs/EXECUTION_ORDER.md](../docs/EXECUTION_ORDER.md) |
| **Cite** | [CITATION.cff](../CITATION.cff) |
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
| **Tag** | `rd-1.0.0` — first R&D GitHub Release; `main` through Slice DB phase 105 |
| **ADR stack** | Hybrid 0001–0016 inherited · **0017–0021** Experimental |
| **Hard gate** | 117 steps with `--rebuild` |
| **Blocker** | libp2p 48h **B1 open** (FAIL ×2; 2h smoke PASS) — see EXECUTION_ORDER |
| **Notes** | [CHANGELOG](../CHANGELOG.md) · [RELEASING](../docs/RELEASING.md) |
| **Industrial sibling** | [`Absolute_Blockchain_Ultimate_Hybrid`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) — **not** this freeze |
| **Self-check** | `python scripts/verify_experimental_rd.py` · `python scripts/verify_parallel_rd_batch.py` · `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |
| **CI** | `experimental-rd.yml`, `test.yml`, `security-audit.yml` |
| **Community health** | **100%** (GitHub community profile) |

### Not yet proven (do not claim in About)

- External security audit
- Prod libp2p 48h soak PASS
- Public VPS testnet / launched mainnet / listed ABS
- GPG-signed release tags (annotated tags in use when signing key absent)

## Honest positioning (release / About)

- **Is:** R&D sandbox; rust-libp2p labs through Slice DB; fail-closed labs; evidence-first blockers
- **Is not:** Hybrid audit pin; live public mainnet; prod libp2p 48h PASS
- **Banner:** evergreen `docs/assets/repo-banner.svg` (no Hybrid version chip)
- **Profile README source:** [PROFILE_README.md](PROFILE_README.md) → publish as `Gruver87/Gruver87`
