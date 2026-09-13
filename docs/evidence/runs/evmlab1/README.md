# Evidence: `evmlab1` — EVM depth lab verify PASS

**Date:** 2026-09-13  
**Script:** `scripts/verify_evm_depth_lab.ps1` → wraps `scripts/evm_pre_48h_harness.py --skip-mesh`

## Result

| Field | Value |
|-------|--------|
| `ok` | **true** |
| Steps | **4/4** PASS |
| Scope | Host labs + focused unit + industrial_gate |

## Covered

- Labs: precompile, rpc, nested, reorg, logs, filters
- Unit: `test_evm_runtime` / `test_evm_rpc_compat` / `test_sprout_profiles`
- COMPAT matrix honesty needles (`EVM_COMPAT_MATRIX.md`)
- industrial_gate EVM depth needles

## Honesty

- Lab / pre-soak only — **not** EVM-only 48h claim
- **Not** soak started / **not** mainnet / **not** BLS
- Mesh smoke optional: `.\scripts\verify_evm_depth_lab.ps1 -WithMesh`
- Operator re-check: `.\scripts\verify_evm_depth_lab.ps1`

Artifact: `verify_evm_depth_lab.json` in this directory.
