# Changelog

All notable changes are documented here. Format based on [Keep a Changelog](https://keepachangelog.com/).

**Experimental tags:** `rd-X.Y.Z` on `main` (this repo).  
**Hybrid industrial tags:** `v1.3.*` live in [Ultimate Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) — not this Releases page.

**Current API wave:** `api_wave = 61` (check: `GET /status`)

Canonical language for this repository is **English**. Older inherited entries below may still mix Russian from the Hybrid fork history.

---

## [Unreleased]

### Experimental R&D

- Slice CZ: Identify observed confirm charges the canonical key (trailing `/p2p/<peer>` does not occupy a second unique slot); `confirm_observed_addr` still returns the raw observed string
- Slice DA: operator add/remove and behaviour expire match the canonical charge key (suffix cannot occupy or miss the crate slot)
- Slice DB: persist JSON load collapses trailing `/p2p/<peer>` so restore cannot occupy a second unique slot
- Hard gate **117 PASS / 117** with `--rebuild` (operator-local, 2026-08-15)
- EVM RPC: block-level `logsBloom` on `eth_getBlockByNumber` / `ByHash` reconstructed from the log index via `QueryFacadePort.get_evm_logs_by_block` (not getLogs caps; not a sealed consensus header). `transactionsRoot` / `receiptsRoot` still stub. Soak not run.
- EVM execution: nested inline CALL `RETURNDATACOPY` / `RETURNDATASIZE` use the live return buffer (child RETURN and REVERT data). Not a sealed header. Soak not run.
- EVM execution: inline STATICCALL refuses SSTORE/LOG/CREATE/TSTORE/SELFDESTRUCT and value-CALL; child storage is not committed; parent continues. Soak not run.
- EVM execution: nested CALL OOG burns all forwarded gas and does not commit child writes; REVERT still refunds unused gas. Parent continues. Soak not run.
- Long-Range (ADR 0017): persisted WS checkpoint (`ABS_WS_CHECKPOINT_PATH`, height+hash) survives restart; tip-import HARD REFUSE below the anchor and when the store is empty (`ws_no_anchor`). Digest-only JSON, not a live quorum. `feature_long_range=false` on industrial JSON. Soak not run.
- Long-Range (ADR 0017): checkpoint height is unique — a different hash at the anchor height is `anchor_hash_mismatch` (not a descendant), even if the caller claims shared ancestry; the exact checkpoint hash is `is_anchor` without a parent walk. Soak not run.
- Long-Range (ADR 0017): persist load requires a digest — omitting it no longer accepts a rewritten height/hash. Load error still fail-closed empty WS (tip-import `ws_no_anchor`), not a dropped gate. Digest-only, not BLS. Soak not run.
- Long-Range (ADR 0017): env seeds a WS checkpoint only when the persist file is missing; an existing empty `items` file must not re-seed from leftover `ABS_WS_ANCHOR_*` (cannot lower the anchor). Soak not run.
- Long-Range (ADR 0017): `P2PNode.import_block` enforce path refuses a child below a persisted WS anchor (`ws_below_ws_anchor`) and still imports a valid child of the checkpoint. Lab-armed via `FEATURE_LONG_RANGE` env only — industrial JSON stays `feature_long_range=false`; flag-off uses AncestryWindow only. Not a lab Wave-13. Soak not run.
- libp2p `/abs/wire`: `send_abs_wire` HARD REFUSE when egress prepare fails (no encode-around-admit fallback). 3-node Absolute v1/v2 ping + junk admit refuse lab. Not a hard-gate slice. `feature_libp2p=false` on industrial JSON. Soak not run.
- libp2p `/abs/wire`: inbound ACK `OK:` only for parseable ADR 0008 v1/v2 or lab pack_wire; garbage is `REFUSE:`, not inbox'd, not counted as Absolute recv. Soak not run.
- EVM: STATICCALL is sticky into nested CALL/DELEGATECALL (EIP-214); Python interpreter handoff refuses SSTORE/LOG/CREATE/TSTORE/SELFDESTRUCT under `_abs_read_only`; rust does not merge DELEGATECALL storage in static context. Soak not run.
- EVM: precompiles 0x01–0x09 on the apply-path nested CALL/STATICCALL hook and `call_contract` (not eth_call only). Identity/sha256 evidenced. Not a geth gas audit. Soak not run.
- EVM: host apply treats `to` in 0x01–0x09 as a message-call (not CREATE); mempool `_is_evm_deploy_tx` skips precompiles. Soak not run.
- EVM: nested CALL to an empty account (EOA) succeeds with empty returndata and still transfers value. No-code / precompile writeback drops `set_storage` so DELEGATECALL into 0x01–0x09 cannot wipe the caller. Soak not run.
- EVM: nested CALL/CALLCODE with value fail-closes when the caller cannot cover satoshi (`insufficient_call_value`): no child, no writeback mint via saturating_sub. Matches native inline Insufficient. Soak not run.

---

## [rd-1.0.0] - 2026-08-15

First GitHub Release for [Gruver87/experimental](https://github.com/Gruver87/experimental) (GitHub **Latest** on this repo). Not the Hybrid audit pin.

### ADR 0019 rust-libp2p

- Slices **A–CY** (phase 102) behind Cargo `libp2p`
- Hard gate **114 PASS / 114** with `--rebuild` (operator-local, 2026-08-15)
- Slice CX: relay-client circuit `ExternalAddrConfirmed` omitted from crate ExternalAddresses book
- Slice CY: AutoNAT/UPnP `ExternalAddrConfirmed` admit-canonical-or-omit (canonical charge key; at cap omit)
- Circuit `/p2p-circuit` never occupies the crate book (CW–CX)
- TCP+TLS remains default mesh; `feature_libp2p=false` on prod JSON

### GitHub surface

- README / AT_A_GLANCE / community files (CoC, Contributing, Security, Support) point at **this** repo
- Issue/PR templates and releasing docs use `rd-*` tags and `main`
- Wheel-on-release attaches a libp2p wheel to GitHub Release; **PyPI upload refused** (would collide with Hybrid `abs_native`)

### Inherited Profile F (already on `main`)

- `FEATURE_LIBP2P` / `FEATURE_LONG_RANGE` default + prod forced **off** on industrial JSON
- ADR 0017 Long-Range labs · ADR 0018 dual-stack adapter · EVM precompile waves
- CI: `.github/workflows/experimental-rd.yml`

---

## [Unreleased] (Hybrid-inherited history below)

The remainder of this file is the changelog inherited from the Hybrid tree at fork time, plus Experimental waves that landed before `rd-1.0.0`. Hybrid audit-pin releases are **not** published from this repository.

### Experimental R&D (Gruver87/experimental only)

- Profile F: `FEATURE_LIBP2P` / `FEATURE_LONG_RANGE` (default + prod forced **off** on industrial JSON)
- ADR 0017 Long-Range / weak-subjectivity research + `scripts/long_range_lab.py`
- ADR 0018 libp2p dual-stack transport adapter (phase-1 stub) + `scripts/libp2p_lab_smoke.py`
- EVM compat matrix + RPC wave: `eth_call` ABI word encode, `eth_estimateGas` create path, richer receipts
- CI fast lane: `.github/workflows/experimental-rd.yml` (no tip-v2 48h soak hard gate)
- Wave-2: WS `CheckpointCertificate` + AncestryWindow bridge; `DualStackDialer` + `libp2p_two_node_lab.py`; EVM precompiles sha256/identity
- Wave-3: EVM ecrecover (0x01); libp2p multiaddr + in-process swarm lab; optional WS tip-import gate on TipSafetyService / shadow (`FEATURE_LONG_RANGE` + optional `ABS_WS_ANCHOR_*`)
- Wave-4: EVM ripemd160 (0x03); libp2p 3-node in-process mesh lab; WS checkpoint JSON export/import
- Wave-5: EVM modexp (0x05, EIP-2565 gas); libp2p request/response lab; TipSafety WS tip-import gate in `long_range_lab`
- Wave-6: EVM blake2f (0x09 EIP-152); libp2p multi-hop relay lab; WS `CheckpointStore` rotation
- Wave-7: EVM bn254 ecAdd/ecMul/ecPairing (0x06–0x08 via `py_ecc`); libp2p discovery stub; `CheckpointStore.apply_latest`
- Wave-8: receipt `logsBloom`; `evm_precompile_lab`; libp2p Identify + `dial_discovered`; CheckpointStore JSON persist; `verify_experimental_rd`
- ADR 0019: rust-libp2p industrial path (Cargo feature `libp2p`, Noise/Yamux/Identify/Ping, `Libp2pNode` PyO3, `libp2p_rust_two_node_lab.py`); TCP+TLS remains default

### Industrial harden (no new features)

- **Public surface polish** — tighter README (evidence-first hero), ADR index, architecture ADR table 0008–0016, banner refresh; pin docs to `v1.3.1339-tip-v2-industrial`
- **Audit pin tag `v1.3.1339-tip-v2-industrial`** + [AUDIT_ENGAGEMENT_BRIEF.md](docs/AUDIT_ENGAGEMENT_BRIEF.md) for firm engagement
- **Phase 2 tip-v2 48h soak PASS** (2026-08-05→07): `logs/soak_report_tipv2_48h_rerun.json` (`passed=true`, fail=0, mesh_warn=0); evidence `docs/evidence/runs/375d14f/`
- **Phase 3 ops cutover dry-run PASS** (2026-08-07): bridge OFF + ceremony + secrets dry-run + DR DockerMesh1; evidence `docs/evidence/runs/phase3-da25c34/`
- **Phase 4 audit binder READY** (2026-08-07): industrial_gate `--min-soak-hours 48` + `export_audit_pack`; tracker 6/8 firm-owned open; evidence `docs/evidence/runs/phase4-691329c/`
- Soft-skip prod adversarial drills in CI; `/health/ready` soft wire_probe; soak scoring + `docker_prod_3node` `--detach` fix (`375d14f`)
- Phase 1: rustfmt tip cutover sources; cargo-audit scoped pyo3 ignores + Dependabot triage doc
- Gap analysis synced to Wave C tip-v2; threat model + audit scope letter; industrial runbook
- DR backup scripts tolerate docker stderr (PowerShell Stop trap)
- Tip-v2 re-smoke + prior Aug 2–4 48h FAIL (historical only; superseded by Aug 5–7 PASS)
- `export_audit_pack` / `industrial_gate` recognize tip-v2 evidence under `docs/evidence/runs/`
- Gates load `.env` for ceremony pin; skimmer honesty (AT_A_GLANCE Phase 3–4)

### Wave D — bake mesh harden + attestation/rate soft-refuse

- Soft-refuse `attestation_local_height_mismatch`, ingress `rate_limit_*`, and `tip_unknown_parent` (not state_root response codes — those must still dispatch for wire probe)
- Restore lexicographic dial ownership replace; skip remembering docker IP dial targets
- Canonical bootstrap dials only (mesh-1→2/3, mesh-2→3, mesh-3 empty) to avoid inverted dual-dial
- Bind bootstrap hostname→peer_id so inbound-IP peers cover seeds
- `PeerConnection.close` cancels send worker (no asyncio “Task was destroyed” storm)
- Longer state_root wire probe wait (15s); GET_PEERS on priority set
- Consistency re-probe keeps last-known green while wire solicit runs (stops `/health/ready` flicker during multi-second probes)
- Priority P2P sends (state_root / get_block / …) bypass the gossip send queue so attestations cannot starve wire probes
- `health_watch` truncates its log at start (soak FAIL counts are session-scoped)
- Image-baked ready×3 + probe on `abs-blockchain-prod:local`; short 2h soak evidence under commit SHA

### Wave A — TLS dual-dial ownership + ready gate

- Canonical peer dial ownership (lexicographic node_id): keep one live registration under A↔B dual dial
- Native TLS `close_notify` before TCP shutdown
- Bootstrap/discovery dials coalesce via `_schedule_connect`
- `verify_p2p_ci` asserts `/health/ready` PASS ×3; CI artifact `mesh-ready-gate`

### Wave B — evidence + secrets/CI harden

- `scripts/package_mesh_evidence.py` + `docs/evidence/`
- Prod SecretManager refuses unknown raw-env names (escape via `ABS_SECRET_ALLOW_RAW`)
- GitHub Actions SHA-pinned; SBOM expands to Cargo + container note

### Wave C — tip+apply satoshi integer cutover

- Tip encoding v2 (`b_satoshi`, `SATOSHI_MULTIPLIER=1e6`) active when `state_root_encoding_version>=2` **and** `state_root_v2_ceremony_ok` (local prod mesh JSON armed; fresh volumes only)
- Native Rocks tip hasher / `account_payload_row` emit integer `b_satoshi` only; v1 float `"b"` remains Python-only for legacy
- StateService apply / fees / gas / reward use satoshi ints (`plan_transfer_fees_sat`, `ApplyBlockResult.burned` satoshi); ABS float at display/wire edges
- SQLite tip path SELECTs `balance_satoshi`; industrial_gate soak needle requires v2/`b_satoshi` contract
- Finality `quorum_live` only when config-armed **and** QC reached; weak-subjectivity honesty surface (prior Wave C honesty)

### Mesh — genesis artifact + tip height-0 + P2P IO

- Shared ceremony genesis JSON (`sync/genesis_artifact.py`, `GENESIS_ARTIFACT_PATH`) so followers import leader #0 + founder — no divergent local mint
- TipSafety / STATUS / handshake treat height **0** as present; empty genesis import skips reward mutation
- Native P2P short-poll reads (`set_read_timeout_only`) — avoid write-starve under long blocking reads
- Soft-refuse `tip_duplicate` / transport EOF (no PeerManager ban on TLS close_notify churn)
- Honesty: chain sync proven; `/health/ready` peers still **partial** under TLS reconnect until Wave A validated on live mesh

### P2P — mesh soft-refuse (probe 503)

- Stop `announce_validator` gossip in prod/staging (ceremony/manifest only)
- Soft-refuse for `validator_register_disabled` and unsolicited solicit races
- Probe FAIL path when peers=0 after bans → `peers_alive=false`

### Architecture — ADR 0016 feature sprouts

- ADR 0016: one industrial L1 tip; FEATURE_* via profiles (App / Bridge / L2 sandbox / Shard), never kitchen-sink on `778888`
- Tip-safety stage-1.5: bounded `AncestryWindow` (not Long-Range)
- `features/nft_ports.py`; NFT → `app-profile`; mesh JSON freeze `feature_*=false`
- Prod compose healthcheck `/health/live` (not `/ready`) — avoid depends_on ↔ peer-quorum chicken-egg
- Serialize `P2PRateLimitTable` + per-conn native IO locks
- Docs: `docs/sprouts/*`; architecture mermaid + honest Proven table

### Docs / GitHub UX

- First-screen honesty: chain sync **Proven**, `/health/ready` **Partial**; ADR **0001–0016**

## [1.3.1338-deterministic-core] — 2026-07-30

### Consensus / determinism

- Forest-aware LMD-GHOST genesis among `parent=None` roots; parent-stub upgrade on late block materialization
- Native `ghost_select_head` parity (heaviest subtree + lex tie-break)
- QueryPort honesty: `NullQueryFacade` no longer swallows `eth_getLogs` (fallback to `bc.db` until attach)
- Industrial `final_audit` / facade needles follow `StateService` / `TxPipeline`

### Observability & secrets (ADR 0015)

- `MetricsExporterPort` + Prometheus snapshot path on `/metrics` (`abs_tps`, chain window TPS)
- `secret_mgmt/` SecretManagerPort (env/K8s, Vault KV, file refuse in prod)
- Boot resolves wallet / BFT keys via SecretManager; `SECRET_BACKEND`
- `docs/DISASTER_RECOVERY.md` runbooks

### Prior same-day port stack (already on trunk)

- ADR 0010 BridgePort · ADR 0011 QueryFacade · ADR 0012 Chaos · ADR 0014 Graceful shutdown

## [1.3.205] — 2026-07-26

### Mempool — unparseable-nonce refuse

- P2P refuses junk / Inf `nonce` before `validate_transaction` (`nonce_unparseable`)
- Soft DoS honesty — no OverflowError into ingest; complements nonce_negative / nonce_too_high
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / account-nonce sequencing

## [1.3.204] — 2026-07-26

### Mempool — unparseable-value refuse

- P2P refuses junk `value` / `amount` before `validate_transaction` (`value_unparseable`)
- Soft DoS honesty — no TypeError into ingest; complements value_negative / value_non_finite
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / amount-cap economics

## [1.3.203] — 2026-07-26

### Mempool — unparseable-gas refuse

- P2P refuses Inf/junk `gas` before `validate_transaction` (`gas_unparseable`)
- Soft DoS honesty — no OverflowError into ingest; complements gas_negative / gas_too_high
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / Rust gas PQ

## [1.3.202] — 2026-07-26

### Mempool — max-value refuse

- P2P refuses oversized wire `value` before `validate_transaction` (`value_too_high`)
- Soft DoS honesty — default 221M ABS (aligns `max_supply`); fantasy amounts fail before DB
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / full tokenomics

## [1.3.201] — 2026-07-26

### Mempool — max-fee refuse

- P2P refuses oversized wire `fee` before `validate_transaction` (`fee_too_high`)
- Soft DoS honesty — default 1e9 ABS; complements `fee_too_low`
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / fee-market

## [1.3.200] — 2026-07-26

### Mempool — max-nonce refuse

- P2P refuses oversized wire `nonce` before `validate_transaction` (`nonce_too_high`)
- Soft DoS honesty — default 1e12 (MAX_P2P_HEIGHT-style); fantasy nonces fail before DB
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / nonce-window

## [1.3.199] — 2026-07-26

### Mempool — max-to refuse

- P2P refuses oversized wire `to` before `validate_transaction` (`to_too_large`)
- Soft DoS honesty — mirrors `from_too_large`; shares `max_addr_chars` / `MAX_P2P_ADDR_LEN`
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / checksum

## [1.3.198] — 2026-07-26

### Mempool — max-from refuse

- P2P refuses oversized wire `from` before `validate_transaction` (`from_too_large`)
- Soft DoS honesty — default 128 chars, aligns Rust `MAX_P2P_ADDR_LEN`
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / checksum

## [1.3.197] — 2026-07-26

### Mempool — max-hash refuse

- P2P refuses oversized wire `hash` before `validate_transaction` (`hash_too_large`)
- Soft DoS honesty — default 128 chars, aligns Rust `MAX_P2P_HASH_LEN`
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / hash↔body bind

## [1.3.196] — 2026-07-26

### Mempool — empty-hash refuse

- P2P refuses empty/whitespace wire `hash` before `validate_transaction` (`hash_empty`)
- Soft DoS honesty — empty hash skipped `duplicate_tx`; this closes that gap
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / hash↔body bind

## [1.3.195] — 2026-07-26

### Mempool — empty-to refuse

- P2P refuses empty/whitespace `to` before `validate_transaction` (`to_empty`)
- Soft DoS honesty — mirrors `from_empty`; cheaper than `missing_address`
- Honesty: not tip proof / Long-Range / libp2p / public mainnet / contract-create

## [1.3.194] — 2026-07-26

### Mempool — non-finite fee refuse

- P2P refuses NaN/Inf `fee` before `validate_transaction` (`fee_non_finite`)
- Soft DoS honesty — complements `fee_negative` (NaN/Inf slip past `< 0`)
- Honesty: not tip proof / Long-Range / libp2p / public mainnet

## [1.3.193] — 2026-07-26

### Mempool — non-finite value refuse

- P2P refuses NaN/Inf `value` before `validate_transaction` (`value_non_finite`)
- Soft DoS honesty — complements `value_negative` (NaN/Inf slip past `< 0`)
- Honesty: not tip proof / Long-Range / libp2p / public mainnet

## [1.3.146] — 2026-07-26

### P2P — catch-up tip probe + head↔height bind

- Known local `peer.head` must match claimed height before ahead catch-up
- Solicit local-tip `state_root` before `get_blocks` download (`p2p_catch_up_tip_probe`)
- Honesty: not tip proof / Long-Range / libp2p / mainnet

## [1.3.145] — 2026-07-26

### P2P — peer score quality (strikes + import fails)

- Soft health score penalizes strikes and failed imports for eclipse prune / evict
- Failed gossip/sync imports attributed to sourcing peer
- Honesty: not tip proof / hard isolation / Long-Range / libp2p / mainnet

## [1.3.144] — 2026-07-26

### P2P — solicit-armed mempool shell (skip unsolicited ECDSA)

- Native `read_message_loop_events` refuses unarmed `MSG_MEMPOOL` before batch sig verify
- Python arms only during mempool pull waiter (`kind=mempool`)
- Honesty: not anti-Sybil / tip proof / libp2p / mainnet

## [1.3.143] — 2026-07-26

### Mempool — cheap refuse + new_tx primary rate

- `MSG_NEW_TX` removed from rate-limit exempt (gossip on primary budget)
- Dup-hash refuse before `validate_transaction`; sig-before-DB order
- P2P ingest skips second chain validate via `chain_prevalidated`
- Honesty: not anti-Sybil / fee-market / Long-Range / full Rocks rewrite

## [1.3.142] — 2026-07-26

### Tests — Standard pytest solicit-only needle

- Align unsolicited state_root honesty needle with v1.3.138 solicit-only strike
- Unblocks full suite / `check_all -Mode Standard`
- Honesty: not tip proof / libp2p / mainnet

## [1.3.141] — 2026-07-26

### Sync — same-height state match is wire-only

- `sync_state` no longer invents consistency from local `get_block(peer_height)`
- Only wire same-height roots may paint `state_consistent=True`
- Honesty: not tip proof / fork-choice / libp2p / mainnet

## [1.3.140] — 2026-07-26

### Sync — never invent peer.head from local blocks

- `request_heads` skips peers with empty head (no local tip invent)
- Aligns with catch-up-require-head; check_all evidence tag refreshed
- Honesty: not tip proof / fork-choice / libp2p / mainnet

## [1.3.139] — 2026-07-26

### P2P — catch-up requires peer.head

- Height-only ahead claims without peer.head refuse get_blocks catch-up
- Closes soft ownership hole after fantasy-head clear on height cap
- Honesty: not tip proof / fork-choice / libp2p / mainnet

## [1.3.138] — 2026-07-26

### P2P + ops — solicit-only state_root + ceremony status

- Unsolicited state_root_response struck; never flips consistency
- `ceremony_status.py` in `check_all` — honest readiness, never invents pin
- Honesty: not tip proof / mainnet / completed audit

## [1.3.137] — 2026-07-26

### P2P — attestation local-head + solicit-only block responses

- Known target_hash ⇒ target_height must match local header
- Unsolicited MSG_BLOCKS/MSG_BLOCK struck; waiter-only fulfillment
- Honesty: not tip proof / attestation crypto binding / libp2p / mainnet

## [1.3.136] — 2026-07-26

### P2P — soft attestation slot-ahead ownership gate

- Far-ahead attestations refused before LMD apply/relay
- `p2p_max_attestation_slot_ahead` (default matches height ahead window)
- Honesty: not attestation↔head crypto / tip proof / libp2p / mainnet

## [1.3.135] — 2026-07-26

### P2P — local state_root consistency + tip ownership completion

- Known local header ⇒ peer state_root must match; historical expected_head fixed
- Handshake height-ahead; status capped height refuses fantasy peer.head
- Honesty: not merkle tip proof / fork-choice / libp2p / mainnet

## [1.3.134] — 2026-07-26

### P2P — soft NEW_BLOCK height-ahead ownership gate

- Fantasy `MSG_NEW_BLOCK` cannot inflate peer tip beyond `p2p_max_peer_height_ahead`
- Over-window announces refused before sync/import steering
- Honesty: not tip proof / fork-choice / libp2p / mainnet

## [1.3.133] — 2026-07-26

### P2P — authenticated bootstrap seed pins

- `P2P_BOOTSTRAP_PINS` binds seed host:port to TLS fingerprint (+ optional node_id)
- Impostor on seed address does not cover bootstrap; handshake rejects pin mismatch
- Honesty: not DHT trust roots / tip proof / libp2p / mainnet

## [1.3.132] — 2026-07-25

### P2P — resilient bootstrap redial

- Missing bootstrap seeds keep dialing even when other peers exist
- Outbound `dial_target` covers hostname seeds after DNS resolve
- Honesty: not authenticated seed identity / libp2p / mainnet

## [1.3.131] — 2026-07-25

### P2P — solicit-only mempool + status height ahead cap

- Unsolicited `MSG_MEMPOOL` struck; only active get_mempool waiters ingest
- Status `peer.height` capped to local tip + `p2p_max_peer_height_ahead`
- Honesty: not tip proof / anti-Sybil / libp2p / mainnet

## [1.3.130] — 2026-07-25

### Repo professionalism + soft state_root expected_head

- Dependabot, EditorConfig, SUPPORT, AUDITS/RELEASING/REPO_PROFESSIONAL docs, SBOM-on-release
- State_root waiters optionally bind peer `head_hash` to local expected head
- Honesty: not external audit / tip proof / libp2p / mainnet

## [1.3.129] — 2026-07-25

### P2P — outbound state_root height honesty

- Historical state_root probes return that block’s root/hash (never mislabeled tip)
- Ahead/missing requests refused; unsolicited responses cannot inflate peer.height
- Honesty: not tip proof / fork-choice / libp2p / mainnet

## [1.3.128] — 2026-07-25

### P2P — discovery dialability + soft height↔head binding

- MSG_PEERS/GET_PEERS filter non-dialable literal private IPs (unless allow_private)
- Handshake/status: height>0 requires 32-byte hex head_hash (soft binding, not tip proof)
- Honesty: not DHT / libp2p / tip proof / mainnet

## [1.3.127] — 2026-07-25

### P2P — request-bound state_root_response height gate

- Waiters for state_root probes require matching response height (+ digests)
- Wrong-height answers never fulfill consistency waiters
- Honesty: not root-belongs-to-head / tip proof / fork-choice / libp2p / mainnet

## [1.3.126] — 2026-07-25

### P2P — request-bound singular block response hash gate

- Sync waiters for `get_block_by_hash` require matching claimed hash (or null not-found)
- Mismatched well-formed blocks never fulfill fork-reconcile waiters
- Honesty: not tip proof / fork-choice / full sync ownership / libp2p / mainnet

## [1.3.125] — 2026-07-25

### P2P — request-bound blocks response + prod native shell fail-closed

- Sync waiters validate `blocks` against requested range/parent/continuity (Rust)
- Rejected responses never fulfill waiters with attacker data
- Prod/`require_native_crypto` requires `read_message_loop_events`; ready exposes shell flag
- Honesty: not full sync ownership / tip proof / fork-choice / libp2p / mainnet

## [1.3.124] — 2026-07-25

### P2P — native status.head_hash digest semantic gate

- Loop-shell: non-empty `status.head_hash` must be 32-byte hex (optional `0x`)
- Empty / null / non-object keepalives remain OK
- Honesty: height↔hash binding / peer auth / full message-loop not claimed

## [1.3.123] — 2026-07-25

### P2P — native state_root_response digest semantic gate

- Loop-shell requires 32-byte hex `state_root` + `head_hash` (optional `0x`)
- Strike: `bad_state_root_digest`; shape still `bad_state_root_response`
- Honesty: correlation / proof / sync ownership / full message-loop not claimed

## [1.3.122] — 2026-07-25

### P2P — native singular block response hash semantic gate

- Loop-shell verifies non-null `block` payloads (canonical hash); `null` = not-found OK
- Completes new_block → blocks → block hash ingress sequence
- Honesty: request correlation / import / full message-loop not claimed

## [1.3.121] — 2026-07-25

### P2P — native blocks batch hash semantic gate + Makefile UX

- Loop-shell verifies each block in sync `blocks` arrays (canonical hash)
- Root `Makefile` (`build` / `test-quick` / `test-gate` / `mesh-up`) for Linux/macOS
- Honesty: import/fork-choice / full message-loop / crates split / fake PR theater not claimed

## [Unreleased]

### Docs — skimmer README UX

- README: 30-second status card, 60-second start, repo layout, jump TOC (above the fold)
- `docs/AT_A_GLANCE.md` one-screen card; CONTRIBUTING 60s setup
- Honesty unchanged: not public mainnet; no fake PR theater / crates mega-split

## [1.3.120] — 2026-07-25

### P2P — native new_block canonical-hash semantic gate

- Loop-shell rejects `new_block` when claimed hash ≠ canonical recompute
- Strike: `bad_block_hash`; shape still `bad_block_announce`
- Honesty: parent/proposer/state_root / full message-loop / libp2p not claimed

## [1.3.119] — 2026-07-25

### P2P — native mempool batch signature semantic gate

- Loop-shell verifies each tx in `mempool` batches with local chain_id preimage
- Reuses new_tx strike reasons; shape failures stay `bad_mempool_batch`
- Honesty: nonce/balance ingest / full message-loop / libp2p not claimed

## [1.3.118] — 2026-07-25

### P2P — native new_tx signature semantic gate

- Loop-shell verifies singular `new_tx` signatures with local chain_id preimage
- Strike reasons: `missing_tx_signature` / `missing_tx_public_key` / `bad_tx_signature`
- Honesty: mempool batch / state checks / full message-loop not claimed

## [1.3.117] — 2026-07-25

### P2P — native attestation semantic gate

- Loop-shell verifies attestation identity + secp256k1 before dispatch
- Strike reasons: `bad_attestation_identity` / `bad_attestation_sig`
- Honesty: tx semantic / full message-loop / libp2p not claimed

## [1.3.116] — 2026-07-25

### P2P — native message-loop event shell

- `read_message_loop_events` ordered dispatch/strike/keepalive/idle/eof
- Python `_message_loop` consumes shell when available; handlers/bans stay Python
- Honesty: still not full message-loop ownership / libp2p

## [1.3.115] — 2026-07-25

### P2P — native handshake policy fuse + Max-gate fixes

- `handshake_roundtrip` enforces chain_id + TLS identity (fingerprint allowlist stays Python)
- `/health/ready` accepts native `_native_listener` for prod `p2p_running`
- K8s configmap + prod smoke profile sync `p2p_native_transport`
- Honesty: still not full message-loop / libp2p

## [1.3.114] — 2026-07-25

### P2P — prod-mandatory native transport

- Prod defaults/requires `p2p_native_transport=true` (config + `prod_gate`)
- Fail-closed when native transport required but unavailable (no asyncio fallback)
- Skip Python dual shape re-validate on native read path
- Honesty: still not full message-loop / libp2p

## [1.3.113] — 2026-07-25

### P2P — native handshake payload gate

- Fail-closed handshake/ack shape check on `handshake_roundtrip` (`bad_handshake_payload`)
- Chain-id / TLS / policy remain Python
- Honesty: still not full message-loop / libp2p

## [1.3.112] — 2026-07-25

### P2P — native cross-shard shape gates

- Fail-closed `cross_shard_tx` / `cross_shard_ack` / `shard_migration` on native read
- Strike reasons: `bad_cross_shard_tx` / `bad_cross_shard_ack` / `bad_shard_migration`
- Honesty: still not full message-loop / libp2p

## [1.3.111] — 2026-07-25

### P2P — native state-root shape gates

- Fail-closed `state_root_request` / `state_root_response` on native read
- Strike reasons: `bad_state_root_request` / `bad_state_root_response`
- Honesty: still not full message-loop / libp2p

## [1.3.110] — 2026-07-25

### P2P — native peer discovery shape gates

- Fail-closed `peers` / `validator_register` on native read
- Strike reasons: `bad_peers_list` / `bad_validator_register`
- Honesty: still not full message-loop / libp2p

## [1.3.109] — 2026-07-25

### P2P — native singular block payload gate

- Fail-closed non-null `block` shape check on native read (`bad_block_payload`)
- Null not-found responses still allowed (Python parity)
- Honesty: still not full message-loop / libp2p

## [1.3.108] — 2026-07-25

### P2P — native tx gossip shape gates

- Fail-closed `new_tx` / `mempool` on native read (`bad_wire_tx` / `bad_mempool_batch`)
- Unified `check_ingress_shape_gates` helper on read path
- Honesty: still not full message-loop / libp2p

## [1.3.107] — 2026-07-25

### P2P — native block fetch shape gates

- Fail-closed `get_blocks` / `get_block_by_hash` / `blocks` on native read
- Strike reasons: `bad_get_blocks` / `bad_get_block_by_hash` / `bad_blocks_batch`
- Honesty: still not full message-loop / libp2p

## [1.3.106] — 2026-07-25

### P2P — native block sync shape gates

- Fail-closed `new_block` announce check on native read (`bad_block_announce`)
- Fail-closed `get_block` height check on native read (`bad_get_block`)
- Honesty: still not full message-loop / libp2p

## [1.3.105] — 2026-07-25

### P2P — native attestation shape gate

- Fail-closed attestation shape check on native read (`bad_attestation_shape`)
- Signature verify remains Python
- Honesty: still not full message-loop / libp2p

## [1.3.104] — 2026-07-25

### P2P — native status payload gate

- Fail-closed `status` shape check on native read (`bad_status_payload`)
- Null status keepalives still allowed (Python parity)
- Honesty: still not full message-loop / libp2p

## [1.3.103] — 2026-07-25

### P2P — native mid-session handshake gate

- `session_established` rejects mid-session `handshake`/`handshake_ack` on native read
- Python marks session after successful `_do_handshake`; WireReject bumps rejects
- Honesty: still not full message-loop / libp2p

## [1.3.102] — 2026-07-25

### P2P — native I/O timeout config

- Config `p2p_native_io_timeout_ms` applied via `set_timeout_ms` on accept/connect
- Aligns asyncio native-read `wait_for` with socket timeout
- Honesty: still not full message-loop / libp2p

## [1.3.101] — 2026-07-25

### P2P — native batch/chunk config knobs

- Config `p2p_native_read_batch` / `write_batch` / `read_chunk` (+ env)
- Shared Rust clamp helpers; status + Prometheus gauges
- Honesty: still not full message-loop / libp2p

## [1.3.100] — 2026-07-25

### P2P — native housekeeping payload gate

- Fail-closed `ping`/`pong`/`get_mempool`/`get_peers` shape check on native read
- Closes auto-keepalive bypass of Python `_housekeeping_payload_ok`
- Honesty: still not full message-loop / libp2p

## [1.3.99] — 2026-07-25

### P2P — native keepalive consume (pong + touch)

- Consume inbound `pong` on native read path; report `keepalive_touches`
- Empty keepalive-only batches touch `last_seen` via synthetic pong in Python
- Honesty: still not full message-loop / libp2p

## [1.3.98] — 2026-07-25

### P2P — native auto-pong keepalive

- `read_message` / `read_messages` can auto-reply to ping and omit it from results
- Config `p2p_native_auto_pong` (default true with native transport)
- Honesty: keepalive only — still not full message-loop / libp2p

## [1.3.97] — 2026-07-25

### P2P — native peer cert CN/SAN identities

- `peer_cert_identities` extracts CN + SAN DNS/URI from rustls peer cert
- Native TLS handshake identity bind works without asyncio writer
- Honesty: still not full message-loop / libp2p

## [1.3.96] — 2026-07-25

### P2P — native handshake_roundtrip I/O fuse

- `handshake_roundtrip` writes/reads handshake envelopes in one native call
- `_do_handshake` wired; validate/chain_id/TLS policy stay Python
- Honesty: still not full message-loop / libp2p

## [1.3.95] — 2026-07-25

### P2P — native write_messages / write_payloads batch

- Batch encode+write and batch write of prepared payloads
- Send-loop drains queue into one native hop when possible
- Honesty: still not full message-loop / libp2p; egress admit stays Python

## [1.3.94] — 2026-07-25

### P2P — native read_messages batch pump

- `P2PNativeConn.read_messages` drains up to N decoded envelopes per call
- `PeerConnection.recv` queues `_pending_msgs`; admit stays Python
- Honesty: still not full message-loop / libp2p; default still asyncio

## [1.3.93] — 2026-07-25

### P2P — native write_message pump (encode + write)

- `P2PNativeConn.write_message` fuses wire encode + write in one call
- `PeerConnection._write_message` wired; egress prepare/admit remains Python when enabled
- Honesty: still not full message-loop / libp2p; default still asyncio

## [1.3.92] — 2026-07-25

### P2P — native read_message pump (frame + wire parse)

- `P2PNativeConn.read_message` fuses framed read + wire parse in one call
- `PeerConnection.recv` uses it on native transport; rate admit remains Python when ingress on
- Honesty: still not full message-loop / libp2p; default still asyncio

## [1.3.91] — 2026-07-25

### P2P — native rustls TLS on transport slice

- rustls mTLS for `P2PNativeListener` / `P2PNativeConn` (CERT_REQUIRED, no hostname check)
- Native + TLS allowed when material valid; peer cert SHA-256 fingerprint exposed
- Honesty: not libp2p; identity bind still Python; default still asyncio

## [1.3.90] — 2026-07-25

### P2P — native plain-TCP transport slice

- `P2PNativeListener` / `P2PNativeConn`: accept, connect, framed read/write in Rust
- Opt-in `p2p_native_transport` (default off; TLS incompatible)
- Honesty: not TLS/libp2p; handshake/dispatch still Python

## [1.3.89] — 2026-07-25

### P2P — Sybil / Eclipse hardening

- Public-only `/24`/`/64` subnet diversity + reserved outbound dial slots on `P2PConnectionGovernor`
- Eclipse ratio telemetry + densest-subnet prune; Prometheus subnet/reserved/eclipse metrics
- Honesty: not ASN/BGP diversity; not full Rust transport; private mesh exempt from subnet caps

## [1.3.88] — 2026-07-25

### Native — P2P kernel fuzz / smoke

- `fuzz_api`: frame feed, wire parse/roundtrip, rate+egress admit sequences
- `cdylib`+`rlib`, cargo-fuzz targets, `scripts/fuzz_native.ps1`, CI workflow
- Honesty: fuzz ≠ full audit; TCP/message loop still Python; not public mainnet

## [1.3.87] — 2026-07-25

### P2P — unified native egress prepare

- `p2p_egress_prepare`: encode + allowlist + size + egress admit (mirror of ingress)
- Wired into `PeerConnection._prepare_outbound` (send queue + priority)
- Status: `native_p2p_egress_prepare`
- Honesty: not full Rust transport; TCP/message loop still Python

## [1.3.86] — 2026-07-25

### P2P — native NDJSON line framer

- `P2PLineFramer`: buffered chunk → complete `\n` lines; fail-closed oversize before newline
- Wired into `PeerConnection._read_wire_line` (chunked `read` + framer)
- Honesty: not full Rust transport; TCP/message loop still Python

## [1.3.85] — 2026-07-25

### P2P — outbound egress bandwidth (cost-weighted)

- Separate egress byte window on `P2PRateLimitTable`; `admit_egress` / `p2p_egress_admit`
- Wired into `PeerConnection` send path before write
- Config: `p2p_max_outbound_bytes_per_sec`; metrics: `abs_p2p_egress_rejects_total`
- Honesty: not full Rust transport; TCP/message loop still Python

## [1.3.84] — 2026-07-25

### EVM — inline CREATE → save_account writeback journal

- Successful inline CREATE/CREATE2 appends `save_account` to `pending_writeback_ops` (before `transfer_value`)
- Marker: `native_inline_writeback_create`
- Honesty: full Rust P2P transport still not claimed; not public mainnet

## [1.3.83] — 2026-07-25

### EVM — inline value → satoshi writeback journal

- Successful inline value CALL/CREATE appends `transfer_value` to `bridge_state.pending_writeback_ops`
- Adapter flushes into nested writeback / tx journal (`_take_bridge_pending_writeback`)
- Markers: `native_inline_writeback_value`, `native_inline_writeback_ops`
- Honesty: inline CREATE `save_account` journal still not claimed; not public mainnet

## [1.3.82] — 2026-07-25

### EVM — CREATE/CREATE2 eligible init with RETURN runtime

- Leaf-eligible init (no CALL/CREATE/LOG/SELFDESTRUCT) runs in Rust
- Deployed code = `return_data` (EIP-170 cap 24576); empty/STOP still supported
- Markers: `native_inline_create_runtime`, `native_inline_create_runtime_len`
- Host ops inside init still fall through to Python create hook
- Honesty: DB satoshi journal ownership still not claimed

## [1.3.81] — 2026-07-25

### EVM — inline CREATE2 (empty / STOP init)

- CREATE2 (`0xF5`) with empty/STOP init runs in Rust when `bridge_state.codes` present
- Address: EIP-1014 by default; `create2_eip1014=false` → Absolute legacy seed
- Value fail-closed via balances; non-trivial init still Python hook
- Markers: `native_inline_create2`, `native_inline_create2_eip1014`
- Honesty: DB satoshi journal ownership still not claimed

## [1.3.80] — 2026-07-25

### EVM — inline simple CREATE (empty / STOP init)

- CREATE (`0xF0`) with empty or STOP-only init runs in Rust when `bridge_state.codes` present
- Address via `evm_deploy_address_create`; empty runtime registered under codes/storages
- Value transfer fail-closed via balances; insufficient → push 0 without hook
- CREATE2 / non-trivial init still fall through to Python create hook
- Honesty: DB satoshi journal ownership / full CREATE2 runtime still not claimed

## [1.3.79] — 2026-07-25

### EVM — CALLCODE value ownership (fail-closed balances)

- Eligible CALLCODE with `value > 0` runs in-Rust when `bridge_state.balances` present
- Value credited to current account (EVM CALLCODE semantics); same-addr = net no-op after fail-closed check
- Insufficient balance → CALLCODE fails without child exec / without Python hook
- Missing balances map → fall through to Python hook
- Honesty: CREATE frames / DB satoshi journal ownership still not claimed

## [1.3.78] — 2026-07-25

### P2P — per-peer bandwidth / cost-weighted ingress budget

- `P2PRateLimitTable` byte window + `ingress_cost_units` (blocks/mempool ×2)
- Wired into `p2p_ingress_admit`; reject reason `bandwidth_exceeded`
- Config: `p2p_max_bytes_per_sec` (default 4 MiB/s, `P2P_MAX_BYTES_PER_SEC`)
- Prometheus: `abs_p2p_bandwidth_rejects_total`, `abs_p2p_max_bytes_per_sec`
- Honesty: not full Rust transport; outbound bandwidth not claimed

## [1.3.77] — 2026-07-25

### P2P — Rust ingress data plane (wire + rate) + connection governor

- `p2p_ingress_admit`: one native path for decode → type allowlist → primary/exempt rate
- `P2PConnectionGovernor`: max_peers + per-IP inbound cap (`p2p_max_inbound_per_ip`)
- Python message loop uses ingress when available (skips duplicate Python rate tick)
- Honesty: not a full Rust P2P rewrite; gossip/sync/apply stay Python control plane

## [1.3.76] — 2026-07-25

### EVM — value-transfer CALL ownership (fail-closed balances)

- Inline CALL with `value > 0` when `bridge_state.balances` is present
- Fail-closed debit (no silent clamp); insufficient → CALL fails without child exec
- Revert restores balance snapshot; success keeps transfer + storage
- Missing balances map → fall through to Python hook (real DB path)
- Honesty: CALLCODE value / DB-backed satoshi writeback still via adapter journal

## [1.3.75] — 2026-07-25

### EVM — multi-depth value=0 CALL frames (Priority 38)

- Call-frames may contain CALL*/LOG (not only leaf-eligible bytecode)
- Depth tracked via `_abs_inline_depth` (cap `MAX_INLINE_CALL_DEPTH=4`)
- CREATE/SELFDESTRUCT still fall through to Python hook
- Honesty: value-transfer CALL still not owned in Rust

## [1.3.74] — 2026-07-25

### EVM — value=0 CALL/STATICCALL inline leaf (Priority 38)

- Eligible value=0 CALL/STATICCALL runs inside parent Rust host frame (no Python hook)
- Callee storage from `bridge_state.storages` (persisted on success); empty if absent
- Non-zero value CALL still falls through to Python (no silent debit)
- Honesty: not multi-depth host stack; CREATE/value-transfer still via adapter

## [1.3.73] — 2026-07-25

### Load — apply-queue priority lanes

- `ChainApplyQueue` uses `PriorityQueue`: REORG > FORGE > ADD > IMPORT (FIFO within lane)
- Sync import floods no longer starve forge / fork resolution once jobs are queued
- Prometheus: `abs_chain_apply_error_total`, `abs_chain_apply_priority_lanes`
- Honesty: does not invent separate apply workers; still one serial tip mutator

## [1.3.72] — 2026-07-25

### P2P — sync admission + outbound honesty (close v1.3.66 debt)

- Global `p2p_max_sync_inflight` cap on concurrent peer sync tasks (default 2)
- Outbound `max_peers` enforced on `connect_peer` (was inbound-only)
- Aggregate `_outbound_drops` + Prometheus `abs_p2p_outbound_drops_total`
- Config-driven `p2p_send_queue_max` / `p2p_drain_timeout_sec`
- Secondary `p2p_exempt_messages_per_sec` budget for rate-limit-exempt wire types
- Prod/require_native: fail-closed if `P2PRateLimitTable` init fails
- Honesty: not full P2P DoS/QoS; not public mainnet

## [1.3.71] — 2026-07-25

### EVM — in-Rust inline leaf frame (Priority 37)

- Eligible DELEGATECALL/CALLCODE (value=0) children run as push/pop inside parent Rust host frame
- Skips Python `contract_call` re-entry when child code is resolvable and host-op-free
- Falls through to hook for CALL/STATICCALL, value transfer, ineligible bytecode, or host/handoff stop
- Honesty: not a full multi-depth Rust host stack; CREATE/SELFDESTRUCT/value CALL still via Python

## [1.3.70] — 2026-07-25

### EVM — recursive frame correctness (arena sync)

- Flush Rust storage arena to Python before nested CALL
- Re-sync arena after DELEGATECALL/CALLCODE storage merge
- Adapter DELEGATECALL/CALLCODE uses in-flight `_abs_live_storage`
- Preserve `native_nested_*` flags on nested call results
- Honesty: not a Rust-owned multi-frame stack; Python FFI per CALL depth remains

## [1.3.69] — 2026-07-25

### Load — block-scoped sat session for mixed apply

- Mixed native block apply keeps in-memory sat session across txs
- Single account writeback at end (plus tracked supply, no per-tx supply scan)
- `scripts/verify_industrial_waves.py` — full checklist for waves 1.3.65–1.3.69

## [1.3.68] — 2026-07-25

### Bridge — semantic event bind + fail-closed debit

- `try_debit_satoshi` — underflow raises (no silent clamp)
- Rocks/SQLite `debit_and_create_bridge_lock` uses fail-closed debit
- Rust bridge: optional topic0/recipient/amount semantic lock-log bind
- Prod bridge requires `bridge_require_l1_event=true`

## [1.3.67] — 2026-07-25

### EVM — tx writeback journal + Rust storage arena

- Nested writeback ops buffered until top-level call/deploy success
- SLOAD/SSTORE use Rust-owned HashMap arena, flushed to Python dict on exit

## [1.3.66] — 2026-07-25

### Load — apply backpressure + tip O(1) + P2P coalesce

- Apply queue expires not-yet-started jobs past deadline
- Mempool remove only after successful block import
- Rocks tip via chain_tip meta + native `prefix_last`
- Coalesced sync/connect tasks; bounded peer send queue with drain timeout
- Saturation metrics: expired/timeout/exec + sync task depth

## [1.3.65] — 2026-07-25

### Security — L1 fail-closed hardening

- Attestation pubkey bound to claimed validator address
- Prod/staging blocks unauthenticated P2P `validator_register`
- Native block apply fail-closed under `require_native_crypto` / prod
- `amount._native_required` honors `ABS_REQUIRE_NATIVE_CRYPTO`
- Corrupt Rocks account JSON raises `AccountCorruptError`
- HTTP/JSON-RPC body size + batch caps

## [1.3.64] — 2026-07-25

### Added — Rocks batch writeback account preload

- `RocksEngine.get_account_rows` — batch load account JSON rows
- `RocksChainStore.load_writeback_accounts` / Hybrid delegate
- Adapter preloads touched accounts via Rocks before native apply

## [1.3.63] — 2026-07-25

### Added — unified writeback bundle (accounts + logs)

- `RocksEngine.commit_writeback_bundle` — single WriteBatch for accounts + EVM logs
- `RocksChainStore.commit_writeback_bundle` / Hybrid delegate under `_write_lock`
- Adapter uses bundle commit after `evm_apply_writeback_ops`

## [1.3.62] — 2026-07-25

### Added — store-lock Rocks writeback commit

- `RocksEngine.commit_account_rows` — native batch account put
- `RocksChainStore.commit_writeback_accounts` under `_write_lock`
- Adapter uses store-lock commit after `evm_apply_writeback_ops`

## [1.3.61] — 2026-07-25

### Added — native writeback apply (in-memory)

- `evm_apply_writeback_ops` — apply planned ops to accounts map in Rust
- Adapter commits via Python DB after native apply

## [1.3.60] — 2026-07-25

### Added — CREATE writeback ops (Rust planner)

- `evm_plan_create_writeback` — `save_account` + optional `transfer_value`
- Adapter CREATE path applies via shared writeback ops (no double-credit)

## [1.3.59] — 2026-07-25

### Added — nested CALL writeback ops (Rust planner)

- `evm_plan_nested_call_writeback` — concrete `ops[]` with resolved addresses
- Adapter applies ops via Python DB (`_apply_nested_writeback_ops`)

## [1.3.58] — 2026-07-25

### Added — native account view decode (nested CALL preload)

- `account_view_from_blob` / `account_storage_map_from_raw` in abs_native
- `RocksEngine.get_account_view`; adapter `_account_view` for nested CALL code/storage

## [1.3.57] — 2026-07-25

### Added — LOG/CALL/CREATE host bodies in Rust

- `execute_log_native` / `execute_call_native` / `execute_create_native` in abs_native
- Thin `bridge_hooks` for `contract_call` / `contract_create` / `selfdestruct`
- Segment `logs[]` merged into interpreter; no Python opcode loop for these hosts when hooks present

## [1.3.56] — 2026-07-25

### Added — nested CALL/CREATE/LOG host frame (Rust runner + bridge)

- `evm_run_nested_host_frame` — child frame with runtime `host_bridge` (CALL/CREATE/LOG)
- `EVMAdapter._contract_call_hook` prefers nested host frame before Python opcode loop
- Honesty: host op *bodies* remain Python callbacks via `EvmRuntimeBridge`

## [1.3.55] — 2026-07-25

### Added — nested CALL native bridge surface (BALANCE/EXTCODE*)

- `evm_bytecode_is_nested_native_eligible` — allows bridge ops, rejects recursive CALL/CREATE/LOG
- Nested frame `allow_bridge=True`; adapter keeps host_context bridge hooks

## [1.3.54] — 2026-07-25

### Added — EVM/mempool high-load harness

- `scripts/evm_mempool_load_harness.py` — concurrent mempool enqueue + ChainApplyQueue forge (simple+EVM), not `/health/live`

## [1.3.53] — 2026-07-25

### Added — apply isolation metrics + dedicated sync executor

- Prometheus: `abs_chain_apply_queue_depth`, `abs_chain_apply_wait_seconds_total`, `abs_chain_apply_reject_total`, `abs_p2p_import_offload_total`
- Dedicated `AbsSyncState` ThreadPoolExecutor (no longer shares default pool with apply)
- Mining logs and skips forge tick on apply-queue backpressure

## [1.3.52] — 2026-07-25

### Added — serial ChainApplyQueue (mine + import)

- `core/chain_apply_queue.py`: single worker serializes forge_and_apply / import / reorg
- Mining uses atomic create+sign+add; P2P imports share the same queue (closes tip race)

## [1.3.51] — 2026-07-25

### Changed — P2P/sync import off the asyncio event loop

- `_import_block_async` / `_reorg_and_import_async` via `asyncio.to_thread`; announce, sync batch, reconcile no longer freeze the loop on EVM apply
- Follower genesis `fast_sync` also offloaded

## [1.3.50] — 2026-07-25

### Added — nested pure bytecode frame

- Rust `evm_run_nested_pure_frame`; adapter fast-path for host/bridge-free child CALL bytecode

## [1.3.49] — 2026-07-25

### Added — nested CALL frame decode planner

- Rust `evm_decode_nested_call_frame`; host bridge CALL/CALLCODE/DELEGATECALL/STATICCALL stack decode

## [1.3.48] — 2026-07-25

### Added — nested CALL gas planner

- Rust `evm_plan_nested_call_gas`; interpreter CALL gas via EIP-150 + stipend planner

## [1.3.47] — 2026-07-25

### Added — nested CALL effects planner

- Rust `evm_plan_nested_call_effects`; adapter CALL writeback driven by native policy

## [1.3.46] — 2026-07-25

### Added — mixed simple+EVM native apply

- `_apply_mixed_block_native` via host_effects; multi-tx block assembly honors nonce cursor

## [1.3.45] — 2026-07-21

### Fixed — native apply honesty + prod example ceremony addresses

- Writeback: skip empty new accounts; preserve EVM code/storage; receipt `status=1` on success
- Example validator manifest uses ceremony addresses (no `0x…0001` placeholders)
- Audit proposer check, prod-smoke FEATURE clear, sync incomplete-vs-ahead, oracle secret=`""`

## [1.3.44] — 2026-07-21

### Added — EVM host-in-apply fee effects

- Rust `blockchain_apply_host_effects`; all-EVM blocks run host then native fee/nonce/reward

## [1.3.43] — 2026-07-21

### Added — native P2P rate-limit / strike table

- Rust `P2PRateLimitTable` + tick/exempt/ban helpers; `p2p_node` prefers abs_native

## [1.3.42] — 2026-07-21

### Added — native RocksDB typed key codecs

- Rust `rocks_*` pack/key/prefix builders; `storage/keycodec.py` prefers abs_native

## [1.3.41] — 2026-07-21

### Added — EVM host storage snapshot around runner

- Native storage snapshot/restore; until_halt aborts restore dirty SSTORE on REVERT/OOG
- Interpreter frame snap + adapter fail-closed writeback on reverted delegate/callcode

## [1.3.40] — 2026-07-21

### Added — native eth raw tx decode kernel

- Rust `decode_eth_raw_tx` / `decode_eth_raw_tx_hex` for legacy / EIP-1559 / EIP-4844 + recover
- `crypto/eth_tx.py` prefers abs_native JSON with Python RLP fallback

## [1.3.39] — 2026-07-21

### Added — native FFG finality + slashing conflict kernels

- Rust Casper/Beacon evaluate + FinalityEngine quorum helpers; double-vote/proposal conflict checks
- Python finality/slashing modules prefer abs_native with fallback

## [1.3.38] — 2026-07-21

### Added — native GHOST + simple block apply/replay

- Rust GHOST/LMD kernels; `blockchain_apply_simple_block` / `blockchain_replay_simple_blocks` for fee+reward simple transfers
- Blockchain add_block/reorg prefer native when chain has no EVM calldata

## [1.3.37] — 2026-07-21

### Hardened — bridge L1-proof / light / PBS / AI honesty

- Prod forbids weakening `BRIDGE_REQUIRE_L1_PROOF` via env; relayer blind-confirm hard-fails on prod API
- Light client rejects unanchored peer bootstrap; PBS fee-bid simulation (not MEV protection); AI validator feature-gated + no invented MEV numbers

## [1.3.36] — 2026-07-21

### Hardened — WASM/finality/reorg/RANDAO honesty + atomic chain backup replace

- WASM operational vs registry; finality standalone observer; reorg heuristic_low_risk
- ValidatorSelection not RANDAO; ChainStorage.replace_chain atomic temp swap

---

## [1.3.35] — 2026-07-21

### Hardened — MiniVM/ZK/Lightning/DAO honesty + relayer status

- MiniVM feature-gated; Lightning direct-only; unsigned DAO vote blocked in prod
- ZK no invented validity / no GET private keys; bridge_relayer_live ≠ binary smoke

---

## [1.3.34] — 2026-07-21

### Hardened — Rust L1 lock verify / receipt status / event-log address / atomic debit

- Rust verifies L1 on lock; requires receipt status; optional contract-log binding
- confirm_lock passes to_chain; atomic debit/refund APIs

---

## [1.3.33] — 2026-07-21

### Hardened — bridge event replay / atomic credit / plasma force / smart-accounts

- Event-derived bridge replay key + atomic claim/credit; l1_event_bound honesty
- Plasma force blocked in prod; Smart Accounts feature-gated with execution_bound labels

---

## [1.3.32] — 2026-07-21

### Hardened — L1 receipt status / EVM static / NFT-PQ-will-multisig honesty

- L1 confirmations require successful receipt status; EVM corrupt storage + static_call read-only
- NFT feature gate (off in prod); will force blocked in prod; PQ/multisig honesty labels

---

## [1.3.31] — 2026-07-21

### Hardened — oracle quorum / sync finally / peer fork / bridge-MEV-AI-will

- Oracle signature+unique reporters; consensus healthy from ingest_fail
- Sync finally + fail counters; P2P chain_compatible; bridge/MEV/AI/will honesty

---

## [1.3.30] — 2026-07-21

### Hardened — ready/WS / feature init / bridge proof / L2 missing / storage / consensus

- Prod ready checks WS + feature init errors; status degrades on feature_init_errors
- Bridge proof_ok needs ETH RPC; L2/network unbound error keys; corrupt storage RPC fail
- Consensus ingest fail counters and healthy flag

---

## [1.3.29] — 2026-07-21

### Hardened — topology/prod / filters / migrate / SQLite features / metrics-WS / tip

- Prod topology needs peers; eth filters unbound raise; aux migrate skip corrupt
- SQLite feature JSON counted; metrics/alerts for sqlite+WS; backup tip fail-closed

---

## [1.3.28] — 2026-07-21

### Hardened — mining/status / WS-P2P send / API missing / clone / SQLite / amount

- eth_mining prod/P2P-running honesty; /status subsystems + SyncEngine degrade
- WS broadcast and legacy P2P send fail-loud; unbound API error keys; Rocks clone checkpoint fail-closed
- SQLite JSON decode counter; amount native required mode

---

## [1.3.27] — 2026-07-21

### Hardened — Rocks NFT/EVM decode / catch_up gather / IMS missing / get_meta

- Decode helpers fail-closed; get_meta returns default on corrupt; catch_up_sync records broadcast_fail
- IMS/sharding missing error keys; peer_sync and catch_up loop alerts

---

## [1.3.26] — 2026-07-21

### Hardened — remaining gather / Rocks mutate / attestation errors / BlockBuilder

- Cross-shard and validator_register gossip record broadcast_fail; Rocks mutate/burn fail-closed decode
- Missing consensus/sharding/slashing/finality surfaces expose error keys; BlockBuilder not advertised as live forge

---

## [1.3.25] — 2026-07-21

### Hardened — supply canonical / Rocks point-gets / broadcast_fail / core_real

- `/state/supply` DB-only not canonical; Rocks point-gets fail-closed decode; broadcast gather counts fails
- core_real exposes engines; no fake quorum_live; finality/state missing errors; prod block sign hard-fail

---

## [1.3.24] — 2026-07-21

### Hardened — Core engines prod / status wire / IMS canonical / Rocks meta-tx

- Prod hard-fails StateEngine/Finality/IMS; ready checks engines; status degrades on wire probe gaps
- DB-only balances/supply never claim IMS-canonical; Rocks meta/TX list/reorg purge bump decode counter
- Metrics + alert for missing core engines on prod-like nodes

---

## [1.3.23] — 2026-07-21

### Hardened — P2P bind / ready wire / status degraded / peers mining

- Bind failure clears `_running`; ready requires wire probe + bound server with peers
- `/status` degraded when inconsistent; mining/eth_mining gate peers even if mesh_min=0
- Rocks latest/accounts/validators/reorg bump json_decode_failures

---

## [1.3.22] — 2026-07-21

### Hardened — Rocks decode / topology / SyncEngine prod / eth_mining mesh

- Rocks corrupt list rows bump json_decode_failures; metrics + alert emit the counter
- topology_healthy needs state_consistent with peers; reconcile without SyncEngine clears flag
- Prod hard-fails SyncEngine init; eth_mining respects mesh_min_peers gate

---

## [1.3.21] — 2026-07-21

### Hardened — sync_state / mesh / bridge-L1 / ready peer_count honesty

- Solo sync_state clears consistency and returns False; same-height peer root required before True
- Mesh mining STATUS path gates on state_consistent; bridge_relayer_live needs rust smoke
- L1 unconfigured / bridge disabled → ok=False; ready peer_count probe failure fail-closed

---

## [1.3.20] — 2026-07-21

### Hardened — Proxy CORS, receipt omit→0, ready/sync honesty

- CORS miss never echoes allowlist; empty list never promotes to `*`
- Ready with peers requires state_consistent; SyncEngine missing → p2p_fallback fail-closed
- Receipt status omit/unknown → 0x0

---

## [1.3.19] — 2026-07-21

### Hardened — Sync incomplete, CORS miss, repair success, receipt fail-closed

- P2P catch-up: Sync incomplete + reached_target gate for state_root baseline
- CORS allowlist miss returns empty origin; repair success = repair+harness+consistent
- SQLite receipt/tx status normalize fail-closed on missing/unknown

---

## [1.3.18] — 2026-07-21

### Hardened — fast_sync honesty, ready DB probe, Rocks TX iter

- fast_sync: tip-match / no-new / after-import → sync_state(); peer-loss clears stale probed-ok
- Rocks _iter_transaction_rows: warn + json_decode_failures; /health/ready db_probe + db_probe_error

---

## [1.3.17] — 2026-07-21

### Hardened — Never-probed wire honesty

- Solo/deferred sync_state leaves wire_probe_ok=None (never probed ≠ probed-ok)
- Prometheus abs_sync_wire_probe_ok=-1 when never probed; eth_syncing stays syncing with peers until probe runs
- peer_sync_fail in ops_errors; AbsoluteSyncWireProbeNeverProbed alert (from 1.3.16) matches gauge

---

## [1.3.16] — 2026-07-21

### Hardened — Shared SyncEngine, unsolicited state_root honesty, probe/sqlite alerts

- One SyncEngine shared with P2P; unsolicited root match never sets consistent=True
- Fork-recovery default state_consistent=False; AbsoluteSyncWireProbeNeverProbed + AbsoluteProdSqliteEngine

---

## [1.3.15] — 2026-07-21

### Hardened — Sync/RPC honesty, SQLite metrics engine, compose freeze

- Missing get_state_root + eth_syncing peer-inconsistency honesty; repair via sync_state only
- SQLite engine label in stats/metrics; abs_db_engine; no Rocks gauges/config_fallback on SQLite
- industrial_gate: DB_ENGINE + JWT_ENFORCE_ADMIN compose freeze

---

## [1.3.14] — 2026-07-21

### Hardened — SQLite↔Rocks reorg parity, L1 probe honesty, slash/CORS

- SQLite reorg purges evm_logs/tx_prop; truncate_blocks_above = full chain truncate
- Rocks corrupt TX/prop keys deleted on reorg; L1 unprobed ≠ ok
- slash_validator → DB fail-loud; REST CORS empty ≠ *

---

## [1.3.13] — 2026-07-21

### Hardened — Rocks/CORS/TLS overlay honesty, fail-closed state defaults

- `_state_consistent` getattr defaults False across status/mining/sync
- Rocks reorg/get_stats fail-loud; mempool sig-verify + cross-shard gossip warnings
- 3node p2ptls FAIL_CLOSED/BIND_IDENTITY + gate freeze; CORS proxy no hardcoded *

---

## [1.3.12] — 2026-07-21

### Hardened — Wire-probe fail-closed, import/sync honesty, ready/compose freeze

- Empty/timeout state_root wire probe with peers → inconsistent (not silent green)
- Soft import rejects + sync stalls counted; batch sync via `import_block`
- Prod `/health/ready` checks `p2p_running`; metrics sync defaults fail-closed
- Single-node compose↔JSON freeze; `.env.example` documents chain_id 778888

---

## [1.3.11] — 2026-07-21

### Hardened — Sync consistency metrics, loop/import honesty, deploy freezes

- `abs_state_consistent` / wire-probe gauges + alerts/panels
- import/sync/discovery/bootstrap ops counters; fail-closed unknown wire probe
- `/status` security includes ops_errors + attestation_local_fail
- Compose bridge/redis freeze; k8s bridge-OFF gate; rocks tuning source label

---

## [1.3.10] — 2026-07-21

### Hardened — Semantic peer-tx honesty, mesh Redis JSON, compose freeze

- Peer tx semantic/mempool rejects → warn + `peer_tx_reject` counter; gossip strikes `bad_peer_tx`
- `abs_p2p_peer_tx_reject_total` metric + alert/Grafana panel
- Mesh JSON redis parity with compose; industrial_gate compose↔JSON numeric freeze
- `post_soak_verify` includes `k8s_prod_gate`

---

## [1.3.09] — 2026-07-21

### Hardened — Pre-ban strike logs, loop honesty, k8s embed freeze

- `_strike_peer_sync` warns on every pre-ban strike (`strike N/M`)
- `_catch_up_loop` STATUS send return → `peer_status_send_fail`; maintenance/catch_up fails → warning + ops counters
- `k8s_prod_gate`: embedded ConfigMap JSON ≡ `node.prod.k8s.json`
- industrial_gate shared_keys + `state_root_legacy` / `rust_bridge_path`; bridge bin required only if bridge ON
- Alert/panel: `abs_p2p_attestation_local_fail_total`

---

## [1.3.08] — 2026-07-21

### Hardened — Swiss-watch ops honesty, JSON parity, EVM native fail-closed

- Fix dead `peer_status_send_fail` (check `Peer.send` return); mid-session handshake warn logs
- Strike-backed rejects + attestation sign fail → warning; `abs_p2p_attestation_local_fail_total`
- Grafana ops_errors + mid_session_handshake panels; alert `AbsoluteP2POpsErrorsBurst`
- industrial_gate freezes full prod JSON set + shared industrial keys; post_soak adds ops/status tests
- Prod JSON parity: `state_root_legacy_cutoff_height`, k8s `rust_bridge_path`; `.env.example` mesh knobs
- EVM CREATE/CREATE2 legacy helpers fail-closed under `ABS_REQUIRE_NATIVE_CRYPTO`

---

## [1.3.07] — 2026-07-21

### Hardened — ops_errors metrics, mid-session handshake reject, prod rate hard errors

- Prometheus: `abs_p2p_peer_send_fail_total`, `abs_p2p_ops_errors{kind=…}` + alert/panel
- Mid-session `handshake`/`handshake_ack` → strike `mid_session_handshake` (not rate-exempt)
- industrial_gate: prod JSON `p2p_max_messages_per_sec > 0` hard error; freeze new metric needles
- `.env.example`: `P2P_HOST`

---

## [1.3.06] — 2026-07-21

### Hardened — CI final_audit blocking, housekeeping gates, status honesty

- CI: `final_audit` is blocking (removed soft-fail)
- P2P housekeeping payloads fail-closed (ping/pong/get_*); `peer_send_fail` ops counter
- `/status` `p2p_hardening` mirrors shape/rate-limit counters; topology errors keep security fields
- Deploy: `P2P_EVICT_MIN_SCORE` env parity; industrial_gate prints warnings + `--fail-on-warnings`

---

## [1.3.05] — 2026-07-21

### Hardened — Rate-limit strikes, P2P knob parity, Rocks alerts

- P2P: rate-limit excess → strike/`rate_limit_exceeded`; unexpected recv I/O → `WireReject(recv_error)`
- Metrics/alerts: `abs_p2p_rate_limit_drops_total`; Rocks cache/buffer unset alerts
- Deploy: pin P2P abuse knobs in prod JSON/compose/k8s; `.env.example` P2P block; bridge default OFF
- post_soak_verify includes `test_p2p_industrial.py`; EVIDENCE_MATRIX labels honesty fix

---

## [1.3.04] — 2026-07-21

### Hardened — Wire-reject strikes, P2P alerts, Rocks deploy parity

- P2P: malformed/oversized lines → `WireReject` + strike/`shape_rejects` (no silent disconnect)
- Prometheus alerts + Grafana panels for shape/handshake rejects and active bans
- Rocks tuning metrics (`abs_rocksdb_*`); k8s/mesh JSON + gate freeze for ROCKSDB_*
- industrial_gate freezes `/metrics` series + alerts surface

---

## [1.3.03] — 2026-07-21

### Hardened — Observability + ceremony UX + Rocks env in deploy

- Prometheus: `abs_p2p_shape_rejects*`, handshake rejects, active bans
- `/status` P2P security includes `shape_rejects_total`
- Ceremony auto-detect from `data/ceremony_deploy.json` / `data/ceremony_keys`
- Docker/K8s: `ROCKSDB_BLOCK_CACHE_MB`, `WRITE_BUFFER_MB`, `COLUMN_FAMILIES`

---

## [1.3.02] — 2026-07-21

### Hardened — Post-soak industrial polish (Swiss-watch pass)

- industrial_gate: fix RocksChainStore check + RocksEngine `column_families` surface
- P2P: shape-reject counters in `get_p2p_security_status`; housekeeping payload gate
- Rocks: schema_version bump honesty on CF enable; `.env.example` / prod CF docs
- native: fail-closed `sha256_hex_batch` / `double_sha256_hex` under ABS_REQUIRE_NATIVE_CRYPTO
- node_version default → `1.3.02-industrial`; `scripts/post_soak_verify.py` entry

---

## [1.3.01] — 2026-07-21

### Hardened — Soak evidence strict mode, CI audit pack, devnet manifest fail-loud

- stamp_release_evidence --require-soak-hours; CI export_audit_pack step
- main.py devnet manifest resolve fail-loud; soak stamp hints in PS scripts

---

## [1.3.00] — 2026-07-21

### Hardened — Audit pack encoding snapshot, founder pin fail-loud

- export_audit_pack includes state_root_encoding.json + manifest field
- main.py founder pin and .env load fail-loud; industrial_gate audit pack checks

---

## [1.2.99] — 2026-07-21

### Hardened — State-root encoding honesty API, harness check, evidence stamp

- GET /chain/state-root/encoding; harness state_root_encoding_honest check
- stamp_release_evidence records state_root_encoding_v1; block URL fail-loud errors

---

## [1.2.98] — 2026-07-21

### Hardened — AI/MEV/PQ probes, security-audit bridge gate, main fail-loud

- module_probes: ai_agents + mev + pq; honest stats endpoints with import_error
- security-audit workflow: bridge_off_audit_gate job
- main.py: monitor/RPC proxy/validator key provider failures log exception text

---

## [1.2.97] — 2026-07-21

### Hardened — Lightning/ZK probes, CI bridge gate, audit pack

- module_probes: lightning + zk; /lightning/stats and /zk/info import_error
- GitHub Actions bridge_off_audit_gate; export_audit_pack includes gate JSON

---

## [1.2.96] — 2026-07-21

### Hardened — evidence bridge gate, WASM/Plasma probes, release stamp

- testnet_readiness + prod_evidence_suite call bridge_off_audit_gate
- stamp_release_evidence.py for bridge_decision_off + soak reference
- /features module_probes; wasm/plasma stats import_error pattern
- external_audit bridge L1 auto-check uses bridge_off_audit_gate

---

## [1.2.95] — 2026-07-21

### Hardened — bridge OFF audit gate, K8s TLS merge, consensus import errors

- `bridge_off_audit_gate.py` automates EVIDENCE_MATRIX 10-control checklist
- K8s TLS merge script + Job example for abs-p2p-tls
- Casper/beacon endpoints expose import_error on probe failure

---

## [1.2.94] — 2026-07-21

### Hardened — K8s per-pod TLS, supply/repair fail-loud, bridge audit checklist

- StatefulSet projected P2P TLS (CA + per-ordinal cert-manager secrets)
- Supply/repair/sync/L1 RPC errors exposed + logged
- EVIDENCE_MATRIX Bridge OFF pre-enable checklist (10 items)
- test_harness_http.py for peer_probe_ok via HTTP

---

## [1.2.93] — 2026-07-21

### Hardened — API repair fail-loud, verify_p2p strict skips, cert-manager per-pod

- Harness/oracle/fork repair errors exposed + logged; peer_probe_error in harness
- verify_p2p_ci wave/bridge/prod-endpoint skips fail-closed unless VERIFY_P2P_ALLOW_SKIP=1
- docs/STATE_ROOT_ENCODING_MIGRATION.md; cert-manager per-pod example

---

## [1.2.92] — 2026-07-21

### Hardened — mining fail-loud, state_root encoding scaffold

- Mining loop: PBS/MEV/shard/epoch/light-client errors logged
- `runtime/state_root_encoding.py` — v1 active, v2 satoshi scaffold blocked
- `/status` exposes `state_root_policy.encoding`
- K8s `cert-manager-p2p.example.yaml`; industrial_gate mining log checks

---

## [1.2.91] — 2026-07-21

### Hardened — P2P ops fail-loud, K8s TLS mesh, CI skip policy

- P2P: propagation/connect/status errors logged; `ops_errors` in `/status` `p2p_hardening`
- K8s: Redis init wait, `abs-p2p-tls` mount, ordinal TLS in entrypoint; configmap JSON synced
- `verify_p2p_ci`: prod-smoke/mesh3 native skip fail-closed unless `VERIFY_P2P_ALLOW_SKIP=1`
- Tests: `test_p2p_ops_errors.py`, `test_verify_p2p_skip_policy.py`

---

## [1.2.90] — 2026-07-21

### Hardened — status honesty + mesh Redis validate

- GET /status: honest core_real, rate_limit_backend, p2p_hardening
- Prod mesh Config.validate requires Redis RL + URL
- K8s Redis probes + TLS/Redis on node.prod.k8s.json; k8s_prod_gate extended

### Fail-loud

- ChainStorage backup, WebSocket send, consensus parallel add_block, bridge oracle

### Docs / tests

- [RELEASE_NOTES_v1.2.90.md](RELEASE_NOTES_v1.2.90.md)

---

## [1.2.89] — 2026-07-21

### Hardened — mesh Redis + auth + honesty

- Prod 3-node compose: Redis service + REDIS_RATE_LIMIT/URL on all nodes; prod_gate enforces
- JWT secret lazy from env; Redis RL fail-closed by default + mid-flight deny
- Bridge/Casper/Beacon API honesty; repair sync_error; mining/P2P/hybrid silent-fail purge
- full_audit solo P2P fail-closed; handshake identity reject test

### Docs

- [RELEASE_NOTES_v1.2.89.md](RELEASE_NOTES_v1.2.89.md)

---

## [1.2.88] — 2026-07-21

### Hardened — soak / rate limit / TLS

- health_watch fail-exit on hard FAIL; soak/industrial_gate require wall-clock hours
- Prod Redis RL: no memory fallback; honest backend logging
- Single-node `docker-compose.prod.p2ptls.yml` + `docker_prod.ps1 -P2pTls`
- Mining path: log peer-root / sync schedule failures (prod clears consistency)

### Docs / tests

- SECURITY.md P2P TLS + Redis; mint_admin_jwt + prod TLS tests
- [RELEASE_NOTES_v1.2.88.md](RELEASE_NOTES_v1.2.88.md)

---

## [1.2.87] — 2026-07-21

### Hardened — P2P

- TLS enabled ⇒ always `CERT_REQUIRED` (removed `CERT_NONE` path)
- Handshake `node_id` cryptographically bound to peer cert CN/SAN
- Optional `P2P_TLS_PEER_FINGERPRINTS` allowlist; richer `/p2p/security` tls block
- Prod gate: TLS+mTLS required on **all** prod profiles (not only mesh)

### Hardened — Auth / API / config

- JWT admin requires `role=admin`; `scripts/mint_admin_jwt.py` for prod ops
- Constant-time RPC API key verify; GET rate-limited
- `bridge_enabled` default false; prod forces wallet + TLS bind/fail-closed
- Genesis strict default in prod; PBS behind `feature_mev`; slash honesty fields

### Hardened — L1 bridge tooling (bridge remains OFF)

- Atomic `save_l1_queue`; fail-loud `get_contract_code` on RPC errors
- Cutover: relayer / L1 probe exceptions → errors
- API honesty: Solana marked dev-only; rust stderr logged

### Docs

- [docs/P2P_TLS.md](docs/P2P_TLS.md), [docs/BRIDGE_L1_MAINNET.md](docs/BRIDGE_L1_MAINNET.md), [RELEASE_NOTES_v1.2.87.md](RELEASE_NOTES_v1.2.87.md), [SECURITY.md](SECURITY.md)

---

## [1.2.86] — 2026-07-21

### Fixed / hardened

- **Prod Config:** pply_env / alidate cannot weaken signatures, proposer, peer state_root, JWT admin, RPC keys; forbid RATE_LIMIT_RPM=0 and ALLOW_INSECURE_PUBLIC_BIND
- **Slash persist / callback:** fail-loud (no silent swallow)
- **Rate limiter:** prod requires working limiter; Redis errors fail-closed when Redis RL enabled; RPC auth ImportError fails start when required
- **Compose:** mem_limit/cpus + log rotation on prod + prod.3node
- **External audit tracker:** human items need real note + http(s) evidence URL (rejects template stubs)
- **industrial_gate:** TLS warning reads prod mesh JSON (was dead on bare Config())

### Changed

- **docker_prod_3node.ps1:** TLS+mTLS overlay **default** (-NoP2pTls to opt out)
- Mesh JSON + compose overlay: P2P_TLS_REQUIRE_CLIENT_CERT=true
- Threat model documented in docs/P2P_TLS.md

### Evidence / docs

- Bridge decision **OFF** recorded for mainnet-v1 / pre-audit until audited L1 contracts
- Soak checkbox synced; float tip-root known-limitation stamp for auditors

### Notes

- Prepares stack for **external audit engagement**; does **not** claim audit complete or public mainnet

---

## [1.2.85] — 2026-07-21

### Proven (ops)

- **48h prod mesh soak PASS** (2026-07-19 07:02 → 2026-07-21 07:03): `fail_lines=0`, `hours_requested=48`
- `industrial_gate --min-soak-hours 48` OK · `testnet_readiness -MinSoakHours 48` OK
- Strict pre-rescore report kept (`mesh_warn=11`, all height delta ≤1); rescored `passed=true`

### Added / changed

- **`docker-compose.prod.3node.yml`**: json-file log rotation `50m` × `3` (soak-safe vs Docker VM disk fill)
- **`health_watch.ps1`**: mesh align allows height delta ≤1; tip hash check only when heights equal
- **`soak_monitor.ps1`**: `-RescoreOnly`, transient mesh-warn policy, UTF-8 report without BOM
- Docs / README / REPO_PROFILE: honest 48h PASS status

### Notes

- Local soak artifacts under `logs/` remain gitignored
- Still **not** a launched public mainnet; external audit / public VPS / bridge cutover remain open

---

## [1.2.84] — 2026-07-17

### Fixed / hardened

- **Mining sync probe:** log + clear `_state_consistent` on `sync_state` failure (no silent pass)
- **SyncEngine:** log wire state_root probe failures; expose `wire_probe_ok` in status
- **Genesis meta:** fail-loud in prod on `set_meta` write failure
- **State-root mismatch audit:** log when `record_state_root_mismatch` fails
- **API `/chain/state-root/status`:** return `peer_probe_error` instead of looking like 0 peers OK
- **IMS reconcile:** `fail_loud` for nonce mirror errors in prod
- **prod_gate:** forbid `allow_state_root_rewrite=true`; mesh1 peers≥1; mesh2/3 `follower_genesis_sync`
- **industrial_gate:** `_check_fail_loud_surfaces` static freeze

### Added

- `tests/unit/test_silent_except_honesty.py`

### Notes

- Live 48h soak mesh is **not** restarted by this release
- Tip float `"b"` encoding and float `balance` column unchanged

---

## [1.2.83] — 2026-07-17

### Fixed / hardened

- **IMS:** post-block `reconcile_from_store` from DB satoshi (fees/rewards/burns); seed fail-loud in prod
- **API `/state/*`:** DB cross-check + `canonical` flag; `/state/supply` prefers DB; `/state/credit` blocked in prod
- **`get_address_activity` / `PersistentStorage.get_account_state` / Rocks+SQLite `get_total_supply`:** prefer satoshi
- **`Blockchain` funds check:** compare in satoshi
- **`industrial_gate`:** freeze tip float `"b"` soak contract + IMS reconcile surface

### Added

- `tests/unit/test_ims_reconcile_honesty.py`

### Notes

- Live 48h soak mesh is **not** restarted by this release
- Tip `compute_db_state_root` float `"b"` encoding unchanged
- Float ABS column still retained

---

## [1.2.82] — 2026-07-17

### Fixed

- **SQLite genesis reset** (`_reset_accounts_from_alloc_locked`): dual-write `balance_satoshi`
- **`nonce_increment`**: INSERT includes `balance_satoshi=0` (match `increment_nonce`)
- **`DatabaseStateAdapter`**: `get_balance_satoshi` via `canonical_balance_satoshi` (no float×1e6)
- **`migrate_sqlite_to_rocks`**: preserve `balance_satoshi` when present
- **`PersistentStorage.update_balance`**: delegate to DB dual-write (no accidental nonce bump)

### Added

- `tests/unit/test_balance_write_path_unify.py`
- `industrial_gate` checks reset_accounts + adapter satoshi path

### Notes

- Live 48h soak mesh is **not** restarted by this release
- Tip `compute_db_state_root` float `"b"` encoding unchanged (soak contract)
- Float ABS column still retained

---

## [1.2.81] — 2026-07-17

### Changed

- **StateEngine:** account balances stored as integer satoshi; genesis/tx wire still ABS via `runtime.amount`
- **`compute_state_engine_root`:** payload uses `balance_satoshi`
- **`Blockchain.get_balance` / `get_balance_satoshi`:** via `runtime.state_truth` (prefer satoshi dual-write)
- **`industrial_gate`:** StateEngine + `canonical_balance_satoshi` surface check

### Added

- `runtime/state_truth.py`
- `tests/unit/test_state_engine_satoshi.py`

### Notes

- Live 48h soak mesh is **not** restarted by this release
- Tip consensus root remains DB/Rocks; StateEngine is auxiliary deterministic sandbox
- Float ABS column still retained for compatibility

---

## [1.2.80] — 2026-07-17

### Changed

- **Money path:** dual-write `balance_satoshi` (INTEGER) alongside float `balance` on SQLite + Rocks account rows; reads prefer satoshi
- **`runtime/amount.py`:** `dual_write_balance`, `account_satoshi`, `apply_delta_satoshi`
- **`industrial_gate`:** `_check_balance_precision` static surface

### Added

- `tests/unit/test_balance_satoshi_dual_write.py`

### Notes

- Live 48h soak mesh is **not** restarted by this release; new dual-write applies on next node image rebuild
- Float ABS column retained for compatibility — not yet dropped

---

## [1.2.79] — 2026-07-17

### Fixed / hardened (core доводка — no new features)

- **Docs:** NFT/EVM logs on prod hybrid are RocksDB (not SQLite-only); ARCHITECTURE + MAINNET_GAP + README aligned with STORAGE_ROCKSDB
- **IMS sync:** `except: pass` on ImmutableState apply → fail-loud in prod
- **PS1:** remaining Unicode em-dashes scrubbed in `scripts/*.ps1`
- **State root:** prod refuses tip header `state_root`/`hash` rewrite (`allow_state_root_rewrite=false`); genesis h=0 still alignable
- **Consensus:** prod `consensus_mode=unified` skips parallel Casper/Beacon/LMD/standalone engines in `main.py` (adapter already unified)
- **Amounts:** `runtime/amount.py` shared satoshi helpers; IMS + tx_validator import them
- **EVM:** unsalted CREATE address deterministic (no `time.time()`); CREATE2 EIP-1014 path unchanged and tested

### Added

- `tests/unit/test_amount_units.py`, `test_state_root_rewrite_guard.py`, `test_evm_create_address.py`

---

## [1.2.78] — 2026-07-17

### Added

- **`scripts/export_audit_pack.py`** / **`.ps1`** — soak-safe static audit pack (gates, docs, soak artifacts, zip + `manifest.json`); never restarts prod mesh
- **`external_audit_tracker`** — `-SyncAutomated` / `-ShowAutomated`, `--evidence-url` / `--evidence-note` on `--set`
- **`tests/unit/test_export_audit_pack.py`**

### Fixed

- **`prepare_48h_soak.ps1`** — PowerShell parse error from Unicode em-dash
- **Ops PS1 strings** — ASCII hyphens in `bridge_cutover_evidence_suite`, `docker_devnet`, `reset_genesis`, `setup_prod_env`

### Changed

- **`industrial_gate.ps1`** — forwards `-MinSoakHours`, `-CeremonyDir`, `-RequireCeremonyPin`, `-Json`
- **`restart_soak_prod_mesh.ps1`** — default log `logs/soak_48h_v1.2.77.log`
- **Docs** — honest 48h soak status (RUNNING since 2026-07-17, not PASS); EVIDENCE_MATRIX, MAINNET_GAP, PUBLIC_TESTNET, REPO_PROFILE

---

## [1.2.77] — 2026-07-14

### Fixed

- **P2P rate limit** — exempt `new_block`, `get_block`, `get_blocks`, `new_tx`, and mempool sync types from per-peer 500/s throttle so prod mesh catch-up no longer drops consensus traffic from the leader (`docker-prod-mesh-1`)

### Changed

- **`scripts/industrial_gate.py`** — stricter check that sync wire types stay rate-limit exempt
- **`tests/unit/test_p2p_industrial.py`** — expanded sync exempt coverage

---

## [1.2.76] — 2026-07-14

### Fixed

- **`docker_prod_3node.ps1`** — PowerShell parse error (Unicode em-dash in TLS verify catch block)
- **`gen_p2p_mesh_tls.py`** — Windows fallback via `cryptography` when `openssl` absent; also probes Git for Windows `openssl.exe`

### Added

- **`scripts/p2p_tls_crypto.py`** — pure-Python CA/node cert generation
- **`tests/unit/test_p2p_tls_crypto.py`**
- **`prod_mesh_resilience_suite.ps1`** — preflight hint when mesh unreachable (e.g. placeholder `RPC_API_KEYS`)

### Changed

- **`docs/P2P_TLS.md`** — Windows TLS generation note

---

## [1.2.75] — 2026-07-14

### Added

- **`scripts/verify_p2p_tls_mesh.py`** — static cert + live `/p2p/security.tls` verify for prod mesh
- **`scripts/p2p_tls_preflight.py`** + **`prepare_p2p_tls_mesh.ps1`** — TLS material preflight
- **`scripts/p2p_tls_evidence_suite.ps1`** — gen/start/verify TLS mesh + optional failover drill
- **`scripts/docker_prod_3node_p2ptls.ps1`**, **`probe_p2p_tls_mesh.ps1`**
- **`soak_preflight.py --require-p2p-tls`**, **`prepare_48h_soak.ps1 -RequireP2pTls`**
- **`monolith_gate.py --p2p-tls-preflight`** / **`--p2p-tls-live`**
- **`tests/unit/test_verify_p2p_tls_mesh.py`**

### Changed

- **`prod_mesh_resilience_suite.ps1`** — `-P2pTls` runs TLS verify after mesh probe
- **`verify_prod_mesh_probe.py`** — records `p2p_tls_enabled` / `p2p_tls_ready` in deep probe
- **`docs/P2P_TLS.md`** — evidence suite, soak, monolith gate workflow

---

## [1.2.74] — 2026-07-14

### Added

- **`scripts/verify_prod_mesh_probe.py`** + **`probe_prod_mesh.ps1`** — structured prod mesh verify (`:18180-:18182`, chain 778888)
- **`scripts/prod_mesh_resilience_suite.ps1`** — probe + stabilize + failover + optional DR rehearsal (no soak)
- **`scripts/ceremony_evidence_suite.ps1`** + **`prepare_ceremony_deploy.ps1`** — genesis ceremony preflight path
- **`tests/unit/test_verify_prod_mesh_probe.py`**

### Changed

- **`docs/GENESIS_CEREMONY.md`**, **`docs/EVIDENCE_MATRIX.md`**, **`docs/MAINNET_GAP_ANALYSIS.md`**, **`docs/PUBLIC_TESTNET.md`**

---

## [1.2.73] — 2026-07-14

### Added

- **`scripts/bridge_cutover_evidence_suite.ps1`** — unified bridge L1 cutover path (`-RpcOnly` / `-Full` / `-Live`)
- **`scripts/prepare_bridge_l1_cutover.ps1`** — wrapper for cutover evidence suite
- **`.env.bridge.cutover.example`** — L1 RPC + contract env template for prod cutover
- **`scripts/testnet_backup_restore.ps1`** — Docker testnet seed backup + optional DR rehearsal
- **`scripts/testnet_log_rotate.sh`** — rotate `data/node.log` inside testnet containers (VPS cron)
- **`tests/unit/test_bridge_cutover_evidence.py`**

### Changed

- **`docs/BRIDGE_L1_MAINNET.md`** — evidence suite workflow
- **`docs/VPS_DEPLOY.md`**, **`docs/PUBLIC_TESTNET.md`** — backup/restore + log rotation checklist
- **`bridge_l1_cutover.py`** — hint for evidence suite on placeholder contract failures

---

## [1.2.72] — 2026-07-14

### Added

- **`scripts/testnet_dns_cutover.py`** — DNS resolve + HTTPS `/api` probe before public cutover
- **`scripts/prepare_testnet_dns_cutover.ps1`** — workstation wrapper for DNS/TLS verification
- **`scripts/vps_testnet_bootstrap_mesh3.sh`** — Linux VPS 3-node testnet mesh bootstrap
- **`vps_testnet_preflight.py --mesh3` / `--domain`** — mesh3 deploy steps + optional HTTPS cutover probe
- **`tests/unit/test_testnet_dns_cutover.py`**

### Changed

- **`vps_testnet_bootstrap.sh`** — optional `--mesh3` / `MESH3=1` for validator overlay
- **`deploy/nginx/testnet.example.conf`** — port 80 ACME + HTTPS redirect for certbot
- **`prepare_vps_testnet.ps1`** — `-Mesh3`, `-Domain` flags
- **`docs/VPS_DEPLOY.md`**, **`docs/PUBLIC_TESTNET.md`** — VPS mesh3 + DNS cutover path

---

## [1.2.71] — 2026-07-14

### Added

- **3-node public testnet mesh** — `docker-compose.testnet.mesh3.yml`, `docker/node.testnet.validator3.json`, ports `:19082/:19088/:19502`
- **`scripts/docker_testnet_mesh3.ps1`** — start seed + 2 validators and verify sync
- **`scripts/testnet_health_watch.ps1`** — periodic mesh health polling (`-Mesh2` / `-Mesh3`)
- **`verify_testnet_mesh.py --mesh3`** — 3-node verify (`:19080/:19081/:19082`)
- **`probe_testnet_mesh.ps1 -Mesh3`**, **`docker_testnet_seed.ps1 -Mesh3`**
- **`public_testnet_gate.py --mesh3`**, **`testnet_evidence_suite.ps1 -Mesh3`**
- **`TESTNET_EXPECTED_PEERS`** env override in `runtime/config.py` (seed expects 2 peers in mesh3 overlay)

### Changed

- **`.env.testnet.example`** — validator-3 port vars (`TESTNET_HTTP_PORT_3`, RPC, P2P)
- **`docs/PUBLIC_TESTNET.md`** — 3-node mesh + health watch checklist

---

## [1.2.70] — 2026-07-14

### Added

- **`scripts/verify_testnet_mesh.py`** — 2-node public testnet mesh verify (seed :19080 + validator :19081, `/testnet/mesh`)
- **`scripts/docker_testnet_mesh.ps1`** — start seed+validator and verify sync
- **`scripts/probe_testnet_mesh.ps1`** — quick port probe for testnet mesh
- **`public_testnet_gate.py --mesh`** — optional 2-node mesh check in live gate
- **`tests/unit/test_verify_testnet_mesh.py`**

### Changed

- **`docker/node.testnet.seed.json`** / **validator** — `testnet_expected_peers: 1` for 2-node mesh health
- **`testnet_evidence_suite.ps1`** — mesh verify when `-WithValidator`

---

## [1.2.69] — 2026-07-14

### Added

- **`scripts/testnet_uptime_probe.py`** + **`.ps1`** — cron-friendly testnet health snapshot (`logs/testnet_uptime.json`, optional `--append` jsonl)
- **`deploy/nginx/install_testnet_nginx.sh`** — VPS nginx site installer with domain substitution
- **`monolith_gate --vps-testnet-preflight`** / **`-VpsTestnetLive`**
- **`tests/unit/test_testnet_uptime_probe.py`**

### Changed

- **`testnet_evidence_suite.ps1`** — full path: seed → public gate → VPS preflight → uptime probe
- **`testnet_readiness.ps1 -VpsPreflight`** — optional VPS preflight step
- **`docker-compose.testnet.yml`** — validator host ports `19081/19087/19501` (was `9081/9087/9501`)
- **`.env.testnet.example`** — validator port vars
- **`vps_testnet_bootstrap.sh`** — live preflight + uptime probe after seed boot
- **`docs/PUBLIC_TESTNET.md`**, **`docs/VPS_DEPLOY.md`**

---

## [1.2.68] — 2026-07-14

### Added

- **`--probe-l1-rpc-only`** — validate `ETH_RPC_URL` before L1 contracts are deployed (placeholder contracts → WARN, not FAIL)
- **`scripts/vps_testnet_preflight.py`** + **`prepare_vps_testnet.ps1`** — VPS public testnet preflight (nginx template, env, public gate)
- **`tests/unit/test_vps_testnet_preflight.py`**

### Changed

- Bridge cutover gates print hint when contracts are still placeholder
- **`public_testnet_gate.py`** default live URL `:19080` (was `:9080`)
- **`docs/BRIDGE_L1_MAINNET.md`**, **`docs/PUBLIC_TESTNET.md`** — rpc-only vs full probe workflow

---

## [1.2.67] — 2026-07-14

### Added

- **`scripts/bridge_l1_live_probe.py`** + **`bridge_l1_live_probe.ps1`** — unified L1 bridge probe (`static` / `--probe-l1` / `--live` / `--full`); writes `logs/bridge_l1_live_probe.json`
- **`--probe-l1`** and **`--bridge-live`** on `mainnet_readiness.py`, `industrial_gate.py`, `monolith_gate.py`, `verify_prod_stack.py`
- PowerShell: `industrial_gate.ps1 -BridgeCutover -ProbeL1`, `monolith_gate.ps1 -BridgeCutover -ProbeL1 -BridgeLive`
- **`tests/unit/test_bridge_l1_live_probe.py`**

### Changed

- **`bridge_l1_cutover.py`** — includes `l1_rpc` probe summary in gate meta when `--probe-l1`
- **`mainnet_readiness.py`** — `--probe-l1` works without `--live` (fixes prior `probe_l1=live` coupling)
- **`docs/BRIDGE_L1_MAINNET.md`** — live probe workflow

---

## [1.2.66] — 2026-07-13

### Added

- **`scripts/gen_p2p_mesh_tls.py`** — generate CA + node1/node2/node3 P2P TLS material for prod Docker mesh
- **`docker-compose.prod.3node.p2ptls.yml`** — compose overlay with `/app/p2p_tls` mounts and `P2P_TLS_*` env
- **`docker_prod_3node.ps1 -P2pTls`** — auto-generate certs, start mesh with TLS overlay, verify `/p2p/security.tls.ready`
- **`tests/unit/test_gen_p2p_mesh_tls.py`**

### Changed

- **`docs/P2P_TLS.md`** — Docker prod mesh TLS section

---

## [1.2.65] — 2026-07-13

### Added

- **`scripts/soak_preflight.py`** — prod mesh readiness for 48h soak (health, P2P security, harness, topology); writes `logs/soak_preflight.json`; does **not** start soak
- **`scripts/prepare_48h_soak.ps1`** — PowerShell wrapper for preflight
- **`monolith_gate.py --soak-preflight`** and **`monolith_gate.ps1 -SoakPreflight`**
- **`tests/unit/test_soak_preflight.py`**

### Changed

- **`restart_soak_prod_mesh.ps1`** — dynamic `git describe` tag in evidence + soak metadata; preflight hint in output
- **`verify_prod_stack.py --live-prod-mesh`** — P2P security policy check on all three nodes

---

## [1.2.64] — 2026-07-13

### Added

- **Optional P2P wire TLS** — `network/p2p_tls.py`, config/env `P2P_TLS_*`, fail-closed start when enabled but misconfigured
- **`scripts/gen_p2p_dev_tls.py`** — dev CA + node cert generator (OpenSSL)
- **`docs/P2P_TLS.md`** — P2P TLS vs nginx HTTP TLS
- **`GET /p2p/security.tls`** — readiness block

### Changed

- Industrial gate warns when prod profile runs with `p2p_tls_enabled=false`

---

## [1.2.63] — 2026-07-13

### Added

- **`prod-mesh3-ci-recovery`** — isolated ceremony spawn on `:15280–15282` + node2 SIGTERM/rejoin drill (GitHub Actions Linux)
- **`verify_spawn_mesh3_recovery()`** — process-based failover for CI (mirrors Docker `prod-mesh3-recovery`)
- **`verify_p2p_ci.py --recovery`** — append failover drill to `--mode prod-mesh3`

### Changed

- CI workflow: prod mesh3 step now runs spawn + recovery (55 min timeout)
- `verify_mesh3_recovery` accepts custom `stop_node2` / `start_node2` callbacks

---

## [1.2.62] — 2026-07-13

### Added

- **Rate-limit exempt wire types** — `block`, `blocks`, `status`, handshake/ping/state-root not counted (safe sync bursts on prod hub)
- **`industrial_gate` P2P hardening check** — static allowlist, security surface, config defaults
- **`verify_pair`** runs `verify_p2p_security_mesh` (2-node devnet + CI)

### Changed

- P2P maintenance clears strike counters for disconnected peers
- `/p2p/security` reports `rate_limit_exempt_types` count

---

## [1.2.61] — 2026-07-13

### Added

- **Handshake chain_id mismatch → strike/ban** — wrong-network peers accumulate strikes; `handshake_rejects` in `/p2p/security`
- **`docker_prod_3node.ps1 -RecoveryDrill`** — runs `prod-mesh3-recovery` after mesh boot
- **Recovery drill** now validates P2P security on all nodes after node2 rejoin

### Fixed

- **Rate limit no longer bans peers** — excess messages are dropped only (sync bursts were false-banning prod hub)
- **Wire EOF/parse close** — disconnect without strike/ban on peer close (fixes prod mesh split)

### Changed

- `probe_mesh_nodes.ps1 -Deep` shows `hs_rejects` from topology security
- `GET /status.p2p_summary.security` includes `handshake_rejects`

---

## [1.2.60] — 2026-07-13

### Fixed

- **`probe_mesh_nodes.ps1`** — PowerShell parse error from UTF-8 em dash; `-Deep` also tries `/p2p/security` when topology lacks `security`
- **`verify_p2p_security_mesh`** — fallback to `/p2p/topology.security` on 404; WARN (not FAIL) when `status.p2p_summary` missing on older nodes; rebuild hint for prod mesh

---

## [1.2.59] — 2026-07-13

### Added

- **P2P `_maintenance_loop`** — periodic stale/unhealthy peer eviction and ban expiry
- **`GET /status.monolith_summary`** — compact readiness snapshot (P2P, consensus, native crypto, bridge)

---

## [1.2.58] — 2026-07-13

### Added

- **`GET /status.p2p_summary`** — compact mesh health + security snapshot (peer scores, bans, rate limits)
- **`verify_p2p_security_mesh()`** in `verify_p2p_ci.py` — validates `/p2p/security` and status summary on all mesh nodes

### Changed

- `verify_n_nodes` / `verify_prod_post_checks` run P2P security checks before pass

---

## [1.2.57] — 2026-07-13

### Added

- **P2P security layer:** temporary peer bans after repeated wire abuse (`p2p_ban_seconds`, `p2p_rate_limit_strikes`)
- **Wire type allowlist:** reject unknown P2P message types with strike/ban
- **Low-score peer eviction:** `p2p_evict_min_score` drops unhealthy peers when alternatives exist
- **`GET /p2p/security`** — rate limits, active bans, eviction policy (also embedded in `/p2p/topology.security`)
- Env overrides: `P2P_BAN_SECONDS`, `P2P_RATE_LIMIT_STRIKES`, `P2P_EVICT_MIN_SCORE`, `P2P_MAX_MESSAGES_PER_SEC`

### Changed

- `probe_mesh_nodes.ps1 -Deep` prints P2P security summary from topology

---

## [1.2.56] — 2026-07-13

### Added

- **`scripts/monolith_gate.py`** — unified static gate: industrial + mainnet readiness + launch checklist → `data/monolith_gate.json`
- **`scripts/monolith_gate.ps1`** — PowerShell wrapper
- **P2P rate limit:** `p2p_max_messages_per_sec` (default 500) per-peer wire throttle

### Changed

- `test_blockchain_full` uses monolith gate instead of separate industrial/bridge preflight steps
- `industrial_gate` forwards `bridge_cutover` / `live_prod_mesh` / `strict_audit` to mainnet readiness
- CI: monolith static gate step on Python 3.12

---

## [1.2.55] — 2026-07-13

### Fixed

- **P2P auto mode:** `-P2P` / `--prefer-devnet` no longer hijacks live prod mesh on `:18180–:18182`; use `--prefer-prod-mesh` or `-ProdMesh` for prod checks
- **Harness timeouts:** `verify_p2p_ci` uses `_consistency_harness()` with `quick=1` and ≥45s HTTP timeout on prod ports (fixes false `node1 harness: timed out`)

---

## [1.2.54] — 2026-07-13

### Added

- **`-ProdMeshFull`** on `test_blockchain_full.ps1` — after `-ProdMesh` gates runs `prod_evidence_suite` (stabilize, health, failover drill, signed tx, EVM smoke)
- **`scripts/prod_mesh_full.ps1`** — one-command alias for full prod mesh ops proof
- **`prod_evidence_suite.ps1`** — `-FailoverWaitSec` parameter (passed to `prod_mesh_failover.ps1`)

### Tests

- `tests/unit/test_prod_mesh_full_gate.py`

---

## [1.2.53] — 2026-07-13

### Added

- **`-ProdMesh` / `-ProdMeshSpawn`** on `test_blockchain_full.ps1` — live prod 3-node P2P gate (`prod-mesh3-live`) + deep mesh probe + `mainnet_readiness --live-prod-mesh`
- **P2P industrial hardening:** max wire message size (`p2p_max_message_bytes`), peer health scores in topology/`/p2p/peer-score`
- **`verify_p2p_ci --mode auto`** now detects prod mesh on `:18180–:18182` before devnet
- **`probe_mesh_nodes.ps1 -Deep`** — topology + consistency harness summary (auto on `-ProdMesh`)

### Tests

- `tests/unit/test_p2p_industrial.py` — oversized message drop, auto prod-mesh detection

---

## [1.2.52] — 2026-07-13

### Added

- **Full blockchain test script:** `scripts/test_blockchain_full.ps1` / `.sh` now runs industrial gate, mainnet readiness (`--bridge-cutover`), bridge L1 cutover + preflight (static)
- **`check_everything.ps1`** delegates to `test_blockchain_full.ps1 -SkipNativeBuild` (single entry point)
- Unit tests: `tests/unit/test_l1_rpc_contract.py` for `eth_getCode` helper

---

## [1.2.51] — 2026-07-13

### Added

- **Bridge cutover (probe/live):** verify L1 contracts are actually deployed by calling `eth_getCode` for `BRIDGE_L1_LOCK_CONTRACT` and `BRIDGE_L1_MINT_CONTRACT` (fails closed on empty bytecode)

### Fixed

- **SQLite migration:** legacy `accounts` table now auto-adds `code` and `storage` columns to support state-root/account export on older DBs

---

## [1.2.43] — 2026-07-13

### Fixed

- **Rocks reorg:** purge EVM logs and tx propagation indexes above truncated height (fork safety on prod mesh)
- **External audit:** penetration test + third-party audit cannot be marked done with `auto:` notes only
- **Industrial gate:** smoke-test `abs_bridge_bin` when binary is present
- **Prod gate:** `node.prod.mainnet-v1.example.json` must keep `bridge_enabled=false` until L1 contracts

### Notes

- Bridge outbound without `l1_tx_hash` still uses ABS-side receipt hash + L1 queue (async relayer path); L1 contracts remain future cutover work
- 48h soak artifact still required for full mainnet readiness (`--min-soak-hours 48`)

---

## [1.2.42] — 2026-07-13

### Added

- **Lightning**: HTLC add/settle/refund, signed channel states (`features/l2_crypto`), BFS routing, SQLite tables `lightning_htlcs` / `lightning_channel_states`
- **Plasma**: native Merkle roots + inclusion proofs, signed L2 txs, L1 root metadata
- **WASM**: `wasmtime` engine with host `storage_get` / `storage_set` ABI (`features/wasm_engine.py`)
- **Oracles**: reporter submissions + median quorum aggregation (`oracle_reports` table)
- **ZK**: fixed balance proof verification; `create_zk_transaction` API compatibility
- HTTP: `/lightning/htlc/*`, `/lightning/route`, `/plasma/proof`, `/oracles/reports/submit`, `/oracles/aggregate`
- Tests: `tests/unit/test_l2_advanced_features.py` (29 tests pass in L2/ZK/WASM suite)

### Notes

- Advanced L2 modules are **functional + persisted** but remain **R&D** until independent audit. See `RELEASE_NOTES_v1.2.42.md`.

---

## [1.2.41] — 2026-07-13

### Added

- `scripts/mesh_heal_fork.ps1` — reseed node1 chainstore from node2 when hub diverges
- `mesh_recover.ps1 -HealFork` shortcut
- Stabilize auto-heal node1 fork (`ABS_STABILIZE_AUTO_HEAL=0` to disable)
- Post-forge mesh hold: hub waits for wire peer confirmation before next block

### Changed

- Mesh mining gate fail-closed (no solo forge on `state_consistent` alone)
- P2P STATUS echo + state-root height refresh on reconnect
- Prod stabilize: JWT from `.env`, cluster-tip success, failover pre-sync in evidence suite

### Live ops

- `prod_evidence_suite.ps1 -GitTag v1.2.41` **PASS** (stabilize, health, failover, signed tx, EVM)

---

## [1.2.31] — 2026-07-12

### Added

- `--live-prod-mesh` readiness gate for Docker prod mesh :18180–18182
- `scripts/record_evidence_run.py` for local evidence JSON
- Prod mesh health_watch timeouts (reduce soak false FAILs)

---

## [1.2.30] — 2026-07-12

### Changed

- Unified consensus: parallel Casper/Beacon block feeds disabled in prod path
- Genesis ceremony hashes via native crypto kernel
- Industrial gate `--min-soak-hours` for completed soak evidence

### Live ops

- 48h prod mesh soak started; EVM smoke re-PASS on block #7 (all 3 RPC)

---

## [1.2.29] — 2026-07-12

### Added

- Rust RLP kernel (`rlp_encode`, `rlp_decode`, `rlp_decode_single`) for Ethereum raw tx hot path
- `tests/unit/test_rlp_native.py` — native/Python parity

### Changed

- `crypto/rlp.py` uses `abs_native` when available; Python fallback for dev
- Industrial gate + native self-test cover RLP roundtrip

---

## [1.2.28] — 2026-07-12

### Added

- Fail-closed prod `/contract/deploy` (mempool only); CI prod-mesh3 signed-tx + EVM evidence
- Rust `pubkey_to_eth_address`; `KeyGenerator.derive_address_eth()`
- `docs/evidence_run.example.json`; release notes v1.2.28

### Fixed / hardened

- `block_builder` Merkle tx_root aligned with `core.blockchain`
- Cross-shard digests via native `hash_text`
- Industrial gate: abs_native self-test + wheel export checks
- Mining block-sign errors logged; native fail-closed merkle/canonical paths

### Tests

- `test_api_prod_direct_deploy.py`, `test_block_builder_merkle.py`, `test_keygen_native.py`

---

## [1.2.27] — 2026-07-12

### Added

- `RELEASE_NOTES_v1.2.27.md` — verification mermaid flows + copy-paste prod mesh checks

### Fixed

- **Prod mesh mining stall** — `mesh_ready_for_mining` no longer latches on stale P2P wire roots; STATUS height alignment fallback
- **Event loop freeze** — hub P2P broadcast non-blocking; `blockchain.add_block` via `asyncio.to_thread` (EVM deploy no longer blocks mining)
- **Parallel state-root RPC** — faster peer queries; sync engine skips mismatch while peer catching up
- **EVM deploy txs** — `tx_validator` allows zero-value deploy; `prod_evm_smoke.py` mempool-only cross-node path (no direct deploy fallback)
- **Prod JWT** — `verify_p2p_ci._mint_admin_jwt_from_secret()` for mesh when `/auth/token` disabled

### Proven (local Docker mesh)

- Cross-node EVM: mempool deploy + `eth_getStorageAt` on all 3 RPC nodes (Jul 12 evening run)
- See `docs/EVIDENCE_MATRIX.md`

### Tests

- `tests/unit/test_mesh_mining_ready.py` — stale wire + STATUS height fallback cases

---

## [1.2.26] — 2026-07-06

### Added

- `scripts/prod_evm_smoke.py` — prod HTTP deploy + `eth_getStorageAt` on RPC :18546–:18548
- `scripts/prod_evidence_suite.ps1` — one-shot health + failover + signed tx + EVM

### Fixed

- `prod_signed_tx_smoke.py` — missing `import time`

---

## [1.2.25] — 2026-07-06

### Docs

- `docs/EVIDENCE_MATRIX.md` — proven vs not-proven ops (failover, signed tx, EVM prod, soak 24h+, audit)
- README / MAINNET_GAP / PUBLIC_TESTNET aligned with live prod mesh evidence gaps

---

## [1.2.24] — 2026-07-06

### Added

- Public testnet Docker stack: `docker-compose.testnet.yml`, seed/validator configs, `docker_testnet_seed.ps1`
- nginx TLS/rate-limit template `deploy/nginx/testnet.example.conf`
- `.env.testnet.example` for JWT/RPC keys and ports

---

## [1.2.23] — 2026-07-06

### Added

- Rocks read path for tx propagation (`get_tx_propagation_trace`, `get_recent_tx_propagation`)
- `scripts/testnet_readiness.ps1` — automated PUBLIC_TESTNET local prerequisites

---

## [1.2.22] — 2026-07-06

### Added

- `RocksEngine.state_root_from_account_prefix` — native Rocks scan + state root without Python blob round-trip
- Shared `compute_state_root_from_account_blobs` in Rust `state_trie`

### Changed

- `RocksChainStore.compute_state_root` uses native prefix scan when accumulator is cold

---

## [1.2.21] — 2026-07-06

### Added

- RocksDB storage for `nft_offers`, `nft_auctions`, and `nft_sales` (hybrid prod) + aux migrations
- Reorg invariant test: `StateRootAccumulator` / `compute_state_root` vs `live_state_root` meta

### Fixed

- `soak_monitor.ps1` — hashtable splat to `health_watch` (long soak no longer exits in 50ms); stricter pass criteria

---

## [1.2.20] — 2026-07-06

### Added

- RocksDB storage for `nft_tokens` (hybrid prod path) + aux migration

---

## [1.2.19] — 2026-07-06

### Fixed

- Prod mesh mining stuck when `request_peer_state_roots` returned fewer than 2 responses (`runtime/mesh_mining.py`)

### Added

- Rocks reorg tip metadata test; mesh mining gate unit tests

---

## [1.2.18] — 2026-07-06

### Added

- `prod_mesh_failover.ps1`, `prod_signed_tx_smoke.py`, `prod_mesh_industrial.ps1`
- `verify_p2p_ci --mode prod-mesh3-recovery`
- RocksDB `evm_logs` persistence + hybrid aux migration

### Fixed

- Mesh recovery drill: peer-count fallback when topology is `under_mesh`
- PowerShell exit codes for health_watch / industrial gate

---

## [1.2.17] — 2026-07-06

### Added

- `scripts/soak_monitor.ps1` — 24h+ prod mesh soak with JSON report
- Harness `?quick=1&peer_timeout=3` for fast monitoring polls

### Fixed

- `health_watch.ps1` — harness timeout, quick/full cycle, mesh height alignment, `failed_checks` array handling

### Changed

- `health_watch` uses quick harness by default; full peer scan every 6th cycle

---

## [1.2.16] — 2026-07-06

### Fixed

- Prod mesh followers crash-loop: `require_wallet_file` vs watch-only synced follower (height > 1)
- `docker_prod_3node.ps1/.sh`: `-KeepVolumes` auto-skips DB seed; no-seed path starts all 3 nodes together
- Prod mesh script: node2/node3 wait `/health/ready` (5 min), logs on failure

---

## [1.2.15] — 2026-07-05

### Fixed

- CI: remove unused `numpy` import in `features/postquantum.py` (test collection)
- CI: Docker prod image pushes **GHCR only** (no Docker Hub `abs-blockchain-prod:ci` 401)
- CI: `publish-wheel-on-release.yml` invalid `if: secrets.*` syntax

### Added

- `scripts/health_watch.ps1` — prod mesh poll + optional webhook

### Changed

- `MAINNET_GAP_ANALYSIS.md`, `INCIDENT_RESPONSE.md`, `REPO_PROFILE.md` — RocksDB DR, 703 tests, CI refs
- `OBSERVABILITY.md`, README — health watch docs

---

## [1.2.14] — 2026-07-05

### Added

- `docs/ARCHITECTURE.md` — honest mermaid architecture (prod vs dev paths)
- `docs/PUBLIC_TESTNET.md` — public testnet go-live checklist (not live)
- `.github/workflows/security-audit.yml` — pip-audit on `requirements.txt`

### Changed

- README: GitHub Actions CI badges (tests, docker, security), architecture section, v1.2.13 refs, 703 tests

---

## [1.2.13] — 2026-07-05

### Fixed

- Backup manifest `chain_tip` read from checkpoint copy (was silently 0)
- Verify skips strict tip match when manifest tip is 0 (unknown)

---

## [1.2.12] — 2026-07-05

### Fixed

- Docker backup: mount chain volume read-write (node1 stopped); open RocksDB read-only for checkpoint

---

## [1.2.11] — 2026-07-05

### Fixed

- Docker backup: do not `rmtree` bind-mounted `/backup` (EBUSY on Windows Docker)

---

## [1.2.10] — 2026-07-05

### Fixed

- Docker mesh backup: bind-mount script file instead of stdin pipe (PowerShell on Windows)
- Verify `backup_manifest.json` + `chainstore/` before declaring backup OK
- Resolve node1 image by ID (`docker inspect .Image`) for reliable `docker run`

---

## [1.2.9] — 2026-07-05

### Fixed

- Docker mesh backup uses `docker run` + existing node1 image/volume (no `compose run` rebuild)
- `Dockerfile.prod` — dummy `src/lib.rs` before `cargo fetch` for abs_native layer cache

---

## [1.2.8] — 2026-07-05

### Fixed

- `dr_restore_rehearsal.ps1` — explicit `-DockerMesh1` call (array splat broke switch binding on PS 5.1)
- Docker backup uses `--entrypoint python` (avoid main.py swallowing stdin pipe)

---

## [1.2.7] — 2026-07-05

### Fixed

- Docker mesh backup: stop node1 briefly + one-off checkpoint (RocksDB LOCK while node running)
- Optional `-Live` read-only checkpoint when prod image includes `read_only` RocksEngine

### Changed

- `RocksEngine` — `read_only=True` opens DB with `open_for_read_only` for live backups

---

## [1.2.6] — 2026-07-05

### Fixed

- `backup_chainstore.ps1 -DockerMesh1` — stdin-piped checkpoint backup (no `/app/scripts/` in old prod images)

### Added

- `scripts/docker_backup_in_container.py` — minimal in-container backup via `docker exec python -`

---

## [1.2.5] — 2026-07-05

### Fixed

- `scripts/dr_restore_rehearsal.ps1` — ASCII-only strings (Windows PowerShell 5.1 parse error on em-dash)

### Added

- `scripts/bench_storage_commit.py` — SQLite vs RocksDB commit latency benchmark

---

## [1.2.4] — 2026-07-05

### Added

- RocksDB tuning: `ROCKSDB_BLOCK_CACHE_MB`, `ROCKSDB_WRITE_BUFFER_MB` → native `RocksEngine`
- LSM property introspection in `get_stats()` (`rocksdb_properties`)
- `scripts/dr_restore_rehearsal.ps1` — temp restore verify without touching live data
- `RELEASE_NOTES_v1.2.3.md`

### Changed

- `docs/STORAGE_ROCKSDB.md` — aux.db permanent scope + tuning table

---

## [1.2.3] — 2026-07-05

### Added

- `docs/STORAGE_ROCKSDB.md` — honest hybrid RocksDB architecture + roadmap
- `storage/chain_backup.py` — backup/restore for Rocks chainstore and SQLite
- `scripts/backup_chainstore.py`, `restore_chainstore.py`, `backup_chainstore.ps1`
- `scripts/backup_rocks_drill.py` — CI DR drill for RocksDB
- `tests/unit/test_chain_backup.py`

### Changed

- CI: `backup_rocks_drill.py` + rocks unit tests in hybrid critical gate

---

## [1.2.2] — 2026-07-05

### Added

- `.github/workflows/docker-prod-image.yml` — BuildKit + GHA cache; publishes `ghcr.io/gruver87/abs-blockchain-node` on master/tags
- `-PullLatest` / `--pull-latest` for prod mesh scripts (uses GHCR image via `ABS_PROD_IMAGE`)
- `docs/DOCKER_IMAGES.md` — honest Docker/GHCR ops guide
- BuildKit cache layers in `Dockerfile.devnet-rust` (same pattern as prod)

### Changed

- `docker-compose.prod.3node.yml` — `ABS_PROD_IMAGE` override for prebuilt images
- Prod mesh README section — GHCR pull path documented

---

## [1.2.1] — 2026-07-05

### Added

- `GET /status` — `p2p_sync_status`, `peers_connected`, `validators_registered`, `mesh_min_peers`, `bridge_disabled_reason`
- `GET /bridge/status` — alias for bridge overview
- `scripts/probe_mesh_nodes.ps1` — multi-port mesh/bridge/features probe
- `LightClient.sync_headers_from_peers()` for untrusted peer headers
- `tests/unit/test_light_client_sync.py`

### Fixed

- Light client local bootstrap: `sync_from_blockchain()` uses trusted sequential `add_header()` (was failing peer validation on local DB → “0 headers synced”)
- Explorer dashboard: contextual P2P badges; deployment mode row; bridge off reason
- `scripts/full_audit.py`: solo/stale/under-mesh warnings instead of generic “inconsistent”
- `setup_prod_env.ps1`: explicit `BRIDGE_ENABLED=false` for mainnet-v1 cutover policy

### Docs

- README: deployment matrix, chain IDs 77777 vs 778888, test count 698, probe script
- [RELEASE_NOTES_v1.2.1.md](RELEASE_NOTES_v1.2.1.md)

---

## [1.2.0-industrial] — Wave 37–63 (июнь 2026)

### Wave 63 — Admin lockdown for node repair endpoints

- Node-admin POST endpoints (`/p2p/reconnect`, `/sync/fast-sync`, `/sync/reconcile`, `/chain/consistency/repair`, `/testnet/reorg-exercise`, `/testnet/fork-exercise`) are no longer dev-public when JWT admin enforcement is enabled
- Docker 3-node devnet now runs with `JWT_ENFORCE_ADMIN=true` and a devnet-only `JWT_SECRET`, so recovery/sync tests exercise the real admin boundary
- `verify_p2p_ci.py` automatically obtains a dev JWT from `/auth/token` and retries protected repair/recovery POSTs with `Authorization: Bearer ...`
- Unit coverage now asserts dev-admin `/sync/reconcile` rejects unauthenticated requests and accepts authenticated calls through the auth boundary
- Multi-node proof now reports manifest/evidence-backed effective validator counts and separates low-height pending checks from real failed checks
- **`api_wave` remains 61** — Wave 63 hardens access policy, not the REST API surface

### Wave 62 — Live Docker recovery gate

- `verify_p2p_ci.py --mode devnet3-recovery` — live 3-node Docker recovery drill that stops `node2`, keeps `node1/node3` consistent, restarts `node2`, and requires mesh rejoin plus matching `state_root`
- `scripts/docker_devnet_3node.ps1 -Recovery` — optional industrial gate after normal 3-node verification
- Recovery assertions verify persistent heights, root convergence, peer rejoin, and `topology_healthy=true` after restart
- **`api_wave` remains 61** — Wave 62 hardens live verification, not the REST API surface

### Wave 61 — Network hygiene + real peer rejoin

- P2P handshake now advertises each node's real listening `p2p_port`, so peer discovery/rejoin stores stable node addresses instead of ephemeral TCP socket ports
- `GET /p2p/topology` / `GET /p2p/peer-score` — live peer graph, known rejoin candidates, height gaps, last-seen ages, and topology health
- `POST /p2p/reconnect` — actively reconnect bootstrap/known peers from the unified node runtime
- `scripts/docker_devnet_3node.ps1` — host-port guard prevents local `python main.py` from being mixed with Docker devnet ports
- **`api_wave` → 61**

### Wave 60 — CI L1 RPC + relayer live e2e

- `bridge/mock_l1_rpc.py` — in-process Ethereum JSON-RPC endpoint for isolated CI
- `GET /testnet/bridge-relayer-proof` — relayer readiness dashboard
- `verify_p2p_ci.py` — `verify_bridge_relayer()` + `--mode ci-bridge-relayer`
- **`api_wave` → 60**

### Wave 59 — Bridge relayer e2e + Explorer fork UI

- `RustBridge.enqueue_l1_incoming()` — L1 incoming queue for relayer watch
- `POST /bridge2/transfer` — routes through `RustBridge` when enabled (incoming/outbound)
- `POST /bridge/oracle/l1-register` — enqueues incoming/outbound L1 queue entries
- Explorer — Testnet Fork Monitor card, `l1_tx_hash` on bridge forms, `bridge2` RustBridge path
- `verify_p2p_ci.py` — `verify_bridge()` after adversarial; `--mode ci-bridge` isolated test
- `tests/unit/test_bridge_relayer_e2e.py` — lock → queue → relayer incoming e2e
- **`api_wave` → 59**

### Wave 58 — Fork CI (partition + recovery)

- `GET/POST /testnet/fork-exercise` — fork-status before/after + P2P reconcile drill
- `verify_p2p_ci.py` — `verify_fork_recovery()` after multi-node proof
- `--mode ci-fork` — real partition test: stop follower node, mine ahead, restart, reconcile
- **`api_wave` → 58**

### Wave 57 — Real core (no random stubs in consensus path)

- **Deterministic proposer** — `ConsensusEngine` + `ValidatorSelection.select_proposer_weighted`; removed `random` fallbacks and AI-validator mining shortcut
- **Finality quorum** — `FinalityEngine` uses live validator count (not hardcoded 32)
- **Reorg finality guard** — `Blockchain.reorg_to_ancestor()` refuses rollback below finalized checkpoint
- **P2P reorg** — `ReorgPredictor.analyze_live_peers()` wired into fork reconcile
- **MEV** — fee-ordering analysis from mempool (no `random.uniform` profits)
- **Bridge honesty** — Python bridge adapter only for explicit dev/test paths; Docker uses `RustBridge`
- `GET /status` → `core_real` flags; **`api_wave` → 57**

### Wave 56 — Multi-node proof (3-validator devnet)

- `docker/validators.devnet3.json` — 3 miners + attesters; `node*.devnet3.rust.json` configs
- `GET /testnet/multi-node-proof` — mesh + harness + validators + attestations + `proof_ok`
- `POST /testnet/reorg-exercise` — canonical replay drill (`reorg_safe` flag)
- Proposer rotation threshold: `distinct_proposers >= 3` when `expected_validators >= 3` and height ≥ 12
- `verify_p2p_ci.py` — `verify_multi_node_proof()` after state harness (attestations, rotation, reorg drill)
- **`api_wave` → 56**

### Wave 55 — 5-validator devnet

- `docker-compose.devnet-5validator.yml` — 5 nodes `:8080`–`:8084`, 3 miners + 2 attesters
- `docker/validators.devnet5.json` — manifest; addresses derived at runtime (no keys on disk)
- `GET /testnet/validators` — validator set health, proposer rotation stats
- Mining proposer gate — only selected validator forges when `active_validators > 1`
- `verify_p2p_ci.py --mode devnet5`; `.\scripts\docker_devnet_5validator.ps1`
- Devnet5 sync fix — seeded-chain `dev_signer` skip, `ensure_state_at_tip` replay at tip
- **`scripts/full_audit.py`** — unified audit: syntax, Waves 52–55, secrets, mega/final, pytest, live API, P2P
- `verify_p2p_ci.py` — unique tx recipient per run (no false fail on repeat audit)

### Wave 54 — State consistency harness

- `GET /chain/consistency/harness` — tip alignment, peer roots, supply cap, mismatch audit
- `GET /testnet/state-consistency` — alias for harness on multi-node devnet
- `POST /chain/consistency/repair` — replay chain when live state drifted from tip
- `verify_p2p_ci.py` — cross-node harness check + auto-repair in devnet/ci3 modes

### Wave 53 — Fork / slashing / partition CI

- `GET /testnet/fork-status` — divergent heads, height gaps, `consensus_healthy`, slash summary
- `GET /slashing/events` — persisted slash events from SQLite
- `verify_p2p_ci.py --mode ci3` / `ci-adversarial` — isolated 3-node + double-vote slash test
- Atomic `reorg_to_ancestor` rollback; `ensure_state_at_tip()` on boot; staking catch-up only on miner

### Wave 52 — 3-node testnet (Docker)

- `docker-compose.devnet-3node.yml` — node1 `:8080`, node2 `:8081`, node3 `:8082`
- `GET /testnet/mesh` — peer heights, `mesh_healthy`, `expected_peers`
- `verify_p2p_ci.py --mode devnet3` — 3-node sync + tx on node2 **and** node3 mempools
- `.\scripts\docker_devnet_3node.ps1` — seed DB, force-recreate, CI verify
- Faucet top-up in verify when dev signer balance low

### Wave 51 — Transaction propagation (P2P)

- Full signed tx gossip + mempool pull sync (`get_mempool` / `mempool` P2P messages)
- SQLite `tx_propagation_events` — lifecycle: submit → mempool → P2P → block → receipt
- `GET /tx/trace/{hash}`, `GET /tx/propagation/recent`
- Explorer dashboard: Tx Propagation Trace
- `verify_p2p_ci.py` checks node2 mempool after `/tx/send` on node1

### Wave 50 — Strict state_root on all nodes

- `state_root_strict_p2p` (default `true`) — P2P import rejects `state_root` mismatch above baseline
- `GET /chain/state-root/status` — local root, peer comparison, policy, recent mismatches
- SQLite `state_root_mismatches` audit log; pruned on reorg
- `/sync/status` includes `state_root_strict_p2p` and policy fields

### Wave 49 — Block proposer audit log

- `block_proposer_audit` SQLite table on every confirmed block
- Backfill from historical `blocks` on node start
- `GET /chain/proposers/stats` — top proposers by block count
- `GET /chain/proposers/history` — paginated audit log (`proposer` filter)
- `GET /chain/proposer/{addr}` — proposer detail + recent blocks
- Pruned on reorg; `proposer_audit_count` in `/chain/metrics`

### Wave 48 — Address tx index + receipt backfill

- `GET /address/{addr}/activity` — balance, sent/received counts, last tx height
- `GET /address/{addr}/txs` — paginated history (`limit`, `offset`, `direction=sent|received|all`)
- Idempotent backfill: historical `transactions` → `tx_receipts` on each node start

### Wave 47 — Core L1 receipts + chain metrics

- `tx_receipts` SQLite table on every confirmed tx
- `GET /chain/metrics` — avg block time, tx/receipt counts
- `GET /tx/receipt/{hash}`, `GET /receipts/block/{height}`
- Receipts pruned on reorg (`truncate_chain_state`)

### Wave 46 — NFT SQLite persistence

- NFT tokens, offers, auctions, sales history в SQLite
- Genesis collection seed при пустой БД; mint/buy/transfer сохраняются
- `GET /nft/stats`, `nft_persisted` в `/l2/status`

### Wave 45 — Reorg predictor + dev bridge

- SQLite-история оценок реорга (`reorg_assessments`)
- Исправлены `GET /reorg/depth`, `/reorg/fork`, добавлены `/reorg/history`
- `GET /features` — `api_wave`, `l2_modules`, подсказка `bridge_dev_confirm`
- Dev: `POST /bridge/confirm-pending` и alias `/bridge/dev-confirm-pending` (без HMAC)

### Wave 44 — L2 dashboard + MEV history

- `GET /l2/status` — единый дашборд Lightning / Plasma / Will / WASM / AI
- MEV analyzer: история в SQLite, `GET /mev/history`

### Wave 43 — AI agents

- AI agents / trades в SQLite, create fee 0.01 ABS
- Plasma `submit-block`: подсказки при пустой очереди

### Wave 42 — WASM + relayer status

- WASM VM: контракты / storage / events в SQLite, deploy fee 0.01 ABS
- `GET /bridge/relayer/status` — L1 queue + pending locks

### Wave 41 — Crypto Will

- Завещания в SQLite: create блокирует L1, execute → heir, cancel → refund
- `POST /will/execute` (`force=true` в dev)

### Wave 40 — L2 persistence

- Lightning: каналы в SQLite, open/close влияет на L1 ABS
- Plasma: deposits / blocks / exits в SQLite, deposit/exit влияет на L1

### Wave 39 — Oracle registry + bridge L1 queue

- HMAC-signed oracle feeds в SQLite (`GET /oracles/feeds`, `POST /oracles/feeds/submit`)
- `POST /bridge/lock` с `l1_tx_hash` → `data/bridge_l1_queue.json`
- `GET /bridge/l1-queue`, alias `GET /oracles/l1-queue`

### Wave 37–38 — EVM hardening + P2P

- EVM: LOG, EXTCODE, SELFDESTRUCT, BLOCKHASH, CALLCODE; bytecode validator в mempool
- EVM logs в SQLite (`GET /evm/logs`)
- Sharding: cross-shard реальные переводы балансов
- Bridge: `l1_tx_hash` обязателен при `ETH_RPC_URL`
- Секреты только в `.env`, честная документация в `docs/ALL_COMMANDS.txt`

---

## Проверено локально

| Проверка | Результат |
|----------|-----------|
| `pytest tests/unit` | 217 passed, 1 skipped |
| Docker devnet 2 nodes | P2P sync, heights aligned, `state_roots_match=True` |
| Docker devnet 3 nodes | `GET /testnet/mesh`, tx on node2+node3 mempools |
| `api_wave` | 52 |
| `mega_audit.py` | 256 REST routes |

---

## Честно: что это **не** даёт

- Не production mainnet
- Не полный EVM / не Ethereum-совместимость на 100%
- Bridge / Lightning / Plasma / MEV — dev/test or analysis modules with real L1 effects where stated
- Крипто-аудит не проводился

См. [DISCLAIMER.md](DISCLAIMER.md) и **Часть 0** в [docs/ALL_COMMANDS.txt](docs/ALL_COMMANDS.txt).
