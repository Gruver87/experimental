# Professional repository posture — Experimental

Hygiene for [Gruver87/experimental](https://github.com/Gruver87/experimental).
This is the **R&D sandbox**, not the Hybrid audit pin.

## Industry baseline

| Practice | Typical peers | This sandbox |
|----------|---------------|--------------|
| Clear README + honesty | Required | Yes — R&D only, TCP+TLS default, not-mainnet |
| LICENSE | MIT/Apache | [LICENSE](../LICENSE) MIT |
| SECURITY.md + private disclosure | Required | [SECURITY.md](../SECURITY.md) |
| CONTRIBUTING + CoC | Common | Yes (English) |
| ISSUE / PR templates | Common | Yes |
| CODEOWNERS | Common | Yes |
| CI badges | Common | experimental-rd / tests / security |
| Dependabot | Common | Yes |
| SUPPORT.md | Common | Yes |
| Release process | Common | [docs/RELEASING.md](RELEASING.md) · tags `rd-X.Y.Z` |
| Audit status (honest) | Best practice | [docs/AUDITS.md](AUDITS.md) — pin is Hybrid |
| SBOM on release | Growing | `sbom-on-release.yml` |
| External audit PDF | Mainnet-grade | **Pending on Hybrid** — not this repo |

## What this sandbox leads on

- ADR 0019 rust-libp2p slices with fail-closed advertised cap (crate book of 20)
- Profile F labs: Long-Range, EVM precompiles, dual-stack adapter
- Evidence-first README: lab PASS ≠ prod libp2p cutover

## What this sandbox does **not** claim

- Hybrid 48h soak / Phase 3–4 binder
- Prod libp2p mesh
- Public mainnet / listed ABS
- External firm audit complete

Industrial pin: [Ultimate Hybrid `v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial).
