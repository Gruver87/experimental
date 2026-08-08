# Experimental sandbox (NOT the audit pin)

This folder is a **local R&D copy** of Absolute Blockchain Ultimate Hybrid.

| Path | Role |
|------|------|
| `Desktop\Absolute_Blockchain_Ultimate_Hybrid` | **Audit freeze** - tip-v2 industrial pin `v1.3.1339-tip-v2-industrial`. Do not break for firm audit. |
| `Desktop\Absolute_Blockchain_Experimental` | **This copy** - libp2p / Long-Range / deeper EVM compatibility experiments. |

## Rules

1. **Do not push** from here to the audit GitHub `master` / audit tags.
2. If you want cloud backup for R&D, create a **new separate** GitHub repo and add it as another remote (e.g. `rd`).
3. Work on branch `experimental/libp2p-longrange-evm` (or feature branches off it).
4. Honesty still applies: experimental != public mainnet != audited.

## Suggested R&D tracks (out of audit scope)

- libp2p transport rewrite / dual-stack with current TCP+TLS mesh
- Long-Range / tip-proof research (not claimed on industrial pin)
- Broader EVM compatibility (beyond current subset)

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
