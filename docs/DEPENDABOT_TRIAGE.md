# Dependabot triage (industrial harden)

**Updated:** 2026-08-08  
**Rule:** no kitchen-sink merges — only bumps that keep CI green and reduce risk.

## Hold (do not merge until migration PR is green)

| PR | Package | Why hold |
|----|---------|----------|
| [#7](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/7) | pyo3 0.22→0.29 | Required for pyo3 RUSTSEC clear; ~386 compile breaks (`new_bound` / `with_gil` API). Tracked; interim ignores in [`.cargo/audit.toml`](../.cargo/audit.toml) |
| — | rkyv via rust_decimal | `RUSTSEC-2026-0235` ignored interim (optional feature unused; `default-features=false` + `std` only). Prefer dropping optional lock edges later rather than enabling `rkyv` feature. |
| — | hickory-proto via libp2p-mdns | `RUSTSEC-2026-0119` ignored interim (ADR 0019 opt-in mDNS lab; needs upstream libp2p-mdns → hickory≥0.26). Prod mesh stays TCP+TLS. |
| — | ring 0.16 / rustls-webpki 0.101 via libp2p-tls | `RUSTSEC-2025-0009`, `0098/0099/0104` ignored interim (stale optional tls lock edges; Noise+TCP path only). Prefer lockfile prune or upstream libp2p-tls bump. |
| [#2](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/2) | rand 0.8→0.10 | Dev-dep churn; wait for pyo3 wave |
| [#10](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/10) | socket2 0.5→0.6 | Native P2P surface; needs soak |
| [#8](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/8) | wasmtime major | R&D FEATURE only; prod OFF |
| [#14](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/14) | cryptography major | Needs full pytest |
| [#12](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/12) | redis major | Mesh rate-limit path |
| [#13](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/13) | websockets major | WS RPC path |
| [#9](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/9) | pyjwt minor+ | Auth surface — CI required |
| [#11](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/11) | serde_json patch | Usually safe — merge after Tests green |
| [#15](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/15) | sha2 0.10→0.11 | Native hash surface — after pyo3 |

## Safe to merge when Actions CI is green (actions only)

| PR | Action |
|----|--------|
| [#3](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/3) | actions/checkout |
| [#5](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/5) | actions/setup-python |
| [#4](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/4) | docker/login-action |
| [#1](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/1) | docker/metadata-action |
| [#6](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/pull/6) | softprops/action-gh-release |

Merge order: checkout → setup-python → docker/* → gh-release. Re-run `security-audit.yml` + `test.yml` after each.

## Exit criteria

- `cargo audit` clean **without** pyo3 ignores (pyo3 ≥ 0.29)  
- No open Dependabot PRs older than 30 days without triage note here  
