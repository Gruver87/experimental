## Summary

Brief description of what changed and **why**.

> This is **Absolute Blockchain Experimental** — R&D sandbox, **not** the Hybrid audit pin and **not** a launched public mainnet. Do not claim prod libp2p cutover without updating honesty docs.

## Related issues

Fixes #

## Type of change

- [ ] Bug fix
- [ ] ADR 0019 / libp2p slice
- [ ] Long-Range / EVM depth lab
- [ ] Documentation / evidence honesty
- [ ] Tests / CI
- [ ] Security-related
- [ ] Dependabot / deps only

## Checklist

- [ ] `python scripts/check_secrets.py` clean (no secrets)
- [ ] Local verify: `python scripts/verify_experimental_rd.py` **or** `.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild` when native/libp2p changed
- [ ] Docs / `CHANGELOG` / release notes updated if this is a shippable `rd-*` snapshot
- [ ] No false “mainnet / audit complete / soak / prod libp2p” claims
- [ ] PR targets **`main`** (never Hybrid `master` for R&D kernels)

## Test plan

- [ ] …
