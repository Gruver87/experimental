# Long-Range lab profile (ADR 0017 — Profile F companion)

Weak-subjectivity / Long-Range research. **Not** prod mesh `778888`.

## Rules

1. **`feature_long_range=false`** on Experimental prod mesh JSON (`docker/node.prod*.json`)
   and on **staging** (Config + `long_range_feature_armed` hard-off).
2. Lab arm: `node.long_range.lab.json` (+ lab1/lab2) + `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`).
3. Persist: `ABS_WS_CHECKPOINT_PATH` (digest + Ed25519 committee). Seed via
   `python scripts/seed_long_range_lab_ws.py --restart` (required before soak).
   Mid-soak the miner rolls the WS floor forward (`ABS_WS_ROLL_GAP=512` /
   `ABS_WS_ROLL_CONFIRM=16` / `ABS_WS_ROLL_INTERVAL_SEC=120`) and peers
   republish/adopt via gossip — no operator re-seed for tip growth.
4. Lab node: `tip_safety_enforce=true` + `TIP_SAFETY_ENFORCE=true` so WS tip gate attaches.
5. Timed lab 2h / 48h only after libp2p 48h PASS ([EXECUTION_ORDER.md](../EXECUTION_ORDER.md) Phase 2). **Lab 48h PASS on disk:** [`lr48pass1`](../evidence/runs/lr48pass1/) (B2 closed). Prod JSON stays `feature_long_range=false`.
6. BLS aggregate remains **design-only**. Lab-industrial certs use **Ed25519 committee 2/3**.

## Protocol tasks (lab mesh must self-heal)

| Task | Behavior |
|------|----------|
| Seed once | Operator seed → restart; empty store → `ws_no_anchor` refuse |
| Roll floor | Miner only; pin confirmed tip−16 when gap ≥ 512 |
| Adopt gossip | Non-regressive; defer if cert height > local tip; refuse equivocation |
| Push on connect | Only when peer tip ≥ local anchor (else brick catch-up) |
| TipSafety | Contiguous tip+1 light advance; full backfill only on jumps / WS change |
| Mesh | under-mesh reconnect (catch-up + mining ≥8s); wire_soft_fail lab forge |

Detail: [`STRICT_SOAK_PARITY.md`](STRICT_SOAK_PARITY.md).

## Evidence ledger (lab only)

| Run | Result |
|-----|--------|
| [`lr2h9f3a`](../evidence/runs/lr2h9f3a/) | solo 2h PASS |
| [`lr2hmesh`](../evidence/runs/lr2hmesh/) | 3-node mesh 2h PASS |
| [`lr2hintensify`](../evidence/runs/lr2hintensify/) | intensify 2h PASS |
| [`lr48fail1`](../evidence/runs/lr48fail1/) | lab 48h FAIL (historical) |
| [`lr48pass1`](../evidence/runs/lr48pass1/) | lab 48h PASS — B2 closed |
| LR STRICT mid (2026-09-25→26) | **stopped** fail_lines=2 ~24h — code heal landed; **re-soak on command** |

## Lab proof (no soak)

```powershell
python scripts/gen_long_range_lab_committee.py
python scripts/long_range_lab_2h_harness.py
python -m pytest tests/unit -k "long_range" -q
```

Preflight also checks: profile doc needles, compose port isolation (`29080`/`29081`/`29082`),
`ABS_WS_CHECKPOINT_PATH`, bind-mounts, `tip_safety_enforce`, `feature_libp2p=false`,
`start_soak_long_range_lab.ps1`, roll_forward module + P2P maintenance loop (industrial_gate).

## Compose + soak (operator)

```powershell
.\scripts\start_soak_long_range_lab.ps1              # 2h on 29080-29082
.\scripts\start_soak_long_range_lab.ps1 -Hours 48    # only after mesh 2h PASS
.\scripts\start_soak_long_range_lab.ps1 -Hours 48 -Strict   # STRICT bar (on command)

python scripts/long_range_lab_live_probe.py --all-nodes

docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml down -v
```

Ports: HTTP `29080–29082`, RPC `29545–29547`, P2P `26000–26002` — not prod `18180–18182`.

**PASS bar (lab default):** `passed=true`, `hard_fails=0`, `hours_elapsed` ≥ requested, honesty
`long_range_defense=true` at start. Evidence under `logs/soak_*_long_range_lab*` then
`docs/evidence/runs/<id>/`.

**PASS bar (STRICT):** same as [`lp2pstrict1`](../evidence/runs/lp2pstrict1/) —
`fail_lines=0`, `mesh_warn=0`, IntervalSec=60, FullHarnessEvery=6.

**Not claimed:** BLS quorum · prod `778888` · public mainnet · Hybrid audit pin ·
STRICT LR 48h until a new evidence pack is written.

See [EXPERIMENTAL_RD_PROFILE.md](EXPERIMENTAL_RD_PROFILE.md) · [adr/0017-long-range-research.md](../adr/0017-long-range-research.md).
