# At a glance — Experimental

One-screen card. Full detail: [README](../README.md) · sandbox rules: [EXPERIMENTAL_SANDBOX](../EXPERIMENTAL_SANDBOX.md).

## What this is

R&D sandbox for Absolute Blockchain: rust-libp2p (ADR 0019), Long-Range (ADR 0017), EVM depth. Hybrid Python + Rust L1 **fork** of the industrial tree.

## What it is not

The audit-freeze pin · public audited mainnet · listed ABS · prod libp2p mesh · Hybrid `v1.3.*-industrial` tags.

## Status

| | |
|---|---|
| Repo | [`Gruver87/experimental`](https://github.com/Gruver87/experimental) · default **`main`** |
| R&D tag | **`rd-1.0.0`** (prerelease snapshot) |
| ADR 0019 | Slices **A–DB** · phase **105** |
| Hard gate | **117** steps with `--rebuild` (operator-local, 2026-08-15) |
| Default transport | **TCP+TLS** — `feature_libp2p=false` on prod JSON |
| Industrial pin | [Hybrid `v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial) |
| 48h soak here | **PASS** (2026-08-20→22, TCP+TLS, `hard_fails=0`) — not libp2p; prior FAIL 2026-08-16→18 on record |
| Self-check | `.\scripts\verify_hard_all.ps1` (fail-closed, no soak start) · `python scripts/verify_experimental_rd.py` · `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` |

## Proven vs not (honest)

| Proven (lab) | Not claimed |
|--------------|-------------|
| rust-libp2p swarm A–DB behind Cargo `libp2p` | Prod libp2p mesh cutover |
| Experimental 48h TCP+TLS soak (`hard_fails=0`) | Long-Range production / firm audit PDF |
| Advertised unique cap 20; circuit out of crate book | Public IPFS DHT / Noise = mTLS |
| AutoNAT/UPnP confirm admit-canonical-or-omit | Tip proof / public mainnet |
| Identify observed confirm charges canonical key | Firm audit PDF |
| Add/remove/expire match canonical charge key | NTFS replace = POSIX inode-atomic |
| Long-Range / EVM precompile labs | Public VPS testnet / launched mainnet |
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

- Hybrid pin (do not break): [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid)
- Contribute: [CONTRIBUTING](../CONTRIBUTING.md)
- GitHub About: [REPO_PROFILE](../.github/REPO_PROFILE.md)
