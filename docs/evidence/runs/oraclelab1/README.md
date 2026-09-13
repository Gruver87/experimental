# Evidence: `oraclelab1` — Phase 5.2 Oracle lab PASS

**Date:** 2026-09-13  
**Script:** `scripts/verify_oracle_lab.ps1` → wraps `scripts/oracle_lab.py`

## Result

| Field | Value |
|-------|--------|
| `ok` | **true** |
| Steps | **4/4** PASS |
| Profile | aux SQLite (ADR 0016 sprout) |

## Covered

- HMAC refuse + signed submit
- Quorum median + one-vote-per-reporter dedupe
- Unit: `tests/unit/test_wave39_oracle_bridge.py`
- Prod mesh JSON: `feature_oracles=false` on mesh1/2/3

## Honesty

- Lab only — **not** `feature_oracles=true` on prod `778888`
- **Not** consensus trust path / **not** soak / **not** mainnet
- Operator re-check: `.\scripts\verify_oracle_lab.ps1`
