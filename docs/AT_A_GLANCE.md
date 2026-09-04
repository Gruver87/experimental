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
| 48h soak here | TCP+TLS **PASS** (`0a7932c4`). **libp2p 48h PASS** (2026-09-01→03, [`3c801b87`](evidence/runs/3c801b87/), `hard_fails=0`, `mesh_warn=0`). Prior FAIL ×2: `35104db0` · `87f51b3e`. Not Long-Range / not mainnet. |
| Self-check | `.\scripts\verify_hard_all.ps1` (fail-closed, no soak start) · `python scripts/verify_experimental_rd.py` · `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |

## Pipeline (columns)

| 1 libp2p 48h | 2a LR solo 2h | 2b LR mesh 2h | 2c LR lab 48h | 3 EVM | 4 Mempool Rust |
|:------------:|:-------------:|:-------------:|:-------------:|:-----:|:--------------:|
| **PASS** [`3c801b87`](evidence/runs/3c801b87/) | **PASS** [`lr2h9f3a`](evidence/runs/lr2h9f3a/) | **PASS** [`lr2hmesh`](evidence/runs/lr2hmesh/) | **OPEN** (B2) | next | phase 0 ready |

Full map: [ARCHITECTURE § R&D execution chain](ARCHITECTURE.md#rd-execution-chain) · [EXECUTION_ORDER](EXECUTION_ORDER.md).

## Proven vs not (honest)

| Proven (lab) | Not claimed |
|--------------|-------------|
| rust-libp2p swarm A–DB + **libp2p 48h PASS** (`3c801b87`) | Long-Range production / firm audit PDF |
| Experimental 48h TCP+TLS soak (`0a7932c4`) + libp2p soak (`3c801b87`) | Public mainnet / Hybrid pin relabel |
| Advertised unique cap 20; circuit out of crate book | Public IPFS DHT / Noise = mTLS |
| AutoNAT/UPnP confirm admit-canonical-or-omit | Tip proof / public mainnet |
| Identify observed confirm charges canonical key | Firm audit PDF |
| Add/remove/expire match canonical charge key | NTFS replace = POSIX inode-atomic |
| Long-Range WS lab (ADR 0017 + **mesh 2h PASS** [`lr2hmesh`](evidence/runs/lr2hmesh/)) | Long-Range **production** / BLS / prod arm / lab 48h PASS (until closed) |
| EVM depth lab (waves 8–11 + RPC honesty incl. gasPrice/tx lookup/blockNumber/filters; `GET /evm/status`) | Full geth parity / EIP-4844 / EVM-only 48h soak claim |
| Oracle quorum + shard 2/3 labs (`oracle_lab`, `cross_shard_lab`; prod flags off) | Oracles/sharding on prod mesh 778888 |
| Gruver87 council ADR 0022 (Profile C `:19080`, 87 genesis mint) | Council 48h soak / on-chain signed gov / mainnet treasury |
| Fail-closed identity/persist ACL labs (Windows) | Merging Dependabot major bumps |

## Where R&D lives

| Path | Role |
|------|------|
| `native/abs_native/src/libp2p_swarm.rs` | ADR 0019 swarm (feature `libp2p`) |
| `scripts/libp2p_rust_*_lab.py` | Slice labs |
| `scripts/verify_adr0019_libp2p_hard.py` | Hard gate |
| `docs/adr/0019-rust-libp2p-industrial.md` | Slice ledger |
| `docs/sprouts/` | Profile F / Long-Range / EVM matrix |
| `docs/sprouts/GOVERNANCE_COUNCIL_PROFILE.md` | Profile C council NFT (778889) |

## Next click

- **Execution order (what when):** [EXECUTION_ORDER.md](EXECUTION_ORDER.md)
- Hybrid pin (do not break): [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid)
- Contribute: [CONTRIBUTING](../CONTRIBUTING.md)
- GitHub About: [REPO_PROFILE](../.github/REPO_PROFILE.md)
