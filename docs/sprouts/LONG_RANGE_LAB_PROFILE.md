# Long-Range lab profile (ADR 0017 — Profile F companion)

Weak-subjectivity / Long-Range research. **Not** prod mesh `778888`.

## Rules

1. **`feature_long_range=false`** on Experimental prod mesh JSON (`docker/node.prod*.json`).
2. Lab arm: `node.long_range.lab.json` (+ lab1/lab2) + `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`).
3. Persist: `ABS_WS_CHECKPOINT_PATH` (digest + Ed25519 committee). Seed via
   `python scripts/seed_long_range_lab_ws.py --restart` (required before soak).
4. Lab node: `tip_safety_enforce=true` + `TIP_SAFETY_ENFORCE=true` so WS tip gate attaches.
5. Timed lab 2h / 48h only after libp2p 48h PASS ([EXECUTION_ORDER.md](../EXECUTION_ORDER.md) Phase 2).
6. BLS aggregate remains **design-only**. Lab-industrial certs use **Ed25519 committee 2/3**.

## Lab proof (no soak)

```powershell
python scripts/gen_long_range_lab_committee.py
python scripts/long_range_lab_2h_harness.py
python -m pytest tests/unit -k "long_range" -q
```

Preflight also checks: profile doc needles, compose port isolation (`29080`/`29081`/`29082`),
`ABS_WS_CHECKPOINT_PATH`, bind-mounts, `tip_safety_enforce`, `feature_libp2p=false`,
`start_soak_long_range_lab.ps1`.

## Compose + soak (operator)

```powershell
.\scripts\start_soak_long_range_lab.ps1              # 2h on 29080-29082
.\scripts\start_soak_long_range_lab.ps1 -Hours 48    # only after mesh 2h PASS

python scripts/long_range_lab_live_probe.py --all-nodes

docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml down -v
```

Ports: HTTP `29080–29082`, RPC `29545–29547`, P2P `26000–26002` — not prod `18180–18182`.

**PASS bar (lab):** `passed=true`, `hard_fails=0`, `hours_elapsed` ≥ requested, honesty
`long_range_defense=true` at start. Evidence under `logs/soak_*_long_range_lab*` then
`docs/evidence/runs/<id>/`.

**Not claimed:** BLS quorum · prod `778888` · public mainnet · Hybrid audit pin.

See [EXPERIMENTAL_RD_PROFILE.md](EXPERIMENTAL_RD_PROFILE.md) · [adr/0017-long-range-research.md](../adr/0017-long-range-research.md).
