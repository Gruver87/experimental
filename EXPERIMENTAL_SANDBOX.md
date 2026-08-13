# Experimental sandbox (NOT the audit pin)

This folder / [Gruver87/experimental](https://github.com/Gruver87/experimental) is an **R&D copy** of Absolute Blockchain Ultimate Hybrid.

| Path | Role |
|------|------|
| `Desktop\Absolute_Blockchain_Ultimate_Hybrid` | **Audit freeze** — tip-v2 industrial pin `v1.3.1339-tip-v2-industrial`. Do not break for firm audit. |
| `Desktop\Absolute_Blockchain_Experimental` | **This copy** — libp2p / Long-Range / deeper EVM experiments. |

## Rules

1. **Push only** to [Gruver87/experimental](https://github.com/Gruver87/experimental) (`origin`).
2. Remote `audit-frozen` is fetch-only — **do not** push to the audit pin repo.
3. Work on `experimental/libp2p-longrange-evm` / `rd/*` branches (merge to `main` when ready).
4. Honesty: experimental ≠ public mainnet ≠ audited ≠ prod libp2p mesh.

## Transport default

- **Default mesh transport:** native **TCP + TLS/mTLS** (ADR 0002).
- **libp2p:** opt-in only (`FEATURE_LIBP2P=true`, ADR 0018 + ADR 0019 rust swarm). Never on industrial JSON.
- **Long-Range:** lab only (`FEATURE_LONG_RANGE=true`, ADR 0017).

Profile F: [docs/sprouts/EXPERIMENTAL_RD_PROFILE.md](docs/sprouts/EXPERIMENTAL_RD_PROFILE.md)

## R&D tracks

| Track | Entry |
|-------|-------|
| EVM compat | [EVM_COMPAT_MATRIX.md](docs/sprouts/EVM_COMPAT_MATRIX.md) · precompiles lab |
| Long-Range | `python scripts/long_range_lab.py` · ADR 0017 |
| libp2p (Python dual-stack) | `python scripts/libp2p_lab_smoke.py` · ADR 0018 |
| libp2p (rust industrial) | [ADR 0019](docs/adr/0019-rust-libp2p-industrial.md) Slices **A–BU** · `scripts/verify_adr0019_libp2p_hard.ps1` |

## Verify

```powershell
cd $env:USERPROFILE\Desktop\Absolute_Blockchain_Experimental

# Profile F units + Python labs
python scripts\verify_experimental_rd.py

# ADR 0019 rust-libp2p hard gate (83 steps after Slice BU; 84 with `-Rebuild`)
powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p_hard.ps1

# Optional: Hybrid (sibling) + Experimental as one operator view
powershell -ExecutionPolicy Bypass -File scripts\verify_absolute_unified.ps1 -Mode Standard
```

## Bootstrap this copy

```powershell
cd $env:USERPROFILE\Desktop\Absolute_Blockchain_Experimental
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\scripts\build_native.ps1
# For ADR 0019 rust labs, rebuild with libp2p feature (see README)
```

Frozen audit original:

`C:\Users\vovun\Desktop\Absolute_Blockchain_Ultimate_Hybrid`
