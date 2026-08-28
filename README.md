# Absolute Blockchain — Experimental sandbox

![Absolute Blockchain Experimental — R&D sandbox](docs/assets/repo-banner.svg)

**R&D only.** rust-libp2p · Long-Range · EVM depth. **Not** the audit-freeze tree.

Canonical docs language is **English**. If GitHub shows a translation, open **View original**.

[![Release](https://img.shields.io/github/v/release/Gruver87/experimental?label=release)](https://github.com/Gruver87/experimental/releases/tag/rd-1.0.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Experimental R&D](https://github.com/Gruver87/experimental/actions/workflows/experimental-rd.yml/badge.svg?branch=main)](https://github.com/Gruver87/experimental/actions/workflows/experimental-rd.yml)
[![Tests CI](https://github.com/Gruver87/experimental/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/Gruver87/experimental/actions/workflows/test.yml)
[![Security checks](https://github.com/Gruver87/experimental/actions/workflows/security-audit.yml/badge.svg?branch=main)](https://github.com/Gruver87/experimental/actions/workflows/security-audit.yml)
[![Community health](https://img.shields.io/badge/community%20health-100%25-brightgreen)](https://github.com/Gruver87/experimental#docs-map)

> **Industrial pin lives next door:** [`Absolute_Blockchain_Ultimate_Hybrid`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) · tag [`v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial)  
> **This repo:** Profile F labs. Do not port these kernels onto the Hybrid pin.

**Skimmer (60s):** [AT_A_GLANCE](docs/AT_A_GLANCE.md) · **What runs when:** [EXECUTION_ORDER](docs/EXECUTION_ORDER.md) · **Evidence:** [EVIDENCE_MATRIX](docs/EVIDENCE_MATRIX.md)

---

## Who this is for

| Audience | Start here |
|----------|------------|
| **Architects / principals** | [AT_A_GLANCE](docs/AT_A_GLANCE.md) → [ARCHITECTURE](docs/ARCHITECTURE.md) → ADR [0017](docs/adr/0017-long-range-research.md) / [0019](docs/adr/0019-rust-libp2p-industrial.md) / [0020](docs/adr/0020-libp2p-industrial-mesh.md) |
| **Grant officers / diligence** | Proven-vs-not table below · [EVIDENCE_MATRIX](docs/EVIDENCE_MATRIX.md) · [EXECUTION_ORDER](docs/EXECUTION_ORDER.md) blockers (B1 open: libp2p 48h) |
| **Operators** | [Start in 60 seconds](#start-in-60-seconds) · `python scripts/verify_experimental_rd.py` · optional `python scripts/verify_parallel_rd_batch.py` |
| **Auditors (this tree)** | R&D sandbox only — firm engagement package lives on the [Hybrid pin](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/AUDIT_ENGAGEMENT_BRIEF.md) |

Sandbox rules: [EXPERIMENTAL_SANDBOX.md](EXPERIMENTAL_SANDBOX.md) · Profile F: [EXPERIMENTAL_RD_PROFILE](docs/sprouts/EXPERIMENTAL_RD_PROFILE.md)

---

## Start in 60 seconds

```bash
git clone https://github.com/Gruver87/experimental.git
cd experimental
pip install -r requirements.txt && cp .env.example .env
```

| OS | Native | R&D self-check | ADR 0019 hard (libp2p) |
|----|--------|----------------|------------------------|
| **Windows** | `.\scripts\build_native.ps1` | `python scripts/verify_experimental_rd.py` | `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |
| **Linux / macOS** | `make build` | same Python | `python scripts/verify_adr0019_libp2p_hard.py --rebuild` |

Explorer (solo): http://localhost:8080

---

## Proven vs not

| Claim | Status | Proof |
|-------|--------|-------|
| ADR 0019 rust-libp2p slices **A–DB** (phase 105) | **Lab PASS** | hard gate **117** steps with `--rebuild` |
| Circuit never occupies crate ExternalAddresses | **Lab PASS** | Slices CW–CX |
| AutoNAT/UPnP confirm gated to advertised cap | **Lab PASS** | Slice CY |
| Identify observed confirm charges canonical key | **Lab PASS** | Slice CZ |
| Add/remove/expire match canonical charge key | **Lab PASS** | Slice DA |
| Persist JSON load collapses `/p2p/<peer>` suffix | **Lab PASS** | Slice DB |
| Experimental mesh transport | **ADR 0020 libp2p** | `feature_libp2p=true` on Experimental prod mesh JSON; Hybrid pin stays TCP+TLS |
| Profile F Long-Range / EVM / oracle / shard labs | **Lab only** | ADR 0017 · `EVM_COMPAT_MATRIX` · `LONG_RANGE_LAB_PROFILE` · prod sprout flags **off** |
| Hybrid 48h soak / firm audit / public mainnet | **No — other repo** | [Hybrid pin](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) |
| Prod libp2p 48h soak | **Not PASS** (B1 open) | FAIL ×2 (`35104db0`, `87f51b3e`); **2h smoke PASS** (`mesh-fix-smoke-2h`); 48h #3 not started — [EXECUTION_ORDER](docs/EXECUTION_ORDER.md) |
| 48h soak on this tree (TCP+TLS) | **PASS** | 2026-08-20→22 `hard_fails=0` — [evidence `0a7932c4`](docs/evidence/runs/0a7932c4/) — not libp2p cutover; not Hybrid `375d14f` |

**Jump:** [Tracks](#what-is-active-here) · [Verify](#clone--verify) · [Docs](#docs-map) · [Contribute](CONTRIBUTING.md)

---

## What is active here

| Track | Status | Entry |
|-------|--------|-------|
| **ADR 0019 rust-libp2p** | Slices **A–DB** (phase 105) behind Cargo `libp2p` | [ADR 0019](docs/adr/0019-rust-libp2p-industrial.md) |
| **ADR 0020 Experimental mesh** | libp2p on `778888` JSON; 48h **B1 open** | [EXECUTION_ORDER](docs/EXECUTION_ORDER.md) |
| **ADR 0017 Long-Range** | Lab / WS tip gate + `abs-lr-lab` compose | `python scripts/long_range_lab_2h_harness.py` |
| **EVM depth / RPC honesty** | Waves 8–11 + compat matrix | [EVM_COMPAT_MATRIX](docs/sprouts/EVM_COMPAT_MATRIX.md) |
| **ADR 0021 mempool Rust** | Phase 0 ports only | [ADR 0021](docs/adr/0021-mempool-validation-rust-phases.md) |

Latest ADR 0019 work lands on `main`. Historical slice PRs: [#16](https://github.com/Gruver87/experimental/pull/16).

---

## Clone & verify

### Experimental only (ADR 0019 hard — 116 steps, 117 with `--rebuild`)

```powershell
# Windows — rebuild native libp2p wheel when Rust changed
powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
```

```bash
python scripts/verify_adr0019_libp2p_hard.py --rebuild
python scripts/verify_experimental_rd.py
```

### Hybrid + Experimental as one operator view

If the audit-freeze Hybrid clone sits next to this folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_absolute_unified.ps1 -Mode Standard
```

Report: `data/verify_absolute_unified.json`  
Honesty: two repos, one check — **not** a git merge / **not** prod libp2p.

---

## Build rust-libp2p wheel (opt-in)

```powershell
cd native\abs_native
$env:CARGO_TARGET_DIR = (Resolve-Path .\target).Path
maturin build --release --features "pyo3/extension-module,libp2p" --out ".\target\wheels"
cd ..\..
python -m pip install --force-reinstall --no-deps .\native\abs_native\target\wheels\abs_native-0.1.0-cp310-abi3-win_amd64.whl
```

Default Hybrid CI / prod mesh builds **without** the `libp2p` feature.

---

## Honesty (read this)

- Green lab / hard verify ≠ tip existence proof ≠ firm audit PDF.
- Experimental prod mesh JSON (`778888`) is **libp2p** (ADR 0020). Hybrid audit-pin JSON stays `feature_libp2p=false`. TCP+TLS soak `0a7932c4` is not libp2p evidence.
- Do **not** push R&D into the audit-freeze Hybrid repo.
- ABS tokenomics in-repo model ≠ listed asset / public mainnet.
- Experimental tags are `rd-X.Y.Z` — **never** the Hybrid `v1.3.*-industrial` line.

---

## Docs map

| Need | Open |
|------|------|
| One-screen card | [AT_A_GLANCE](docs/AT_A_GLANCE.md) |
| Execution order (blockers) | [EXECUTION_ORDER](docs/EXECUTION_ORDER.md) |
| Evidence ledger | [EVIDENCE_MATRIX](docs/EVIDENCE_MATRIX.md) |
| Sandbox rules | [EXPERIMENTAL_SANDBOX.md](EXPERIMENTAL_SANDBOX.md) |
| rust-libp2p industrial slices | [docs/adr/0019-rust-libp2p-industrial.md](docs/adr/0019-rust-libp2p-industrial.md) |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Profile F flags | [docs/sprouts/EXPERIMENTAL_RD_PROFILE.md](docs/sprouts/EXPERIMENTAL_RD_PROFILE.md) |
| Long-Range lab profile | [docs/sprouts/LONG_RANGE_LAB_PROFILE.md](docs/sprouts/LONG_RANGE_LAB_PROFILE.md) |
| Releasing | [docs/RELEASING.md](docs/RELEASING.md) · [CHANGELOG](CHANGELOG.md) |
| Security / contribute | [SECURITY](SECURITY.md) · [CONTRIBUTING](CONTRIBUTING.md) · [SUPPORT](SUPPORT.md) · [Code of Conduct](CODE_OF_CONDUCT.md) |
| Cite this software | [CITATION.cff](CITATION.cff) |
| GitHub About paste | [REPO_PROFILE](.github/REPO_PROFILE.md) |
| Audit pin (other repo) | [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) · [EVIDENCE_MATRIX](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/EVIDENCE_MATRIX.md) |

---

## Contribute

1. **Star** · **Watch → Releases**
2. Issues with lab/gate evidence — [CONTRIBUTING.md](CONTRIBUTING.md)
3. PRs to **`main`** (this sandbox). Never open Hybrid PRs for R&D kernels.

## License

MIT — [LICENSE](LICENSE)

---

*Author: ULADZIMIR DABRANSKI (D.U.P.) · Owner: [Gruver87](https://github.com/Gruver87) · Default branch: `main`*  
*Last surface update: **2026-08-28** — parallel R&D labs + LR compose wired; TCP+TLS 48h PASS (`0a7932c4`); libp2p 48h **B1 open** (not PASS). Not a launched public mainnet.*
