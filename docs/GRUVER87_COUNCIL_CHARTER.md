# Gruver87 Genesis Council — Charter

**Version:** 1.0 · **Date:** 2026-08-28  
**Status:** Design (lab/staging) — not public mainnet governance  
**ADR:** [0022-gruver87-genesis-council-governance.md](adr/0022-gruver87-genesis-council-governance.md)

---

## 1. Purpose

The **Gruver87 Genesis Council '87** is a fixed council of **87 steward NFTs**
that provides **limited, transparent governance** over ecosystem spending and
community priorities. It exists to align long-term contributors with Absolute
Blockchain — not to replace validators or claim L1 security guarantees.

**Public rationale for 87:** founder birth year **1987** and identity **Gruver87**.

---

## 2. What council members are

| Yes | No |
|-----|-----|
| Stewards with **one vote per NFT** | Validators or block signers |
| Participants in **whitelist** DAO topics | «Guarantors» of chain security in legal sense |
| Visible in a **public manifest** | Hidden insiders with undisclosed extra mint |
| Bound by this charter + timelock | Emergency override of consensus or prod flags |

---

## 3. Relationship to ABS tokenomics

Absolute genesis allocation (221M ABS) is defined in `runtime/tokenomics.py`:

| Pool | Share | Council role |
|------|------:|--------------|
| Founder (D.U.P.) | 17.4% | **Out of scope** — not governed by council |
| Ecosystem | 10.0% | Spend proposals **after** validator DAO unlock |
| Treasury | 10.0% | Same |
| Staking | 12.6% | **Out of scope** — epoch release only |
| Mining | 50.0% | **Out of scope** — emission |

**Anti double-dip rule:** founder economic share is **17.4% ABS only** + **one**
Founder Seat NFT (#87). Additional NFTs to founder wallets are forbidden.

---

## 4. Seat allocation (87 total)

| ID range | Tier | Bucket | Count |
|----------|------|--------|------:|
| #001–#029 | Genesis | Early supporters + sale | 29 |
| #030–#058 | Council | Community distribution | 29 |
| #059–#086 | Steward | Grants + buffer + reserve | 28 |
| **#087** | **Founder** | **Gruver87 seat (soulbound 36 mo)** | **1** |

**Buckets (operational):**

- Founder: 1 (#087)
- Core reserve multisig: 0–3 (vesting)
- Early supporters: 20
- Community: 40
- Grant seats: 15
- Buffer (timelock): 8–11

Exact holder addresses live in the published manifest at mint time.

---

## 5. Voting mechanics

| Parameter | Value |
|-----------|------:|
| Vote weight | 1 NFT = 1 vote |
| Quorum (standard proposals) | 30 |
| Quorum (treasury spend) | 45 |
| Supermajority (charter amend) | 58 |
| Timelock (standard) | 72 hours |
| Timelock (treasury policy / contract) | 7 days |
| Delegation | Optional future ADR; v1 **no delegation** (reduces concentration risk early) |

**Signed votes only** in prod/staging deployment profiles.

---

## 6. Proposal lifecycle

```text
Draft → Forum/RFC (min 7 days) → On-chain/staging vote → Timelock → Execute
         ↑                              ↑
    calldata review              quorum met + refuse-list pass
```

Every executable proposal must include:

1. Plain-language summary (RU + EN)
2. Amount in **satoshi integers** (never floats)
3. Recipient address(es)
4. Calldata / spend path review
5. Conflict-of-interest disclosure

---

## 7. Allowed proposal types (v1)

- Ecosystem grants (under per-proposal cap)
- Documentation / evidence / audit budget lines
- Grant-seat NFT assignments (bucket #59–#86)
- App-layer parameter tweaks on Profile C (`778889`) only

---

## 8. Forbidden proposal types (v1)

- Validator set changes
- Consensus / tip-safety / state-root policy
- Enabling bridge or experimental sprouts on prod `778888`
- Redirecting founder allocation
- NFT remint or supply > 87
- Emergency mint of ABS

---

## 9. Multisig and separation of duties

Following industry treasury practice (Uniswap, Lido, OpenZeppelin Governor):

| Role | Holder | Rule |
|------|--------|------|
| Proposal submitter | Any council member | Cannot alone execute |
| Core reserve multisig | 2-of-3 minimum | Keys held by distinct humans |
| Execution | Timelock queue | No same-block vote→send |
| Reporting | Maintainer + community | Quarterly public report |

No single person holds: propose + multisig + execute end-to-end.

---

## 10. Founder commitments (Uladzimir Dabranski / Gruver87)

1. **One** Founder Seat (#87), soulbound 36 months from mint
2. **Abstain** on council votes that grant funds to founder-controlled addresses
3. Publish **quarterly transparency report** (treasury, grants, roadmap status)
4. No `feature_nft` on prod `778888` without new ADR + audit evidence row
5. Maintain `EVIDENCE_MATRIX.md` honesty — no mainnet-ready claims without proof

---

## 11. Long-term anti-rug commitments

These are **policy commitments** visible to the community:

| Commitment | Mechanism |
|------------|-----------|
| Fixed 87 cap | On-chain/staging refuse mint > 87 |
| Locked ecosystem/treasury until DAO | Existing `pool_locks.py` |
| No hidden founder mint | Manifest + genesis alloc hash in ceremony |
| Industrial L1 separate from NFT hype | ADR 0016 profiles |
| Audit before mainnet council cutover | `EVIDENCE_MATRIX.md` external audit row |

---

## 12. Amendment process

Charter changes require:

- RFC ≥ 14 days
- Vote: **58 / 87** supermajority
- Timelock: **14 days**
- Updated ADR appendix if invariants change

---

## 13. Status and evidence

| Phase | Status |
|-------|--------|
| Charter + ADR | **Published** |
| Staging mint 87 | Not started |
| Signed on-chain governance | Not implemented |
| Mainnet council | **Not claimed** |

Evidence updates only via [EVIDENCE_MATRIX.md](EVIDENCE_MATRIX.md).
