# Evidence: `councillab1` — Council lab verify PASS

**Date:** 2026-09-13  
**Script:** `scripts/verify_council_lab.ps1`

## Result

| Field | Value |
|-------|--------|
| `ok` | **true** |
| Steps | **6/6** PASS |
| Profile | C staging `778889` (ADR 0022) |

## Covered

- `guarantor_council_lab.py` (manifest / refuse-list / founder seat)
- `guarantor_council_staging_mint_lab.py` (87 mint, remint refuse, soulbound)
- `tests/unit/test_council_nft.py`
- Staging `chain_id_staging=778889` (not prod `778888`)
- Prod mesh JSON remains `chain_id=778888` / `deployment_mode=prod`

## Honesty

- Lab / Profile C only — **not** council mint on prod `778888`
- **Not** soak / **not** L1 security guarantor claim
- Operator re-check: `.\scripts\verify_council_lab.ps1`

Artifact: `verify_council_lab.json` in this directory.
