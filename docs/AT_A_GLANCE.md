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
| 48h soak here | TCP+TLS **PASS** (2026-08-20→22, `0a7932c4`). libp2p 48h **FAIL** ×2: `35104db0` · `87f51b3e`. libp2p **2h smoke PASS** (2026-08-28, mesh_warn=0) — not 48h. |
| Self-check | `.\scripts\verify_hard_all.ps1` (fail-closed, no soak start) · `python scripts/verify_experimental_rd.py` · `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |

## Proven vs not (honest)

| Proven (lab) | Not claimed |
|--------------|-------------|
| rust-libp2p swarm A–DB behind Cargo `libp2p` | libp2p 48h soak PASS (3-node mesh proven; 48h `35104db0` + `87f51b3e` FAIL) |
| Experimental 48h TCP+TLS soak (`hard_fails=0`) | Long-Range production / firm audit PDF |
| Advertised unique cap 20; circuit out of crate book | Public IPFS DHT / Noise = mTLS |
| AutoNAT/UPnP confirm admit-canonical-or-omit | Tip proof / public mainnet |
| Identify observed confirm charges canonical key | Firm audit PDF |
| Add/remove/expire match canonical charge key | NTFS replace = POSIX inode-atomic |
| Long-Range WS lab (ADR 0017 waves 1–14 + lab compose `abs-lr-lab` + 2h preflight) | Long-Range **production** / BLS quorum / 48h soak armed |
| EVM depth lab (waves 8–11 + RPC honesty incl. getCode/balance/storage; `GET /evm/status`) | Full geth parity / EIP-4844 / EVM-only 48h soak claim |
| Oracle quorum + shard 2/3 labs (`oracle_lab`, `cross_shard_lab`; prod flags off) | Oracles/sharding on prod mesh 778888 |
| Fail-closed identity/persist ACL labs (Windows) | Merging Dependabot major bumps |

## Where R&D lives

| Path | Role |
|------|------|
| `native/abs_native/src/libp2p_swarm.rs` | ADR 0019 swarm (feature `libp2p`) |
| `scripts/libp2p_rust_*_lab.py` | Slice labs |
| `scripts/verify_adr0019_libp2p_hard.py` | Hard gate |
| `docs/adr/0019-rust-libp2p-industrial.md` | Slice ledger |
| `docs/sprouts/` | Profile F / Long-Range / EVM matrix |

## Next click

- **Execution order (what when):** [EXECUTION_ORDER.md](EXECUTION_ORDER.md)
- Hybrid pin (do not break): [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid)
- Contribute: [CONTRIBUTING](../CONTRIBUTING.md)
- GitHub About: [REPO_PROFILE](../.github/REPO_PROFILE.md)
