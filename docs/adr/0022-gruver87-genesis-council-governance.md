# ADR 0022 — Gruver87 Genesis Council (87 NFT Governance)

- **Status:** Accepted (design + lab path; not prod mesh evidence)
- **Date:** 2026-08-28
- **Deciders:** Absolute Blockchain maintainers
- **Related:** ADR 0016 (Profile C), `runtime/tokenomics.py`, `runtime/pool_locks.py`
- **Charter:** [GRUVER87_COUNCIL_CHARTER.md](../GRUVER87_COUNCIL_CHARTER.md)
- **Trust model:** [GRUVER87_LONG_TERM_TRUST_MODEL.md](../GRUVER87_LONG_TERM_TRUST_MODEL.md)

## Context

Absolute ABS tokenomics already defines a **founder genesis allocation (17.4%)**,
locked **ecosystem (10%)** and **treasury (10%)** pools, and **validator-weighted
DAO unlock** for those pools (`PoolLockManager`, 51% validator quorum).

Separately, the project has **147+ NFT SVG assets** and an **app-profile NFT
marketplace** (`features/nft.py`, Profile C `chain_id=778889`). Prod industrial
mesh `778888` keeps `feature_nft=false` per ADR 0016 and `industrial_gate`.

The maintainer proposed **87 limited NFTs** tied to birth year **1987** and
identity **Gruver87**, with governance influence. Early wording mixed **L1
security guarantee** with **DAO membership** — that overclaim is rejected here.

Industry review (ENS delegate dispersion, Uniswap/Lido treasury transparency,
OpenZeppelin Governor + timelock patterns, ERC-5484 soulbound credentials,
NounsBuilder allocation audit lessons) shows **long-term trust** requires:

- Published cap and immutable manifest
- Separation of **economic tokens**, **governance seats**, and **L1 validators**
- Timelocks, quorum, refuse-list, and quarterly public reporting
- Lab/staging evidence before any mainnet cutover claim

## Decision

### 1. Name and supply

- **Collection:** `Gruver87 Genesis Council '87`
- **Supply cap:** **87** — fixed, non-inflationary, remint forbidden after genesis
- **Rationale (public):** founder birth year **1987** + public identity **Gruver87**
- **Not claimed:** NFT holders do **not** guarantee L1 security, uptime, or consensus

### 2. Two-layer governance (do not merge silently)

| Layer | Actor | Scope today | Council ADR adds |
|-------|-------|-------------|------------------|
| **Pool unlock** | Validators (51%) | Unlock ecosystem/treasury spend gates | Unchanged |
| **Spend / grants** | NFT Council | — | Whitelist spend proposals after unlock |

Validators **open the vault**; council **proposes spends inside charter limits**.
Neither layer may bypass tip-safety, prod flags, or bridge policy alone.

### 3. NFT allocation (87 seats)

| Bucket | Count | Notes |
|--------|------:|-------|
| Founder seat | 1 | Token **#87**, soulbound 36 months, 1 vote |
| Core reserve (multisig) | 3 | Vesting 24–48 months; mint only on named hire |
| Early supporters | 20 | Whitelist; transfer after 12 months |
| Community distribution | 40 | Public sale / fair launch on staging |
| Ecosystem grant seats | 15 | Assigned by council vote post-launch |
| Unallocated buffer | 8 | Timelock 24 months → council vote to allocate |
| **Total** | **87** | |

**Founder economic interest stays in 17.4% ABS genesis** (`tokenomics.py`).
Council NFTs are **not** a second hidden founder percentage.

If solo maintainer: core reserve = **0**, buffer = **11** (documented in manifest).

### 4. Vote rules

- **Weight:** 1 NFT = 1 vote (no tier multipliers)
- **Quorum (standard):** 30 / 87 (~34%)
- **Quorum (treasury spend):** 45 / 87 (~51%)
- **Timelock:** 72 hours (standard), 7 days (treasury policy / smart-contract touch)
- **Prod votes:** signed only (matches `/pools/dao/vote` prod refuse on unsigned)
- **Conflict:** founder abstains on grants to self; logged in public minutes

### 5. Council may vote (whitelist v1)

- Ecosystem micro-grants (per-proposal cap on staging; mainnet cap in charter)
- R&D / documentation / evidence priorities
- Assignment of grant-seat NFTs (#71–#85 bucket)
- App-layer fees on Profile C (`778889`) only

### 6. Hard refuse-list (fail-closed)

Council proposals and execution **must refuse**:

- Validator set / consensus parameter changes
- Any `feature_*=true` on prod mesh `778888` JSON
- Tip-safety disable, state-root rewrite, bridge ON without ADR 0010 cutover
- Unlock or redirect **founder pool** (17.4%)
- NFT remint or cap > 87
- Unsigned votes in prod deployment_mode

### 7. Deployment profile

- **Profile C extension:** council NFT + governance on `chain_id=778889` (staging)
- **Forbidden:** `feature_nft=true` on `778888` until explicit post-audit cutover ADR
- **Manifest:** `docs/genesis/gruver87-council-manifest.template.json` → published JSON at mint
- **Metadata immutability:** image hash pinned at mint; issuer cannot mutate post-mint

### 8. Transparency cadence (trust operations)

- **Genesis:** publish full 87-row manifest + multisig addresses before mint tx
- **Quarterly:** treasury/grant report (GitHub + optional IPFS CID)
- **Annual:** community review of charter compliance; amend only via council supermajority (58/87) + 14-day timelock

## Consequences

- New sprout doc: [GOVERNANCE_COUNCIL_PROFILE.md](../sprouts/GOVERNANCE_COUNCIL_PROFILE.md)
- Existing validator DAO remains; council is additive, not a replacement
- `features/nft.py` genesis collection (5 tokens) is **legacy demo** — council uses separate collection id `gruver87-council-87`
- Implementation phases: design (this ADR) → lab mint → public staging council → mainnet cutover only after external audit row in `EVIDENCE_MATRIX.md`

## Honesty

- This ADR does **not** claim public mainnet, audited treasury execution, or that NFT = L1 security.
- Current `/pools/dao/*` responses remain **dev/staging simulation** until signed on-chain governance is implemented and probed.
- **48h soak** for council governance is **not** claimed; industrial L1 soak evidence is separate (ADR 0016 Profile A).
- Long-Range / libp2p experimental work stays out of council prod cutover.

## Definition of Done (phase 0 — design)

- [x] ADR 0022 accepted
- [x] Charter + long-term trust model published
- [x] Manifest template + sprout profile
- [x] `guarantor_council_manifest_gen.py` → `docs/genesis/gruver87-council-manifest.json`
- [x] Lab: `guarantor_council_lab.py` PASS on full manifest
- [x] Staging genesis mint lab (`guarantor_council_staging_mint_lab.py`)
- [x] Staging ceremony script + `POST /council/genesis-mint` (admin JWT; not prod)
- [x] Operator run on live `778889` compose (2026-08-28; 87/87 genesis mint; evidence [`council-staging-genesis-20260828`](../evidence/runs/council-staging-genesis-20260828/))
- [x] `EVIDENCE_MATRIX.md` row updated (lab + live staging; not 48h / not mainnet)
