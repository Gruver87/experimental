# Shard lab profile (Profile E)

Sharding MVP mutates balances and uses cross-shard P2P on the same allowlist
budgets as sync — **never** toggle onto `778888` prod Rocks.

## Config

- Node examples: [`node.shard0.json`](../../node.shard0.json), [`node.shard1.json`](../../node.shard1.json)
- Compose lab: [`docker-compose.shard.lab.yml`](../../docker-compose.shard.lab.yml)
- Separate project name, volumes, and P2P host ports

## Rules

1. Dedicated peer set (do not bootstrap to prod mesh).
2. Separate chainstore volumes.
3. Research only until single-chain L1 is audited and stable.
4. Local lab (no Docker): `python scripts/cross_shard_lab.py`

See ADR 0016 Decision §3 Profile E · oracles: [ORACLE_LAB_PROFILE.md](ORACLE_LAB_PROFILE.md).
