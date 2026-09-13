# Evidence: `shardlab1` — Phase 5.4 Cross-shard lab PASS

**Date:** 2026-09-13  
**Script:** `scripts/verify_cross_shard_lab.ps1` → wraps `scripts/cross_shard_lab.py`

## Result

| Field | Value |
|-------|--------|
| `ok` | **true** |
| Steps | **3/3** PASS |
| Profile | E (ADR 0016) — script lab |

## Covered

- Debit/credit ACK + 2/3 validator quorum
- Insufficient balance refuse
- Prod mesh JSON: `feature_sharding=false` on mesh1/2/3

## Honesty

- Lab only — **not** `feature_sharding=true` on prod `778888`
- **Not** docker shard mesh (optional later: `start_shard_devnet.ps1`)
- **Not** soak / **not** mainnet
- Operator re-check: `.\scripts\verify_cross_shard_lab.ps1`
