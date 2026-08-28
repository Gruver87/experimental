# Oracle lab profile (aux sprout — ADR 0016)

Oracle feeds persist in **SQLite aux**, not prod L1 Rocks on `778888`.

## Rules

1. **`feature_oracles=false`** on Experimental prod mesh JSON (`docker/node.prod.json`).
2. Lab arm: dev JSON or compose with `feature_oracles=true` and **separate aux DB volume**.
3. Signed submit requires `BRIDGE_ORACLE_SECRET` (or registry secret); fail-closed when missing.
4. **Not** consensus trust path — price feeds for apps/bridge relayer only.

## Lab proof

```powershell
python scripts/oracle_lab.py
python -m pytest tests/unit/test_wave39_oracle_bridge.py tests/unit/test_l2_advanced_features.py -k oracle -q
```

Covers HMAC submit, quorum median, one-vote-per-reporter dedupe.

## Live mesh (optional, post libp2p 48h)

Separate compose project — never toggle onto industrial `778888` volumes.

See [SHARD_LAB_PROFILE.md](SHARD_LAB_PROFILE.md) for cross-shard (Profile E) · [EXECUTION_ORDER.md](../EXECUTION_ORDER.md).
