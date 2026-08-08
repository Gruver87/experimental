# Profile F — Experimental R&D (Gruver87/experimental)

Lab-only profile for this sandbox repo. **Never** enable on audit-pin
`778888` industrial mesh JSON.

| Flag | Env | Default | Purpose |
|------|-----|---------|---------|
| `feature_libp2p` | `FEATURE_LIBP2P` | **false** | Dual-stack libp2p transport (ADR 0018); TCP+TLS remains default |
| `feature_long_range` | `FEATURE_LONG_RANGE` | **false** | Weak-subjectivity / Long-Range research (ADR 0017) |

## Transport honesty

- **Default:** native TCP + TLS/mTLS mesh (ADR 0002).
- **libp2p:** opt-in only when `FEATURE_LIBP2P=true` (dev/lab). Industrial compose keeps the flag **off**.

## EVM depth

EVM stays on Profile A apply path ([EVM_DEPTH.md](EVM_DEPTH.md)).
Compatibility gaps: [EVM_COMPAT_MATRIX.md](EVM_COMPAT_MATRIX.md).

## Gates

- `scripts/industrial_gate.py` requires `feature_libp2p=false` and `feature_long_range=false` on prod mesh JSON.
- Lab scripts: `scripts/long_range_lab.py`, `scripts/libp2p_lab_smoke.py`.

See [EXPERIMENTAL_SANDBOX.md](../../EXPERIMENTAL_SANDBOX.md).
