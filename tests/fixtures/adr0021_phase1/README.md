# ADR 0021 phase-1 / phase-3 goldens

Schema-stable refuse/accept vectors for:

- **Phase 1** — `mempool_validate_post_sig` (nonce / balance / address)
- **Phase 3** — `mempool_admit_evm_deploy` (EOF / unsupported opcode / STOP)

Consumed by:

- `tests/unit/test_adr0021_phase1_fixtures.py`
- `scripts/verify_adr0021_phase1.py` (and `.ps1`)

Do not treat these as mesh/soak evidence. Docker image must be rebuilt before
container nodes expose the new kernels.
