# Governance Council profile (Profile C extension)

Council NFT governance extends **Profile C — App staging** (ADR 0016). It does
**not** run on industrial prod mesh `778888`.

## Config

| Key | Value |
|-----|-------|
| Base profile | [APP_STAGING_PROFILE.md](APP_STAGING_PROFILE.md) |
| `chain_id` | `778889` |
| `feature_nft` | `true` |
| Collection id | `gruver87-council-87` |
| Supply cap | **87** (ADR 0022) |
| `deployment_mode` | `staging` |

## Documents

- ADR: [0022-gruver87-genesis-council-governance.md](../adr/0022-gruver87-genesis-council-governance.md)
- Charter: [GRUVER87_COUNCIL_CHARTER.md](../GRUVER87_COUNCIL_CHARTER.md)
- Trust model: [GRUVER87_LONG_TERM_TRUST_MODEL.md](../GRUVER87_LONG_TERM_TRUST_MODEL.md)
- Manifest template: [gruver87-council-manifest.template.json](../genesis/gruver87-council-manifest.template.json)

## Architecture

```text
Profile A (778888)          Profile C (778889)
Industrial L1               App staging + Council NFT
feature_nft=false           feature_nft=true
validators + soak           council mint + grants lab
       │                           │
       │    pool unlock (51% val)  │
       └───────────┬───────────────┘
                   ▼
           ecosystem / treasury spend
           (council proposals + timelock)
```

## Forbidden

- Council NFT mint on `778888` prod mesh JSON
- Council votes on consensus / tip-safety / bridge ON
- NFT remint above 87
- Claiming council = L1 security guarantee

## Lab gate (planned)

```powershell
python scripts/guarantor_council_manifest_gen.py
python scripts/guarantor_council_lab.py
python scripts/guarantor_council_staging_mint_lab.py
```

API (staging, `feature_nft=true`): `GET /council/stats`, `GET /council/manifest?summary=1`

Expected: refuse-list PASS, cap 87 PASS, manifest schema PASS.

## Evidence

| Claim | Status |
|-------|--------|
| ADR + charter published | **Done** |
| Full manifest 87 + SHA-256 | **Done** (`gruver87-council-manifest.json`) |
| `guarantor_council_lab.py` | **PASS** |
| Staging genesis mint lab | **PASS** (`guarantor_council_staging_mint_lab.py`) |
| Live staging compose `778889` | Not started |
| Mainnet council | **Not claimed** |

Update [EVIDENCE_MATRIX.md](../EVIDENCE_MATRIX.md) only after lab PASS.
