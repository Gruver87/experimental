# Absolute Blockchain — Experimental sandbox

> **[Gruver87/experimental](https://github.com/Gruver87/experimental)** — R&D only  
> **Not** the audit-freeze tree. Industrial pin lives in a separate repo.

| Role | Repo / path |
|------|-------------|
| **Audit freeze (do not break)** | [`Absolute_Blockchain_Ultimate_Hybrid`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) · tag [`v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial) |
| **This sandbox** | Profile F R&D: rust-libp2p · Long-Range · EVM depth |

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Experimental R&D](https://github.com/Gruver87/experimental/actions/workflows/experimental-rd.yml/badge.svg?branch=main)](https://github.com/Gruver87/experimental/actions/workflows/experimental-rd.yml)
[![PR #16 libp2p](https://img.shields.io/badge/PR-16%20ADR%200019-blue)](https://github.com/Gruver87/experimental/pull/16)

**Default industrial transport = TCP+TLS.**  
`FEATURE_LIBP2P` / Cargo feature `libp2p` are **opt-in labs** — PASS here ≠ prod mesh cutover ≠ public mainnet.

See [EXPERIMENTAL_SANDBOX.md](EXPERIMENTAL_SANDBOX.md) · Profile F [EXPERIMENTAL_RD_PROFILE](docs/sprouts/EXPERIMENTAL_RD_PROFILE.md).

---

## What is active here

| Track | Status | Entry |
|-------|--------|-------|
| **ADR 0019 rust-libp2p** | Slices **A–BM** (phase 64) behind Cargo `libp2p` | [ADR 0019](docs/adr/0019-rust-libp2p-industrial.md) · hard verify below |
| **ADR 0018 dual-stack / stubs** | Labs + adapter | `scripts/libp2p_*_lab.py` |
| **ADR 0017 Long-Range** | Lab / WS tip gate | `python scripts/long_range_lab.py` |
| **EVM depth / precompiles** | Profile F waves | [EVM_COMPAT_MATRIX](docs/sprouts/EVM_COMPAT_MATRIX.md) |

Active R&D branch: `experimental/libp2p-longrange-evm` → [PR #16](https://github.com/Gruver87/experimental/pull/16).

---

## Clone & verify

```bash
git clone https://github.com/Gruver87/experimental.git
cd experimental
git checkout experimental/libp2p-longrange-evm   # latest ADR 0019 work until merged
pip install -r requirements.txt
cp .env.example .env
```

### Experimental only (ADR 0019 hard — 75 steps)

```powershell
# Windows — rebuild native libp2p wheel when Rust changed
powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
# or without rebuild:
powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p_hard.ps1
```

```bash
python scripts/verify_adr0019_libp2p_hard.py
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
- `feature_libp2p` must stay **false** on prod mesh JSON (`778888`).
- Do **not** push R&D into the audit-freeze Hybrid repo.
- ABS tokenomics in-repo model ≠ listed asset / public mainnet.

---

## Docs map

| Need | Open |
|------|------|
| Sandbox rules | [EXPERIMENTAL_SANDBOX.md](EXPERIMENTAL_SANDBOX.md) |
| rust-libp2p industrial slices | [docs/adr/0019-rust-libp2p-industrial.md](docs/adr/0019-rust-libp2p-industrial.md) |
| Profile F flags | [docs/sprouts/EXPERIMENTAL_RD_PROFILE.md](docs/sprouts/EXPERIMENTAL_RD_PROFILE.md) |
| Audit pin (other repo) | [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) · [EVIDENCE_MATRIX](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/EVIDENCE_MATRIX.md) |

---

## License

MIT — [LICENSE](LICENSE)

Author: ULADZIMIR DABRANSKI (D.U.P.) · Owner: [Gruver87](https://github.com/Gruver87)  
Last surface update: **2026-08-13** — ADR 0019 through Slice **BM** · unified Hybrid+Experimental verify.
