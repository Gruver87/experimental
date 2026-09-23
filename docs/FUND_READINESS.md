# Fund / diligence readiness — Experimental (honest)

**Audience:** grant officers, technical diligence, advisors.  
**Date:** 2026-09-23 · Repo: [`Gruver87/experimental`](https://github.com/Gruver87/experimental) · branch `main`  
**Not:** public audited mainnet · not Hybrid audit-freeze pin · not listed ABS.

One-screen status: [AT_A_GLANCE.md](AT_A_GLANCE.md) · Evidence ledger: [EVIDENCE_MATRIX.md](EVIDENCE_MATRIX.md) · Gaps: [MAINNET_GAP_ANALYSIS.md](MAINNET_GAP_ANALYSIS.md) · Vision (Hybrid): [VISION](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/VISION.md).

---

## What this is

Industrial **R&D / private-testnet** hybrid L1 (Python orchestration + Rust hot path). Experimental mesh default transport: **rust-libp2p Noise/Yamux (ADR 0020)**. Hybrid pin remains TCP+TLS.

## What we claim (with evidence)

| Claim | Evidence |
|-------|----------|
| libp2p industrial mesh 48h | [`3c801b87`](evidence/runs/3c801b87/) `hard_fails=0` |
| Long-Range **lab** 48h | [`lr48pass1`](evidence/runs/lr48pass1/) — prod JSON keeps `feature_long_range=false` |
| Post-EVM prep mesh 48h | [`evm48pass1`](evidence/runs/evm48pass1/) |
| Mempool+validation STRICT 48h | [`mempool48pass1`](evidence/runs/mempool48pass1/) |
| ADR 0021 global R&D audit | [`adr0021gaudit1`](evidence/runs/adr0021gaudit1/) 13/13 |
| Wire satoshi cutover + float-only refuse | Units + industrial waves; **mesh 48h** [`ind48pass1`](evidence/runs/ind48pass1/) |
| Host verify restore | Waves 542 needles + pytest **2734 passed** (2026-09-21) |
| Industrial polish tip 48h (`719deb4`) | [`ind48pass1`](evidence/runs/ind48pass1/) `hard_fails=0` tip ~46099→~56972 |

## What we do **not** claim

- Public mainnet / external firm security audit complete  
- Long-Range production / BLS  
- Full geth parity / EIP-4844  
- Bridge L1 lock/mint contracts live  
- NIST PQ signature backends (correct `NotImplemented`)  
- Hybrid pin relabel as this tree  

## Architecture (diligence map)

```text
API / JSON-RPC / WebSocket  →  Core + Mempool  →  Consensus / P2P / Sync
                                      ↓
                              StoragePort / Rocks
                                      ↓
                              abs_native (Rust PyO3)
```

ADRs: 0001 tip-safety · 0009 hybrid · 0016 profiles · 0017 Long-Range (lab) · 0019–0020 libp2p · 0021 mempool Rust · 0022 council (staging).

## Pre-audit checklist (code side)

| Item | Status |
|------|--------|
| Fail-closed money (satoshi) + wire refuse float-only | Done |
| Persist / backup fail-closed | Done |
| Industrial HIGH honesty pack | Done |
| Host pytest + waves green | Done 2026-09-21 |
| Mesh probe + pre-soak | Done 2026-09-21 → led to soak |
| Ceremony dry-run status | `ceremony_status` ready=True (≠ mainnet) |
| CI badges green (Security / Tests / Experimental R&D) | Tip `719deb4` — all four workflows green |
| Tip 48h soak after industrial polish (`719deb4`) | **PASS** [`ind48pass1`](evidence/runs/ind48pass1/) |
| External audit / secrets rotate / validator ceremony live | Org Phase 6 |

## CI badges (must be green for diligence)

- Experimental R&D · Blockchain Tests · Security checks (cargo-audit)

If a badge is red: treat as **blocker for fund decks** until fixed on `main`.

## Recommended diligence path (60 minutes)

1. Read this page + [AT_A_GLANCE](AT_A_GLANCE.md)  
2. Skim [EVIDENCE_MATRIX](EVIDENCE_MATRIX.md) soak index  
3. Open GitHub Actions on `main` — confirm green  
4. Optional: `.\scripts\verify_pre_soak.ps1 -SkipPrepare` on a workstation with mesh  
5. Hybrid engagement brief (firm audit): [Hybrid AUDIT_ENGAGEMENT_BRIEF](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/AUDIT_ENGAGEMENT_BRIEF.md)

**Bottom line:** ready for **technical diligence on an industrial private mesh / R&D L1**. Not ready to claim **public audited mainnet**.
