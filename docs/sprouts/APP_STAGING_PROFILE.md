# App staging profile (Profile C — NFT)

NFT is tier **`app-profile`** (not industrial L1 `"production"`). Use a
**different `chain_id`** and Rocks volume from `778888`.

## Config

- Example: [`docker/node.staging.app.json`](../../docker/node.staging.app.json)
- `chain_id`: `778889` (staging app)
- `feature_nft`: `true`
- All other FEATURE_* sprouts: `false`
- `deployment_mode`: `staging` (not prod mesh)

## Port contract

[`features/nft_ports.py`](../../features/nft_ports.py) — `NftMarketplacePort`.
Mint/buy wrap balance deltas + NFT persist in `db.atomic()` when the store
exposes it (`uow_atomic` in `/nft` stats). Staging compose:
[`docker-compose.staging.app.yml`](../../docker-compose.staging.app.yml).

## Forbidden

- Enabling `FEATURE_NFT` on `docker/node.prod.mesh*.json` / `778888`

## Governance council (extension)

87 steward NFT + DAO design: [GOVERNANCE_COUNCIL_PROFILE.md](GOVERNANCE_COUNCIL_PROFILE.md) (ADR 0022). Same `chain_id=778889`; not prod mesh.
