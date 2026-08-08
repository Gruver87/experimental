# Experimental sandbox (NOT the audit pin)

This folder is a **local R&D copy** of Absolute Blockchain Ultimate Hybrid.

| Path | Role |
|------|------|
| `Desktop\Absolute_Blockchain_Ultimate_Hybrid` | **Audit freeze** - tip-v2 industrial pin `v1.3.1339-tip-v2-industrial`. Do not break for firm audit. |
| `Desktop\Absolute_Blockchain_Experimental` | **This copy** - libp2p / Long-Range / deeper EVM compatibility experiments. |

## Rules

1. **Push only** to [Gruver87/experimental](https://github.com/Gruver87/experimental) (`origin`).
2. Remote `audit-frozen` is fetch-only — **do not** push to the audit pin repo.
3. Work on `experimental/libp2p-longrange-evm` / `rd/*` branches.
4. Honesty: experimental != public mainnet != audited.

## Transport default

- **Default mesh transport:** native **TCP + TLS/mTLS** (ADR 0002).
- **libp2p:** opt-in only (`FEATURE_LIBP2P=true`, ADR 0018). Never on industrial JSON.
- **Long-Range:** lab only (`FEATURE_LONG_RANGE=true`, ADR 0017).

Profile F: [docs/sprouts/EXPERIMENTAL_RD_PROFILE.md](docs/sprouts/EXPERIMENTAL_RD_PROFILE.md)

## R&D tracks

| Track | Entry |
|-------|-------|
| EVM compat | [EVM_COMPAT_MATRIX.md](docs/sprouts/EVM_COMPAT_MATRIX.md) · precompiles 0x02/0x04 |
| Long-Range | `python scripts/long_range_lab.py` · ADR 0017 (checkpoint + AncestryWindow) |
| libp2p | `python scripts/libp2p_lab_smoke.py` · `python scripts/libp2p_two_node_lab.py` · ADR 0018 |

## Bootstrap this copy

```powershell
cd $env:USERPROFILE\Desktop\Absolute_Blockchain_Experimental
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\scripts\build_native.ps1
.\scripts\verify_project.ps1
```

Frozen audit original:

`C:\Users\vovun\Desktop\Absolute_Blockchain_Ultimate_Hybrid`
