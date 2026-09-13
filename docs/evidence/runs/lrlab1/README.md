# Evidence: `lrlab1` — Long-Range lab verify PASS

**Date:** 2026-09-13  
**Script:** `scripts/verify_long_range_lab.ps1`

## Result

| Field | Value |
|-------|--------|
| `ok` | **true** |
| Steps | **5/5** PASS |

## Covered

- `long_range_lab.py` (checkpoint / WS refuse / persist)
- `long_range_p2p_lab.py`
- `long_range_gossip_lab.py`
- Prod mesh JSON: `feature_long_range=false` on mesh1/2/3

## Honesty

- Lab only — **not** `feature_long_range=true` on prod `778888`
- **Not** 2h/48h soak start / **not** BLS / **not** tip-proof
- Operator re-check: `.\scripts\verify_long_range_lab.ps1`

Artifact: `verify_long_range_lab.json` in this directory.
