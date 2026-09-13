# Evidence: `bridgeoff1` — Phase 5.5 Bridge OFF honesty PASS

**Date:** 2026-09-13  
**Script:** `scripts/verify_bridge_off_lab.ps1` → wraps `scripts/bridge_off_audit_gate.py`

## Result

| Field | Value |
|-------|--------|
| `ok` | **true** |
| Steps | **3/3** PASS |

## Covered

- `bridge_off_audit_gate.py` (warnings allowed for missing evidence_run marker)
- Prod mesh JSON: `bridge_enabled=false`
- Compose default: `BRIDGE_ENABLED:-false`

## Honesty

- **Not** bridge cutover / **not** L1 contracts live
- **Not** soak / **not** mainnet
- `bridge OFF PASS != bridge ready`
- Operator re-check: `.\scripts\verify_bridge_off_lab.ps1`
