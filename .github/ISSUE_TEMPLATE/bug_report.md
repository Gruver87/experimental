---
name: Bug report
about: Report a reproducible defect in Experimental labs / ADR 0019 / Profile F
title: "[BUG] "
labels: ["bug"]
assignees: Gruver87
---

## Summary

Clear description of the failure.

## Environment

- OS:
- Python:
- Git tag / commit: (prefer latest `rd-*` tag on `main`)
- How you ran: ADR 0019 hard gate / `verify_experimental_rd.py` / solo `main.py` / other:

## Steps to reproduce

1.
2.
3.

## Expected vs actual

**Expected:**
**Actual:**

## Self-check already run?

```text
python scripts/verify_experimental_rd.py
# if native/libp2p:
.\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
```

Paste the **FAIL** step + stdout (redact secrets).

## Checklist

- [ ] Not a secrets leak (no `.env`, keys, or wallet JSON)
- [ ] Not claiming “public mainnet / audit complete / prod libp2p” without evidence
- [ ] This is Experimental — Hybrid pin bugs go to Ultimate Hybrid
