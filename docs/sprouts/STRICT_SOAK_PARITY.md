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
| `p2p=tip_skew` + `aligned=True` | `ind48pass1`, `lp2pstrict1` | tip-v2 mine-window ±1–2 | OK line (not WARN) |
| `transient_delta` / `strict_confirm` | `ind48pass1`, `lp2pstrict1`, `lr48pass1` | poll skew healed | OK after resnapshot |
| `failed=peer_probe_ok` | `mempool48pass1`, `3c801b87`, `lr48pass1` | Noise ACK / wire solicit timeout | Soft WARN; `mesh_warn` = only `WARN mesh misaligned` |
| `failed=harness_timeout` + sticky aligned | `mempool48pass1`, `lr48pass1` ×16 | HTTP harness timeout under load | Soft WARN (`SoftHarnessChecks`); soft-only never Strict FAIL |
| `failed=ready_flap` / dual ready+status HOL | `mempool48pass1`, **`lr48pass1` ×13 FAIL** | `/health/ready` + `/status` timeout (lab used **5s** timeouts) | Soft ready_flap + **HeavyProbe** (prod timeouts when ports≥2) + dual_timeout live recover |
| `WARN mesh partial aligned` | `lr48pass1` ×13 | tip row excluded under HOL | WARN only (not Strict fail_line) |
| `p2p=under_mesh` peers=1 | `evm48pass1` (×8) | peer drop | WARN label; reconnect hardened 2026-09-23 |
| `WARN tip stagnant` (under limit) | `lr48pass1` | tip-growth watch before hard limit | WARN; hard-FAIL only after TipStagnantFailAfterSec |

## Hard / STRICT killers (fixed or still watch)

| Signal | Packs | Fix |
|--------|-------|-----|
| Soft-only harness + sticky `aligned=False` → Strict FAIL | LR / mempool edge | `health_watch.ps1`: soft-only never hard-FAIL |
| Lab mesh 5s HTTP timeouts → ready FAIL lines | **`lr48pass1` ×13** | `HeavyProbe` when `Ports.Count>=2` (prod-grade ready/status/harness) |
| Dual ready+status timeout → `Ok=false` FAIL | `lr48pass1` | live + status retry → soft `ready_flap` |
| Strict `FAIL mesh probe` (Partial) | would kill STRICT | Partial stays **WARN** (skew still FAIL) |
| `peer_probe` empty/timeout | mempool / 3c801b87 / LR | harness retries **3×** (`api/http.py`) |
| `under_mesh` peers&lt;mesh_min | `evm48pass1` | catch-up calls `reconnect_known_peers` |
| tip stagnant FAIL (LR) | lab tip-dead | keep TipStagnantFailAfterSec (48h default 3600s) |
| `WARN mesh misaligned` | `lr48fail1` ×28 | Strict confirm 4×3s; persistent skew = FAIL |

## Evidence

| Pack | Result |
|------|--------|
| Libp2p STRICT [`lp2pstrict1`](../evidence/runs/lp2pstrict1/) | **48h PASS** 2026-09-23→25 (`warn_lines=0`, tip ~57209→~68082) |
| LR STRICT mid-run (stopped) | **NOT PASS** — fail_lines=2 at ~24h; tip plateaus; root cascade fixed 2026-09-26 (see below). Re-soak on command only. |


## Root cause (LR STRICT mid-soak 2026-09-25→26)

Cascade observed at ~24h (`fail_lines=2`, tip plateaus h17150/h17253/h18549 ×30+ cycles):

1. Peer flap → `peers=1` / sticky `state_consistent=False` (wire solicit HOL timeout)
2. `mesh_min_peers_before_mine=2` + hard mining skip while inconsistent → **tip dead**
3. Catch-up + 70s wire probes pile GIL → `/health/ready`+`/status` dual-timeout → STRICT FAIL
4. Soft `ready_flap` recovered 4×; live also HOL twice → hard fail_lines

Fixes (2026-09-26): under-mesh reconnect in mining loop; `wire_soft_fail` STATUS-unanimous forge (lab only); no sticky `force_inconsistent` on probe exception outside prod; wire sticky empty max 5; health_watch sibling re-probe + longer live recovery.

## Honesty

- Default 48h [`ind48pass1`](../evidence/runs/ind48pass1/) ≠ STRICT libp2p [`lp2pstrict1`](../evidence/runs/lp2pstrict1/).
- STRICT libp2p ≠ STRICT mempool sidecar (no admit/refuse sidecar here).
- Long-Range STRICT stays on lab ports **29080–29082**, never prod 18180.
- EVM STRICT = `start_soak_evm_mesh_48h_strict.ps1` (same Strict bar after EVM prep).
  Not EVM-only 48h / not geth / distinct from default [`evm48pass1`](../evidence/runs/evm48pass1/).
