# At a glance — Experimental

One-screen card. Full detail: [README](../README.md) · sandbox rules: [EXPERIMENTAL_SANDBOX](../EXPERIMENTAL_SANDBOX.md).

## What this is

R&D sandbox for Absolute Blockchain: rust-libp2p (ADR 0019), Long-Range (ADR 0017), EVM depth. Hybrid Python + Rust L1 **fork** of the industrial tree.

## What it is not

The audit-freeze pin · public audited mainnet · listed ABS · Hybrid `v1.3.*-industrial` tags.

## Status

| | |
|---|---|
| Repo | [`Gruver87/experimental`](https://github.com/Gruver87/experimental) · default **`main`** |
| R&D tag | **`rd-1.0.0`** (prerelease snapshot) |
| ADR 0019 | Slices **A–DB** · phase **105** |
| Hard gate | **117** steps with `--rebuild` (operator-local, 2026-08-15) |
| Default transport | **libp2p (ADR 0020)** on Experimental prod mesh JSON — Hybrid pin stays TCP+TLS |
| Industrial pin | [Hybrid `v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial) |
| 48h soaks here | TCP+TLS **PASS** (`0a7932c4`) · **libp2p** [`3c801b87`](evidence/runs/3c801b87/) · **LR lab** [`lr48pass1`](evidence/runs/lr48pass1/) · **Phase 3 post-EVM** [`evm48pass1`](evidence/runs/evm48pass1/). Not BLS / not mainnet / not EVM-only. |
| Self-check | `.\scripts\verify_hard_all.ps1` (fail-closed, no soak start) · `python scripts/verify_experimental_rd.py` · `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |

## Pipeline (columns)

| 1 libp2p 48h | 2a LR solo 2h | 2b LR mesh 2h | 2c LR lab 48h | 3 EVM mesh 48h | 4 Mempool Rust |
|:------------:|:-------------:|:-------------:|:-------------:|:--------------:|:--------------:|
| **PASS** [`3c801b87`](evidence/runs/3c801b87/) | **PASS** [`lr2h9f3a`](evidence/runs/lr2h9f3a/) | **PASS** [`lr2hmesh`](evidence/runs/lr2hmesh/) | **PASS** [`lr48pass1`](evidence/runs/lr48pass1/) | **PASS** [`evm48pass1`](evidence/runs/evm48pass1/) | **4.0–4.3 landed + mesh bake** |

Full map: [ARCHITECTURE § R&D execution chain](ARCHITECTURE.md#rd-execution-chain) · [EXECUTION_ORDER](EXECUTION_ORDER.md).

## Proven vs not (honest)

| Proven (lab / Experimental mesh) | Not claimed |
|--------------|-------------|
| rust-libp2p swarm A–DB + **libp2p 48h PASS** (`3c801b87`) | Long-Range **production** / firm audit PDF |
| Experimental 48h TCP+TLS (`0a7932c4`) + libp2p (`3c801b87`) | Public mainnet / Hybrid pin relabel |
| Advertised unique cap 20; circuit out of crate book | Public IPFS DHT / Noise = mTLS |
| AutoNAT/UPnP confirm admit-canonical-or-omit | Tip proof / public mainnet |
| Identify observed confirm charges canonical key | Firm audit PDF |
| Add/remove/expire match canonical charge key | NTFS replace = POSIX inode-atomic |
| Long-Range WS lab + mesh 2h [`lr2hmesh`](evidence/runs/lr2hmesh/) + **lab 48h PASS** [`lr48pass1`](evidence/runs/lr48pass1/) | Long-Range **prod arm** / BLS / `feature_long_range` on `778888` |
| Phase 3 post-EVM-prep mesh 48h [`evm48pass1`](evidence/runs/evm48pass1/) + `evm_pre_48h_harness.py` | Full geth parity / EIP-4844 / **EVM-only** 48h claim |
| EVM depth lab (waves 8–11 + RPC honesty; `GET /evm/status`) | Oracles/sharding on prod mesh 778888 |
| Oracle quorum + shard 2/3 labs (`oracle_lab`, `cross_shard_lab`; prod flags off) | Council 48h soak / on-chain signed gov / mainnet treasury |
| Gruver87 council ADR 0022 (Profile C `:19080`, 87 genesis mint) | Merging Dependabot major bumps |
| Fail-closed identity/persist ACL labs (Windows) | |

## Where R&D lives

| Path | Role |
|------|------|
| `native/abs_native/src/libp2p_swarm.rs` | ADR 0019 swarm (feature `libp2p`) |
| `scripts/libp2p_rust_*_lab.py` | Slice labs |
| `scripts/verify_adr0019_libp2p_hard.py` | Hard gate |
| `scripts/evm_pre_48h_harness.py` | Phase 3 pre-soak (labs+gate+probe+smoke; no soak start) |
| `docs/adr/0019-rust-libp2p-industrial.md` | Slice ledger |
| `docs/sprouts/` | Profile F / Long-Range / EVM matrix |
| `docs/sprouts/GOVERNANCE_COUNCIL_PROFILE.md` | Profile C council NFT (778889) |

## Next click

- **Execution order (what when):** [EXECUTION_ORDER.md](EXECUTION_ORDER.md) — Phase 4 ADR 0021 complete (host + mesh bake); Phase 5+ optional labs
- Hybrid pin (do not break): [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid)
- Contribute: [CONTRIBUTING](../CONTRIBUTING.md)
- GitHub About: [REPO_PROFILE](../.github/REPO_PROFILE.md)
