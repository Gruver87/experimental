# Architecture Decision Records

Boundary ADRs for Absolute Blockchain Ultimate Hybrid.  
**Industrial stack:** **0001–0016** · **0013 unused**.  
**Experimental (this sandbox):** **0017–0020** (not on audit pin).

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-tip-safety.md) | Tip safety | Accepted |
| [0002](0002-p2p-transport-boundary.md) | P2P transport boundary | Accepted |
| [0003](0003-sync-consistency.md) | Sync consistency / solicit hub | Accepted |
| [0004](0004-catchup-path-a.md) | Catch-up Path A | Accepted |
| [0005](0005-fork-reconcile.md) | Fork reconcile | Accepted |
| [0006](0006-storage-boundary.md) | StoragePort | Accepted |
| [0007](0007-consensus-boundary.md) | ConsensusPort / Round SM | Accepted |
| [0008](0008-hotpath-wire-codec.md) | Hot-path wire codec | Accepted |
| [0009](0009-optional-native-fallback.md) | Optional native fallback | Accepted |
| [0010](0010-evm-bridge-boundary.md) | EVM / BridgePort | Accepted |
| [0011](0011-rpc-api-boundary.md) | QueryFacade / RPC | Accepted |
| [0012](0012-chaos-injection.md) | Chaos injection | Accepted |
| *0013* | *(intentionally unused)* | — |
| [0014](0014-graceful-shutdown-deep-health.md) | Graceful shutdown / deep ready | Accepted |
| [0015](0015-observability-secret-management.md) | Observability + SecretManager | Accepted |
| [0016](0016-feature-sprouts-profiles.md) | Feature sprouts / profiles | Accepted |
| [0017](0017-long-range-research.md) | Long-Range / WS research | Accepted (experimental) |
| [0018](0018-libp2p-transport.md) | libp2p dual-stack transport | Accepted (experimental) |
| [0019](0019-rust-libp2p-industrial.md) | rust-libp2p industrial path | Accepted (experimental) |
| [0020](0020-libp2p-industrial-mesh.md) | Experimental industrial libp2p mesh | Accepted (experimental) |
| [0021](0021-mempool-validation-rust-phases.md) | Mempool / validation Rust phases (plan) | Accepted (plan only) |
| [0022](0022-gruver87-genesis-council-governance.md) | Gruver87 Genesis Council (87 NFT governance) | Accepted (design + lab path) |

System map: [ARCHITECTURE.md](../ARCHITECTURE.md) · sprouts: [sprouts/](../sprouts/) · **execution order:** [EXECUTION_ORDER.md](../EXECUTION_ORDER.md)
