# Releasing — Experimental

How [Gruver87/experimental](https://github.com/Gruver87/experimental) ships **R&D** tags.
This is **not** the Hybrid industrial line (`v1.3.*-tip-v2-industrial`).

## Honesty first

- Tag green ≠ prod libp2p mesh ≠ public mainnet ≠ Hybrid audit pin
- Do **not** claim 48h soak unless `hard_fails=0` was actually run on this tree
- Do **not** reuse Hybrid tag names (`v1.3.*`)
- GitHub Release for this repo is a **prerelease** snapshot unless a future ADR says otherwise

## Versioning

| Field | Experimental | Hybrid (other repo) |
|-------|----------------|---------------------|
| Git tag | `rd-X.Y.Z` | `v1.3.*-industrial` |
| Default branch | `main` | `master` |
| GitHub Release | prerelease | Latest industrial pin |
| PyPI `abs_native` | **never** from this repo (name collision) | Hybrid only |

## Checklist (maintainer)

1. Land the slice on `main` (kernel + lab + hard gate).
2. Native libp2p wheel when Rust changed: `python scripts/verify_adr0019_libp2p_hard.py --rebuild`.
3. Docs: `README.md`, `docs/AT_A_GLANCE.md`, `CHANGELOG.md`, `RELEASE_NOTES_rd-X.Y.Z.md`.
4. Commit (exclude wheels / `.env` / `data/`).
5. Push `main`.
6. Annotated tag: `git tag -a rd-X.Y.Z -m "…"`.
7. `git push origin rd-X.Y.Z`.
8. `gh release create rd-X.Y.Z --prerelease --notes-file RELEASE_NOTES_rd-X.Y.Z.md`.

## Supply chain

- Dependabot: [`.github/dependabot.yml`](../.github/dependabot.yml)
- SBOM on release: [`.github/workflows/sbom-on-release.yml`](../.github/workflows/sbom-on-release.yml)
- Wheel attached to GitHub Release (libp2p feature). **PyPI upload is refused** for this repository.
- Secrets: `python scripts/check_secrets.py`

## See also

- [SUPPORT.md](../SUPPORT.md)
- [SECURITY.md](../SECURITY.md)
- Hybrid releasing (other tree): not this file
