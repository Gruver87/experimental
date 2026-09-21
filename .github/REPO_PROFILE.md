# GitHub repository profile — Gruver87/experimental

Apply with:

```powershell
gh repo edit Gruver87/experimental --description "Absolute Blockchain Experimental — R&D (B1–B4 + mempool48pass1; P0/HIGH/MED honesty + fund card). Next: Phase 6 org / tip soak if ordered. Not the audit pin."
gh repo edit Gruver87/experimental --homepage "https://github.com/Gruver87/experimental/blob/main/docs/FUND_READINESS.md"
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
| **Description** | Absolute Blockchain Experimental — R&D (B1–B4 + mempool48pass1; P0/HIGH/MED honesty + fund card). Next: Phase 6 org / tip soak if ordered. Not the audit pin. |
| **Website** | https://github.com/Gruver87/experimental/blob/main/docs/FUND_READINESS.md |
| **Social preview** | Upload evergreen `docs/assets/repo-banner.svg` (export PNG 1280×640) in **Settings → General · Social preview** |
| **Skimmer card** | [docs/AT_A_GLANCE.md](../docs/AT_A_GLANCE.md) |
| **Fund / diligence** | [docs/FUND_READINESS.md](../docs/FUND_READINESS.md) |
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
| **Closed** | B1 libp2p [`3c801b87`](../docs/evidence/runs/3c801b87/) · B2 LR lab [`lr48pass1`](../docs/evidence/runs/lr48pass1/) · Phase 3 [`evm48pass1`](../docs/evidence/runs/evm48pass1/) · Phase 4 [`adr0021gaudit1`](../docs/evidence/runs/adr0021gaudit1/) + STRICT [`mempool48pass1`](../docs/evidence/runs/mempool48pass1/) · industrial P0/HIGH/MED · host verify + mesh probe 2026-09-21 |
| **Open / next** | Phase 6 org · tip 48h **only if ordered** — [FUND_READINESS](../docs/FUND_READINESS.md) · [INDUSTRIAL_MAX_SCAN](../docs/INDUSTRIAL_MAX_SCAN_2026-09-20.md) |
| **Notes** | [CHANGELOG](../CHANGELOG.md) · [RELEASING](../docs/RELEASING.md) |
| **Industrial sibling** | [`Absolute_Blockchain_Ultimate_Hybrid`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) — **not** this freeze |
| **Self-check** | `.\scripts\verify_global_rd_audit.ps1` · `.\scripts\verify_pre_soak.ps1` · `python scripts/verify_experimental_rd.py` |
| **CI** | `experimental-rd.yml`, `test.yml`, `security-audit.yml` |
| **Community health** | **100%** (GitHub community profile) |

### Not yet proven (do not claim in About)

- External security audit
- Long-Range **prod** `feature_long_range` / BLS / mainnet Long-Range
- EVM-only 48h / full geth / EIP-4844
- Public VPS testnet / launched mainnet / listed ABS
- GPG-signed release tags (annotated tags in use when signing key absent)
- Fresh tip 48h soak after 2026-09-21 bake (operator-ordered only)

## Honest positioning (release / About)

- **Is:** R&D sandbox; rust-libp2p industrial mesh **48h PASS**; Long-Range **lab** 48h PASS; Phase 3 post-EVM mesh **48h PASS**; mempool+validation STRICT **48h PASS**; P0/HIGH/MED honesty + fund diligence card; evidence-first blockers
- **Is not:** Hybrid audit pin; live public mainnet; Long-Range production / BLS; EVM-only 48h
- **Banner:** evergreen `docs/assets/repo-banner.svg` (no Hybrid version chip)
- **Profile README source:** [PROFILE_README.md](PROFILE_README.md) → publish as `Gruver87/Gruver87`
- **Surface date:** 2026-09-21
