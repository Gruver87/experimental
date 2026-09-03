# Audits — honest status (Experimental)

**External third-party L1 / smart-contract / penetration audit: not completed.**

**This repository is not the audit pin.** External third-party L1 audit is tracked on
[Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid)
tag [`v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial).

This sandbox ships rust-libp2p / Long-Range / EVM-depth labs. Lab PASS ≠ firm audit PDF.

| Scope | Status | Notes |
|-------|--------|-------|
| ADR 0019 hard gate (`verify_adr0019_libp2p_hard.py`) | Active | Operator-local labs — **not** an external audit |
| Experimental R&D CI (`experimental-rd.yml`) | Active | Profile F + rust-libp2p labs |
| Security workflow (`security-audit.yml`) | Active | pip-audit + cargo-audit (scoped ignores) |
| Independent external audit report | **Pending — Hybrid pin** | Do not claim “audited” from this repo |
| Bug bounty | **Not configured** | Disclose via [SECURITY.md](../SECURITY.md) |
| Parallel R&D after libp2p 48h PASS | **Active (lab/docs)** | B1 closed [`3c801b87`](evidence/runs/3c801b87/); next = LR lab soak (B2) |

**Operator note (2026-09-03):** libp2p 48h **PASS** — evidence [`3c801b87`](evidence/runs/3c801b87/).
LR lab compose (`abs-lr-lab`) is wired; timed 2h **not** started. Do not enable
`feature_long_range` / `feature_oracles` / `feature_sharding` on `778888` JSON.

Related: [SECURITY.md](../SECURITY.md) · [EXPERIMENTAL_SANDBOX.md](../EXPERIMENTAL_SANDBOX.md) · [EXECUTION_ORDER.md](EXECUTION_ORDER.md) · Hybrid [AUDITS.md](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/AUDITS.md)
