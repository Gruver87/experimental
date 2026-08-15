---
name: Ops / verify fail
about: Experimental lab or hard gate fails locally — help triage without dumping secrets
title: "[OPS] "
labels: ["ops", "question"]
assignees: Gruver87
---

## What you ran

```text
python scripts/verify_experimental_rd.py
# or:
.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
```

Exit code / last FAIL step:

## Environment

- OS:
- Python:
- Git tag / commit:
- Native wheel installed with Cargo `libp2p`? (`abs_native.libp2p_available()`)

## Reports

Paste the **error lines** (redact secrets), not full DB dumps.

## Checklist

- [ ] No `.env` / private keys / wallet JSON pasted
- [ ] Re-read [AT_A_GLANCE](../../docs/AT_A_GLANCE.md) — is this a known R&D gap vs Hybrid pin?
