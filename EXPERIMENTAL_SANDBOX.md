# Experimental sandbox (NOT the audit pin)

This folder is a **local R&D copy** of Absolute Blockchain Ultimate Hybrid.

| Path | Role |
|------|------|
| `Desktop\Absolute_Blockchain_Ultimate_Hybrid` | **Audit freeze** — tip-v2 industrial pin `v1.3.1339-tip-v2-industrial`. Do not break for firm audit. |
| `Desktop\Absolute_Blockchain_Experimental` | **This copy** — libp2p / Long-Range / deeper EVM compatibility experiments. |

## Rules

1. **Do not push** from here to the audit GitHub `master` / audit tags until you intentionally create a **separate** remote/repo.
2. A local `pre-push` hook blocks accidental `git push`.
3. Work on branch `experimental/libp2p-longrange-evm` (or further feature branches off it).
4. Honesty still applies: experimental ≠ public mainnet ≠ audited.

## Suggested R&D tracks (out of audit scope)

- libp2p transport rewrite / dual-stack with current TCP+TLS mesh
- Long-Range / tip-proof research (not claimed on industrial pin)
- Broader EVM compatibility (beyond current subset)

## Bootstrap this copy

```powershell
cd $env:USERPROFILE\Desktop\Absolute_Blockchain_Experimental
pip install -r requirements.txt
cp .env.example .env   # if needed — do not reuse prod secrets casually
.\scripts\build_native.ps1
.\scripts\verify_project.ps1
```

Frozen audit original stays untouched at:

`C:\Users\vovun\Desktop\Absolute_Blockchain_Ultimate_Hybrid`
