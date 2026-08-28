# Gruver87 — Long-term trust model

**Purpose:** show how Absolute Blockchain earns **multi-year credibility** through
structure borrowed from top protocols — adapted honestly to our hybrid L1 + lab
posture. This is **not** a marketing claim of mainnet readiness.

**Related:** [ADR 0022](adr/0022-gruver87-genesis-council-governance.md) ·
[Charter](GRUVER87_COUNCIL_CHARTER.md) · [EVIDENCE_MATRIX.md](EVIDENCE_MATRIX.md)

---

## Executive summary

Projects that **survive decades** (Ethereum, Uniswap, ENS, Maker/Sky, Lido)
separate three things Absolute must keep separate:

1. **L1 security** — validators, crypto, soak evidence  
2. **Economic allocation** — genesis/tokenomics with published caps  
3. **Governance membership** — votes on treasury/grants, not consensus hot path  

Absolute already has (2) in code. This document adds (3) as **87 council NFTs**
without breaking (1) or double-paying the founder.

---

## What top projects do (and what we adopt)

### Ethereum Foundation model

| Their pattern | Absolute adoption |
|---------------|-------------------|
| No «founder pre-mine» narrative for EF | Founder **17.4% disclosed** in `tokenomics.py` — no hiding |
| Years of public roadmap + upgrades | `EVIDENCE_MATRIX` + quarterly reports (new) |
| Security ≠ token holder votes on consensus | Council **refuse-list** blocks consensus votes |

### Uniswap / Arbitrum / Optimism (treasury DAOs)

| Their pattern | Absolute adoption |
|---------------|-------------------|
| Large treasury, public dashboards | Publish ecosystem/treasury addresses + quarterly balance report |
| Grant programs with milestones | Grant proposals capped + milestone refunds |
| Timelock on execution | 72h standard, 7d for contract/treasury policy |
| Concentration risk disclosed | 1 vote per NFT, no tier multipliers v1 |

### ENS (delegation done right)

Research (2026 governance concentration study): ENS achieves **less** voting
concentration than token holdings (0.48× amplification) because of **~100 funded
delegates**. Absolute v1: **no delegation** until council mature; optional ADR later.

### Lido / Maker (treasury conservatism)

| Their pattern | Absolute adoption |
|---------------|-------------------|
| Diversified treasury (stables + ETH) | Policy doc: operational runway in stables when live |
| Public wallet labels | All council + pool addresses in manifest |
| Separation of duties | 2-of-3 multisig, propose ≠ execute |

### Nouns / NounsBuilder (NFT = 1 vote lessons)

| Their pattern | Absolute adoption |
|---------------|-------------------|
| 1 NFT = 1 vote | Same |
| Founder allocation bugs (Sherlock audit) | Manifest generated from script; modulo/id tests in lab |
| Non-transferable founder badges | Founder seat #87 soulbound 36 months |

### Soulbound credentials (ERC-5484)

| Their pattern | Absolute adoption |
|---------------|-------------------|
| Non-transferable membership | Founder seat + optional grant seats |
| Immutable metadata after mint | Image SHA-256 in manifest |
| Burn only with issuer consent | Key rotation via documented burn/remint policy (future ADR) |

---

## Absolute trust stack (10 years view)

```text
Year 0–1   DESIGN + LAB
           ADR 0022, charter, manifest, Profile C mint on 778889
           Unit/lab: refuse-list, cap 87, conflict abstain
           Industrial L1 soak/libp2p evidence separate (Profile A)

Year 1–2   STAGING COUNCIL
           87 mint, public holders, quarterly reports
           Validator DAO unlock → council spend proposals (signed)
           External audit engagement (EVIDENCE_MATRIX row)

Year 2–4   TESTNET + APP ECOSYSTEM
           NFT marketplace + grants on staging/testnet
           Bridge only per ADR 0010 after audit
           Delegate program ADR (optional, ENS-style)

Year 4+    MAINNET CUTOVER (only with evidence)
           Separate ADR; prod 778888 council only if audit + soak + charter compliance
           Never merge Long-Range/libp2p experimental into audit pin without ADR
```

---

## Why this does not «rug in month one»

| Rug pattern | Absolute countermeasure |
|-------------|-------------------------|
| Hidden founder dump | 17.4% public; quarterly disclosure |
| Infinite mint | Cap 87 + code refuse |
| DAO theater (unsigned votes) | Prod signed-only; honesty flags on API |
| NFT = security marketing | Charter + ADR explicit refuse |
| Prod sprout flip | `industrial_gate` blocks `feature_nft` on 778888 |
| Silent treasury drain | Locked pools until validator 51%; then council + timelock |
| No evidence | `EVIDENCE_MATRIX` — fail-closed claims |

---

## Economic + governance map (one page)

```text
221,000,000 ABS
├── 17.4% Founder (D.U.P.)     genesis · NOT council-governed
├── 10.0% Ecosystem            locked → validator unlock → council spends (capped)
├── 10.0% Treasury             locked → validator unlock → council spends (capped)
├── 12.6% Staking              epoch release
└── 50.0% Mining               block rewards

87 NFT (Profile C / staging)
├── #087 Founder seat          1 vote · soulbound
├── #001–#086 Community        1 vote each · manifest public
└── NO extra ABS % via NFT
```

---

## Public-facing one-pager (copy-ready)

> **Absolute Blockchain — Gruver87 Genesis Council '87**  
> 87 steward NFTs. Fixed cap. Named for 1987 and Gruver87.  
> **Council governs:** grants, ecosystem priorities, app-layer staging params.  
> **Council does not govern:** validators, consensus, prod flags, founder 17.4%.  
> **L1 security:** validators + industrial evidence — separate from NFT.  
> **Status:** design + lab path. Not public audited mainnet.

---

## Transparency checklist (community verification)

| # | Artifact | Where |
|---|----------|-------|
| 1 | Tokenomics table | `runtime/tokenomics.py` + `/tokenomics` API |
| 2 | Pool lock state | `/pools/locks` |
| 3 | Council charter | `docs/GRUVER87_COUNCIL_CHARTER.md` |
| 4 | ADR refuse-list | `docs/adr/0022-*.md` |
| 5 | 87 manifest | `docs/genesis/gruver87-council-manifest.json` (generated) |
| 6 | Quarterly report | `docs/reports/council/` (to create at first quarter) |
| 7 | Evidence honesty | `docs/EVIDENCE_MATRIX.md` |
| 8 | Prod feature freeze | `docker/node.prod.mesh*.json` (`feature_nft: false`) |

---

## Recommended next implementation steps

1. ~~Manifest gen + lab~~ — **done** (`guarantor_council_manifest_gen.py`, `guarantor_council_lab.py` PASS)
2. **Staging mint ceremony** on `778889` with real holder addresses (replace `TBD_PRE_MINT`)
3. **First quarterly report** — template at `docs/reports/council/TEMPLATE.md`

**Not started:** 48h council soak, mainnet council, delegation program.

---

## Honesty footer

- Comparative analysis references public governance research and industry practice;
  Absolute has **not** replicated Uniswap/ENS treasury scale or audit status.
- **Soak not run** for council governance. L1 soak claims remain in
  `EVIDENCE_MATRIX.md` only where evidenced.
- This document is **trust architecture**, not a token sale prospectus.
