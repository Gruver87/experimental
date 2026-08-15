# rd-1.0.0 — ADR 0019 rust-libp2p through Slice CY (R&D snapshot)

**Tag:** `rd-1.0.0` (prerelease)  
**Repo:** [Gruver87/experimental](https://github.com/Gruver87/experimental)  
**Purpose:** first public GitHub Release for the Experimental sandbox so the repo has a real Releases page — **not** the Hybrid audit pin.

## What this tag proves (operator-local)

| Claim | Evidence |
|-------|----------|
| ADR 0019 slices **A–CY** (phase 102) | `docs/adr/0019-rust-libp2p-industrial.md` |
| Hard gate **114 PASS / 114** with `--rebuild` | `python scripts/verify_adr0019_libp2p_hard.py --rebuild` (2026-08-15) |
| Circuit never occupies rust-libp2p ExternalAddresses | Slices CW–CX labs |
| AutoNAT/UPnP `ExternalAddrConfirmed` admit-canonical-or-omit | Slice CY lab |
| Default mesh remains TCP+TLS | prod JSON `feature_libp2p=false` |

## What this tag does **not** claim

- Hybrid industrial pin / 48h soak / Phase 3–4 audit binder  
- External firm audit complete  
- Public mainnet / listed ABS  
- Prod libp2p cutover / Noise XX as mTLS peer-cert  
- NTFS replace = POSIX inode-atomic  
- `finality_quorum_live=true`

Industrial freeze stays on the **other** repo: [`v1.3.1339-tip-v2-industrial`](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/releases/tag/v1.3.1339-tip-v2-industrial).

## Verify

```powershell
git clone https://github.com/Gruver87/experimental.git
cd experimental
pip install -r requirements.txt
copy .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
python scripts/verify_experimental_rd.py
```

## Auditor / operator note

Start Experimental at [docs/AT_A_GLANCE.md](docs/AT_A_GLANCE.md).  
Start Hybrid firm engagement at Hybrid [AUDIT_ENGAGEMENT_BRIEF](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/blob/master/docs/AUDIT_ENGAGEMENT_BRIEF.md).
