# STRICT soak triage — soft WARN vs hard FAIL (libp2p / LR / EVM parity)
#
# Audience: operators before STRICT 48h packs (libp2p, Long-Range, EVM mesh).
# Not mainnet. Not Hybrid pin.

## Goal

Same **Strict** bar as [`mempool48pass1`](../evidence/runs/mempool48pass1/):
`IntervalSec=60`, `fail=0`, `mesh_warn=0`, long-STRICT `FullHarnessEvery=6`
(not AlwaysFullHarness every 60s — HOL `/health/ready`).

Scripts:
- Libp2p mesh: `.\scripts\start_soak_prod_mesh_48h_strict.ps1`
- Post-EVM mesh: `.\scripts\start_soak_evm_mesh_48h_strict.ps1` (evm_pre_48h_harness → STRICT)
- Long-Range lab: `.\scripts\start_soak_long_range_lab.ps1 -Hours 48 -Strict` (after 2h PASS)
- Mempool (existing): `.\scripts\start_mempool_validation_soak.ps1 -Hours 48`

## Soft errors seen in PASS packs (must not hard-FAIL STRICT)

| Signal | Packs | Nature | Scoring |
|--------|-------|--------|---------|
| `p2p=tip_skew` + `aligned=True` | `ind48pass1` (×47) | tip-v2 mine-window ±1–2 | OK line (not WARN) |
| `transient_delta=1` | `ind48pass1` (×15) | sequential/parallel poll skew | OK after resnapshot |
| `failed=peer_probe_ok` | `mempool48pass1`, `3c801b87` | Noise ACK / wire solicit timeout under load | Soft WARN; `mesh_warn` counts only `WARN mesh misaligned` |
| `failed=harness_timeout` + `aligned=True` | `mempool48pass1` | HTTP harness timeout under load | Soft WARN (`SoftHarnessChecks`) |
| `failed=ready_flap` | `mempool48pass1` | `/health/ready` 503 brief | Soft WARN; long STRICT tolerates |
| `p2p=under_mesh` peers=1 | `evm48pass1` (×8) | peer drop | WARN label; reconnect hardened 2026-09-23 |

## Hard / STRICT killers (fixed or still watch)

| Signal | Packs | Fix |
|--------|-------|-----|
| Soft-only harness + sticky `aligned=False` → Strict FAIL | LR / mempool edge | `health_watch.ps1`: soft-only never hard-FAIL |
| `peer_probe` empty/timeout | mempool / 3c801b87 | harness retries **3×** (`api/http.py`) |
| `under_mesh` peers&lt;mesh_min | `evm48pass1` | catch-up calls `reconnect_known_peers` |
| tip stagnant FAIL (LR) | `lr48pass1` WARNs | lab tip-stagnant gate; keep TipStagnantFailAfterSec |
| `WARN mesh misaligned` | FAIL packs | Strict confirm 4×3s already; persistent skew = FAIL |

## Evidence

| Pack | Result |
|------|--------|
| Libp2p STRICT [`lp2pstrict1`](../evidence/runs/lp2pstrict1/) | **48h PASS** 2026-09-23→25 (`warn_lines=0`, tip ~57209→~68082) |
| LR STRICT / EVM STRICT | Not run yet |

## Honesty

- Default 48h [`ind48pass1`](../evidence/runs/ind48pass1/) ≠ STRICT libp2p [`lp2pstrict1`](../evidence/runs/lp2pstrict1/).
- STRICT libp2p ≠ STRICT mempool sidecar (no admit/refuse sidecar here).
- Long-Range STRICT stays on lab ports **29080–29082**, never prod 18180.
- EVM STRICT = `start_soak_evm_mesh_48h_strict.ps1` (same Strict bar after EVM prep).
  Not EVM-only 48h / not geth / distinct from default [`evm48pass1`](../evidence/runs/evm48pass1/).
