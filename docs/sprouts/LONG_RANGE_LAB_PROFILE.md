# Long-Range lab profile (ADR 0017 — Profile F companion)

Weak-subjectivity / Long-Range research. **Not** prod mesh `778888`.

## Rules

1. **`feature_long_range=false`** on Experimental prod mesh JSON (`docker/node.prod*.json`).
2. Lab arm: `node.long_range.lab.json` + `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`).
3. Persist: `ABS_WS_CHECKPOINT_PATH` (digest-only JSON). Optional empty-store seed via
   `ABS_WS_ANCHOR_HEIGHT` + `ABS_WS_ANCHOR_HASH`.
4. Timed lab 2h / 48h only after libp2p 48h PASS ([EXECUTION_ORDER.md](../EXECUTION_ORDER.md) Phase 2).
5. BLS / signed-cert quorum is **design-only** until ADR 0017 Decision is updated.

## Lab proof (no soak)

```powershell
python scripts/long_range_lab_2h_harness.py
python -m pytest tests/unit -k "long_range" -q
```

## Compose (operator)

```powershell
docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml up -d --build
docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml down -v
```

Ports: HTTP `29080`, RPC `29545`, P2P `26000` — do not collide with prod `18180–18182`.

See [EXPERIMENTAL_RD_PROFILE.md](EXPERIMENTAL_RD_PROFILE.md) · [adr/0017-long-range-research.md](../adr/0017-long-range-research.md).
