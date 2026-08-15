# Contributing — Absolute Blockchain Experimental

Thank you. This is the **R&D sandbox** ([Gruver87/experimental](https://github.com/Gruver87/experimental)) — rust-libp2p, Long-Range, EVM depth. It is **not** the audit-freeze Hybrid pin and **not** a launched public mainnet.

## Before you start

1. **30 seconds:** [docs/AT_A_GLANCE.md](docs/AT_A_GLANCE.md)
2. [DISCLAIMER.md](DISCLAIMER.md) · [EXPERIMENTAL_SANDBOX.md](EXPERIMENTAL_SANDBOX.md)
3. Industrial pin is the **other** repo: [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid). Do **not** open Hybrid PRs for Experimental kernels.

## 60-second setup

```bash
git clone https://github.com/Gruver87/experimental.git
cd experimental
pip install -r requirements.txt && cp .env.example .env
```

```powershell
python scripts/verify_experimental_rd.py
# ADR 0019 rust-libp2p (when native changed):
.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
```

## How to help

| Action | Why |
|--------|-----|
| Star / Watch Releases | Visibility of this sandbox |
| Issues + lab evidence | Bugs with hard-gate / lab stdout |
| Docs / PR | Fixes and tests → **`main`** |

## Branches

| Branch | Role |
|--------|------|
| **`main`** | Default — R&D landing |
| `rd/*` | Slice work before merge |

PR → **`main`**. We do not invent a fake “team PR” history.

## Development

```bash
git checkout -b rd/my-change
# ... edits ...
python scripts/verify_experimental_rd.py
git commit -m "feat(rd): description"
git push origin rd/my-change
```

Open a Pull Request on GitHub against **`main`**.

## Code style

- Minimal diff — do not refactor unrelated code
- Fail-closed: no silent fallbacks that paint green
- Money = satoshi integers
- Do not commit: `.env`, `data/`, keys, `__pycache__`, wheels

## Commit messages

```
feat(rd): ADR 0019 Slice CZ …
fix(rd): refuse uncharged AutoNAT confirm at cap
docs: update Experimental README release badge
test: extend verify_adr0019_libp2p_hard
```

## Questions

- Issues: https://github.com/Gruver87/experimental/issues
- Author: [@Gruver87](https://github.com/Gruver87)

Thank you for keeping Experimental honest — lab PASS is not prod cutover.
