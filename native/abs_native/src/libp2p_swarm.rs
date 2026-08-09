//! ADR 0019 — optional rust-libp2p swarm (FEATURE_LIBP2P / Cargo feature `libp2p`).
//!
//! Slice A: listen/dial/identify/ping.
//! Slice B: `/abs/wire/1.0.0` request-response (Absolute wire bytes).
//! Slice C: dial budgets / backpressure counters.
//! Slice D: status / ADR 0008 bridge / peer policy (Python edge).
//! Slice E: gossipsub announce + identify Received snapshots.
//! Slice F: persistent PeerId keystore + mDNS discovery.
//! Slice G: Kademlia DHT (MemoryStore) + Absolute gossip announce edge.
//! Slice H: circuit-relay-v2 + connection_limits.
//! Slice I: allow/block-list peer enforcement (native ban hooks).
//! Slice K: mDNS Toggle + loopback-only discovery hygiene.
//! Slice L: Absolute wire request timeout + adapter API parity (Python edge).
//! Slice M: ADR 0008 Absolute wire codecs (v1 NDJSON / v2 Borsh AB2) over `/abs/wire`.
//! Slice N: AutoNAT + DCUtR (NAT status + hole-punch over relay).
//! Slice O: persistent bootstrap peer list (JSON file) + dial-all.
//! Slice P: bootstrap reconnect policy (backoff) on ConnectionClosed.
//! Slice Q: gossipsub peer scoring + app score hooks + validation accept metrics.
//! Slice R: ping RTT metrics + unhealthy peer disconnect policy.
//! Slice S: low gossip peer-score auto-block (graylist bridge to allow/block-list).
//! Slice T: persistent learned peerstore (identify/connection → JSON) + warm dial.
//! Slice U: reconnect policy also covers learned peerstore peers (not only bootstrap).
//! Slice V: idle connection timeout policy (swarm keep-alive / idle close).
//! Slice W: IPv6 dual-stack listen/dial (`/ip6/.../tcp/...`) + metrics.
//! Slice X: rendezvous server/client register + discover.
//! Slice Y: DNS multiaddr dial (`/dns4` / `/dns6`) via rust-libp2p dns transport.
//! Slice Z: Prometheus export of libp2p_* status metrics (Python /metrics edge).
//! Slice AA: connection manager — full ConnectionLimits + runtime set_connection_limits.
//! Slice AB: QUIC transport (`/udp/.../quic-v1`) alongside TCP (lab opt-in listen/dial).
//! Slice AC: WebSocket transport (`/tcp/.../ws`) alongside TCP/QUIC (lab opt-in).
//! Slice AD: UPnP / IGD port mapping (opt-in; default off — no gateway required for CI).
//! Slice AE: allow-list (whitelist) Toggle — opt-in complement to Slice I block-list.
//! Slice AF: bandwidth accounting (`BandwidthSinks` → `libp2p_bytes_in` / `libp2p_bytes_out`).
//! Slice AG: external address book (confirmed/expired/candidates + add/remove API).
//! Slice AH: connection lifecycle metrics (inbound/outgoing established, closed, incoming).
//! Slice AI–AO: close-cause / listener / dial attempt / identify / gossip sub /
//!   kad / wire RR event metrics (see ADR 0019).
//! Slice AP: relay server event taxonomy (deny / timeout / circuit closed).
//! Slice AQ: rendezvous server/client event taxonomy (discover served / unregister).
//! Slice AR: AutoNAT probe event taxonomy (inbound/outbound + errors).
//! Slice AS: mDNS discover/expire event metrics + lab TTL override.
//! Slice AT: relay client circuit direction taxonomy (inbound/outbound).
//! Slice AU: outbound dial failure taxonomy (transport / wrong peer / …).
//! Slice AV: inbound ListenError taxonomy (mirror of AU).
//! Slice AW: outbound DialError::Denied taxonomy (`dial_fail_denied`).
//! Slice AX: Denied cause taxonomy (block / allow / connection-limits),
//!   direction-specific (`dial_fail_denied_*` / `incoming_fail_denied_*`).
//! Slice AY: ping failure taxonomy (`timeout` / `unsupported` / `other`).
//! Slice AZ: wire RR outbound/inbound failure taxonomy.
//! Slice BA: deferred gossip validation + ignore/reject outcome metrics.
//!
//! Honesty: compiled swarm ≠ prod industrial mesh (TCP+TLS remains default).

use pyo3::prelude::*;

// Used under feature=libp2p; default Hybrid clippy build has feature off.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const ABS_WIRE_PROTOCOL: &str = "/abs/wire/1.0.0";
/// Default gossip topic for Absolute block announce labs (Slice E).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const ABS_GOSSIP_BLOCKS_TOPIC: &str = "abs/blocks/1.0.0";
/// Absolute Kademlia protocol id (Slice G; not IPFS bootstrap).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const ABS_KAD_PROTOCOL: &str = "/absolute/kad/1.0.0";
/// Default rendezvous namespace (Slice X).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const ABS_RENDEZVOUS_NAMESPACE: &str = "absolute";
/// Default max concurrent outbound dials (Slice C).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_MAX_DIALS: u32 = 32;
/// Max wire / gossip payload bytes (lab bound).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const MAX_WIRE_BYTES: usize = 1024 * 1024;
/// Default `/abs/wire/1.0.0` request-response timeout (Slice L).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_WIRE_TIMEOUT_SECS: u64 = 10;
/// Default mDNS record TTL (Slice F / AS).
pub const DEFAULT_MDNS_TTL_SECS: u64 = 60;
/// Swarm idle connection timeout (Slice V; was hardcoded 60s).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_IDLE_CONNECTION_TIMEOUT_SECS: u64 = 60;
/// Per-entry bootstrap dial settle timeout (Slice O industrial).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_BOOTSTRAP_DIAL_TIMEOUT_SECS: u64 = 8;
/// Slice P reconnect backoff base / cap / attempts.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_RECONNECT_BASE_MS: u64 = 500;
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_RECONNECT_MAX_MS: u64 = 5_000;
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_RECONNECT_MAX_ATTEMPTS: u32 = 8;
/// Per-attempt safety wait for reconnect (errors are watch-only; see OutgoingConnectionError).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_RECONNECT_DIAL_TIMEOUT_SECS: u64 = 5;
/// Slice R ping defaults (faster interval for lab observability).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_PING_INTERVAL_SECS: u64 = 2;
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_PING_TIMEOUT_SECS: u64 = 10;
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_PING_MAX_FAILS: u32 = 3;
/// Slice S: default gossip graylist threshold (matches PeerScoreThresholds::default).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_SCORE_GRAYLIST_THRESHOLD: f64 = -80.0;

/// Classify Absolute ADR 0008 payload on `/abs/wire` (Slice M).
///
/// - `v2`: `AB2:` + hex(Borsh) line (ADR 0008 dual-stack)
/// - `v1`: NDJSON `{...}` line
/// - `lab`: Slice B `libp2p_pack_wire` / other lab frames
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn classify_abs_wire_codec(data: &[u8]) -> &'static str {
    let mut end = data.len();
    while end > 0 && (data[end - 1] == b'\n' || data[end - 1] == b'\r') {
        end -= 1;
    }
    let body = &data[..end];
    if body.starts_with(b"AB2:") {
        "v2"
    } else if body.starts_with(b"{") {
        "v1"
    } else {
        "lab"
    }
}

#[pyfunction]
fn libp2p_available() -> bool {
    cfg!(feature = "libp2p")
}

#[cfg(not(feature = "libp2p"))]
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(libp2p_available, m)?)?;
    Ok(())
}

#[cfg(feature = "libp2p")]
mod enabled {
    use super::{
        libp2p_available, ABS_GOSSIP_BLOCKS_TOPIC, ABS_KAD_PROTOCOL, ABS_RENDEZVOUS_NAMESPACE,
        ABS_WIRE_PROTOCOL, DEFAULT_BOOTSTRAP_DIAL_TIMEOUT_SECS,
        DEFAULT_IDLE_CONNECTION_TIMEOUT_SECS, DEFAULT_MAX_DIALS, DEFAULT_MDNS_TTL_SECS,
        DEFAULT_PING_INTERVAL_SECS, DEFAULT_PING_MAX_FAILS, DEFAULT_PING_TIMEOUT_SECS,
        DEFAULT_RECONNECT_BASE_MS, DEFAULT_RECONNECT_DIAL_TIMEOUT_SECS,
        DEFAULT_RECONNECT_MAX_ATTEMPTS, DEFAULT_RECONNECT_MAX_MS, DEFAULT_SCORE_GRAYLIST_THRESHOLD,
        DEFAULT_WIRE_TIMEOUT_SECS, MAX_WIRE_BYTES,
    };
    use async_trait::async_trait;
    use futures::prelude::*;
    #[allow(deprecated)]
    use libp2p::bandwidth::BandwidthSinks;
    use libp2p::core::transport::ListenerId;
    use libp2p::core::ConnectedPoint;
    use libp2p::multiaddr::Protocol;
    use libp2p::{
        allow_block_list,
        allow_block_list::{AllowedPeers, BlockedPeers},
        autonat, connection_limits, dcutr, gossipsub, identify,
        identity::Keypair,
        kad::{self, store::MemoryStore},
        mdns, noise, ping, relay, rendezvous, request_response,
        swarm::{
            behaviour::toggle::Toggle, ConnectionError, DialError, ListenError, NetworkBehaviour,
            SwarmEvent,
        },
        tcp, upnp, yamux, Multiaddr, PeerId, StreamProtocol, SwarmBuilder,
    };
    use pyo3::exceptions::{PyRuntimeError, PyValueError};
    use pyo3::prelude::*;
    use pyo3::types::PyBytes;
    use std::collections::hash_map::DefaultHasher;
    use std::collections::{HashMap, HashSet, VecDeque};
    use std::hash::{Hash, Hasher};
    use std::io;
    use std::path::Path;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;
    use tokio::sync::{mpsc, oneshot};

    fn load_or_create_keypair(path: &Path) -> Result<Keypair, String> {
        if path.exists() {
            let bytes = std::fs::read(path).map_err(|e| format!("read key: {e}"))?;
            Keypair::from_protobuf_encoding(&bytes).map_err(|e| format!("decode key: {e}"))
        } else {
            if let Some(parent) = path.parent() {
                if !parent.as_os_str().is_empty() {
                    std::fs::create_dir_all(parent).map_err(|e| format!("create key dir: {e}"))?;
                }
            }
            let kp = Keypair::generate_ed25519();
            let enc = kp
                .to_protobuf_encoding()
                .map_err(|e| format!("encode key: {e}"))?;
            std::fs::write(path, enc).map_err(|e| format!("write key: {e}"))?;
            Ok(kp)
        }
    }

    /// Slice O: JSON bootstrap peer book.
    ///
    /// ```json
    /// {"version":1,"peers":{"12D3KooW...":["/ip4/.../tcp/.../p2p/12D3KooW..."]}}
    /// ```
    fn load_bootstrap_peers(path: &Path) -> Result<HashMap<String, Vec<String>>, String> {
        if !path.exists() {
            return Ok(HashMap::new());
        }
        let raw = std::fs::read_to_string(path).map_err(|e| format!("read bootstrap: {e}"))?;
        let v: serde_json::Value =
            serde_json::from_str(&raw).map_err(|e| format!("bootstrap json: {e}"))?;
        let mut out: HashMap<String, Vec<String>> = HashMap::new();
        if let Some(peers) = v.get("peers").and_then(|p| p.as_object()) {
            for (pid, addrs) in peers {
                let list: Vec<String> = match addrs {
                    serde_json::Value::Array(a) => a
                        .iter()
                        .filter_map(|x| x.as_str().map(|s| s.to_string()))
                        .collect(),
                    serde_json::Value::String(s) => vec![s.clone()],
                    _ => Vec::new(),
                };
                if !list.is_empty() {
                    out.insert(pid.clone(), list);
                }
            }
        }
        Ok(out)
    }

    fn save_bootstrap_peers(
        path: &Path,
        peers: &HashMap<String, Vec<String>>,
    ) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)
                    .map_err(|e| format!("create bootstrap dir: {e}"))?;
            }
        }
        let mut map = serde_json::Map::new();
        for (pid, addrs) in peers {
            map.insert(
                pid.clone(),
                serde_json::Value::Array(
                    addrs
                        .iter()
                        .map(|a| serde_json::Value::String(a.clone()))
                        .collect(),
                ),
            );
        }
        let doc = serde_json::json!({
            "version": 1,
            "peers": map,
        });
        let body =
            serde_json::to_string_pretty(&doc).map_err(|e| format!("bootstrap encode: {e}"))?;
        std::fs::write(path, body).map_err(|e| format!("write bootstrap: {e}"))
    }

    fn flatten_bootstrap_addrs(peers: &HashMap<String, Vec<String>>) -> Vec<(String, String)> {
        let mut out = Vec::new();
        let mut keys: Vec<&String> = peers.keys().collect();
        keys.sort();
        for pid in keys {
            if let Some(addrs) = peers.get(pid) {
                for a in addrs {
                    out.push((pid.clone(), a.clone()));
                }
            }
        }
        out
    }

    /// In-flight industrial bootstrap/peerstore dial batch (Slices O/T).
    #[derive(Clone, Copy, PartialEq, Eq)]
    enum BookDialKind {
        Bootstrap,
        Peerstore,
    }

    struct BootstrapDialJob {
        kind: BookDialKind,
        queue: VecDeque<(String, String)>,
        results: Vec<(String, String)>,
        /// Peer currently being dialed (awaiting settle).
        current_peer: Option<String>,
        reply: oneshot::Sender<Result<Vec<(String, String)>, String>>,
        per_dial_deadline: Option<tokio::time::Instant>,
        /// Peers already recorded after per-dial timeout (ignore late events for results).
        abandoned: HashSet<String>,
    }

    fn book_bump_attempted(st: &mut NodeState, kind: BookDialKind) {
        match kind {
            BookDialKind::Bootstrap => {
                st.bootstrap_dials_attempted = st.bootstrap_dials_attempted.saturating_add(1);
            }
            BookDialKind::Peerstore => {
                st.peerstore_dials_attempted = st.peerstore_dials_attempted.saturating_add(1);
            }
        }
    }

    fn book_bump_ok(st: &mut NodeState, kind: BookDialKind) {
        match kind {
            BookDialKind::Bootstrap => {
                st.bootstrap_dials_ok = st.bootstrap_dials_ok.saturating_add(1);
            }
            BookDialKind::Peerstore => {
                st.peerstore_dials_ok = st.peerstore_dials_ok.saturating_add(1);
            }
        }
    }

    fn book_bump_fail(st: &mut NodeState, kind: BookDialKind) {
        match kind {
            BookDialKind::Bootstrap => {
                st.bootstrap_dials_fail = st.bootstrap_dials_fail.saturating_add(1);
            }
            BookDialKind::Peerstore => {
                st.peerstore_dials_fail = st.peerstore_dials_fail.saturating_add(1);
            }
        }
    }

    fn book_bump_timeout(st: &mut NodeState, kind: BookDialKind) {
        match kind {
            BookDialKind::Bootstrap => {
                st.bootstrap_dials_timeout = st.bootstrap_dials_timeout.saturating_add(1);
                st.bootstrap_dials_fail = st.bootstrap_dials_fail.saturating_add(1);
            }
            BookDialKind::Peerstore => {
                st.peerstore_dials_timeout = st.peerstore_dials_timeout.saturating_add(1);
                st.peerstore_dials_fail = st.peerstore_dials_fail.saturating_add(1);
            }
        }
    }

    /// Persist a dialable address into the learned peerstore (Slice T).
    fn peerstore_note_addr(state: &Arc<Mutex<NodeState>>, peer_id: &str, addr: &str) {
        let mut ma = addr.trim().to_string();
        if ma.is_empty() || peer_id.is_empty() {
            return;
        }
        if !ma.contains("/p2p/") {
            ma = format!("{ma}/p2p/{peer_id}");
        }
        // Prefer direct TCP; skip pure circuit listen addrs for warm dial book.
        if ma.contains("/p2p-circuit") && !ma.contains("/tcp/") {
            return;
        }
        let persist = if let Ok(mut st) = state.lock() {
            if st.peerstore_path.is_empty() {
                return;
            }
            let entry = st.peerstore.entry(peer_id.to_string()).or_default();
            if entry.contains(&ma) {
                return;
            }
            // If we already learned a loopback dial endpoint, ignore non-loopback
            // identify listen addrs (hub often binds 127.0.0.1 only; LAN IPs refuse).
            let has_loopback = entry.iter().any(|a| addr_is_loopback(a));
            if has_loopback && !addr_is_loopback(&ma) {
                return;
            }
            entry.push(ma);
            st.peerstore_learned = st.peerstore_learned.saturating_add(1);
            (st.peerstore_path.clone(), st.peerstore.clone())
        } else {
            return;
        };
        let _ = save_bootstrap_peers(Path::new(&persist.0), &persist.1);
    }

    fn addr_is_loopback(addr: &str) -> bool {
        addr.contains("/ip4/127.0.0.1/")
            || addr.contains("/ip4/127.")
            || addr.contains("/ip6/::1/")
            || addr.contains("/ip6/0:0:0:0:0:0:0:1/")
    }

    /// Order reconnect dial targets: loopback TCP first, then other direct TCP,
    /// circuits last. Avoids Autonat/identify LAN addrs stealing the first slot
    /// when the peer only listens on 127.0.0.1.
    fn prefer_reconnect_addrs(addrs: Vec<String>) -> Vec<String> {
        let mut loopback = Vec::new();
        let mut direct = Vec::new();
        let mut rest = Vec::new();
        for a in addrs {
            if a.contains("/p2p-circuit") {
                rest.push(a);
            } else if addr_is_loopback(&a) {
                loopback.push(a);
            } else if a.contains("/tcp/") {
                direct.push(a);
            } else {
                rest.push(a);
            }
        }
        loopback.extend(direct);
        loopback.extend(rest);
        loopback
    }

    /// Slice P: scheduled bootstrap reconnect with exponential backoff.
    #[derive(Clone)]
    struct PendingReconnect {
        attempts: u32,
        next_at: tokio::time::Instant,
        addrs: Vec<String>,
        addr_idx: usize,
    }

    fn reconnect_backoff_ms(base_ms: u64, max_ms: u64, attempts: u32) -> u64 {
        let shift = attempts.min(16);
        let raw = base_ms.saturating_mul(1u64 << shift);
        raw.min(max_ms.max(base_ms))
    }

    /// Clear pending/inflight reconnect for `pid` and count success.
    fn reconnect_settle_ok(
        state: &Arc<Mutex<NodeState>>,
        pending_reconnects: &mut HashMap<String, PendingReconnect>,
        reconnect_inflight: &mut Option<String>,
        reconnect_inflight_deadline: &mut Option<tokio::time::Instant>,
        pid: &str,
    ) {
        let was_pending = pending_reconnects.remove(pid).is_some();
        let was_inflight = reconnect_inflight.as_deref() == Some(pid);
        if was_inflight {
            *reconnect_inflight = None;
            *reconnect_inflight_deadline = None;
        }
        if was_pending || was_inflight {
            if let Ok(mut st) = state.lock() {
                st.reconnect_ok = st.reconnect_ok.saturating_add(1);
            }
        }
    }

    /// Try to start the next bootstrap dial entry. Returns `true` if job finished and reply sent.
    fn bootstrap_advance(
        swarm: &mut libp2p::Swarm<AbsBehaviour>,
        state: &Arc<Mutex<NodeState>>,
        job: &mut Option<BootstrapDialJob>,
    ) -> bool {
        let Some(j) = job.as_mut() else {
            return false;
        };
        if j.current_peer.is_some() {
            return false;
        }
        let timeout = state
            .lock()
            .map(|st| Duration::from_secs(st.bootstrap_dial_timeout_secs.max(1)))
            .unwrap_or_else(|_| Duration::from_secs(DEFAULT_BOOTSTRAP_DIAL_TIMEOUT_SECS));

        loop {
            let Some((pid, addr)) = j.queue.pop_front() else {
                let finished = job.take().expect("bootstrap job");
                let _ = finished.reply.send(Ok(finished.results));
                return true;
            };

            // Already connected — count as success without a new dial.
            let already = state
                .lock()
                .map(|st| st.connected.contains(&pid))
                .unwrap_or(false);
            if already {
                if let Ok(mut st) = state.lock() {
                    book_bump_attempted(&mut st, j.kind);
                    book_bump_ok(&mut st, j.kind);
                }
                j.results.push((pid, "already_connected".into()));
                continue;
            }

            if state
                .lock()
                .map(|st| st.blocked.contains(&pid))
                .unwrap_or(false)
            {
                if let Ok(mut st) = state.lock() {
                    book_bump_attempted(&mut st, j.kind);
                    book_bump_fail(&mut st, j.kind);
                    st.block_denied = st.block_denied.saturating_add(1);
                    // Slice AW/AX: Denied taxonomy on bootstrap/peerstore dial skip.
                    st.dial_fail = st.dial_fail.saturating_add(1);
                    st.dial_fail_denied = st.dial_fail_denied.saturating_add(1);
                    st.dial_fail_denied_block = st.dial_fail_denied_block.saturating_add(1);
                }
                j.results.push((pid, "peer_blocked".into()));
                continue;
            }

            let reserved = if let Ok(mut st) = state.lock() {
                let used = (st.outbound_peers.len() as u32).saturating_add(st.dial_inflight);
                if used < st.max_dials {
                    st.dial_inflight = st.dial_inflight.saturating_add(1);
                    book_bump_attempted(&mut st, j.kind);
                    true
                } else {
                    st.dial_refused_budget = st.dial_refused_budget.saturating_add(1);
                    book_bump_attempted(&mut st, j.kind);
                    book_bump_fail(&mut st, j.kind);
                    false
                }
            } else {
                false
            };
            if !reserved {
                j.results.push((pid, "dial_budget_exceeded".into()));
                continue;
            }

            let ma = match addr.parse::<Multiaddr>() {
                Ok(m) => m,
                Err(e) => {
                    if let Ok(mut st) = state.lock() {
                        st.dial_inflight = st.dial_inflight.saturating_sub(1);
                        book_bump_fail(&mut st, j.kind);
                    }
                    j.results.push((pid, format!("bad multiaddr: {e}")));
                    continue;
                }
            };

            if let Err(e) = swarm.dial(ma) {
                if let Ok(mut st) = state.lock() {
                    st.dial_inflight = st.dial_inflight.saturating_sub(1);
                    book_bump_fail(&mut st, j.kind);
                    st.dial_fail = st.dial_fail.saturating_add(1);
                }
                j.results.push((pid, format!("dial: {e}")));
                continue;
            }

            if let Ok(mut st) = state.lock() {
                st.dialing = st.dialing.saturating_add(1);
            }

            j.current_peer = Some(pid);
            j.per_dial_deadline = Some(tokio::time::Instant::now() + timeout);
            return false;
        }
    }

    fn bootstrap_record_settle(
        state: &Arc<Mutex<NodeState>>,
        job: &mut Option<BootstrapDialJob>,
        peer_id: &str,
        status: String,
        kind: &str,
    ) {
        let Some(j) = job.as_mut() else {
            return;
        };
        if j.abandoned.contains(peer_id) {
            return;
        }
        if j.current_peer.as_deref() != Some(peer_id) {
            return;
        }
        let book = j.kind;
        if let Ok(mut st) = state.lock() {
            match kind {
                "ok" => book_bump_ok(&mut st, book),
                "timeout" => book_bump_timeout(&mut st, book),
                _ => book_bump_fail(&mut st, book),
            }
        }
        j.results.push((peer_id.to_string(), status));
        j.current_peer = None;
        j.per_dial_deadline = None;
    }

    #[derive(Debug, Clone, Default)]
    struct AbsWireCodec;

    #[async_trait]
    impl request_response::Codec for AbsWireCodec {
        type Protocol = StreamProtocol;
        type Request = Vec<u8>;
        type Response = Vec<u8>;

        async fn read_request<T>(
            &mut self,
            _: &Self::Protocol,
            io: &mut T,
        ) -> io::Result<Self::Request>
        where
            T: AsyncRead + Unpin + Send,
        {
            read_lp(io).await
        }

        async fn read_response<T>(
            &mut self,
            _: &Self::Protocol,
            io: &mut T,
        ) -> io::Result<Self::Response>
        where
            T: AsyncRead + Unpin + Send,
        {
            read_lp(io).await
        }

        async fn write_request<T>(
            &mut self,
            _: &Self::Protocol,
            io: &mut T,
            data: Self::Request,
        ) -> io::Result<()>
        where
            T: AsyncWrite + Unpin + Send,
        {
            write_lp(io, &data).await
        }

        async fn write_response<T>(
            &mut self,
            _: &Self::Protocol,
            io: &mut T,
            data: Self::Response,
        ) -> io::Result<()>
        where
            T: AsyncWrite + Unpin + Send,
        {
            write_lp(io, &data).await
        }
    }

    async fn read_lp<T>(io: &mut T) -> io::Result<Vec<u8>>
    where
        T: AsyncRead + Unpin + Send,
    {
        let mut len_buf = [0u8; 4];
        io.read_exact(&mut len_buf).await?;
        let len = u32::from_be_bytes(len_buf) as usize;
        if len > MAX_WIRE_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "wire payload too large",
            ));
        }
        let mut buf = vec![0u8; len];
        if len > 0 {
            io.read_exact(&mut buf).await?;
        }
        Ok(buf)
    }

    async fn write_lp<T>(io: &mut T, data: &[u8]) -> io::Result<()>
    where
        T: AsyncWrite + Unpin + Send,
    {
        if data.len() > MAX_WIRE_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "wire payload too large",
            ));
        }
        let len = (data.len() as u32).to_be_bytes();
        io.write_all(&len).await?;
        if !data.is_empty() {
            io.write_all(data).await?;
        }
        io.flush().await?;
        Ok(())
    }

    #[derive(NetworkBehaviour)]
    struct AbsBehaviour {
        ping: ping::Behaviour,
        identify: identify::Behaviour,
        wire: request_response::Behaviour<AbsWireCodec>,
        gossipsub: gossipsub::Behaviour,
        mdns: Toggle<mdns::tokio::Behaviour>,
        kademlia: kad::Behaviour<MemoryStore>,
        relay: relay::Behaviour,
        relay_client: relay::client::Behaviour,
        /// Slice N: off by default — AutoNAT probe dials raced reconnect (Slice U).
        autonat: Toggle<autonat::Behaviour>,
        /// Slice AD: off by default — needs IGD gateway; CI expects GatewayNotFound.
        upnp: Toggle<upnp::tokio::Behaviour>,
        /// Slice AE: off by default — empty allow-list denies all until allow_peer.
        allowed_peers: Toggle<allow_block_list::Behaviour<AllowedPeers>>,
        dcutr: dcutr::Behaviour,
        /// Slice X: rendezvous point (always on; lab register/discover).
        rendezvous_server: rendezvous::server::Behaviour,
        rendezvous_client: rendezvous::client::Behaviour,
        connection_limits: connection_limits::Behaviour,
        blocked_peers: allow_block_list::Behaviour<BlockedPeers>,
    }

    enum Cmd {
        Listen {
            addr: String,
            reply: oneshot::Sender<Result<Vec<String>, String>>,
        },
        /// Dial relay and listen on `/p2p-circuit` (Slice H reservation).
        ListenRelay {
            relay_addr: String,
            reply: oneshot::Sender<Result<Vec<String>, String>>,
        },
        /// Slice AJ: stop a listener by reported listen multiaddr.
        RemoveListener {
            addr: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        Dial {
            addr: String,
            reply: oneshot::Sender<Result<String, String>>,
        },
        SendWire {
            peer_id: String,
            data: Vec<u8>,
            reply: oneshot::Sender<Result<Vec<u8>, String>>,
        },
        PollInbox {
            reply: oneshot::Sender<Vec<(String, Vec<u8>)>>,
        },
        Subscribe {
            topic: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        Unsubscribe {
            topic: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        Publish {
            topic: String,
            data: Vec<u8>,
            reply: oneshot::Sender<Result<String, String>>,
        },
        PollGossip {
            reply: oneshot::Sender<Vec<(String, String, Vec<u8>)>>,
        },
        /// Slice AM: current gossipsub mesh peers for a topic.
        GossipMeshPeers {
            topic: String,
            reply: oneshot::Sender<Vec<String>>,
        },
        /// Slice AM: peers known to subscribe to a topic (fanout/mesh book).
        GossipTopicPeers {
            topic: String,
            reply: oneshot::Sender<Vec<String>>,
        },
        KadAddAddress {
            peer_id: String,
            addr: String,
            reply: oneshot::Sender<Result<String, String>>,
        },
        KadGetClosest {
            peer_id: String,
            reply: oneshot::Sender<Result<Vec<String>, String>>,
        },
        BlockPeer {
            peer_id: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        UnblockPeer {
            peer_id: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Slice AE: allow-list allow / disallow (requires enable_allow_list).
        AllowPeer {
            peer_id: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        DisallowPeer {
            peer_id: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Explicit AutoNAT server registration (Slice N lab).
        AutonatAddServer {
            peer_id: String,
            addr: Option<String>,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Slice X: register listen/external addrs at a rendezvous peer.
        RendezvousRegister {
            namespace: String,
            rendezvous_peer: String,
            ttl: Option<u64>,
            reply: oneshot::Sender<Result<u64, String>>,
        },
        /// Slice X: discover peers registered at a rendezvous peer.
        RendezvousDiscover {
            namespace: Option<String>,
            rendezvous_peer: String,
            limit: Option<u64>,
            reply: oneshot::Sender<Result<Vec<(String, Vec<String>)>, String>>,
        },
        RendezvousUnregister {
            namespace: String,
            rendezvous_peer: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Slice AG: mark multiaddr as externally reachable / expire it.
        AddExternalAddress {
            addr: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        RemoveExternalAddress {
            addr: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Slice AA: mutate ConnectionLimits (0 = unlimited; omitted fields unchanged).
        SetConnectionLimits {
            max_established_incoming: Option<u32>,
            max_established_outgoing: Option<u32>,
            max_established: Option<u32>,
            max_established_per_peer: Option<u32>,
            max_pending_incoming: Option<u32>,
            max_pending_outgoing: Option<u32>,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Slice O: persist bootstrap peer + multiaddr.
        BootstrapAdd {
            peer_id: String,
            multiaddr: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        BootstrapRemove {
            peer_id: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        BootstrapList {
            reply: oneshot::Sender<HashMap<String, Vec<String>>>,
        },
        /// Dial all persisted bootstrap multiaddrs (sequential).
        BootstrapDial {
            reply: oneshot::Sender<Result<Vec<(String, String)>, String>>,
        },
        /// Slice T: learned peerstore book.
        PeerstoreList {
            reply: oneshot::Sender<HashMap<String, Vec<String>>>,
        },
        PeerstoreClear {
            reply: oneshot::Sender<Result<(), String>>,
        },
        PeerstoreDial {
            reply: oneshot::Sender<Result<Vec<(String, String)>, String>>,
        },
        SetReconnectEnabled {
            enabled: bool,
            reply: oneshot::Sender<()>,
        },
        DisconnectPeer {
            peer_id: String,
            reply: oneshot::Sender<Result<(), String>>,
        },
        /// Slice Q: read gossipsub peer score (None if scoring inactive / unknown peer).
        GossipPeerScore {
            peer_id: String,
            reply: oneshot::Sender<Option<f64>>,
        },
        /// Slice Q: application-specific gossip score contribution.
        SetGossipAppScore {
            peer_id: String,
            score: f64,
            reply: oneshot::Sender<bool>,
        },
        /// Slice Q: Accept/Reject/Ignore a pending gossip message id.
        ReportGossipValidation {
            message_id: String,
            peer_id: String,
            acceptance: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        /// Slice R: tune unhealthy ping disconnect policy.
        SetPingUnhealthyPolicy {
            enabled: bool,
            max_fails: u32,
            max_rtt_ms: u64,
            reply: oneshot::Sender<()>,
        },
        LastPingRttMs {
            peer_id: String,
            reply: oneshot::Sender<Option<u64>>,
        },
        /// Slice S: enable/disable score→block sweep + graylist threshold.
        SetScoreAutoblock {
            enabled: bool,
            graylist_threshold: f64,
            reply: oneshot::Sender<()>,
        },
        Shutdown {
            reply: oneshot::Sender<()>,
        },
    }

    #[derive(Clone, Default)]
    struct IdentifySnap {
        protocol_version: String,
        agent_version: String,
        listen_addrs: Vec<String>,
        protocols: Vec<String>,
        observed_addr: String,
    }

    #[derive(Default)]
    struct NodeState {
        listen_addrs: Vec<String>,
        connected: HashSet<String>,
        /// PeerIds reached via outbound dial (Slice C budget accounting).
        outbound_peers: HashSet<String>,
        dial_ok: u64,
        dial_fail: u64,
        /// Slice AU: DialError taxonomy (counted with dial_fail).
        dial_fail_transport: u64,
        dial_fail_wrong_peer_id: u64,
        dial_fail_no_addresses: u64,
        dial_fail_aborted: u64,
        dial_fail_local_peer_id: u64,
        dial_fail_condition: u64,
        /// Slice AW: DialError::Denied (block / allow / connection-limits).
        dial_fail_denied: u64,
        /// Slice AX: Denied cause (outbound).
        dial_fail_denied_block: u64,
        dial_fail_denied_allow: u64,
        dial_fail_denied_limit: u64,
        dial_inflight: u32,
        dial_refused_budget: u64,
        /// Slice AK: SwarmEvent::Dialing (outbound attempt started).
        dialing: u64,
        /// Slice AK: IncomingConnectionError total (any handshake deny/fail).
        incoming_connection_error: u64,
        /// Slice AV: ListenError taxonomy (counted with incoming_connection_error).
        incoming_fail_transport: u64,
        incoming_fail_wrong_peer_id: u64,
        incoming_fail_aborted: u64,
        incoming_fail_local_peer_id: u64,
        incoming_fail_denied: u64,
        /// Slice AX: Denied cause (inbound).
        incoming_fail_denied_block: u64,
        incoming_fail_denied_allow: u64,
        incoming_fail_denied_limit: u64,
        /// Slice AK: NewExternalAddrOfPeer discoveries.
        peer_external_addr: u64,
        /// Slice AH: listener-side ConnectionEstablished.
        inbound_established: u64,
        /// Slice AH: IncomingConnection (pre-handshake).
        incoming_connections: u64,
        /// Slice AH: ConnectionClosed that dropped the last connection to a peer.
        connection_closed: u64,
        /// Slice AI: ConnectionClosed cause taxonomy (counted with last-peer drop).
        connection_closed_local: u64,
        connection_closed_io: u64,
        connection_closed_keep_alive: u64,
        /// Slice AH: last / max ConnectionEstablished duration (ms).
        established_in_ms_last: u64,
        established_in_ms_max: u64,
        /// Slice AJ: listener lifecycle counters.
        new_listen_addr: u64,
        expired_listen_addr: u64,
        listener_closed: u64,
        listener_error: u64,
        wire_sent: u64,
        wire_recv: u64,
        /// Slice AO: request-response wire failure / response lifecycle.
        wire_outbound_failure: u64,
        /// Slice AZ: request_response::OutboundFailure taxonomy.
        wire_outbound_fail_dial: u64,
        wire_outbound_fail_timeout: u64,
        wire_outbound_fail_connection_closed: u64,
        wire_outbound_fail_unsupported: u64,
        wire_outbound_fail_io: u64,
        wire_inbound_failure: u64,
        /// Slice AZ: request_response::InboundFailure taxonomy.
        wire_inbound_fail_timeout: u64,
        wire_inbound_fail_connection_closed: u64,
        wire_inbound_fail_unsupported: u64,
        wire_inbound_fail_response_omission: u64,
        wire_inbound_fail_io: u64,
        wire_response_sent: u64,
        wire_response_ok: u64,
        /// Slice AF: transport byte counters (BandwidthSinks snapshot).
        bytes_in: u64,
        bytes_out: u64,
        /// Absolute ADR 0008 codec counters (Slice M; lab pack_wire stays in wire_* only).
        abs_wire_v1_sent: u64,
        abs_wire_v2_sent: u64,
        abs_wire_v1_recv: u64,
        abs_wire_v2_recv: u64,
        gossip_pub: u64,
        gossip_recv: u64,
        /// Slice Q: messages accepted after inbox enqueue (validate_messages path).
        gossip_validation_accept: u64,
        gossip_validation_reject: u64,
        /// Slice BA: Ignore acceptance + deferred validation bookkeeping.
        gossip_validation_ignore: u64,
        gossip_validation_pending: u64,
        /// When true, skip auto-Accept and wait for ``report_gossip_validation``.
        enable_gossip_defer_validation: bool,
        last_gossip_message_id: String,
        last_gossip_propagation_peer: String,
        gossip_app_score_sets: u64,
        gossip_not_supported: u64,
        /// Slice AM: remote peer topic join/leave notifications.
        gossip_peer_subscribed: u64,
        gossip_peer_unsubscribed: u64,
        mdns_discovered: u64,
        /// Slice AS: mDNS Expired (loopback hygiene, same as Discovered).
        mdns_expired: u64,
        /// Slice AS: configured mDNS TTL seconds (lab override).
        mdns_ttl_secs: u64,
        kad_routing_updates: u64,
        kad_queries: u64,
        /// Slice AN: Kademlia query / routing event counters.
        kad_query_ok: u64,
        kad_query_fail: u64,
        kad_inbound_requests: u64,
        kad_unroutable_peer: u64,
        kad_routable_peer: u64,
        kad_pending_routable_peer: u64,
        kad_mode_changed: u64,
        relay_reservations: u64,
        relay_circuits: u64,
        /// Slice AP: relay server event taxonomy.
        relay_reservation_denied: u64,
        relay_reservation_timed_out: u64,
        relay_circuit_denied: u64,
        relay_circuit_closed: u64,
        /// Slice AT: relay client circuit direction.
        relay_inbound_circuit: u64,
        relay_outbound_circuit: u64,
        /// Slice AP: optional capacity override (lab deny path); 0 = default.
        relay_max_reservations: u32,
        autonat_probes: u64,
        autonat_status_changes: u64,
        /// Slice AR: AutoNAT probe direction / error taxonomy.
        autonat_inbound_probe: u64,
        autonat_outbound_probe: u64,
        autonat_inbound_probe_error: u64,
        autonat_outbound_probe_error: u64,
        /// 0=unknown, 1=public, 2=private (Slice N).
        autonat_status: u8,
        dcutr_upgrade_success: u64,
        dcutr_upgrade_fail: u64,
        conn_limit_denied: u64,
        block_denied: u64,
        blocked: HashSet<String>,
        /// Slice AE: allow-list denied connections.
        allow_denied: u64,
        allowed: HashSet<String>,
        /// Slice AE: allow-list Toggle enabled.
        enable_allow_list: bool,
        max_dials: u32,
        max_established_incoming: Option<u32>,
        max_established_outgoing: Option<u32>,
        max_established: Option<u32>,
        max_established_per_peer: Option<u32>,
        max_pending_incoming: Option<u32>,
        max_pending_outgoing: Option<u32>,
        /// Slice AA: successful set_connection_limits calls.
        connection_limits_updates: u64,
        enable_mdns: bool,
        /// Slice N: AutoNAT behaviour enabled (probe dials).
        enable_autonat: bool,
        /// Slice AD: UPnP / IGD port mapping (default off).
        enable_upnp: bool,
        /// Slice AD: UPnP event counters.
        upnp_external_addrs: u64,
        upnp_expired_external_addrs: u64,
        upnp_gateway_not_found: u64,
        upnp_non_routable_gateway: u64,
        wire_timeout_secs: u64,
        /// Slice V: swarm idle connection timeout.
        idle_connection_timeout_secs: u64,
        /// Slice V: ConnectionClosed caused by keep-alive / idle timeout.
        idle_timeout_closes: u64,
        /// Slice W: listen addrs that included `/ip6/`.
        ipv6_listens: u64,
        /// Slice W: successful dialer ConnectionEstablished over `/ip6/`.
        ipv6_dial_ok: u64,
        /// Slice X: rendezvous client/server counters.
        rendezvous_registers: u64,
        rendezvous_register_fail: u64,
        rendezvous_discovers: u64,
        rendezvous_discovered_peers: u64,
        rendezvous_discover_fail: u64,
        rendezvous_server_registrations: u64,
        /// Slice AQ: rendezvous server/client event taxonomy.
        rendezvous_server_unregistrations: u64,
        rendezvous_server_discover_served: u64,
        rendezvous_server_discover_not_served: u64,
        rendezvous_server_not_registered: u64,
        rendezvous_server_registration_expired: u64,
        rendezvous_expired: u64,
        /// Slice Y: dials that used `/dns4/` or `/dns6/`.
        dns_dial_ok: u64,
        dns_dial_fail: u64,
        /// Slice AB: QUIC listen/dial counters.
        quic_listens: u64,
        quic_dial_ok: u64,
        quic_dial_fail: u64,
        /// Slice AC: WebSocket listen/dial counters.
        ws_listens: u64,
        ws_dial_ok: u64,
        ws_dial_fail: u64,
        last_error: String,
        inbox: VecDeque<(String, Vec<u8>)>,
        gossip_inbox: VecDeque<(String, String, Vec<u8>)>,
        subscribed: HashSet<String>,
        identify: HashMap<String, IdentifySnap>,
        /// Slice AL: identify protocol event counters.
        identify_received: u64,
        identify_sent: u64,
        identify_pushed: u64,
        identify_error: u64,
        /// peer_id -> last advertised multiaddr from mDNS
        discovered: HashMap<String, String>,
        kad_peers: HashSet<String>,
        key_path: String,
        /// Circuit listen addrs observed after reservation (Slice H).
        circuit_addrs: Vec<String>,
        /// Slice AG: confirmed external multiaddrs (swarm.add_external_address book).
        external_addrs: Vec<String>,
        external_addr_confirmed: u64,
        external_addr_expired: u64,
        external_addr_candidates: u64,
        /// Persistent bootstrap book path (Slice O; empty = memory-only).
        bootstrap_path: String,
        bootstrap: HashMap<String, Vec<String>>,
        bootstrap_dials_ok: u64,
        bootstrap_dials_fail: u64,
        bootstrap_dials_timeout: u64,
        bootstrap_dials_attempted: u64,
        bootstrap_dial_timeout_secs: u64,
        /// Slice T: learned peer multiaddrs (identify/connection), separate from bootstrap.
        peerstore_path: String,
        peerstore: HashMap<String, Vec<String>>,
        peerstore_learned: u64,
        peerstore_dials_ok: u64,
        peerstore_dials_fail: u64,
        peerstore_dials_timeout: u64,
        peerstore_dials_attempted: u64,
        /// Slice P: auto-redial bootstrap peers after disconnect.
        enable_reconnect: bool,
        reconnect_base_ms: u64,
        reconnect_max_ms: u64,
        reconnect_max_attempts: u32,
        reconnect_scheduled: u64,
        reconnect_ok: u64,
        reconnect_fail: u64,
        reconnect_give_up: u64,
        /// Slice U: reconnects scheduled because peer was in learned peerstore.
        reconnect_from_peerstore: u64,
        /// Slice R: ping / liveness.
        ping_ok: u64,
        ping_fail: u64,
        /// Slice AY: ping::Failure taxonomy.
        ping_fail_timeout: u64,
        ping_fail_unsupported: u64,
        ping_fail_other: u64,
        /// Effective ping timing (ms) after env resolve.
        ping_interval_ms: u64,
        ping_timeout_ms: u64,
        ping_rtt_ms_last: u64,
        ping_rtt_ms_max: u64,
        ping_unhealthy_disconnects: u64,
        enable_ping_unhealthy_disconnect: bool,
        /// 0 = RTT threshold disabled.
        ping_max_rtt_ms: u64,
        ping_max_fails: u32,
        ping_fail_streak: HashMap<String, u32>,
        ping_rtt_by_peer: HashMap<String, u64>,
        /// Slice S: auto-block peers at/below gossip graylist score.
        enable_score_autoblock: bool,
        score_graylist_threshold: f64,
        score_autoblocks: u64,
        score_sweep_ticks: u64,
    }

    #[pyclass(name = "Libp2pNode")]
    pub struct Libp2pNode {
        peer_id: String,
        cmd_tx: mpsc::UnboundedSender<Cmd>,
        state: Arc<Mutex<NodeState>>,
        /// Slice AF: live bandwidth counters (filled once swarm transport is built).
        #[allow(deprecated)]
        bandwidth: Arc<Mutex<Option<Arc<BandwidthSinks>>>>,
        _runtime: tokio::runtime::Runtime,
    }

    impl Libp2pNode {
        fn spawn(
            max_dials: u32,
            key_path: Option<String>,
            max_established_incoming: Option<u32>,
            max_established_outgoing: Option<u32>,
            max_established: Option<u32>,
            max_established_per_peer: Option<u32>,
            max_pending_incoming: Option<u32>,
            max_pending_outgoing: Option<u32>,
            enable_mdns: bool,
            wire_timeout_secs: u64,
            bootstrap_path: Option<String>,
            enable_reconnect: bool,
            peerstore_path: Option<String>,
            enable_autonat: bool,
            enable_upnp: bool,
            enable_allow_list: bool,
            idle_connection_timeout_secs: u64,
            relay_max_reservations: Option<u32>,
            mdns_ttl_secs: u64,
        ) -> PyResult<Self> {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .thread_name("abs-libp2p")
                .build()
                .map_err(|e| PyRuntimeError::new_err(format!("tokio runtime: {e}")))?;

            let key_path_str = key_path.unwrap_or_default();
            let bootstrap_path_str = bootstrap_path.unwrap_or_default();
            let peerstore_path_str = peerstore_path.unwrap_or_default();
            let bootstrap_peers = if bootstrap_path_str.is_empty() {
                HashMap::new()
            } else {
                load_bootstrap_peers(Path::new(&bootstrap_path_str))
                    .map_err(|e| PyRuntimeError::new_err(format!("bootstrap load: {e}")))?
            };
            let peerstore_peers = if peerstore_path_str.is_empty() {
                HashMap::new()
            } else {
                load_bootstrap_peers(Path::new(&peerstore_path_str))
                    .map_err(|e| PyRuntimeError::new_err(format!("peerstore load: {e}")))?
            };
            let wire_timeout_secs = wire_timeout_secs.max(1);
            let idle_connection_timeout_secs = idle_connection_timeout_secs.max(1);
            let bootstrap_dial_timeout_secs = resolve_bootstrap_dial_timeout_secs(None);
            let (cmd_tx, mut cmd_rx) = mpsc::unbounded_channel::<Cmd>();
            let state = Arc::new(Mutex::new(NodeState {
                max_dials: max_dials.max(1),
                max_established_incoming,
                max_established_outgoing,
                max_established,
                max_established_per_peer,
                max_pending_incoming,
                max_pending_outgoing,
                enable_mdns,
                enable_autonat,
                enable_upnp,
                enable_allow_list,
                wire_timeout_secs,
                idle_connection_timeout_secs,
                mdns_ttl_secs,
                key_path: key_path_str.clone(),
                bootstrap_path: bootstrap_path_str.clone(),
                bootstrap: bootstrap_peers,
                bootstrap_dial_timeout_secs,
                peerstore_path: peerstore_path_str.clone(),
                peerstore: peerstore_peers,
                enable_reconnect,
                reconnect_base_ms: DEFAULT_RECONNECT_BASE_MS,
                reconnect_max_ms: DEFAULT_RECONNECT_MAX_MS,
                reconnect_max_attempts: DEFAULT_RECONNECT_MAX_ATTEMPTS,
                enable_ping_unhealthy_disconnect: resolve_ping_unhealthy_disconnect(None),
                ping_max_fails: resolve_ping_max_fails(None),
                ping_max_rtt_ms: resolve_ping_max_rtt_ms(None),
                enable_score_autoblock: resolve_score_autoblock(None),
                score_graylist_threshold: resolve_score_graylist_threshold(None),
                enable_gossip_defer_validation: resolve_gossip_defer_validation(None),
                relay_max_reservations: relay_max_reservations.unwrap_or(0),
                ..NodeState::default()
            }));
            let state_bg = Arc::clone(&state);

            let peer_id_cell = Arc::new(Mutex::new(String::new()));
            let peer_id_bg = Arc::clone(&peer_id_cell);
            #[allow(deprecated)]
            let bandwidth = Arc::new(Mutex::new(None::<Arc<BandwidthSinks>>));
            let bandwidth_bg = Arc::clone(&bandwidth);
            let limits_incoming = max_established_incoming;
            let limits_outgoing = max_established_outgoing;
            let limits_total = max_established;
            let limits_per_peer = max_established_per_peer;
            let limits_pending_in = max_pending_incoming;
            let limits_pending_out = max_pending_outgoing;
            let want_mdns = enable_mdns;
            let mdns_ttl = mdns_ttl_secs.max(1);
            let want_autonat = enable_autonat;
            let want_upnp = enable_upnp;
            let want_allow_list = enable_allow_list;
            let relay_cap = relay_max_reservations;
            let wire_timeout = Duration::from_secs(wire_timeout_secs);
            let idle_timeout = Duration::from_secs(idle_connection_timeout_secs);
            let ping_interval = resolve_ping_interval();
            let ping_timeout = resolve_ping_timeout();
            if let Ok(mut st) = state.lock() {
                st.ping_interval_ms = ping_interval.as_millis().min(u128::from(u64::MAX)) as u64;
                st.ping_timeout_ms = ping_timeout.as_millis().min(u128::from(u64::MAX)) as u64;
            }

            runtime.spawn(async move {
                let keypair = if key_path_str.is_empty() {
                    Keypair::generate_ed25519()
                } else {
                    match load_or_create_keypair(Path::new(&key_path_str)) {
                        Ok(kp) => kp,
                        Err(e) => {
                            if let Ok(mut st) = state_bg.lock() {
                                st.last_error = e;
                            }
                            return;
                        }
                    }
                };

                let tcp_built = match SwarmBuilder::with_existing_identity(keypair)
                    .with_tokio()
                    .with_tcp(
                        tcp::Config::default(),
                        noise::Config::new,
                        yamux::Config::default,
                    ) {
                    Ok(b) => b,
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("tcp transport: {e}");
                        }
                        return;
                    }
                };
                // Slice AB: QUIC beside TCP; listen/dial via /udp/.../quic-v1.
                let quic_built = tcp_built.with_quic();
                let dns_built = match quic_built.with_dns() {
                    Ok(b) => b,
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("dns transport: {e}");
                        }
                        return;
                    }
                };
                // Slice AC: WebSocket beside TCP/QUIC; listen/dial via /tcp/.../ws.
                let ws_built = match dns_built
                    .with_websocket(noise::Config::new, yamux::Config::default)
                    .await
                {
                    Ok(b) => b,
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("websocket transport: {e}");
                        }
                        return;
                    }
                };
                let relay_built = match ws_built
                    .with_relay_client(noise::Config::new, yamux::Config::default)
                {
                    Ok(b) => b,
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("relay transport: {e}");
                        }
                        return;
                    }
                };
                // Slice AF: count stream bytes via BandwidthSinks (deprecated API; metrics feature later).
                #[allow(deprecated)]
                let (builder, bandwidth_sinks): (_, Arc<BandwidthSinks>) =
                    relay_built.with_bandwidth_logging();
                if let Ok(mut slot) = bandwidth_bg.lock() {
                    *slot = Some(Arc::clone(&bandwidth_sinks));
                }

                let mut swarm = match builder.with_behaviour(|key, relay_client| {
                    let wire = request_response::Behaviour::with_codec(
                        AbsWireCodec,
                        [(
                            StreamProtocol::new(ABS_WIRE_PROTOCOL),
                            request_response::ProtocolSupport::Full,
                        )],
                        request_response::Config::default().with_request_timeout(wire_timeout),
                    );
                    let message_id_fn = |message: &gossipsub::Message| {
                        let mut hasher = DefaultHasher::new();
                        message.data.hash(&mut hasher);
                        gossipsub::MessageId::from(hasher.finish().to_string())
                    };
                    let gs_cfg = gossipsub::ConfigBuilder::default()
                        .heartbeat_interval(Duration::from_millis(500))
                        .validation_mode(gossipsub::ValidationMode::Strict)
                        .validate_messages()
                        .message_id_fn(message_id_fn)
                        .build()
                        .map_err(|e| format!("gossipsub config: {e}"))?;
                    let mut gossipsub = gossipsub::Behaviour::new(
                        gossipsub::MessageAuthenticity::Signed(key.clone()),
                        gs_cfg,
                    )
                    .map_err(|e| format!("gossipsub: {e}"))?;
                    // Slice Q: industrial peer scoring (loopback whitelisted for local labs).
                    let mut score_params = gossipsub::PeerScoreParams::default();
                    if let Ok(ip) = "127.0.0.1".parse() {
                        score_params.ip_colocation_factor_whitelist.insert(ip);
                    }
                    if let Ok(ip) = "::1".parse() {
                        score_params.ip_colocation_factor_whitelist.insert(ip);
                    }
                    let blocks_topic = gossipsub::IdentTopic::new(ABS_GOSSIP_BLOCKS_TOPIC);
                    score_params.topics.insert(
                        blocks_topic.hash(),
                        gossipsub::TopicScoreParams::default(),
                    );
                    gossipsub
                        .with_peer_score(score_params, gossipsub::PeerScoreThresholds::default())
                        .map_err(|e| format!("gossip peer score: {e}"))?;
                    let mdns = if want_mdns {
                        Toggle::from(Some(
                            mdns::tokio::Behaviour::new(
                                mdns::Config {
                                    ttl: Duration::from_secs(mdns_ttl),
                                    query_interval: Duration::from_secs(1),
                                    enable_ipv6: false,
                                },
                                key.public().to_peer_id(),
                            )
                            .map_err(|e| format!("mdns: {e}"))?,
                        ))
                    } else {
                        Toggle::from(None)
                    };
                    let local = key.public().to_peer_id();
                    let mut kad_cfg = kad::Config::new(StreamProtocol::new(ABS_KAD_PROTOCOL));
                    kad_cfg.set_query_timeout(Duration::from_secs(10));
                    let store = MemoryStore::new(local);
                    let mut kademlia = kad::Behaviour::with_config(local, store, kad_cfg);
                    kademlia.set_mode(Some(kad::Mode::Server));
                    let mut limits = connection_limits::ConnectionLimits::default();
                    if let Some(n) = limits_incoming {
                        limits = limits.with_max_established_incoming(Some(n));
                    }
                    if let Some(n) = limits_outgoing {
                        limits = limits.with_max_established_outgoing(Some(n));
                    }
                    if let Some(n) = limits_total {
                        limits = limits.with_max_established(Some(n));
                    }
                    if let Some(n) = limits_per_peer {
                        limits = limits.with_max_established_per_peer(Some(n));
                    }
                    if let Some(n) = limits_pending_in {
                        limits = limits.with_max_pending_incoming(Some(n));
                    }
                    if let Some(n) = limits_pending_out {
                        limits = limits.with_max_pending_outgoing(Some(n));
                    }
                    Ok(AbsBehaviour {
                        ping: ping::Behaviour::new(
                            ping::Config::new()
                                .with_interval(ping_interval)
                                .with_timeout(ping_timeout),
                        ),
                        identify: identify::Behaviour::new(identify::Config::new(
                            "/absolute/1.0.0".into(),
                            key.public(),
                        )),
                        wire,
                        gossipsub,
                        mdns,
                        kademlia,
                        relay: {
                            let mut relay_cfg = relay::Config::default();
                            if let Some(n) = relay_cap {
                                relay_cfg.max_reservations = (n.max(1)) as usize;
                                // Lab predictability: capacity only (Slice AP deny path).
                                relay_cfg.reservation_rate_limiters.clear();
                                relay_cfg.circuit_src_rate_limiters.clear();
                            }
                            relay::Behaviour::new(local, relay_cfg)
                        },
                        relay_client,
                        autonat: if want_autonat {
                            // Lab-friendly AutoNAT: allow private/loopback peers (Slice N).
                            let mut cfg = autonat::Config::default();
                            cfg.only_global_ips = false;
                            cfg.boot_delay = Duration::from_millis(200);
                            cfg.retry_interval = Duration::from_secs(2);
                            cfg.refresh_interval = Duration::from_secs(10);
                            cfg.throttle_server_period = Duration::from_secs(1);
                            Toggle::from(Some(autonat::Behaviour::new(local, cfg)))
                        } else {
                            Toggle::from(None)
                        },
                        upnp: if want_upnp {
                            Toggle::from(Some(upnp::tokio::Behaviour::default()))
                        } else {
                            Toggle::from(None)
                        },
                        allowed_peers: if want_allow_list {
                            Toggle::from(Some(allow_block_list::Behaviour::default()))
                        } else {
                            Toggle::from(None)
                        },
                        dcutr: dcutr::Behaviour::new(local),
                        rendezvous_server: rendezvous::server::Behaviour::new(
                            rendezvous::server::Config::default(),
                        ),
                        rendezvous_client: rendezvous::client::Behaviour::new(key.clone()),
                        connection_limits: connection_limits::Behaviour::new(limits),
                        blocked_peers: allow_block_list::Behaviour::default(),
                    })
                }) {
                    Ok(b) => b
                        .with_swarm_config(|cfg| {
                            cfg.with_idle_connection_timeout(idle_timeout)
                        })
                        .build(),
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("behaviour: {e}");
                        }
                        return;
                    }
                };

                let local_peer = *swarm.local_peer_id();
                if let Ok(mut pid) = peer_id_bg.lock() {
                    *pid = local_peer.to_string();
                }

                let mut pending_listen: Option<oneshot::Sender<Result<Vec<String>, String>>> = None;
                let mut pending_relay_listen: Option<oneshot::Sender<Result<Vec<String>, String>>> =
                    None;
                let mut relay_listen_deadline: Option<tokio::time::Instant> = None;
                let mut pending_dial: Option<oneshot::Sender<Result<String, String>>> = None;
                let mut pending_dial_dns = false;
                let mut pending_dial_quic = false;
                let mut pending_dial_ws = false;
                let mut bootstrap_job: Option<BootstrapDialJob> = None;
                // Slice AJ: listen multiaddr → ListenerId for remove_listener.
                let mut listen_ids: HashMap<String, ListenerId> = HashMap::new();
                let mut pending_reconnects: HashMap<String, PendingReconnect> = HashMap::new();
                let mut reconnect_inflight: Option<String> = None;
                let mut reconnect_inflight_deadline: Option<tokio::time::Instant> = None;
                let mut pending_wire: HashMap<
                    request_response::OutboundRequestId,
                    oneshot::Sender<Result<Vec<u8>, String>>,
                > = HashMap::new();
                let mut pending_kad: HashMap<
                    kad::QueryId,
                    oneshot::Sender<Result<Vec<String>, String>>,
                > = HashMap::new();
                let mut pending_rendezvous_register: Option<
                    oneshot::Sender<Result<u64, String>>,
                > = None;
                let mut pending_rendezvous_discover: Option<
                    oneshot::Sender<Result<Vec<(String, Vec<String>)>, String>>,
                > = None;
                let mut score_sweep_at =
                    tokio::time::Instant::now() + Duration::from_secs(1);

                loop {
                    let boot_deadline = bootstrap_job.as_ref().and_then(|j| j.per_dial_deadline);
                    let reconnect_deadline = {
                        let mut soonest: Option<tokio::time::Instant> = reconnect_inflight_deadline;
                        for pr in pending_reconnects.values() {
                            soonest = Some(match soonest {
                                Some(s) if s <= pr.next_at => s,
                                _ => pr.next_at,
                            });
                        }
                        soonest
                    };
                    tokio::select! {
                        _ = tokio::time::sleep_until(score_sweep_at) => {
                            score_sweep_at =
                                tokio::time::Instant::now() + Duration::from_secs(1);
                            // Slice AF: refresh bandwidth counters into status surface.
                            if let Ok(mut st) = state_bg.lock() {
                                st.bytes_in = bandwidth_sinks.total_inbound();
                                st.bytes_out = bandwidth_sinks.total_outbound();
                            }
                            // Slice S: periodic gossip score → native block sweep.
                            let (enabled, threshold, peers) = state_bg
                                .lock()
                                .map(|mut st| {
                                    st.score_sweep_ticks =
                                        st.score_sweep_ticks.saturating_add(1);
                                    (
                                        st.enable_score_autoblock,
                                        st.score_graylist_threshold,
                                        st.connected.iter().cloned().collect::<Vec<_>>(),
                                    )
                                })
                                .unwrap_or((false, DEFAULT_SCORE_GRAYLIST_THRESHOLD, Vec::new()));
                            if enabled {
                                for pid in peers {
                                    let Ok(peer) = pid.parse::<PeerId>() else {
                                        continue;
                                    };
                                    let already = state_bg
                                        .lock()
                                        .map(|st| st.blocked.contains(&pid))
                                        .unwrap_or(false);
                                    if already {
                                        continue;
                                    }
                                    let Some(score) =
                                        swarm.behaviour().gossipsub.peer_score(&peer)
                                    else {
                                        continue;
                                    };
                                    if score > threshold {
                                        continue;
                                    }
                                    swarm.behaviour_mut().blocked_peers.block_peer(peer);
                                    let _ = swarm.disconnect_peer_id(peer);
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.blocked.insert(pid.clone());
                                        st.score_autoblocks =
                                            st.score_autoblocks.saturating_add(1);
                                        st.last_error = format!(
                                            "score autoblock peer={pid} score={score} thr={threshold}"
                                        );
                                    }
                                }
                            }
                        }
                        _ = async {
                            if let Some(deadline) = relay_listen_deadline {
                                tokio::time::sleep_until(deadline).await;
                            } else {
                                futures::future::pending::<()>().await;
                            }
                        }, if relay_listen_deadline.is_some() => {
                            relay_listen_deadline = None;
                            if let Some(reply) = pending_relay_listen.take() {
                                let addrs = state_bg
                                    .lock()
                                    .map(|st| st.circuit_addrs.clone())
                                    .unwrap_or_default();
                                if addrs.is_empty() {
                                    let _ = reply.send(Err(
                                        "listen_relay timeout (no circuit addr)".into(),
                                    ));
                                } else {
                                    let _ = reply.send(Ok(addrs));
                                }
                            }
                        }
                        _ = async {
                            if let Some(deadline) = boot_deadline {
                                tokio::time::sleep_until(deadline).await;
                            } else {
                                futures::future::pending::<()>().await;
                            }
                        }, if boot_deadline.is_some() => {
                            if let Some(j) = bootstrap_job.as_mut() {
                                if let Some(pid) = j.current_peer.clone() {
                                    j.abandoned.insert(pid.clone());
                                    // Inflight will clear on late OutgoingConnectionError.
                                    let book = j.kind;
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.dial_inflight =
                                            st.dial_inflight.saturating_sub(1);
                                        book_bump_timeout(&mut st, book);
                                        st.last_error = format!("book_dial timeout: {pid}");
                                    }
                                    j.results.push((pid, "timeout".into()));
                                    j.current_peer = None;
                                    j.per_dial_deadline = None;
                                }
                            }
                            let _ = bootstrap_advance(&mut swarm, &state_bg, &mut bootstrap_job);
                        }
                        _ = async {
                            if let Some(deadline) = reconnect_deadline {
                                tokio::time::sleep_until(deadline).await;
                            } else {
                                futures::future::pending::<()>().await;
                            }
                        }, if reconnect_deadline.is_some() => {
                            // Inflight reconnect timed out (or soft-fail grace elapsed).
                            if let Some(pid) = reconnect_inflight.take() {
                                reconnect_inflight_deadline = None;
                                let still_up = pid
                                    .parse::<PeerId>()
                                    .ok()
                                    .map(|p| swarm.is_connected(&p))
                                    .unwrap_or(false)
                                    || state_bg
                                        .lock()
                                        .map(|st| st.connected.contains(&pid))
                                        .unwrap_or(false);
                                if still_up {
                                    reconnect_settle_ok(
                                        &state_bg,
                                        &mut pending_reconnects,
                                        &mut reconnect_inflight,
                                        &mut reconnect_inflight_deadline,
                                        &pid,
                                    );
                                } else {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.dial_inflight = st.dial_inflight.saturating_sub(1);
                                        st.reconnect_fail = st.reconnect_fail.saturating_add(1);
                                    }
                                    let cfg = state_bg.lock().ok().map(|st| {
                                        (
                                            st.reconnect_base_ms,
                                            st.reconnect_max_ms,
                                            st.reconnect_max_attempts,
                                        )
                                    });
                                    if let Some((base, max_ms, max_att)) = cfg {
                                        if let Some(pr) = pending_reconnects.get_mut(&pid) {
                                            pr.attempts = pr.attempts.saturating_add(1);
                                            if pr.attempts >= max_att {
                                                pending_reconnects.remove(&pid);
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.reconnect_give_up =
                                                        st.reconnect_give_up.saturating_add(1);
                                                }
                                            } else {
                                                let wait = reconnect_backoff_ms(
                                                    base,
                                                    max_ms,
                                                    pr.attempts,
                                                );
                                                pr.next_at = tokio::time::Instant::now()
                                                    + Duration::from_millis(wait);
                                                pr.addr_idx = pr.addr_idx.saturating_add(1);
                                            }
                                        }
                                    }
                                }
                            }

                            // Kick due reconnects (one at a time).
                            if reconnect_inflight.is_none() && bootstrap_job.is_none() {
                                let now = tokio::time::Instant::now();
                                let due = pending_reconnects
                                    .iter()
                                    .filter(|(_, pr)| pr.next_at <= now)
                                    .map(|(pid, _)| pid.clone())
                                    .next();
                                if let Some(pid) = due {
                                    let peer_ok = pid.parse::<PeerId>().ok();
                                    let already = match peer_ok {
                                        Some(p) => swarm.is_connected(&p),
                                        None => false,
                                    } || state_bg
                                        .lock()
                                        .map(|st| st.connected.contains(&pid))
                                        .unwrap_or(false);
                                    if already || peer_ok.is_none() {
                                        if already {
                                            reconnect_settle_ok(
                                                &state_bg,
                                                &mut pending_reconnects,
                                                &mut reconnect_inflight,
                                                &mut reconnect_inflight_deadline,
                                                &pid,
                                            );
                                        } else {
                                            pending_reconnects.remove(&pid);
                                        }
                                    } else if let Some(pr) = pending_reconnects.get(&pid).cloned()
                                    {
                                        let blocked = state_bg
                                            .lock()
                                            .map(|st| st.blocked.contains(&pid))
                                            .unwrap_or(false);
                                        if blocked {
                                            pending_reconnects.remove(&pid);
                                        } else {
                                            let addr = pr
                                                .addrs
                                                .get(pr.addr_idx % pr.addrs.len().max(1))
                                                .cloned();
                                            if let Some(addr) = addr {
                                                let reserved = if let Ok(mut st) = state_bg.lock()
                                                {
                                                    let used = (st.outbound_peers.len() as u32)
                                                        .saturating_add(st.dial_inflight);
                                                    if used < st.max_dials {
                                                        st.dial_inflight =
                                                            st.dial_inflight.saturating_add(1);
                                                        true
                                                    } else {
                                                        st.dial_refused_budget = st
                                                            .dial_refused_budget
                                                            .saturating_add(1);
                                                        false
                                                    }
                                                } else {
                                                    false
                                                };
                                                if !reserved {
                                                    if let Some(pr) =
                                                        pending_reconnects.get_mut(&pid)
                                                    {
                                                        pr.next_at = now
                                                            + Duration::from_millis(200);
                                                    }
                                                } else {
                                                    match addr.parse::<Multiaddr>() {
                                                        Ok(ma) => {
                                                            if let Err(e) = swarm.dial(ma) {
                                                                if let Ok(mut st) =
                                                                    state_bg.lock()
                                                                {
                                                                    st.dial_inflight = st
                                                                        .dial_inflight
                                                                        .saturating_sub(1);
                                                                    st.reconnect_fail = st
                                                                        .reconnect_fail
                                                                        .saturating_add(1);
                                                                    st.last_error = format!(
                                                                        "reconnect dial: {e}"
                                                                    );
                                                                }
                                                                if let Some(pr) =
                                                                    pending_reconnects
                                                                        .get_mut(&pid)
                                                                {
                                                                    pr.attempts = pr
                                                                        .attempts
                                                                        .saturating_add(1);
                                                                    let (base, max_ms, max_att) =
                                                                        state_bg
                                                                            .lock()
                                                                            .map(|st| {
                                                                                (
                                                                                    st.reconnect_base_ms,
                                                                                    st.reconnect_max_ms,
                                                                                    st.reconnect_max_attempts,
                                                                                )
                                                                            })
                                                                            .unwrap_or((
                                                                                DEFAULT_RECONNECT_BASE_MS,
                                                                                DEFAULT_RECONNECT_MAX_MS,
                                                                                DEFAULT_RECONNECT_MAX_ATTEMPTS,
                                                                            ));
                                                                    if pr.attempts >= max_att {
                                                                        pending_reconnects
                                                                            .remove(&pid);
                                                                        if let Ok(mut st) =
                                                                            state_bg.lock()
                                                                        {
                                                                            st.reconnect_give_up = st
                                                                                .reconnect_give_up
                                                                                .saturating_add(1);
                                                                        }
                                                                    } else {
                                                                        let wait =
                                                                            reconnect_backoff_ms(
                                                                                base, max_ms,
                                                                                pr.attempts,
                                                                            );
                                                                        pr.next_at = now
                                                                            + Duration::from_millis(
                                                                                wait,
                                                                            );
                                                                        pr.addr_idx = pr
                                                                            .addr_idx
                                                                            .saturating_add(1);
                                                                    }
                                                                }
                                                            } else {
                                                                // Slice AK: reconnect dial attempt.
                                                                if let Ok(mut st) = state_bg.lock()
                                                                {
                                                                    st.dialing =
                                                                        st.dialing.saturating_add(1);
                                                                }
                                                                reconnect_inflight =
                                                                    Some(pid.clone());
                                                                // Dedicated reconnect dial timeout
                                                                // (not full bootstrap 8s): real
                                                                // failures retry; twin error+ok
                                                                // still settle via ConnectionEstablished.
                                                                reconnect_inflight_deadline =
                                                                    Some(
                                                                        tokio::time::Instant::now()
                                                                            + Duration::from_secs(
                                                                                DEFAULT_RECONNECT_DIAL_TIMEOUT_SECS
                                                                                    .max(1),
                                                                            ),
                                                                    );
                                                            }
                                                        }
                                                        Err(_) => {
                                                            if let Ok(mut st) = state_bg.lock() {
                                                                st.dial_inflight = st
                                                                    .dial_inflight
                                                                    .saturating_sub(1);
                                                                st.reconnect_fail = st
                                                                    .reconnect_fail
                                                                    .saturating_add(1);
                                                            }
                                                            pending_reconnects.remove(&pid);
                                                            if let Ok(mut st) = state_bg.lock() {
                                                                st.reconnect_give_up = st
                                                                    .reconnect_give_up
                                                                    .saturating_add(1);
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        cmd = cmd_rx.recv() => {
                            match cmd {
                                None => break,
                                Some(Cmd::Shutdown { reply }) => {
                                    let _ = reply.send(());
                                    break;
                                }
                                Some(Cmd::Listen { addr, reply }) => {
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            if let Err(e) = swarm.listen_on(ma) {
                                                let _ = reply.send(Err(format!("listen_on: {e}")));
                                            } else {
                                                pending_listen = Some(reply);
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::ListenRelay { relay_addr, reply }) => {
                                    match relay_addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            // Ensure /p2p/<relay> is present for circuit listen.
                                            let has_p2p = ma
                                                .iter()
                                                .any(|p| matches!(p, Protocol::P2p(_)));
                                            if !has_p2p {
                                                let _ = reply.send(Err(
                                                    "relay multiaddr must include /p2p/<peer_id>"
                                                        .into(),
                                                ));
                                                continue;
                                            }
                                            // Circuit listen: transport will dial relay if needed
                                            // and request a reservation (see libp2p-relay client).
                                            let circuit = ma.with(Protocol::P2pCircuit);
                                            if let Err(e) = swarm.listen_on(circuit) {
                                                let _ = reply.send(Err(format!(
                                                    "listen circuit: {e}"
                                                )));
                                            } else {
                                                pending_relay_listen = Some(reply);
                                                relay_listen_deadline = Some(
                                                    tokio::time::Instant::now()
                                                        + Duration::from_secs(12),
                                                );
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::RemoveListener { addr, reply }) => {
                                    // Slice AJ: prefer exact listen multiaddr book match.
                                    let id = listen_ids.get(&addr).copied().or_else(|| {
                                        // Tolerate trailing /p2p/<self> variants by prefix match.
                                        listen_ids.iter().find_map(|(known, id)| {
                                            if known == &addr
                                                || known.starts_with(&addr)
                                                || addr.starts_with(known)
                                            {
                                                Some(*id)
                                            } else {
                                                None
                                            }
                                        })
                                    });
                                    match id {
                                        Some(listener_id) => {
                                            let removed = swarm.remove_listener(listener_id);
                                            let _ = reply.send(Ok(removed));
                                        }
                                        None => {
                                            let _ = reply.send(Err(format!(
                                                "no listener for addr: {addr}"
                                            )));
                                        }
                                    }
                                }
                                Some(Cmd::Dial { addr, reply }) => {
                                    let is_dns =
                                        addr.contains("/dns4/") || addr.contains("/dns6/");
                                    let is_quic = addr.contains("/quic-v1")
                                        || addr.contains("/quic/");
                                    let is_ws = addr.contains("/ws");
                                    // Fast-fail if multiaddr targets a blocked PeerId (Slice I).
                                    if let Ok(ma) = addr.parse::<Multiaddr>() {
                                        let target = ma.iter().find_map(|p| match p {
                                            Protocol::P2p(pid) => Some(pid),
                                            _ => None,
                                        });
                                        if let Some(pid) = target {
                                            let blocked = state_bg
                                                .lock()
                                                .map(|st| st.blocked.contains(&pid.to_string()))
                                                .unwrap_or(false);
                                            if blocked {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.block_denied =
                                                        st.block_denied.saturating_add(1);
                                                    // Slice AW/AX: fast-fail Denied taxonomy.
                                                    st.dial_fail =
                                                        st.dial_fail.saturating_add(1);
                                                    st.dial_fail_denied = st
                                                        .dial_fail_denied
                                                        .saturating_add(1);
                                                    st.dial_fail_denied_block = st
                                                        .dial_fail_denied_block
                                                        .saturating_add(1);
                                                    st.last_error = "peer_blocked".into();
                                                    if is_dns {
                                                        st.dns_dial_fail =
                                                            st.dns_dial_fail.saturating_add(1);
                                                    }
                                                    if is_quic {
                                                        st.quic_dial_fail =
                                                            st.quic_dial_fail.saturating_add(1);
                                                    }
                                                    if is_ws {
                                                        st.ws_dial_fail =
                                                            st.ws_dial_fail.saturating_add(1);
                                                    }
                                                }
                                                let _ = reply.send(Err("peer_blocked".into()));
                                                continue;
                                            }
                                        }
                                    }
                                    // Budget = outbound peers + inflight dials (Slice C).
                                    let reserved = if let Ok(mut st) = state_bg.lock() {
                                        let used = (st.outbound_peers.len() as u32)
                                            .saturating_add(st.dial_inflight);
                                        if used < st.max_dials {
                                            st.dial_inflight =
                                                st.dial_inflight.saturating_add(1);
                                            true
                                        } else {
                                            st.dial_refused_budget =
                                                st.dial_refused_budget.saturating_add(1);
                                            st.last_error = "dial_budget_exceeded".into();
                                            false
                                        }
                                    } else {
                                        false
                                    };
                                    if !reserved {
                                        let _ = reply.send(Err("dial_budget_exceeded".into()));
                                        continue;
                                    }
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            if let Err(e) = swarm.dial(ma) {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.dial_fail = st.dial_fail.saturating_add(1);
                                                    st.dial_inflight =
                                                        st.dial_inflight.saturating_sub(1);
                                                    if is_dns {
                                                        st.dns_dial_fail =
                                                            st.dns_dial_fail.saturating_add(1);
                                                    }
                                                    if is_quic {
                                                        st.quic_dial_fail =
                                                            st.quic_dial_fail.saturating_add(1);
                                                    }
                                                    if is_ws {
                                                        st.ws_dial_fail =
                                                            st.ws_dial_fail.saturating_add(1);
                                                    }
                                                }
                                                let _ = reply.send(Err(format!("dial: {e}")));
                                            } else {
                                                // Slice AK: direct swarm.dial does not emit Dialing.
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.dialing = st.dialing.saturating_add(1);
                                                }
                                                pending_dial = Some(reply);
                                                pending_dial_dns = is_dns;
                                                pending_dial_quic = is_quic;
                                                pending_dial_ws = is_ws;
                                            }
                                        }
                                        Err(e) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.dial_inflight =
                                                    st.dial_inflight.saturating_sub(1);
                                                if is_dns {
                                                    st.dns_dial_fail =
                                                        st.dns_dial_fail.saturating_add(1);
                                                }
                                                if is_quic {
                                                    st.quic_dial_fail =
                                                        st.quic_dial_fail.saturating_add(1);
                                                }
                                                if is_ws {
                                                    st.ws_dial_fail =
                                                        st.ws_dial_fail.saturating_add(1);
                                                }
                                            }
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::SendWire { peer_id, data, reply }) => {
                                    let codec = super::classify_abs_wire_codec(&data);
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            let req_id = swarm.behaviour_mut().wire.send_request(
                                                &pid,
                                                data,
                                            );
                                            pending_wire.insert(req_id, reply);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.wire_sent = st.wire_sent.saturating_add(1);
                                                match codec {
                                                    "v1" => {
                                                        st.abs_wire_v1_sent =
                                                            st.abs_wire_v1_sent.saturating_add(1)
                                                    }
                                                    "v2" => {
                                                        st.abs_wire_v2_sent =
                                                            st.abs_wire_v2_sent.saturating_add(1)
                                                    }
                                                    _ => {}
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::PollInbox { reply }) => {
                                    let items = if let Ok(mut st) = state_bg.lock() {
                                        st.inbox.drain(..).collect()
                                    } else {
                                        Vec::new()
                                    };
                                    let _ = reply.send(items);
                                }
                                Some(Cmd::Subscribe { topic, reply }) => {
                                    let t = gossipsub::IdentTopic::new(topic.clone());
                                    match swarm.behaviour_mut().gossipsub.subscribe(&t) {
                                        Ok(fresh) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.subscribed.insert(topic);
                                            }
                                            let _ = reply.send(Ok(fresh));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("subscribe: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::Unsubscribe { topic, reply }) => {
                                    let t = gossipsub::IdentTopic::new(topic.clone());
                                    match swarm.behaviour_mut().gossipsub.unsubscribe(&t) {
                                        Ok(was) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.subscribed.remove(&topic);
                                            }
                                            let _ = reply.send(Ok(was));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("unsubscribe: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::Publish { topic, data, reply }) => {
                                    if data.len() > MAX_WIRE_BYTES {
                                        let _ = reply.send(Err("gossip payload too large".into()));
                                        continue;
                                    }
                                    let t = gossipsub::IdentTopic::new(topic);
                                    match swarm.behaviour_mut().gossipsub.publish(t, data) {
                                        Ok(mid) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.gossip_pub = st.gossip_pub.saturating_add(1);
                                            }
                                            let _ = reply.send(Ok(mid.to_string()));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("publish: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::PollGossip { reply }) => {
                                    let items = if let Ok(mut st) = state_bg.lock() {
                                        st.gossip_inbox.drain(..).collect()
                                    } else {
                                        Vec::new()
                                    };
                                    let _ = reply.send(items);
                                }
                                Some(Cmd::GossipMeshPeers { topic, reply }) => {
                                    let t = gossipsub::IdentTopic::new(topic);
                                    let peers: Vec<String> = swarm
                                        .behaviour()
                                        .gossipsub
                                        .mesh_peers(&t.hash())
                                        .map(|p| p.to_string())
                                        .collect();
                                    let _ = reply.send(peers);
                                }
                                Some(Cmd::GossipTopicPeers { topic, reply }) => {
                                    let t = gossipsub::IdentTopic::new(topic);
                                    let want = t.hash();
                                    let peers: Vec<String> = swarm
                                        .behaviour()
                                        .gossipsub
                                        .all_peers()
                                        .filter_map(|(peer, topics)| {
                                            if topics.iter().any(|th| *th == &want) {
                                                Some(peer.to_string())
                                            } else {
                                                None
                                            }
                                        })
                                        .collect();
                                    let _ = reply.send(peers);
                                }
                                Some(Cmd::KadAddAddress { peer_id, addr, reply }) => {
                                    match (peer_id.parse::<PeerId>(), addr.parse::<Multiaddr>()) {
                                        (Ok(pid), Ok(ma)) => {
                                            let update = swarm
                                                .behaviour_mut()
                                                .kademlia
                                                .add_address(&pid, ma);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_peers.insert(pid.to_string());
                                            }
                                            let _ = reply.send(Ok(format!("{update:?}")));
                                        }
                                        (Err(e), _) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                        (_, Err(e)) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::KadGetClosest { peer_id, reply }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            let qid = swarm
                                                .behaviour_mut()
                                                .kademlia
                                                .get_closest_peers(pid);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_queries =
                                                    st.kad_queries.saturating_add(1);
                                            }
                                            pending_kad.insert(qid, reply);
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::BlockPeer { peer_id, reply }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            swarm.behaviour_mut().blocked_peers.block_peer(pid);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.blocked.insert(pid.to_string());
                                            }
                                            let _ = reply.send(Ok(()));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::UnblockPeer { peer_id, reply }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            swarm.behaviour_mut().blocked_peers.unblock_peer(pid);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.blocked.remove(&pid.to_string());
                                            }
                                            let _ = reply.send(Ok(()));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::AllowPeer { peer_id, reply }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            match swarm.behaviour_mut().allowed_peers.as_mut() {
                                                Some(al) => {
                                                    al.allow_peer(pid);
                                                    if let Ok(mut st) = state_bg.lock() {
                                                        st.allowed.insert(pid.to_string());
                                                    }
                                                    let _ = reply.send(Ok(()));
                                                }
                                                None => {
                                                    let _ = reply.send(Err(
                                                        "allow_list disabled (enable_allow_list=true)"
                                                            .into(),
                                                    ));
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::DisallowPeer { peer_id, reply }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            match swarm.behaviour_mut().allowed_peers.as_mut() {
                                                Some(al) => {
                                                    al.disallow_peer(pid);
                                                    if let Ok(mut st) = state_bg.lock() {
                                                        st.allowed.remove(&pid.to_string());
                                                    }
                                                    let _ = reply.send(Ok(()));
                                                }
                                                None => {
                                                    let _ = reply.send(Err(
                                                        "allow_list disabled (enable_allow_list=true)"
                                                            .into(),
                                                    ));
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::AutonatAddServer {
                                    peer_id,
                                    addr,
                                    reply,
                                }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            let ma = match addr {
                                                Some(a) => match a.parse::<Multiaddr>() {
                                                    Ok(m) => Some(m),
                                                    Err(e) => {
                                                        let _ = reply.send(Err(format!(
                                                            "bad multiaddr: {e}"
                                                        )));
                                                        continue;
                                                    }
                                                },
                                                None => None,
                                            };
                                            match swarm.behaviour_mut().autonat.as_mut() {
                                                Some(autonat) => {
                                                    autonat.add_server(pid, ma);
                                                    let _ = reply.send(Ok(()));
                                                }
                                                None => {
                                                    let _ = reply.send(Err(
                                                        "autonat disabled (enable_autonat=true)"
                                                            .into(),
                                                    ));
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::RendezvousRegister {
                                    namespace,
                                    rendezvous_peer,
                                    ttl,
                                    reply,
                                }) => {
                                    if pending_rendezvous_register.is_some() {
                                        let _ = reply.send(Err(
                                            "rendezvous register already in flight".into(),
                                        ));
                                        continue;
                                    }
                                    let ns = match rendezvous::Namespace::new(namespace) {
                                        Ok(n) => n,
                                        Err(e) => {
                                            let _ = reply
                                                .send(Err(format!("bad namespace: {e}")));
                                            continue;
                                        }
                                    };
                                    let pid = match rendezvous_peer.parse::<PeerId>() {
                                        Ok(p) => p,
                                        Err(e) => {
                                            let _ = reply
                                                .send(Err(format!("bad peer_id: {e}")));
                                            continue;
                                        }
                                    };
                                    // Lab: advertise listen addrs so register has PeerRecord material.
                                    let listen_snapshot = state_bg
                                        .lock()
                                        .map(|st| st.listen_addrs.clone())
                                        .unwrap_or_default();
                                    for a in listen_snapshot {
                                        if let Ok(ma) = a.parse::<Multiaddr>() {
                                            swarm.add_external_address(ma);
                                        }
                                    }
                                    match swarm.behaviour_mut().rendezvous_client.register(
                                        ns, pid, ttl,
                                    ) {
                                        Ok(()) => {
                                            pending_rendezvous_register = Some(reply);
                                        }
                                        Err(e) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_register_fail = st
                                                    .rendezvous_register_fail
                                                    .saturating_add(1);
                                            }
                                            let _ = reply.send(Err(format!(
                                                "rendezvous register: {e}"
                                            )));
                                        }
                                    }
                                }
                                Some(Cmd::RendezvousDiscover {
                                    namespace,
                                    rendezvous_peer,
                                    limit,
                                    reply,
                                }) => {
                                    if pending_rendezvous_discover.is_some() {
                                        let _ = reply.send(Err(
                                            "rendezvous discover already in flight".into(),
                                        ));
                                        continue;
                                    }
                                    let ns = match namespace {
                                        Some(s) => match rendezvous::Namespace::new(s) {
                                            Ok(n) => Some(n),
                                            Err(e) => {
                                                let _ = reply
                                                    .send(Err(format!("bad namespace: {e}")));
                                                continue;
                                            }
                                        },
                                        None => None,
                                    };
                                    let pid = match rendezvous_peer.parse::<PeerId>() {
                                        Ok(p) => p,
                                        Err(e) => {
                                            let _ = reply
                                                .send(Err(format!("bad peer_id: {e}")));
                                            continue;
                                        }
                                    };
                                    swarm.behaviour_mut().rendezvous_client.discover(
                                        ns, None, limit, pid,
                                    );
                                    pending_rendezvous_discover = Some(reply);
                                }
                                Some(Cmd::RendezvousUnregister {
                                    namespace,
                                    rendezvous_peer,
                                    reply,
                                }) => {
                                    let ns = match rendezvous::Namespace::new(namespace) {
                                        Ok(n) => n,
                                        Err(e) => {
                                            let _ = reply
                                                .send(Err(format!("bad namespace: {e}")));
                                            continue;
                                        }
                                    };
                                    match rendezvous_peer.parse::<PeerId>() {
                                        Ok(pid) => {
                                            swarm
                                                .behaviour_mut()
                                                .rendezvous_client
                                                .unregister(ns, pid);
                                            let _ = reply.send(Ok(()));
                                        }
                                        Err(e) => {
                                            let _ = reply
                                                .send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::AddExternalAddress { addr, reply }) => {
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            let s = ma.to_string();
                                            swarm.add_external_address(ma);
                                            // add_external_address does not emit SwarmEvent.
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.external_addr_confirmed =
                                                    st.external_addr_confirmed.saturating_add(1);
                                                if !st.external_addrs.contains(&s) {
                                                    st.external_addrs.push(s);
                                                }
                                            }
                                            let _ = reply.send(Ok(()));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::RemoveExternalAddress { addr, reply }) => {
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            let s = ma.to_string();
                                            swarm.remove_external_address(&ma);
                                            // remove_external_address does not emit SwarmEvent.
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.external_addr_expired =
                                                    st.external_addr_expired.saturating_add(1);
                                                st.external_addrs.retain(|a| a != &s);
                                            }
                                            let _ = reply.send(Ok(()));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::SetConnectionLimits {
                                    max_established_incoming,
                                    max_established_outgoing,
                                    max_established,
                                    max_established_per_peer,
                                    max_pending_incoming,
                                    max_pending_outgoing,
                                    reply,
                                }) => {
                                    // None = no change; Some(0) = unlimited; Some(n>0) = cap.
                                    let apply = |cur: Option<u32>, upd: Option<u32>| -> Option<u32> {
                                        match upd {
                                            None => cur,
                                            Some(0) => None,
                                            Some(n) => Some(n),
                                        }
                                    };
                                    let snap = if let Ok(mut st) = state_bg.lock() {
                                        st.max_established_incoming = apply(
                                            st.max_established_incoming,
                                            max_established_incoming,
                                        );
                                        st.max_established_outgoing = apply(
                                            st.max_established_outgoing,
                                            max_established_outgoing,
                                        );
                                        st.max_established =
                                            apply(st.max_established, max_established);
                                        st.max_established_per_peer = apply(
                                            st.max_established_per_peer,
                                            max_established_per_peer,
                                        );
                                        st.max_pending_incoming = apply(
                                            st.max_pending_incoming,
                                            max_pending_incoming,
                                        );
                                        st.max_pending_outgoing = apply(
                                            st.max_pending_outgoing,
                                            max_pending_outgoing,
                                        );
                                        st.connection_limits_updates = st
                                            .connection_limits_updates
                                            .saturating_add(1);
                                        (
                                            st.max_established_incoming,
                                            st.max_established_outgoing,
                                            st.max_established,
                                            st.max_established_per_peer,
                                            st.max_pending_incoming,
                                            st.max_pending_outgoing,
                                        )
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    let mut limits = connection_limits::ConnectionLimits::default();
                                    if let Some(n) = snap.0 {
                                        limits = limits.with_max_established_incoming(Some(n));
                                    }
                                    if let Some(n) = snap.1 {
                                        limits = limits.with_max_established_outgoing(Some(n));
                                    }
                                    if let Some(n) = snap.2 {
                                        limits = limits.with_max_established(Some(n));
                                    }
                                    if let Some(n) = snap.3 {
                                        limits = limits.with_max_established_per_peer(Some(n));
                                    }
                                    if let Some(n) = snap.4 {
                                        limits = limits.with_max_pending_incoming(Some(n));
                                    }
                                    if let Some(n) = snap.5 {
                                        limits = limits.with_max_pending_outgoing(Some(n));
                                    }
                                    *swarm.behaviour_mut().connection_limits.limits_mut() = limits;
                                    let _ = reply.send(Ok(()));
                                }
                                Some(Cmd::BootstrapAdd {
                                    peer_id,
                                    multiaddr,
                                    reply,
                                }) => {
                                    if peer_id.parse::<PeerId>().is_err() {
                                        let _ = reply.send(Err("bad peer_id".into()));
                                        continue;
                                    }
                                    if multiaddr.parse::<Multiaddr>().is_err() {
                                        let _ = reply.send(Err("bad multiaddr".into()));
                                        continue;
                                    }
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        let entry =
                                            st.bootstrap.entry(peer_id.clone()).or_default();
                                        if !entry.contains(&multiaddr) {
                                            entry.push(multiaddr.clone());
                                        }
                                        if let Ok(ma) = multiaddr.parse::<Multiaddr>() {
                                            if let Ok(pid) = peer_id.parse::<PeerId>() {
                                                swarm
                                                    .behaviour_mut()
                                                    .kademlia
                                                    .add_address(&pid, ma);
                                            }
                                        }
                                        let path = st.bootstrap_path.clone();
                                        let snap = st.bootstrap.clone();
                                        (path, snap)
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    let res = if persist.0.is_empty() {
                                        Ok(())
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.0), &persist.1)
                                    };
                                    let _ = reply.send(res);
                                }
                                Some(Cmd::BootstrapRemove { peer_id, reply }) => {
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        st.bootstrap.remove(&peer_id);
                                        let path = st.bootstrap_path.clone();
                                        let snap = st.bootstrap.clone();
                                        (path, snap)
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    let res = if persist.0.is_empty() {
                                        Ok(())
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.0), &persist.1)
                                    };
                                    let _ = reply.send(res);
                                }
                                Some(Cmd::BootstrapList { reply }) => {
                                    let snap = state_bg
                                        .lock()
                                        .map(|st| st.bootstrap.clone())
                                        .unwrap_or_default();
                                    let _ = reply.send(snap);
                                }
                                Some(Cmd::BootstrapDial { reply }) => {
                                    if bootstrap_job.is_some() {
                                        let _ = reply.send(Err(
                                            "bootstrap_dial already in progress".into(),
                                        ));
                                        continue;
                                    }
                                    if pending_dial.is_some() {
                                        let _ = reply.send(Err(
                                            "bootstrap_dial blocked: user dial in flight".into(),
                                        ));
                                        continue;
                                    }
                                    let queue = state_bg
                                        .lock()
                                        .map(|st| flatten_bootstrap_addrs(&st.bootstrap))
                                        .unwrap_or_default();
                                    bootstrap_job = Some(BootstrapDialJob {
                                        kind: BookDialKind::Bootstrap,
                                        queue: queue.into(),
                                        results: Vec::new(),
                                        current_peer: None,
                                        reply,
                                        per_dial_deadline: None,
                                        abandoned: HashSet::new(),
                                    });
                                    let _ = bootstrap_advance(
                                        &mut swarm,
                                        &state_bg,
                                        &mut bootstrap_job,
                                    );
                                }
                                Some(Cmd::PeerstoreList { reply }) => {
                                    let snap = state_bg
                                        .lock()
                                        .map(|st| st.peerstore.clone())
                                        .unwrap_or_default();
                                    let _ = reply.send(snap);
                                }
                                Some(Cmd::PeerstoreClear { reply }) => {
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        st.peerstore.clear();
                                        (st.peerstore_path.clone(), st.peerstore.clone())
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    let res = if persist.0.is_empty() {
                                        Ok(())
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.0), &persist.1)
                                    };
                                    let _ = reply.send(res);
                                }
                                Some(Cmd::PeerstoreDial { reply }) => {
                                    if bootstrap_job.is_some() {
                                        let _ = reply.send(Err(
                                            "book dial already in progress".into(),
                                        ));
                                        continue;
                                    }
                                    if pending_dial.is_some() {
                                        let _ = reply.send(Err(
                                            "peerstore_dial blocked: user dial in flight".into(),
                                        ));
                                        continue;
                                    }
                                    let queue = state_bg
                                        .lock()
                                        .map(|st| flatten_bootstrap_addrs(&st.peerstore))
                                        .unwrap_or_default();
                                    bootstrap_job = Some(BootstrapDialJob {
                                        kind: BookDialKind::Peerstore,
                                        queue: queue.into(),
                                        results: Vec::new(),
                                        current_peer: None,
                                        reply,
                                        per_dial_deadline: None,
                                        abandoned: HashSet::new(),
                                    });
                                    let _ = bootstrap_advance(
                                        &mut swarm,
                                        &state_bg,
                                        &mut bootstrap_job,
                                    );
                                }
                                Some(Cmd::SetReconnectEnabled { enabled, reply }) => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.enable_reconnect = enabled;
                                    }
                                    if !enabled {
                                        pending_reconnects.clear();
                                        reconnect_inflight = None;
                                        reconnect_inflight_deadline = None;
                                    }
                                    let _ = reply.send(());
                                }
                                Some(Cmd::DisconnectPeer { peer_id, reply }) => {
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            let _ = swarm.disconnect_peer_id(pid);
                                            let _ = reply.send(Ok(()));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::GossipPeerScore { peer_id, reply }) => {
                                    let score = peer_id
                                        .parse::<PeerId>()
                                        .ok()
                                        .and_then(|pid| swarm.behaviour().gossipsub.peer_score(&pid));
                                    let _ = reply.send(score);
                                }
                                Some(Cmd::SetGossipAppScore {
                                    peer_id,
                                    score,
                                    reply,
                                }) => {
                                    let ok = match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            let applied = swarm
                                                .behaviour_mut()
                                                .gossipsub
                                                .set_application_score(&pid, score);
                                            if applied {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.gossip_app_score_sets = st
                                                        .gossip_app_score_sets
                                                        .saturating_add(1);
                                                }
                                            }
                                            applied
                                        }
                                        Err(_) => false,
                                    };
                                    let _ = reply.send(ok);
                                }
                                Some(Cmd::ReportGossipValidation {
                                    message_id,
                                    peer_id,
                                    acceptance,
                                    reply,
                                }) => {
                                    let kind = acceptance.to_ascii_lowercase();
                                    let acc = match kind.as_str() {
                                        "accept" => gossipsub::MessageAcceptance::Accept,
                                        "reject" => gossipsub::MessageAcceptance::Reject,
                                        "ignore" => gossipsub::MessageAcceptance::Ignore,
                                        other => {
                                            let _ = reply.send(Err(format!(
                                                "acceptance must be accept|reject|ignore, got {other}"
                                            )));
                                            continue;
                                        }
                                    };
                                    match peer_id.parse::<PeerId>() {
                                        Ok(pid) => {
                                            let mid = gossipsub::MessageId::from(message_id);
                                            match swarm
                                                .behaviour_mut()
                                                .gossipsub
                                                .report_message_validation_result(&mid, &pid, acc)
                                            {
                                                Ok(forwarded) => {
                                                    if let Ok(mut st) = state_bg.lock() {
                                                        match kind.as_str() {
                                                            "accept" => {
                                                                st.gossip_validation_accept = st
                                                                    .gossip_validation_accept
                                                                    .saturating_add(1);
                                                            }
                                                            "reject" => {
                                                                st.gossip_validation_reject = st
                                                                    .gossip_validation_reject
                                                                    .saturating_add(1);
                                                            }
                                                            "ignore" => {
                                                                // Slice BA.
                                                                st.gossip_validation_ignore = st
                                                                    .gossip_validation_ignore
                                                                    .saturating_add(1);
                                                            }
                                                            _ => {}
                                                        }
                                                        if st.gossip_validation_pending > 0 {
                                                            st.gossip_validation_pending = st
                                                                .gossip_validation_pending
                                                                .saturating_sub(1);
                                                        }
                                                    }
                                                    let _ = reply.send(Ok(forwarded));
                                                }
                                                Err(e) => {
                                                    let _ = reply.send(Err(format!(
                                                        "report_gossip_validation: {e}"
                                                    )));
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad peer_id: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::SetPingUnhealthyPolicy {
                                    enabled,
                                    max_fails,
                                    max_rtt_ms,
                                    reply,
                                }) => {
                                    let mut drop_list: Vec<String> = Vec::new();
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.enable_ping_unhealthy_disconnect = enabled;
                                        st.ping_max_fails = max_fails.max(1);
                                        st.ping_max_rtt_ms = max_rtt_ms;
                                        if enabled && max_rtt_ms > 0 {
                                            for (pid, ms) in st.ping_rtt_by_peer.iter() {
                                                if *ms >= max_rtt_ms {
                                                    drop_list.push(pid.clone());
                                                }
                                            }
                                            if !drop_list.is_empty() {
                                                st.ping_unhealthy_disconnects = st
                                                    .ping_unhealthy_disconnects
                                                    .saturating_add(drop_list.len() as u64);
                                                st.last_error = format!(
                                                    "ping unhealthy policy drop n={}",
                                                    drop_list.len()
                                                );
                                            }
                                        }
                                    }
                                    for pid in drop_list {
                                        if let Ok(p) = pid.parse::<PeerId>() {
                                            let _ = swarm.disconnect_peer_id(p);
                                        }
                                    }
                                    let _ = reply.send(());
                                }
                                Some(Cmd::LastPingRttMs { peer_id, reply }) => {
                                    let rtt = state_bg
                                        .lock()
                                        .ok()
                                        .and_then(|st| st.ping_rtt_by_peer.get(&peer_id).copied());
                                    let _ = reply.send(rtt);
                                }
                                Some(Cmd::SetScoreAutoblock {
                                    enabled,
                                    graylist_threshold,
                                    reply,
                                }) => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.enable_score_autoblock = enabled;
                                        st.score_graylist_threshold = graylist_threshold;
                                    }
                                    let _ = reply.send(());
                                }
                            }
                        }
                        event = swarm.select_next_some() => {
                            match event {
                                SwarmEvent::NewListenAddr {
                                    listener_id,
                                    address,
                                } => {
                                    let s = address.to_string();
                                    let is_circuit = address
                                        .iter()
                                        .any(|p| matches!(p, Protocol::P2pCircuit));
                                    let is_ip6 = s.contains("/ip6/");
                                    let is_quic =
                                        s.contains("/quic-v1") || s.contains("/quic/");
                                    let is_ws = s.contains("/ws");
                                    listen_ids.insert(s.clone(), listener_id);
                                    // Slice X/AG: listen addrs become external so register has material.
                                    if !is_circuit {
                                        swarm.add_external_address(address.clone());
                                    }
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.new_listen_addr =
                                            st.new_listen_addr.saturating_add(1);
                                        if !st.listen_addrs.contains(&s) {
                                            st.listen_addrs.push(s.clone());
                                        }
                                        // Slice AG: Swarm.add_external_address does not emit SwarmEvent.
                                        if !is_circuit {
                                            st.external_addr_confirmed =
                                                st.external_addr_confirmed.saturating_add(1);
                                            if !st.external_addrs.contains(&s) {
                                                st.external_addrs.push(s.clone());
                                            }
                                        }
                                        if is_circuit && !st.circuit_addrs.contains(&s) {
                                            st.circuit_addrs.push(s.clone());
                                        }
                                        if is_ip6 && !is_circuit {
                                            st.ipv6_listens = st.ipv6_listens.saturating_add(1);
                                        }
                                        if is_quic && !is_circuit {
                                            st.quic_listens = st.quic_listens.saturating_add(1);
                                        }
                                        if is_ws && !is_circuit {
                                            st.ws_listens = st.ws_listens.saturating_add(1);
                                        }
                                    }
                                    if is_circuit {
                                        if let Some(reply) = pending_relay_listen.take() {
                                            relay_listen_deadline = None;
                                            let addrs = state_bg
                                                .lock()
                                                .map(|st| st.circuit_addrs.clone())
                                                .unwrap_or_else(|_| vec![s.clone()]);
                                            let _ = reply.send(Ok(addrs));
                                        }
                                    } else if let Some(reply) = pending_listen.take() {
                                        let addrs = state_bg
                                            .lock()
                                            .map(|st| st.listen_addrs.clone())
                                            .unwrap_or_else(|_| vec![s]);
                                        let _ = reply.send(Ok(addrs));
                                    }
                                }
                                SwarmEvent::ExpiredListenAddr {
                                    listener_id,
                                    address,
                                } => {
                                    let s = address.to_string();
                                    listen_ids.retain(|addr, id| {
                                        !(*id == listener_id && addr == &s)
                                    });
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.expired_listen_addr =
                                            st.expired_listen_addr.saturating_add(1);
                                        st.listen_addrs.retain(|a| a != &s);
                                        st.circuit_addrs.retain(|a| a != &s);
                                        st.external_addrs.retain(|a| a != &s);
                                    }
                                }
                                SwarmEvent::ListenerClosed {
                                    listener_id,
                                    addresses,
                                    reason,
                                } => {
                                    listen_ids.retain(|_, id| *id != listener_id);
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.listener_closed =
                                            st.listener_closed.saturating_add(1);
                                        for a in addresses.iter().map(|x| x.to_string()) {
                                            st.listen_addrs.retain(|x| x != &a);
                                            st.circuit_addrs.retain(|x| x != &a);
                                            st.external_addrs.retain(|x| x != &a);
                                        }
                                        if let Err(e) = reason {
                                            st.last_error = format!("listener_closed: {e}");
                                        }
                                    }
                                }
                                SwarmEvent::ListenerError { listener_id, error } => {
                                    let _ = listener_id;
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.listener_error =
                                            st.listener_error.saturating_add(1);
                                        st.last_error = format!("listener_error: {error}");
                                    }
                                }
                                SwarmEvent::IncomingConnection { .. } => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.incoming_connections =
                                            st.incoming_connections.saturating_add(1);
                                    }
                                }
                                SwarmEvent::Dialing { .. } => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.dialing = st.dialing.saturating_add(1);
                                    }
                                }
                                SwarmEvent::NewExternalAddrOfPeer { peer_id, address } => {
                                    let pid = peer_id.to_string();
                                    let s = address.to_string();
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.peer_external_addr =
                                            st.peer_external_addr.saturating_add(1);
                                    }
                                    peerstore_note_addr(&state_bg, &pid, &s);
                                }
                                SwarmEvent::ConnectionEstablished {
                                    peer_id,
                                    endpoint,
                                    established_in,
                                    ..
                                } => {
                                    let pid = peer_id.to_string();
                                    let is_dialer = endpoint.is_dialer();
                                    let est_ms = established_in
                                        .as_millis()
                                        .min(u128::from(u64::MAX))
                                        as u64;
                                    // Explicit peer so gossipsub mesh forms without mDNS.
                                    swarm.behaviour_mut().gossipsub.add_explicit_peer(&peer_id);
                                    let kad_addr = match &endpoint {
                                        ConnectedPoint::Dialer { address, .. } => {
                                            Some(address.clone())
                                        }
                                        ConnectedPoint::Listener { send_back_addr, .. } => {
                                            Some(send_back_addr.clone())
                                        }
                                    };
                                    if let Some(addr) = kad_addr.clone() {
                                        swarm
                                            .behaviour_mut()
                                            .kademlia
                                            .add_address(&peer_id, addr);
                                    }
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.connected.insert(pid.clone());
                                        st.kad_peers.insert(pid.clone());
                                        st.established_in_ms_last = est_ms;
                                        if est_ms > st.established_in_ms_max {
                                            st.established_in_ms_max = est_ms;
                                        }
                                        if is_dialer {
                                            st.outbound_peers.insert(pid.clone());
                                            st.dial_ok = st.dial_ok.saturating_add(1);
                                            st.dial_inflight =
                                                st.dial_inflight.saturating_sub(1);
                                            if let Some(addr) = kad_addr.as_ref() {
                                                if addr.to_string().contains("/ip6/") {
                                                    st.ipv6_dial_ok =
                                                        st.ipv6_dial_ok.saturating_add(1);
                                                }
                                            }
                                        } else {
                                            st.inbound_established =
                                                st.inbound_established.saturating_add(1);
                                        }
                                    }
                                    // Slice T: remember connection endpoint in peerstore.
                                    if let Some(addr) = kad_addr.as_ref() {
                                        peerstore_note_addr(&state_bg, &pid, &addr.to_string());
                                    }
                                    // Slice P: any re-establish of a pending bootstrap peer counts ok
                                    // (covers dialer success and races where OutgoingConnectionError
                                    // cleared inflight before ConnectionEstablished).
                                    reconnect_settle_ok(
                                        &state_bg,
                                        &mut pending_reconnects,
                                        &mut reconnect_inflight,
                                        &mut reconnect_inflight_deadline,
                                        &pid,
                                    );
                                    if is_dialer {
                                        if let Some(reply) = pending_dial.take() {
                                            if pending_dial_dns {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.dns_dial_ok =
                                                        st.dns_dial_ok.saturating_add(1);
                                                }
                                                pending_dial_dns = false;
                                            }
                                            if pending_dial_quic {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.quic_dial_ok =
                                                        st.quic_dial_ok.saturating_add(1);
                                                }
                                                pending_dial_quic = false;
                                            }
                                            if pending_dial_ws {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.ws_dial_ok =
                                                        st.ws_dial_ok.saturating_add(1);
                                                }
                                                pending_dial_ws = false;
                                            }
                                            let _ = reply.send(Ok(pid.clone()));
                                        } else {
                                            pending_dial_dns = false;
                                            pending_dial_quic = false;
                                            pending_dial_ws = false;
                                        }
                                        let is_current = bootstrap_job
                                            .as_ref()
                                            .and_then(|j| j.current_peer.as_deref())
                                            == Some(pid.as_str());
                                        if is_current {
                                            bootstrap_record_settle(
                                                &state_bg,
                                                &mut bootstrap_job,
                                                &pid,
                                                "ok".into(),
                                                "ok",
                                            );
                                            let _ = bootstrap_advance(
                                                &mut swarm,
                                                &state_bg,
                                                &mut bootstrap_job,
                                            );
                                        }
                                    }
                                }
                                SwarmEvent::OutgoingConnectionError { peer_id, error, .. } => {
                                    let limit_denied = matches!(
                                        &error,
                                        DialError::Denied { cause }
                                            if cause
                                                .downcast_ref::<connection_limits::Exceeded>()
                                                .is_some()
                                    );
                                    let block_denied = matches!(
                                        &error,
                                        DialError::Denied { cause }
                                            if cause
                                                .downcast_ref::<allow_block_list::Blocked>()
                                                .is_some()
                                    );
                                    let allow_denied = matches!(
                                        &error,
                                        DialError::Denied { cause }
                                            if cause
                                                .downcast_ref::<allow_block_list::NotAllowed>()
                                                .is_some()
                                    );
                                    let pid = peer_id.map(|p| p.to_string()).unwrap_or_default();
                                    let abandoned = !pid.is_empty()
                                        && bootstrap_job
                                            .as_ref()
                                            .map(|j| j.abandoned.contains(&pid))
                                            .unwrap_or(false);
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.last_error = format!("outgoing: {error}");
                                        if !abandoned {
                                            st.dial_fail = st.dial_fail.saturating_add(1);
                                            st.dial_inflight =
                                                st.dial_inflight.saturating_sub(1);
                                            // Slice AU: DialError taxonomy.
                                            match &error {
                                                DialError::Transport(_) => {
                                                    st.dial_fail_transport = st
                                                        .dial_fail_transport
                                                        .saturating_add(1);
                                                }
                                                DialError::WrongPeerId { .. } => {
                                                    st.dial_fail_wrong_peer_id = st
                                                        .dial_fail_wrong_peer_id
                                                        .saturating_add(1);
                                                }
                                                DialError::NoAddresses => {
                                                    st.dial_fail_no_addresses = st
                                                        .dial_fail_no_addresses
                                                        .saturating_add(1);
                                                }
                                                DialError::Aborted => {
                                                    st.dial_fail_aborted = st
                                                        .dial_fail_aborted
                                                        .saturating_add(1);
                                                }
                                                DialError::LocalPeerId { .. } => {
                                                    st.dial_fail_local_peer_id = st
                                                        .dial_fail_local_peer_id
                                                        .saturating_add(1);
                                                }
                                                DialError::DialPeerConditionFalse(_) => {
                                                    st.dial_fail_condition = st
                                                        .dial_fail_condition
                                                        .saturating_add(1);
                                                }
                                                DialError::Denied { .. } => {
                                                    // Slice AW/AX: Denied + cause taxonomy.
                                                    st.dial_fail_denied = st
                                                        .dial_fail_denied
                                                        .saturating_add(1);
                                                    if block_denied {
                                                        st.dial_fail_denied_block = st
                                                            .dial_fail_denied_block
                                                            .saturating_add(1);
                                                    } else if allow_denied {
                                                        st.dial_fail_denied_allow = st
                                                            .dial_fail_denied_allow
                                                            .saturating_add(1);
                                                    } else if limit_denied {
                                                        st.dial_fail_denied_limit = st
                                                            .dial_fail_denied_limit
                                                            .saturating_add(1);
                                                    }
                                                }
                                            }
                                        }
                                        if limit_denied {
                                            st.conn_limit_denied =
                                                st.conn_limit_denied.saturating_add(1);
                                        }
                                        if block_denied {
                                            st.block_denied = st.block_denied.saturating_add(1);
                                        }
                                        if allow_denied {
                                            st.allow_denied = st.allow_denied.saturating_add(1);
                                        }
                                    }
                                    if let Some(reply) = pending_dial.take() {
                                        if pending_dial_dns {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.dns_dial_fail =
                                                    st.dns_dial_fail.saturating_add(1);
                                            }
                                            pending_dial_dns = false;
                                        }
                                        if pending_dial_quic {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.quic_dial_fail =
                                                    st.quic_dial_fail.saturating_add(1);
                                            }
                                            pending_dial_quic = false;
                                        }
                                        if pending_dial_ws {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.ws_dial_fail =
                                                    st.ws_dial_fail.saturating_add(1);
                                            }
                                            pending_dial_ws = false;
                                        }
                                        let msg = if block_denied {
                                            "peer_blocked".into()
                                        } else if allow_denied {
                                            "peer_not_allowed".into()
                                        } else {
                                            format!("outgoing: {error}")
                                        };
                                        let _ = reply.send(Err(msg));
                                    } else {
                                        pending_dial_dns = false;
                                        pending_dial_quic = false;
                                        pending_dial_ws = false;
                                    }
                                    if !pid.is_empty() && !abandoned {
                                        let is_current = bootstrap_job
                                            .as_ref()
                                            .and_then(|j| j.current_peer.as_deref())
                                            == Some(pid.as_str());
                                        if is_current {
                                            let status = if block_denied {
                                                "peer_blocked".into()
                                            } else {
                                                format!("outgoing: {error}")
                                            };
                                            bootstrap_record_settle(
                                                &state_bg,
                                                &mut bootstrap_job,
                                                &pid,
                                                status,
                                                "fail",
                                            );
                                            let _ = bootstrap_advance(
                                                &mut swarm,
                                                &state_bg,
                                                &mut bootstrap_job,
                                            );
                                        }
                                        if reconnect_inflight.as_deref() == Some(pid.as_str()) {
                                            // Ignore spurious dial errors if the peer is already up
                                            // (libp2p may emit OutgoingConnectionError alongside success).
                                            let still_up = pid
                                                .parse::<PeerId>()
                                                .ok()
                                                .map(|p| swarm.is_connected(&p))
                                                .unwrap_or(false)
                                                || state_bg
                                                    .lock()
                                                    .map(|st| st.connected.contains(&pid))
                                                    .unwrap_or(false);
                                            if still_up {
                                                reconnect_settle_ok(
                                                    &state_bg,
                                                    &mut pending_reconnects,
                                                    &mut reconnect_inflight,
                                                    &mut reconnect_inflight_deadline,
                                                    &pid,
                                                );
                                            } else if let Ok(mut st) = state_bg.lock() {
                                                // Watch-only: libp2p often emits OutgoingConnectionError
                                                // alongside a still-progressing dial / twin success.
                                                // Clearing inflight here starts a second dial and
                                                // storms Windows loopback. Hard-fail via deadline.
                                                st.last_error = format!(
                                                    "outgoing(reconnect watch): {error}"
                                                );
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::IncomingConnectionError { error, .. } => {
                                    let limit_denied = matches!(
                                        &error,
                                        ListenError::Denied { cause }
                                            if cause
                                                .downcast_ref::<connection_limits::Exceeded>()
                                                .is_some()
                                    );
                                    let block_denied = matches!(
                                        &error,
                                        ListenError::Denied { cause }
                                            if cause
                                                .downcast_ref::<allow_block_list::Blocked>()
                                                .is_some()
                                    );
                                    let allow_denied = matches!(
                                        &error,
                                        ListenError::Denied { cause }
                                            if cause
                                                .downcast_ref::<allow_block_list::NotAllowed>()
                                                .is_some()
                                    );
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.incoming_connection_error =
                                            st.incoming_connection_error.saturating_add(1);
                                        st.last_error = format!("incoming: {error}");
                                        // Slice AV: ListenError taxonomy.
                                        match &error {
                                            ListenError::Transport(_) => {
                                                st.incoming_fail_transport = st
                                                    .incoming_fail_transport
                                                    .saturating_add(1);
                                            }
                                            ListenError::WrongPeerId { .. } => {
                                                st.incoming_fail_wrong_peer_id = st
                                                    .incoming_fail_wrong_peer_id
                                                    .saturating_add(1);
                                            }
                                            ListenError::Aborted => {
                                                st.incoming_fail_aborted = st
                                                    .incoming_fail_aborted
                                                    .saturating_add(1);
                                            }
                                            ListenError::LocalPeerId { .. } => {
                                                st.incoming_fail_local_peer_id = st
                                                    .incoming_fail_local_peer_id
                                                    .saturating_add(1);
                                            }
                                            ListenError::Denied { .. } => {
                                                // Slice AV/AX: Denied + cause taxonomy.
                                                st.incoming_fail_denied = st
                                                    .incoming_fail_denied
                                                    .saturating_add(1);
                                                if block_denied {
                                                    st.incoming_fail_denied_block = st
                                                        .incoming_fail_denied_block
                                                        .saturating_add(1);
                                                } else if allow_denied {
                                                    st.incoming_fail_denied_allow = st
                                                        .incoming_fail_denied_allow
                                                        .saturating_add(1);
                                                } else if limit_denied {
                                                    st.incoming_fail_denied_limit = st
                                                        .incoming_fail_denied_limit
                                                        .saturating_add(1);
                                                }
                                            }
                                        }
                                        if limit_denied {
                                            st.conn_limit_denied =
                                                st.conn_limit_denied.saturating_add(1);
                                        }
                                        if block_denied {
                                            st.block_denied = st.block_denied.saturating_add(1);
                                        }
                                        if allow_denied {
                                            st.allow_denied = st.allow_denied.saturating_add(1);
                                        }
                                    }
                                }
                                SwarmEvent::ExternalAddrConfirmed { address } => {
                                    let s = address.to_string();
                                    let is_circuit = address
                                        .iter()
                                        .any(|p| matches!(p, Protocol::P2pCircuit));
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.external_addr_confirmed =
                                            st.external_addr_confirmed.saturating_add(1);
                                        if !st.external_addrs.contains(&s) {
                                            st.external_addrs.push(s.clone());
                                        }
                                        if is_circuit {
                                            if !st.circuit_addrs.contains(&s) {
                                                st.circuit_addrs.push(s.clone());
                                            }
                                            if !st.listen_addrs.contains(&s) {
                                                st.listen_addrs.push(s.clone());
                                            }
                                        }
                                    }
                                    if is_circuit {
                                        if let Some(reply) = pending_relay_listen.take() {
                                            relay_listen_deadline = None;
                                            let addrs = state_bg
                                                .lock()
                                                .map(|st| st.circuit_addrs.clone())
                                                .unwrap_or_else(|_| vec![s]);
                                            let _ = reply.send(Ok(addrs));
                                        }
                                    }
                                }
                                SwarmEvent::ExternalAddrExpired { address } => {
                                    let s = address.to_string();
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.external_addr_expired =
                                            st.external_addr_expired.saturating_add(1);
                                        st.external_addrs.retain(|a| a != &s);
                                    }
                                }
                                SwarmEvent::NewExternalAddrCandidate { address } => {
                                    let _ = address;
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.external_addr_candidates =
                                            st.external_addr_candidates.saturating_add(1);
                                    }
                                }
                                SwarmEvent::ConnectionClosed {
                                    peer_id,
                                    cause,
                                    ..
                                } => {
                                    let pid = peer_id.to_string();
                                    let idle_close =
                                        matches!(cause, Some(ConnectionError::KeepAliveTimeout));
                                    let still = swarm.is_connected(&peer_id);
                                    if !still {
                                        swarm.behaviour_mut().gossipsub.remove_explicit_peer(&peer_id);
                                    }
                                    if let Ok(mut st) = state_bg.lock() {
                                        if !still {
                                            st.connected.remove(&pid);
                                            st.outbound_peers.remove(&pid);
                                            st.connection_closed =
                                                st.connection_closed.saturating_add(1);
                                            // Slice AI: cause buckets align with last-peer closes.
                                            match &cause {
                                                None => {
                                                    st.connection_closed_local = st
                                                        .connection_closed_local
                                                        .saturating_add(1);
                                                }
                                                Some(ConnectionError::IO(_)) => {
                                                    st.connection_closed_io = st
                                                        .connection_closed_io
                                                        .saturating_add(1);
                                                }
                                                Some(ConnectionError::KeepAliveTimeout) => {
                                                    st.connection_closed_keep_alive = st
                                                        .connection_closed_keep_alive
                                                        .saturating_add(1);
                                                }
                                            }
                                        }
                                        if idle_close {
                                            st.idle_timeout_closes =
                                                st.idle_timeout_closes.saturating_add(1);
                                            st.last_error =
                                                format!("idle connection timeout peer={pid}");
                                        }
                                    }
                                    // Slice P/U: schedule reconnect after full disconnect for
                                    // bootstrap book peers, else learned peerstore peers.
                                    if !still {
                                        let schedule = state_bg.lock().ok().and_then(|st| {
                                            if !st.enable_reconnect {
                                                return None;
                                            }
                                            if st.blocked.contains(&pid) {
                                                return None;
                                            }
                                            let (addrs, from_peerstore) =
                                                if let Some(a) = st.bootstrap.get(&pid) {
                                                    if a.is_empty() {
                                                        return None;
                                                    }
                                                    (a.clone(), false)
                                                } else if let Some(a) = st.peerstore.get(&pid) {
                                                    if a.is_empty() {
                                                        return None;
                                                    }
                                                    (a.clone(), true)
                                                } else {
                                                    return None;
                                                };
                                            Some((
                                                prefer_reconnect_addrs(addrs),
                                                from_peerstore,
                                                st.reconnect_base_ms,
                                                pending_reconnects.contains_key(&pid),
                                            ))
                                        });
                                        if let Some((addrs, from_peerstore, base_ms, already)) =
                                            schedule
                                        {
                                            if !already && !addrs.is_empty() {
                                                pending_reconnects.insert(
                                                    pid.clone(),
                                                    PendingReconnect {
                                                        attempts: 0,
                                                        next_at: tokio::time::Instant::now()
                                                            + Duration::from_millis(base_ms.max(1)),
                                                        addrs,
                                                        addr_idx: 0,
                                                    },
                                                );
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.reconnect_scheduled = st
                                                        .reconnect_scheduled
                                                        .saturating_add(1);
                                                    if from_peerstore {
                                                        st.reconnect_from_peerstore = st
                                                            .reconnect_from_peerstore
                                                            .saturating_add(1);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Ping(ev)) => {
                                    let pid = ev.peer.to_string();
                                    let mut drop_peer = false;
                                    match ev.result {
                                        Ok(rtt) => {
                                            let ms = rtt.as_millis().min(u128::from(u64::MAX))
                                                as u64;
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.ping_ok = st.ping_ok.saturating_add(1);
                                                st.ping_rtt_ms_last = ms;
                                                if ms > st.ping_rtt_ms_max {
                                                    st.ping_rtt_ms_max = ms;
                                                }
                                                st.ping_rtt_by_peer.insert(pid.clone(), ms);
                                                st.ping_fail_streak.remove(&pid);
                                                if st.enable_ping_unhealthy_disconnect
                                                    && st.ping_max_rtt_ms > 0
                                                    && ms >= st.ping_max_rtt_ms
                                                {
                                                    st.ping_unhealthy_disconnects = st
                                                        .ping_unhealthy_disconnects
                                                        .saturating_add(1);
                                                    st.last_error = format!(
                                                        "ping unhealthy rtt_ms={ms} peer={pid}"
                                                    );
                                                    drop_peer = true;
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.ping_fail = st.ping_fail.saturating_add(1);
                                                // Slice AY: Failure taxonomy.
                                                match &e {
                                                    ping::Failure::Timeout => {
                                                        st.ping_fail_timeout = st
                                                            .ping_fail_timeout
                                                            .saturating_add(1);
                                                    }
                                                    ping::Failure::Unsupported => {
                                                        st.ping_fail_unsupported = st
                                                            .ping_fail_unsupported
                                                            .saturating_add(1);
                                                    }
                                                    ping::Failure::Other { .. } => {
                                                        st.ping_fail_other = st
                                                            .ping_fail_other
                                                            .saturating_add(1);
                                                    }
                                                }
                                                st.last_error = format!("ping fail {pid}: {e}");
                                                let streak = st
                                                    .ping_fail_streak
                                                    .entry(pid.clone())
                                                    .or_insert(0);
                                                *streak = streak.saturating_add(1);
                                                let streak_n = *streak;
                                                let max_fails = st.ping_max_fails.max(1);
                                                let unhealthy = st.enable_ping_unhealthy_disconnect;
                                                if unhealthy && streak_n >= max_fails {
                                                    st.ping_unhealthy_disconnects = st
                                                        .ping_unhealthy_disconnects
                                                        .saturating_add(1);
                                                    drop_peer = true;
                                                }
                                            }
                                        }
                                    }
                                    if drop_peer {
                                        let _ = swarm.disconnect_peer_id(ev.peer);
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Identify(ev)) => {
                                    match ev {
                                        identify::Event::Received { peer_id, info, .. } => {
                                            let snap = IdentifySnap {
                                                protocol_version: info.protocol_version.clone(),
                                                agent_version: info.agent_version.clone(),
                                                listen_addrs: info
                                                    .listen_addrs
                                                    .iter()
                                                    .map(|a| a.to_string())
                                                    .collect(),
                                                protocols: info
                                                    .protocols
                                                    .iter()
                                                    .map(|p| p.to_string())
                                                    .collect(),
                                                observed_addr: info.observed_addr.to_string(),
                                            };
                                            // Slice N: AutoNAT servers are explicit-only via
                                            // `autonat_add_server`. Auto-register from identify caused
                                            // probe dials that raced reconnect_inflight (Slice U flake).
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.identify_received =
                                                    st.identify_received.saturating_add(1);
                                                st.identify.insert(peer_id.to_string(), snap);
                                            }
                                            // Slice T: learn identify listen addrs into peerstore.
                                            let pid = peer_id.to_string();
                                            for a in info.listen_addrs.iter().map(|a| a.to_string())
                                            {
                                                peerstore_note_addr(&state_bg, &pid, &a);
                                            }
                                        }
                                        identify::Event::Sent { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.identify_sent =
                                                    st.identify_sent.saturating_add(1);
                                            }
                                        }
                                        identify::Event::Pushed { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.identify_pushed =
                                                    st.identify_pushed.saturating_add(1);
                                            }
                                        }
                                        identify::Event::Error { peer_id, error, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.identify_error =
                                                    st.identify_error.saturating_add(1);
                                                st.last_error = format!(
                                                    "identify error peer={peer_id}: {error}"
                                                );
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Gossipsub(ev)) => {
                                    match ev {
                                        gossipsub::Event::Message {
                                            propagation_source,
                                            message_id,
                                            message,
                                        } => {
                                            let topic = message.topic.to_string();
                                            let defer = state_bg
                                                .lock()
                                                .map(|st| st.enable_gossip_defer_validation)
                                                .unwrap_or(false);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.gossip_recv = st.gossip_recv.saturating_add(1);
                                                st.last_gossip_message_id =
                                                    message_id.to_string();
                                                st.last_gossip_propagation_peer =
                                                    propagation_source.to_string();
                                                if st.gossip_inbox.len() < 1024 {
                                                    st.gossip_inbox.push_back((
                                                        propagation_source.to_string(),
                                                        topic,
                                                        message.data,
                                                    ));
                                                }
                                                if defer {
                                                    // Slice BA: app must call report_gossip_validation.
                                                    st.gossip_validation_pending = st
                                                        .gossip_validation_pending
                                                        .saturating_add(1);
                                                }
                                            }
                                            if defer {
                                                // Leave message pending until explicit Accept/Reject/Ignore.
                                            } else {
                                                // Default: accept after enqueue so existing labs keep
                                                // forwarding.
                                                match swarm
                                                    .behaviour_mut()
                                                    .gossipsub
                                                    .report_message_validation_result(
                                                        &message_id,
                                                        &propagation_source,
                                                        gossipsub::MessageAcceptance::Accept,
                                                    ) {
                                                    Ok(_) => {
                                                        if let Ok(mut st) = state_bg.lock() {
                                                            st.gossip_validation_accept = st
                                                                .gossip_validation_accept
                                                                .saturating_add(1);
                                                        }
                                                    }
                                                    Err(e) => {
                                                        if let Ok(mut st) = state_bg.lock() {
                                                            st.last_error = format!(
                                                                "gossip validate accept: {e}"
                                                            );
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        gossipsub::Event::GossipsubNotSupported { peer_id } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.gossip_not_supported = st
                                                    .gossip_not_supported
                                                    .saturating_add(1);
                                                st.last_error = format!(
                                                    "gossipsub not supported: {peer_id}"
                                                );
                                            }
                                        }
                                        gossipsub::Event::Subscribed { peer_id, topic } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.gossip_peer_subscribed = st
                                                    .gossip_peer_subscribed
                                                    .saturating_add(1);
                                                st.last_error = format!(
                                                    "gossip subscribed peer={peer_id} topic={topic}"
                                                );
                                            }
                                        }
                                        gossipsub::Event::Unsubscribed { peer_id, topic } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.gossip_peer_unsubscribed = st
                                                    .gossip_peer_unsubscribed
                                                    .saturating_add(1);
                                                st.last_error = format!(
                                                    "gossip unsubscribed peer={peer_id} topic={topic}"
                                                );
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Mdns(ev)) => match ev {
                                    mdns::Event::Discovered(list) => {
                                        for (peer, addr) in list {
                                            // Slice K hygiene: ignore non-loopback mDNS (LAN noise).
                                            let loopback = addr.iter().any(|p| match p {
                                                Protocol::Ip4(ip) => ip.is_loopback(),
                                                Protocol::Ip6(ip) => ip.is_loopback(),
                                                _ => false,
                                            });
                                            if !loopback {
                                                continue;
                                            }
                                            swarm
                                                .behaviour_mut()
                                                .gossipsub
                                                .add_explicit_peer(&peer);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.mdns_discovered =
                                                    st.mdns_discovered.saturating_add(1);
                                                st.discovered
                                                    .insert(peer.to_string(), addr.to_string());
                                            }
                                        }
                                    }
                                    mdns::Event::Expired(list) => {
                                        for (peer, addr) in list {
                                            // Slice AS / K: same loopback hygiene as Discovered.
                                            let loopback = addr.iter().any(|p| match p {
                                                Protocol::Ip4(ip) => ip.is_loopback(),
                                                Protocol::Ip6(ip) => ip.is_loopback(),
                                                _ => false,
                                            });
                                            if !loopback {
                                                continue;
                                            }
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.mdns_expired =
                                                    st.mdns_expired.saturating_add(1);
                                                if st.discovered.get(&peer.to_string())
                                                    == Some(&addr.to_string())
                                                {
                                                    st.discovered.remove(&peer.to_string());
                                                }
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Kademlia(ev)) => {
                                    match ev {
                                        kad::Event::RoutingUpdated { peer, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_routing_updates =
                                                    st.kad_routing_updates.saturating_add(1);
                                                st.kad_peers.insert(peer.to_string());
                                            }
                                        }
                                        kad::Event::OutboundQueryProgressed {
                                            id,
                                            result,
                                            step,
                                            ..
                                        } => {
                                            if !step.last {
                                                continue;
                                            }
                                            if let kad::QueryResult::GetClosestPeers(res) = result {
                                                let ok = res.is_ok();
                                                if let Ok(mut st) = state_bg.lock() {
                                                    if ok {
                                                        st.kad_query_ok =
                                                            st.kad_query_ok.saturating_add(1);
                                                    } else {
                                                        st.kad_query_fail =
                                                            st.kad_query_fail.saturating_add(1);
                                                    }
                                                }
                                                if let Some(reply) = pending_kad.remove(&id) {
                                                    match res {
                                                        Ok(ok_peers) => {
                                                            let peers: Vec<String> = ok_peers
                                                                .peers
                                                                .into_iter()
                                                                .map(|p| p.peer_id.to_string())
                                                                .collect();
                                                            let _ = reply.send(Ok(peers));
                                                        }
                                                        Err(e) => {
                                                            let _ = reply.send(Err(format!(
                                                                "kad get_closest: {e}"
                                                            )));
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        kad::Event::InboundRequest { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_inbound_requests = st
                                                    .kad_inbound_requests
                                                    .saturating_add(1);
                                            }
                                        }
                                        kad::Event::UnroutablePeer { peer } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_unroutable_peer = st
                                                    .kad_unroutable_peer
                                                    .saturating_add(1);
                                                st.last_error =
                                                    format!("kad unroutable peer={peer}");
                                            }
                                        }
                                        kad::Event::RoutablePeer { peer, address } => {
                                            let s = address.to_string();
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_routable_peer =
                                                    st.kad_routable_peer.saturating_add(1);
                                                st.kad_peers.insert(peer.to_string());
                                            }
                                            peerstore_note_addr(
                                                &state_bg,
                                                &peer.to_string(),
                                                &s,
                                            );
                                        }
                                        kad::Event::PendingRoutablePeer { peer, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_pending_routable_peer = st
                                                    .kad_pending_routable_peer
                                                    .saturating_add(1);
                                                st.kad_peers.insert(peer.to_string());
                                            }
                                        }
                                        kad::Event::ModeChanged { new_mode } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.kad_mode_changed =
                                                    st.kad_mode_changed.saturating_add(1);
                                                st.last_error =
                                                    format!("kad mode changed: {new_mode:?}");
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Relay(ev)) => {
                                    #[allow(deprecated)]
                                    match ev {
                                        relay::Event::ReservationReqAccepted { renewed, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_reservations =
                                                    st.relay_reservations.saturating_add(1);
                                                if renewed {
                                                    // renewals still count as accepted reservations
                                                    let _ = renewed;
                                                }
                                            }
                                        }
                                        relay::Event::ReservationReqDenied { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_reservation_denied = st
                                                    .relay_reservation_denied
                                                    .saturating_add(1);
                                                st.last_error = "relay reservation denied".into();
                                            }
                                        }
                                        relay::Event::ReservationTimedOut { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_reservation_timed_out = st
                                                    .relay_reservation_timed_out
                                                    .saturating_add(1);
                                            }
                                        }
                                        relay::Event::CircuitReqAccepted { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuits =
                                                    st.relay_circuits.saturating_add(1);
                                            }
                                        }
                                        relay::Event::CircuitReqDenied { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuit_denied = st
                                                    .relay_circuit_denied
                                                    .saturating_add(1);
                                                st.last_error = "relay circuit denied".into();
                                            }
                                        }
                                        relay::Event::CircuitClosed { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuit_closed = st
                                                    .relay_circuit_closed
                                                    .saturating_add(1);
                                            }
                                        }
                                        relay::Event::ReservationReqAcceptFailed { .. }
                                        | relay::Event::ReservationReqDenyFailed { .. }
                                        | relay::Event::CircuitReqDenyFailed { .. }
                                        | relay::Event::CircuitReqOutboundConnectFailed { .. }
                                        | relay::Event::CircuitReqAcceptFailed { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.last_error = "relay hop internal failure".into();
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::RelayClient(ev)) => {
                                    match ev {
                                        relay::client::Event::ReservationReqAccepted {
                                            relay_peer_id,
                                            ..
                                        } => {
                                            let local = *swarm.local_peer_id();
                                            let addr = format!(
                                                "/p2p/{relay_peer_id}/p2p-circuit/p2p/{local}"
                                            );
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_reservations =
                                                    st.relay_reservations.saturating_add(1);
                                                if !st.circuit_addrs.contains(&addr) {
                                                    st.circuit_addrs.push(addr.clone());
                                                }
                                            }
                                            if let Some(reply) = pending_relay_listen.take() {
                                                relay_listen_deadline = None;
                                                let _ = reply.send(Ok(vec![addr]));
                                            }
                                        }
                                        relay::client::Event::InboundCircuitEstablished {
                                            ..
                                        } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuits =
                                                    st.relay_circuits.saturating_add(1);
                                                st.relay_inbound_circuit = st
                                                    .relay_inbound_circuit
                                                    .saturating_add(1);
                                            }
                                        }
                                        relay::client::Event::OutboundCircuitEstablished {
                                            ..
                                        } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuits =
                                                    st.relay_circuits.saturating_add(1);
                                                st.relay_outbound_circuit = st
                                                    .relay_outbound_circuit
                                                    .saturating_add(1);
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Autonat(ev)) => {
                                    match ev {
                                        autonat::Event::InboundProbe(ref probe) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.autonat_probes =
                                                    st.autonat_probes.saturating_add(1);
                                                st.autonat_inbound_probe = st
                                                    .autonat_inbound_probe
                                                    .saturating_add(1);
                                                if matches!(
                                                    probe,
                                                    autonat::InboundProbeEvent::Error { .. }
                                                ) {
                                                    st.autonat_inbound_probe_error = st
                                                        .autonat_inbound_probe_error
                                                        .saturating_add(1);
                                                    st.last_error =
                                                        "autonat inbound probe error".into();
                                                }
                                            }
                                        }
                                        autonat::Event::OutboundProbe(ref probe) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.autonat_probes =
                                                    st.autonat_probes.saturating_add(1);
                                                st.autonat_outbound_probe = st
                                                    .autonat_outbound_probe
                                                    .saturating_add(1);
                                                if matches!(
                                                    probe,
                                                    autonat::OutboundProbeEvent::Error { .. }
                                                ) {
                                                    st.autonat_outbound_probe_error = st
                                                        .autonat_outbound_probe_error
                                                        .saturating_add(1);
                                                    st.last_error =
                                                        "autonat outbound probe error".into();
                                                }
                                            }
                                        }
                                        autonat::Event::StatusChanged { new, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.autonat_status_changes = st
                                                    .autonat_status_changes
                                                    .saturating_add(1);
                                                st.autonat_status = match new {
                                                    autonat::NatStatus::Public(_) => 1,
                                                    autonat::NatStatus::Private => 2,
                                                    autonat::NatStatus::Unknown => 0,
                                                };
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Upnp(ev)) => match ev {
                                    upnp::Event::NewExternalAddr(addr) => {
                                        swarm.add_external_address(addr.clone());
                                        let s = addr.to_string();
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.upnp_external_addrs =
                                                st.upnp_external_addrs.saturating_add(1);
                                            if !st.listen_addrs.contains(&s) {
                                                st.listen_addrs.push(s);
                                            }
                                        }
                                    }
                                    upnp::Event::ExpiredExternalAddr(_) => {
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.upnp_expired_external_addrs = st
                                                .upnp_expired_external_addrs
                                                .saturating_add(1);
                                        }
                                    }
                                    upnp::Event::GatewayNotFound => {
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.upnp_gateway_not_found =
                                                st.upnp_gateway_not_found.saturating_add(1);
                                            st.last_error = "upnp_gateway_not_found".into();
                                        }
                                    }
                                    upnp::Event::NonRoutableGateway => {
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.upnp_non_routable_gateway = st
                                                .upnp_non_routable_gateway
                                                .saturating_add(1);
                                            st.last_error = "upnp_non_routable_gateway".into();
                                        }
                                    }
                                },
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Dcutr(ev)) => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        match ev.result {
                                            Ok(_) => {
                                                st.dcutr_upgrade_success = st
                                                    .dcutr_upgrade_success
                                                    .saturating_add(1);
                                            }
                                            Err(_) => {
                                                st.dcutr_upgrade_fail =
                                                    st.dcutr_upgrade_fail.saturating_add(1);
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::RendezvousServer(ev)) => {
                                    match ev {
                                        rendezvous::server::Event::PeerRegistered { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_server_registrations = st
                                                    .rendezvous_server_registrations
                                                    .saturating_add(1);
                                            }
                                        }
                                        rendezvous::server::Event::PeerUnregistered { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_server_unregistrations = st
                                                    .rendezvous_server_unregistrations
                                                    .saturating_add(1);
                                            }
                                        }
                                        rendezvous::server::Event::DiscoverServed { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_server_discover_served = st
                                                    .rendezvous_server_discover_served
                                                    .saturating_add(1);
                                            }
                                        }
                                        rendezvous::server::Event::DiscoverNotServed { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_server_discover_not_served = st
                                                    .rendezvous_server_discover_not_served
                                                    .saturating_add(1);
                                            }
                                        }
                                        rendezvous::server::Event::PeerNotRegistered { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_server_not_registered = st
                                                    .rendezvous_server_not_registered
                                                    .saturating_add(1);
                                                st.last_error =
                                                    "rendezvous peer not registered".into();
                                            }
                                        }
                                        rendezvous::server::Event::RegistrationExpired(_) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_server_registration_expired = st
                                                    .rendezvous_server_registration_expired
                                                    .saturating_add(1);
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::RendezvousClient(ev)) => {
                                    match ev {
                                        rendezvous::client::Event::Registered { ttl, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_registers = st
                                                    .rendezvous_registers
                                                    .saturating_add(1);
                                            }
                                            if let Some(reply) =
                                                pending_rendezvous_register.take()
                                            {
                                                let _ = reply.send(Ok(ttl));
                                            }
                                        }
                                        rendezvous::client::Event::RegisterFailed {
                                            error, ..
                                        } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_register_fail = st
                                                    .rendezvous_register_fail
                                                    .saturating_add(1);
                                            }
                                            if let Some(reply) =
                                                pending_rendezvous_register.take()
                                            {
                                                let _ = reply.send(Err(format!(
                                                    "rendezvous register failed: {error:?}"
                                                )));
                                            }
                                        }
                                        rendezvous::client::Event::Discovered {
                                            registrations,
                                            ..
                                        } => {
                                            let mut out: Vec<(String, Vec<String>)> = Vec::new();
                                            let mut n_peers = 0u64;
                                            for reg in registrations {
                                                let pid = reg.record.peer_id().to_string();
                                                let addrs: Vec<String> = reg
                                                    .record
                                                    .addresses()
                                                    .iter()
                                                    .map(|a| a.to_string())
                                                    .collect();
                                                n_peers = n_peers.saturating_add(1);
                                                out.push((pid, addrs));
                                            }
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_discovers = st
                                                    .rendezvous_discovers
                                                    .saturating_add(1);
                                                st.rendezvous_discovered_peers = st
                                                    .rendezvous_discovered_peers
                                                    .saturating_add(n_peers);
                                            }
                                            if let Some(reply) =
                                                pending_rendezvous_discover.take()
                                            {
                                                let _ = reply.send(Ok(out));
                                            }
                                        }
                                        rendezvous::client::Event::DiscoverFailed {
                                            error, ..
                                        } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_discover_fail = st
                                                    .rendezvous_discover_fail
                                                    .saturating_add(1);
                                            }
                                            if let Some(reply) =
                                                pending_rendezvous_discover.take()
                                            {
                                                let _ = reply.send(Err(format!(
                                                    "rendezvous discover failed: {error:?}"
                                                )));
                                            }
                                        }
                                        rendezvous::client::Event::Expired { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.rendezvous_expired =
                                                    st.rendezvous_expired.saturating_add(1);
                                            }
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Wire(ev)) => {
                                    use request_response::{Event, Message};
                                    match ev {
                                        Event::Message { peer, message, .. } => match message {
                                            Message::Request {
                                                request,
                                                channel,
                                                ..
                                            } => {
                                                let codec =
                                                    super::classify_abs_wire_codec(&request);
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.wire_recv =
                                                        st.wire_recv.saturating_add(1);
                                                    match codec {
                                                        "v1" => {
                                                            st.abs_wire_v1_recv = st
                                                                .abs_wire_v1_recv
                                                                .saturating_add(1)
                                                        }
                                                        "v2" => {
                                                            st.abs_wire_v2_recv = st
                                                                .abs_wire_v2_recv
                                                                .saturating_add(1)
                                                        }
                                                        _ => {}
                                                    }
                                                    if st.inbox.len() < 1024 {
                                                        st.inbox.push_back((
                                                            peer.to_string(),
                                                            request.clone(),
                                                        ));
                                                    }
                                                }
                                                // Echo ack: same payload prefix "OK:" + len
                                                let mut ack = b"OK:".to_vec();
                                                ack.extend_from_slice(
                                                    &(request.len() as u32).to_be_bytes(),
                                                );
                                                let _ = swarm
                                                    .behaviour_mut()
                                                    .wire
                                                    .send_response(channel, ack);
                                            }
                                            Message::Response {
                                                request_id,
                                                response,
                                            } => {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.wire_response_ok =
                                                        st.wire_response_ok.saturating_add(1);
                                                }
                                                if let Some(reply) =
                                                    pending_wire.remove(&request_id)
                                                {
                                                    let _ = reply.send(Ok(response));
                                                }
                                            }
                                        },
                                        Event::OutboundFailure {
                                            request_id,
                                            error,
                                            ..
                                        } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.wire_outbound_failure = st
                                                    .wire_outbound_failure
                                                    .saturating_add(1);
                                                // Slice AZ: OutboundFailure taxonomy.
                                                match &error {
                                                    request_response::OutboundFailure::DialFailure => {
                                                        st.wire_outbound_fail_dial = st
                                                            .wire_outbound_fail_dial
                                                            .saturating_add(1);
                                                    }
                                                    request_response::OutboundFailure::Timeout => {
                                                        st.wire_outbound_fail_timeout = st
                                                            .wire_outbound_fail_timeout
                                                            .saturating_add(1);
                                                    }
                                                    request_response::OutboundFailure::ConnectionClosed => {
                                                        st.wire_outbound_fail_connection_closed = st
                                                            .wire_outbound_fail_connection_closed
                                                            .saturating_add(1);
                                                    }
                                                    request_response::OutboundFailure::UnsupportedProtocols => {
                                                        st.wire_outbound_fail_unsupported = st
                                                            .wire_outbound_fail_unsupported
                                                            .saturating_add(1);
                                                    }
                                                    request_response::OutboundFailure::Io(_) => {
                                                        st.wire_outbound_fail_io = st
                                                            .wire_outbound_fail_io
                                                            .saturating_add(1);
                                                    }
                                                }
                                                st.last_error =
                                                    format!("wire outbound: {error}");
                                            }
                                            if let Some(reply) = pending_wire.remove(&request_id)
                                            {
                                                let _ = reply
                                                    .send(Err(format!("wire outbound: {error}")));
                                            }
                                        }
                                        Event::InboundFailure { error, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.wire_inbound_failure = st
                                                    .wire_inbound_failure
                                                    .saturating_add(1);
                                                // Slice AZ: InboundFailure taxonomy.
                                                match &error {
                                                    request_response::InboundFailure::Timeout => {
                                                        st.wire_inbound_fail_timeout = st
                                                            .wire_inbound_fail_timeout
                                                            .saturating_add(1);
                                                    }
                                                    request_response::InboundFailure::ConnectionClosed => {
                                                        st.wire_inbound_fail_connection_closed = st
                                                            .wire_inbound_fail_connection_closed
                                                            .saturating_add(1);
                                                    }
                                                    request_response::InboundFailure::UnsupportedProtocols => {
                                                        st.wire_inbound_fail_unsupported = st
                                                            .wire_inbound_fail_unsupported
                                                            .saturating_add(1);
                                                    }
                                                    request_response::InboundFailure::ResponseOmission => {
                                                        st.wire_inbound_fail_response_omission = st
                                                            .wire_inbound_fail_response_omission
                                                            .saturating_add(1);
                                                    }
                                                    request_response::InboundFailure::Io(_) => {
                                                        st.wire_inbound_fail_io = st
                                                            .wire_inbound_fail_io
                                                            .saturating_add(1);
                                                    }
                                                }
                                                st.last_error =
                                                    format!("wire inbound: {error}");
                                            }
                                        }
                                        Event::ResponseSent { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.wire_response_sent =
                                                    st.wire_response_sent.saturating_add(1);
                                            }
                                        }
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                }
            });

            let mut peer_id = String::new();
            for _ in 0..100 {
                if let Ok(pid) = peer_id_cell.lock() {
                    if !pid.is_empty() {
                        peer_id = pid.clone();
                        break;
                    }
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            if peer_id.is_empty() {
                let err = state
                    .lock()
                    .map(|s| s.last_error.clone())
                    .unwrap_or_default();
                return Err(PyRuntimeError::new_err(format!(
                    "libp2p node failed to start: {err}"
                )));
            }

            Ok(Self {
                peer_id,
                cmd_tx,
                state,
                bandwidth,
                _runtime: runtime,
            })
        }
    }

    #[pymethods]
    impl Libp2pNode {
        #[new]
        #[pyo3(signature = (
            max_dials = DEFAULT_MAX_DIALS,
            key_path = None,
            max_established_incoming = None,
            max_established_outgoing = None,
            max_established = None,
            max_established_per_peer = None,
            max_pending_incoming = None,
            max_pending_outgoing = None,
            enable_mdns = None,
            wire_timeout_secs = None,
            bootstrap_path = None,
            enable_reconnect = None,
            peerstore_path = None,
            enable_autonat = None,
            enable_upnp = None,
            enable_allow_list = None,
            idle_connection_timeout_secs = None,
            relay_max_reservations = None,
            mdns_ttl_secs = None
        ))]
        fn new_py(
            max_dials: u32,
            key_path: Option<String>,
            max_established_incoming: Option<u32>,
            max_established_outgoing: Option<u32>,
            max_established: Option<u32>,
            max_established_per_peer: Option<u32>,
            max_pending_incoming: Option<u32>,
            max_pending_outgoing: Option<u32>,
            enable_mdns: Option<bool>,
            wire_timeout_secs: Option<u64>,
            bootstrap_path: Option<String>,
            enable_reconnect: Option<bool>,
            peerstore_path: Option<String>,
            enable_autonat: Option<bool>,
            enable_upnp: Option<bool>,
            enable_allow_list: Option<bool>,
            idle_connection_timeout_secs: Option<u64>,
            relay_max_reservations: Option<u32>,
            mdns_ttl_secs: Option<u64>,
        ) -> PyResult<Self> {
            Self::spawn(
                max_dials,
                key_path,
                resolve_u32_limit(
                    max_established_incoming,
                    "ABS_LIBP2P_MAX_ESTABLISHED_INCOMING",
                ),
                resolve_u32_limit(
                    max_established_outgoing,
                    "ABS_LIBP2P_MAX_ESTABLISHED_OUTGOING",
                ),
                resolve_u32_limit(max_established, "ABS_LIBP2P_MAX_ESTABLISHED"),
                resolve_u32_limit(
                    max_established_per_peer,
                    "ABS_LIBP2P_MAX_ESTABLISHED_PER_PEER",
                ),
                resolve_u32_limit(max_pending_incoming, "ABS_LIBP2P_MAX_PENDING_INCOMING"),
                resolve_u32_limit(max_pending_outgoing, "ABS_LIBP2P_MAX_PENDING_OUTGOING"),
                resolve_enable_mdns(enable_mdns),
                resolve_wire_timeout_secs(wire_timeout_secs),
                resolve_bootstrap_path(bootstrap_path),
                resolve_enable_reconnect(enable_reconnect),
                resolve_peerstore_path(peerstore_path),
                resolve_enable_autonat(enable_autonat),
                resolve_enable_upnp(enable_upnp),
                resolve_enable_allow_list(enable_allow_list),
                resolve_idle_connection_timeout_secs(idle_connection_timeout_secs),
                resolve_u32_limit(relay_max_reservations, "ABS_LIBP2P_RELAY_MAX_RESERVATIONS"),
                resolve_mdns_ttl_secs(mdns_ttl_secs),
            )
        }

        #[getter]
        fn peer_id(&self) -> String {
            self.peer_id.clone()
        }

        fn listen(&self, multiaddr: &str) -> PyResult<Vec<String>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::Listen {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(addrs)) => Ok(addrs),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("listen reply dropped")),
            }
        }

        /// Slice AJ: remove a listener by its reported listen multiaddr.
        fn remove_listener(&self, multiaddr: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::RemoveListener {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(v)) => Ok(v),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("remove_listener reply dropped")),
            }
        }

        fn dial(&self, multiaddr: &str) -> PyResult<String> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::Dial {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(pid)) => Ok(pid),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("dial reply dropped")),
            }
        }

        /// Dial a relay and listen via circuit-relay-v2 (Slice H).
        ///
        /// ``relay_multiaddr`` must include ``/p2p/<relay_peer_id>``.
        /// Returns circuit listen multiaddrs once the reservation is accepted.
        fn listen_relay(&self, relay_multiaddr: &str) -> PyResult<Vec<String>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::ListenRelay {
                    relay_addr: relay_multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(addrs)) => Ok(addrs),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("listen_relay reply dropped")),
            }
        }

        /// Circuit listen addrs observed after ``listen_relay`` (Slice H).
        fn circuit_addrs(&self) -> Vec<String> {
            self.state
                .lock()
                .map(|s| s.circuit_addrs.clone())
                .unwrap_or_default()
        }

        /// Register a peer as AutoNAT dial-back server (Slice N).
        #[pyo3(signature = (peer_id, multiaddr=None))]
        fn autonat_add_server(&self, peer_id: &str, multiaddr: Option<&str>) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::AutonatAddServer {
                    peer_id: peer_id.to_string(),
                    addr: multiaddr.map(|s| s.to_string()),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("autonat_add_server reply dropped")),
            }
        }

        /// Slice AA: update ConnectionLimits at runtime.
        ///
        /// ``None`` = leave unchanged; ``0`` = unlimited; ``n>0`` = hard cap.
        /// Existing connections are not shed (rust-libp2p policy).
        #[pyo3(signature = (
            max_established_incoming = None,
            max_established_outgoing = None,
            max_established = None,
            max_established_per_peer = None,
            max_pending_incoming = None,
            max_pending_outgoing = None
        ))]
        fn set_connection_limits(
            &self,
            max_established_incoming: Option<u32>,
            max_established_outgoing: Option<u32>,
            max_established: Option<u32>,
            max_established_per_peer: Option<u32>,
            max_pending_incoming: Option<u32>,
            max_pending_outgoing: Option<u32>,
        ) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SetConnectionLimits {
                    max_established_incoming,
                    max_established_outgoing,
                    max_established,
                    max_established_per_peer,
                    max_pending_incoming,
                    max_pending_outgoing,
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "set_connection_limits reply dropped",
                )),
            }
        }

        /// Register at a rendezvous peer (Slice X). Returns TTL seconds.
        #[pyo3(signature = (rendezvous_peer_id, namespace=None, ttl=None))]
        fn rendezvous_register(
            &self,
            rendezvous_peer_id: &str,
            namespace: Option<&str>,
            ttl: Option<u64>,
        ) -> PyResult<u64> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::RendezvousRegister {
                    namespace: namespace.unwrap_or(ABS_RENDEZVOUS_NAMESPACE).to_string(),
                    rendezvous_peer: rendezvous_peer_id.to_string(),
                    ttl,
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(ttl)) => Ok(ttl),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("rendezvous_register reply dropped")),
            }
        }

        /// Discover peers via a rendezvous peer (Slice X).
        /// Returns ``{peer_id: [multiaddr, ...]}``.
        #[pyo3(signature = (rendezvous_peer_id, namespace=None, limit=None))]
        fn rendezvous_discover(
            &self,
            rendezvous_peer_id: &str,
            namespace: Option<&str>,
            limit: Option<u64>,
        ) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::RendezvousDiscover {
                    namespace: Some(namespace.unwrap_or(ABS_RENDEZVOUS_NAMESPACE).to_string()),
                    rendezvous_peer: rendezvous_peer_id.to_string(),
                    limit,
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            let snap = match rx.blocking_recv() {
                Ok(Ok(v)) => v,
                Ok(Err(e)) => return Err(PyValueError::new_err(e)),
                Err(_) => return Err(PyRuntimeError::new_err("rendezvous_discover reply dropped")),
            };
            Python::with_gil(|py| {
                let d = pyo3::types::PyDict::new_bound(py);
                for (pid, addrs) in snap {
                    d.set_item(pid, addrs)?;
                }
                Ok(d.into())
            })
        }

        /// Unregister from a rendezvous peer (Slice X).
        #[pyo3(signature = (rendezvous_peer_id, namespace=None))]
        fn rendezvous_unregister(
            &self,
            rendezvous_peer_id: &str,
            namespace: Option<&str>,
        ) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::RendezvousUnregister {
                    namespace: namespace.unwrap_or(ABS_RENDEZVOUS_NAMESPACE).to_string(),
                    rendezvous_peer: rendezvous_peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "rendezvous_unregister reply dropped",
                )),
            }
        }

        /// Persist a bootstrap peer multiaddr (Slice O).
        fn bootstrap_add(&self, peer_id: &str, multiaddr: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BootstrapAdd {
                    peer_id: peer_id.to_string(),
                    multiaddr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("bootstrap_add reply dropped")),
            }
        }

        fn bootstrap_remove(&self, peer_id: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BootstrapRemove {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("bootstrap_remove reply dropped")),
            }
        }

        /// Return `{peer_id: [multiaddr, ...]}` from the bootstrap book.
        fn bootstrap_list(&self) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BootstrapList { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            let snap = rx
                .blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("bootstrap_list reply dropped"))?;
            Python::with_gil(|py| {
                let d = pyo3::types::PyDict::new_bound(py);
                for (pid, addrs) in snap {
                    d.set_item(pid, addrs)?;
                }
                Ok(d.into())
            })
        }

        /// Sequentially dial all persisted bootstrap multiaddrs and settle each
        /// (ok / fail / timeout / already_connected / budget / blocked) before return.
        fn bootstrap_dial(&self) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BootstrapDial { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(items)) => Python::with_gil(|py| {
                    let out = pyo3::types::PyList::empty_bound(py);
                    for (pid, status) in items {
                        let tup = pyo3::types::PyTuple::new_bound(
                            py,
                            &[pid.into_py(py), status.into_py(py)],
                        );
                        out.append(tup)?;
                    }
                    Ok(out.into())
                }),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("bootstrap_dial reply dropped")),
            }
        }

        /// Slice T: learned peerstore map peer_id → multiaddrs.
        fn peerstore_list(&self) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PeerstoreList { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            let snap = rx
                .blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("peerstore_list reply dropped"))?;
            Python::with_gil(|py| {
                let d = pyo3::types::PyDict::new_bound(py);
                for (pid, addrs) in snap {
                    d.set_item(pid, addrs)?;
                }
                Ok(d.into())
            })
        }

        fn peerstore_clear(&self) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PeerstoreClear { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("peerstore_clear reply dropped")),
            }
        }

        /// Slice T: industrial sequential dial of learned peerstore entries.
        fn peerstore_dial(&self) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PeerstoreDial { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(items)) => Python::with_gil(|py| {
                    let out = pyo3::types::PyList::empty_bound(py);
                    for (pid, status) in items {
                        let tup = pyo3::types::PyTuple::new_bound(
                            py,
                            &[pid.into_py(py), status.into_py(py)],
                        );
                        out.append(tup)?;
                    }
                    Ok(out.into())
                }),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("peerstore_dial reply dropped")),
            }
        }

        /// Enable/disable Slice P bootstrap reconnect policy.
        fn set_reconnect_enabled(&self, enabled: bool) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SetReconnectEnabled { enabled, reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("set_reconnect_enabled reply dropped"))?;
            Ok(())
        }

        /// Drop all connections to a peer (lab / policy testing).
        fn disconnect_peer(&self, peer_id: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::DisconnectPeer {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("disconnect_peer reply dropped")),
            }
        }

        /// Slice Q: gossipsub peer score, or None if unknown / scoring inactive.
        fn gossip_peer_score(&self, peer_id: &str) -> PyResult<Option<f64>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::GossipPeerScore {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("gossip_peer_score reply dropped"))
        }

        /// Slice Q: set application-specific gossip score for a peer.
        fn set_gossip_app_score(&self, peer_id: &str, score: f64) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SetGossipAppScore {
                    peer_id: peer_id.to_string(),
                    score,
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("set_gossip_app_score reply dropped"))
        }

        /// Slice Q: Accept/Reject/Ignore a gossip message id (validate_messages path).
        fn report_gossip_validation(
            &self,
            message_id: &str,
            peer_id: &str,
            acceptance: &str,
        ) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::ReportGossipValidation {
                    message_id: message_id.to_string(),
                    peer_id: peer_id.to_string(),
                    acceptance: acceptance.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(v)) => Ok(v),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "report_gossip_validation reply dropped",
                )),
            }
        }

        /// Slice R: enable/disable unhealthy ping disconnect + thresholds.
        fn set_ping_unhealthy_policy(
            &self,
            enabled: bool,
            max_fails: u32,
            max_rtt_ms: u64,
        ) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SetPingUnhealthyPolicy {
                    enabled,
                    max_fails,
                    max_rtt_ms,
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("set_ping_unhealthy_policy reply dropped"))?;
            Ok(())
        }

        /// Slice R: last successful ping RTT in milliseconds for a peer.
        fn last_ping_rtt_ms(&self, peer_id: &str) -> PyResult<Option<u64>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::LastPingRttMs {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("last_ping_rtt_ms reply dropped"))
        }

        /// Slice S: enable score→block sweep; peers at/below threshold are blocked.
        fn set_score_autoblock(&self, enabled: bool, graylist_threshold: f64) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SetScoreAutoblock {
                    enabled,
                    graylist_threshold,
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("set_score_autoblock reply dropped"))?;
            Ok(())
        }

        /// Send Absolute wire bytes over `/abs/wire/1.0.0`; returns response ack bytes.
        fn send_wire(&self, peer_id: &str, data: &[u8]) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SendWire {
                    peer_id: peer_id.to_string(),
                    data: data.to_vec(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(resp)) => Python::with_gil(|py| Ok(PyBytes::new_bound(py, &resp).into())),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("send_wire reply dropped")),
            }
        }

        /// Drain inbound wire messages as list of (peer_id, payload_bytes).
        fn poll_inbox(&self) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PollInbox { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            let items = rx
                .blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("poll_inbox reply dropped"))?;
            Python::with_gil(|py| {
                let out = pyo3::types::PyList::empty_bound(py);
                for (peer, data) in items {
                    let tup = pyo3::types::PyTuple::new_bound(
                        py,
                        &[peer.into_py(py), PyBytes::new_bound(py, &data).into_py(py)],
                    );
                    out.append(tup)?;
                }
                Ok(out.into())
            })
        }

        fn listen_addrs(&self) -> Vec<String> {
            self.state
                .lock()
                .map(|s| s.listen_addrs.clone())
                .unwrap_or_default()
        }

        /// Slice AG: confirmed external multiaddrs.
        fn external_addrs(&self) -> Vec<String> {
            self.state
                .lock()
                .map(|s| s.external_addrs.clone())
                .unwrap_or_default()
        }

        /// Slice AG: mark multiaddr as externally reachable.
        fn add_external_address(&self, multiaddr: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::AddExternalAddress {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "add_external_address reply dropped",
                )),
            }
        }

        /// Slice AG: expire a previously confirmed external multiaddr.
        fn remove_external_address(&self, multiaddr: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::RemoveExternalAddress {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "remove_external_address reply dropped",
                )),
            }
        }

        fn connected_peers(&self) -> Vec<String> {
            self.state
                .lock()
                .map(|s| {
                    let mut v: Vec<String> = s.connected.iter().cloned().collect();
                    v.sort();
                    v
                })
                .unwrap_or_default()
        }

        /// mDNS discoveries: dict peer_id -> multiaddr (Slice F).
        fn discovered_peers(&self) -> PyResult<PyObject> {
            Python::with_gil(|py| {
                let st = self
                    .state
                    .lock()
                    .map_err(|e| PyRuntimeError::new_err(format!("state lock poisoned: {e}")))?;
                let d = pyo3::types::PyDict::new_bound(py);
                for (peer, addr) in &st.discovered {
                    d.set_item(peer, addr)?;
                }
                Ok(d.into())
            })
        }

        /// Subscribe to a gossipsub topic (Slice E).
        fn subscribe(&self, topic: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::Subscribe {
                    topic: topic.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(fresh)) => Ok(fresh),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("subscribe reply dropped")),
            }
        }

        fn unsubscribe(&self, topic: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::Unsubscribe {
                    topic: topic.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(ok)) => Ok(ok),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("unsubscribe reply dropped")),
            }
        }

        /// Publish bytes on a gossipsub topic; returns message id string.
        fn publish(&self, topic: &str, data: &[u8]) -> PyResult<String> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::Publish {
                    topic: topic.to_string(),
                    data: data.to_vec(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(mid)) => Ok(mid),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("publish reply dropped")),
            }
        }

        /// Drain gossip messages as list of (peer_id, topic, payload_bytes).
        fn poll_gossip(&self) -> PyResult<PyObject> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PollGossip { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            let items = rx
                .blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("poll_gossip reply dropped"))?;
            Python::with_gil(|py| {
                let out = pyo3::types::PyList::empty_bound(py);
                for (peer, topic, data) in items {
                    let tup = pyo3::types::PyTuple::new_bound(
                        py,
                        &[
                            peer.into_py(py),
                            topic.into_py(py),
                            PyBytes::new_bound(py, &data).into_py(py),
                        ],
                    );
                    out.append(tup)?;
                }
                Ok(out.into())
            })
        }

        /// Slice AM: gossipsub mesh peers for a topic (PeerId strings).
        fn gossip_mesh_peers(&self, topic: &str) -> PyResult<Vec<String>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::GossipMeshPeers {
                    topic: topic.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("gossip_mesh_peers reply dropped"))
        }

        /// Slice AM: peers known subscribed to a topic (broader than mesh).
        fn gossip_topic_peers(&self, topic: &str) -> PyResult<Vec<String>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::GossipTopicPeers {
                    topic: topic.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            rx.blocking_recv()
                .map_err(|_| PyRuntimeError::new_err("gossip_topic_peers reply dropped"))
        }

        /// Add peer multiaddr into Kademlia routing table (Slice G).
        fn kad_add_address(&self, peer_id: &str, multiaddr: &str) -> PyResult<String> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::KadAddAddress {
                    peer_id: peer_id.to_string(),
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(s)) => Ok(s),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("kad_add_address reply dropped")),
            }
        }

        /// Iterative get_closest_peers; returns list of peer id strings.
        fn kad_get_closest_peers(&self, peer_id: &str) -> PyResult<Vec<String>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::KadGetClosest {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(peers)) => Ok(peers),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("kad_get_closest reply dropped")),
            }
        }

        /// Block a PeerId (Slice I allow/block-list). Closes existing connections.
        fn block_peer(&self, peer_id: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BlockPeer {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("block_peer reply dropped")),
            }
        }

        /// Remove PeerId from the block list (Slice I).
        fn unblock_peer(&self, peer_id: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::UnblockPeer {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("unblock_peer reply dropped")),
            }
        }

        /// Currently blocked PeerIds (Slice I).
        fn blocked_peers(&self) -> Vec<String> {
            self.state
                .lock()
                .map(|s| {
                    let mut v: Vec<String> = s.blocked.iter().cloned().collect();
                    v.sort();
                    v
                })
                .unwrap_or_default()
        }

        /// Allow a PeerId (Slice AE allow-list). Requires ``enable_allow_list=true``.
        fn allow_peer(&self, peer_id: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::AllowPeer {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("allow_peer reply dropped")),
            }
        }

        /// Remove PeerId from the allow-list (Slice AE). Closes existing connections.
        fn disallow_peer(&self, peer_id: &str) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::DisallowPeer {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(())) => Ok(()),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("disallow_peer reply dropped")),
            }
        }

        /// Currently allowed PeerIds (Slice AE). Empty when allow-list disabled.
        fn allowed_peers(&self) -> Vec<String> {
            self.state
                .lock()
                .map(|s| {
                    let mut v: Vec<String> = s.allowed.iter().cloned().collect();
                    v.sort();
                    v
                })
                .unwrap_or_default()
        }

        /// Identify snapshot for a peer (empty dict if not yet received).
        fn identify_info(&self, peer_id: &str) -> PyResult<PyObject> {
            Python::with_gil(|py| {
                let st = self
                    .state
                    .lock()
                    .map_err(|e| PyRuntimeError::new_err(format!("state lock poisoned: {e}")))?;
                let d = pyo3::types::PyDict::new_bound(py);
                if let Some(snap) = st.identify.get(peer_id) {
                    d.set_item("peer_id", peer_id)?;
                    d.set_item("protocol_version", &snap.protocol_version)?;
                    d.set_item("agent_version", &snap.agent_version)?;
                    d.set_item("listen_addrs", snap.listen_addrs.clone())?;
                    d.set_item("protocols", snap.protocols.clone())?;
                    d.set_item("observed_addr", &snap.observed_addr)?;
                    d.set_item("received", true)?;
                } else {
                    d.set_item("peer_id", peer_id)?;
                    d.set_item("received", false)?;
                }
                Ok(d.into())
            })
        }

        /// Metrics for /status / security status (ADR 0019).
        fn metrics(&self) -> PyResult<PyObject> {
            Python::with_gil(|py| {
                // Slice AF: prefer live BandwidthSinks; fall back to last sweep snapshot.
                let live = self
                    .bandwidth
                    .lock()
                    .ok()
                    .and_then(|g| g.as_ref().map(|s| (s.total_inbound(), s.total_outbound())));
                let st = self
                    .state
                    .lock()
                    .map_err(|e| PyRuntimeError::new_err(format!("state lock poisoned: {e}")))?;
                let (bytes_in, bytes_out) = live.unwrap_or((st.bytes_in, st.bytes_out));
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("libp2p_peers", st.connected.len())?;
                d.set_item("libp2p_dial_ok", st.dial_ok)?;
                d.set_item("libp2p_dial_fail", st.dial_fail)?;
                d.set_item("libp2p_dial_fail_transport", st.dial_fail_transport)?;
                d.set_item("libp2p_dial_fail_wrong_peer_id", st.dial_fail_wrong_peer_id)?;
                d.set_item("libp2p_dial_fail_no_addresses", st.dial_fail_no_addresses)?;
                d.set_item("libp2p_dial_fail_aborted", st.dial_fail_aborted)?;
                d.set_item("libp2p_dial_fail_local_peer_id", st.dial_fail_local_peer_id)?;
                d.set_item("libp2p_dial_fail_condition", st.dial_fail_condition)?;
                d.set_item("libp2p_dial_fail_denied", st.dial_fail_denied)?;
                d.set_item("libp2p_dial_fail_denied_block", st.dial_fail_denied_block)?;
                d.set_item("libp2p_dial_fail_denied_allow", st.dial_fail_denied_allow)?;
                d.set_item("libp2p_dial_fail_denied_limit", st.dial_fail_denied_limit)?;
                d.set_item("libp2p_dial_inflight", st.dial_inflight)?;
                d.set_item("libp2p_outbound_peers", st.outbound_peers.len())?;
                d.set_item("libp2p_dial_refused_budget", st.dial_refused_budget)?;
                d.set_item("libp2p_max_dials", st.max_dials)?;
                d.set_item("libp2p_dialing", st.dialing)?;
                d.set_item(
                    "libp2p_incoming_connection_error",
                    st.incoming_connection_error,
                )?;
                d.set_item("libp2p_incoming_fail_transport", st.incoming_fail_transport)?;
                d.set_item(
                    "libp2p_incoming_fail_wrong_peer_id",
                    st.incoming_fail_wrong_peer_id,
                )?;
                d.set_item("libp2p_incoming_fail_aborted", st.incoming_fail_aborted)?;
                d.set_item(
                    "libp2p_incoming_fail_local_peer_id",
                    st.incoming_fail_local_peer_id,
                )?;
                d.set_item("libp2p_incoming_fail_denied", st.incoming_fail_denied)?;
                d.set_item(
                    "libp2p_incoming_fail_denied_block",
                    st.incoming_fail_denied_block,
                )?;
                d.set_item(
                    "libp2p_incoming_fail_denied_allow",
                    st.incoming_fail_denied_allow,
                )?;
                d.set_item(
                    "libp2p_incoming_fail_denied_limit",
                    st.incoming_fail_denied_limit,
                )?;
                d.set_item("libp2p_peer_external_addr", st.peer_external_addr)?;
                d.set_item("libp2p_inbound_established", st.inbound_established)?;
                d.set_item("libp2p_incoming_connections", st.incoming_connections)?;
                d.set_item("libp2p_connection_closed", st.connection_closed)?;
                d.set_item("libp2p_connection_closed_local", st.connection_closed_local)?;
                d.set_item("libp2p_connection_closed_io", st.connection_closed_io)?;
                d.set_item(
                    "libp2p_connection_closed_keep_alive",
                    st.connection_closed_keep_alive,
                )?;
                d.set_item("libp2p_established_in_ms_last", st.established_in_ms_last)?;
                d.set_item("libp2p_established_in_ms_max", st.established_in_ms_max)?;
                d.set_item("libp2p_new_listen_addr", st.new_listen_addr)?;
                d.set_item("libp2p_expired_listen_addr", st.expired_listen_addr)?;
                d.set_item("libp2p_listener_closed", st.listener_closed)?;
                d.set_item("libp2p_listener_error", st.listener_error)?;
                d.set_item("libp2p_wire_sent", st.wire_sent)?;
                d.set_item("libp2p_wire_recv", st.wire_recv)?;
                d.set_item("libp2p_wire_outbound_failure", st.wire_outbound_failure)?;
                d.set_item("libp2p_wire_outbound_fail_dial", st.wire_outbound_fail_dial)?;
                d.set_item(
                    "libp2p_wire_outbound_fail_timeout",
                    st.wire_outbound_fail_timeout,
                )?;
                d.set_item(
                    "libp2p_wire_outbound_fail_connection_closed",
                    st.wire_outbound_fail_connection_closed,
                )?;
                d.set_item(
                    "libp2p_wire_outbound_fail_unsupported",
                    st.wire_outbound_fail_unsupported,
                )?;
                d.set_item("libp2p_wire_outbound_fail_io", st.wire_outbound_fail_io)?;
                d.set_item("libp2p_wire_inbound_failure", st.wire_inbound_failure)?;
                d.set_item(
                    "libp2p_wire_inbound_fail_timeout",
                    st.wire_inbound_fail_timeout,
                )?;
                d.set_item(
                    "libp2p_wire_inbound_fail_connection_closed",
                    st.wire_inbound_fail_connection_closed,
                )?;
                d.set_item(
                    "libp2p_wire_inbound_fail_unsupported",
                    st.wire_inbound_fail_unsupported,
                )?;
                d.set_item(
                    "libp2p_wire_inbound_fail_response_omission",
                    st.wire_inbound_fail_response_omission,
                )?;
                d.set_item("libp2p_wire_inbound_fail_io", st.wire_inbound_fail_io)?;
                d.set_item("libp2p_wire_response_sent", st.wire_response_sent)?;
                d.set_item("libp2p_wire_response_ok", st.wire_response_ok)?;
                d.set_item("libp2p_bytes_in", bytes_in)?;
                d.set_item("libp2p_bytes_out", bytes_out)?;
                d.set_item("libp2p_external_addrs", st.external_addrs.len())?;
                d.set_item("libp2p_external_addr_confirmed", st.external_addr_confirmed)?;
                d.set_item("libp2p_external_addr_expired", st.external_addr_expired)?;
                d.set_item(
                    "libp2p_external_addr_candidates",
                    st.external_addr_candidates,
                )?;
                d.set_item("libp2p_abs_wire_v1_sent", st.abs_wire_v1_sent)?;
                d.set_item("libp2p_abs_wire_v2_sent", st.abs_wire_v2_sent)?;
                d.set_item("libp2p_abs_wire_v1_recv", st.abs_wire_v1_recv)?;
                d.set_item("libp2p_abs_wire_v2_recv", st.abs_wire_v2_recv)?;
                d.set_item("libp2p_gossip_pub", st.gossip_pub)?;
                d.set_item("libp2p_gossip_recv", st.gossip_recv)?;
                d.set_item(
                    "libp2p_gossip_validation_accept",
                    st.gossip_validation_accept,
                )?;
                d.set_item(
                    "libp2p_gossip_validation_reject",
                    st.gossip_validation_reject,
                )?;
                d.set_item(
                    "libp2p_gossip_validation_ignore",
                    st.gossip_validation_ignore,
                )?;
                d.set_item(
                    "libp2p_gossip_validation_pending",
                    st.gossip_validation_pending,
                )?;
                d.set_item(
                    "libp2p_gossip_defer_validation",
                    st.enable_gossip_defer_validation,
                )?;
                d.set_item("libp2p_last_gossip_message_id", &st.last_gossip_message_id)?;
                d.set_item(
                    "libp2p_last_gossip_propagation_peer",
                    &st.last_gossip_propagation_peer,
                )?;
                d.set_item("libp2p_gossip_app_score_sets", st.gossip_app_score_sets)?;
                d.set_item("libp2p_gossip_not_supported", st.gossip_not_supported)?;
                d.set_item("libp2p_gossip_peer_subscribed", st.gossip_peer_subscribed)?;
                d.set_item(
                    "libp2p_gossip_peer_unsubscribed",
                    st.gossip_peer_unsubscribed,
                )?;
                d.set_item("libp2p_gossip_peer_score", true)?;
                d.set_item("libp2p_gossip_topics", st.subscribed.len())?;
                d.set_item("libp2p_identify_peers", st.identify.len())?;
                d.set_item("libp2p_identify_received", st.identify_received)?;
                d.set_item("libp2p_identify_sent", st.identify_sent)?;
                d.set_item("libp2p_identify_pushed", st.identify_pushed)?;
                d.set_item("libp2p_identify_error", st.identify_error)?;
                d.set_item("libp2p_mdns_discovered", st.mdns_discovered)?;
                d.set_item("libp2p_mdns_expired", st.mdns_expired)?;
                d.set_item("libp2p_mdns_ttl_secs", st.mdns_ttl_secs)?;
                d.set_item("libp2p_discovered_peers", st.discovered.len())?;
                d.set_item("libp2p_kad_peers", st.kad_peers.len())?;
                d.set_item("libp2p_kad_routing_updates", st.kad_routing_updates)?;
                d.set_item("libp2p_kad_queries", st.kad_queries)?;
                d.set_item("libp2p_kad_query_ok", st.kad_query_ok)?;
                d.set_item("libp2p_kad_query_fail", st.kad_query_fail)?;
                d.set_item("libp2p_kad_inbound_requests", st.kad_inbound_requests)?;
                d.set_item("libp2p_kad_unroutable_peer", st.kad_unroutable_peer)?;
                d.set_item("libp2p_kad_routable_peer", st.kad_routable_peer)?;
                d.set_item(
                    "libp2p_kad_pending_routable_peer",
                    st.kad_pending_routable_peer,
                )?;
                d.set_item("libp2p_kad_mode_changed", st.kad_mode_changed)?;
                d.set_item("libp2p_relay_reservations", st.relay_reservations)?;
                d.set_item("libp2p_relay_circuits", st.relay_circuits)?;
                d.set_item(
                    "libp2p_relay_reservation_denied",
                    st.relay_reservation_denied,
                )?;
                d.set_item(
                    "libp2p_relay_reservation_timed_out",
                    st.relay_reservation_timed_out,
                )?;
                d.set_item("libp2p_relay_circuit_denied", st.relay_circuit_denied)?;
                d.set_item("libp2p_relay_circuit_closed", st.relay_circuit_closed)?;
                d.set_item("libp2p_relay_inbound_circuit", st.relay_inbound_circuit)?;
                d.set_item("libp2p_relay_outbound_circuit", st.relay_outbound_circuit)?;
                d.set_item("libp2p_relay_max_reservations", st.relay_max_reservations)?;
                d.set_item("libp2p_autonat_probes", st.autonat_probes)?;
                d.set_item("libp2p_autonat_status_changes", st.autonat_status_changes)?;
                d.set_item("libp2p_autonat_inbound_probe", st.autonat_inbound_probe)?;
                d.set_item("libp2p_autonat_outbound_probe", st.autonat_outbound_probe)?;
                d.set_item(
                    "libp2p_autonat_inbound_probe_error",
                    st.autonat_inbound_probe_error,
                )?;
                d.set_item(
                    "libp2p_autonat_outbound_probe_error",
                    st.autonat_outbound_probe_error,
                )?;
                d.set_item("libp2p_autonat_status", st.autonat_status)?;
                d.set_item("libp2p_dcutr_upgrade_success", st.dcutr_upgrade_success)?;
                d.set_item("libp2p_dcutr_upgrade_fail", st.dcutr_upgrade_fail)?;
                d.set_item("libp2p_bootstrap_peers", st.bootstrap.len())?;
                d.set_item("libp2p_bootstrap_dials_ok", st.bootstrap_dials_ok)?;
                d.set_item("libp2p_bootstrap_dials_fail", st.bootstrap_dials_fail)?;
                d.set_item("libp2p_bootstrap_dials_timeout", st.bootstrap_dials_timeout)?;
                d.set_item(
                    "libp2p_bootstrap_dials_attempted",
                    st.bootstrap_dials_attempted,
                )?;
                d.set_item(
                    "libp2p_bootstrap_dial_timeout_secs",
                    st.bootstrap_dial_timeout_secs,
                )?;
                d.set_item("libp2p_peerstore_peers", st.peerstore.len())?;
                d.set_item("libp2p_peerstore_learned", st.peerstore_learned)?;
                d.set_item("libp2p_peerstore_dials_ok", st.peerstore_dials_ok)?;
                d.set_item("libp2p_peerstore_dials_fail", st.peerstore_dials_fail)?;
                d.set_item("libp2p_peerstore_dials_timeout", st.peerstore_dials_timeout)?;
                d.set_item(
                    "libp2p_peerstore_dials_attempted",
                    st.peerstore_dials_attempted,
                )?;
                d.set_item("libp2p_peerstore_path", &st.peerstore_path)?;
                d.set_item("libp2p_reconnect_enabled", st.enable_reconnect)?;
                d.set_item("libp2p_reconnect_scheduled", st.reconnect_scheduled)?;
                d.set_item("libp2p_reconnect_ok", st.reconnect_ok)?;
                d.set_item("libp2p_reconnect_fail", st.reconnect_fail)?;
                d.set_item("libp2p_reconnect_give_up", st.reconnect_give_up)?;
                d.set_item(
                    "libp2p_reconnect_from_peerstore",
                    st.reconnect_from_peerstore,
                )?;
                d.set_item("libp2p_ping_ok", st.ping_ok)?;
                d.set_item("libp2p_ping_fail", st.ping_fail)?;
                d.set_item("libp2p_ping_fail_timeout", st.ping_fail_timeout)?;
                d.set_item("libp2p_ping_fail_unsupported", st.ping_fail_unsupported)?;
                d.set_item("libp2p_ping_fail_other", st.ping_fail_other)?;
                d.set_item("libp2p_ping_interval_ms", st.ping_interval_ms)?;
                d.set_item("libp2p_ping_timeout_ms", st.ping_timeout_ms)?;
                d.set_item("libp2p_ping_rtt_ms_last", st.ping_rtt_ms_last)?;
                d.set_item("libp2p_ping_rtt_ms_max", st.ping_rtt_ms_max)?;
                d.set_item(
                    "libp2p_ping_unhealthy_disconnects",
                    st.ping_unhealthy_disconnects,
                )?;
                d.set_item(
                    "libp2p_ping_unhealthy_disconnect",
                    st.enable_ping_unhealthy_disconnect,
                )?;
                d.set_item("libp2p_ping_max_fails", st.ping_max_fails)?;
                d.set_item("libp2p_ping_max_rtt_ms", st.ping_max_rtt_ms)?;
                d.set_item("libp2p_score_autoblock", st.enable_score_autoblock)?;
                d.set_item(
                    "libp2p_score_graylist_threshold",
                    st.score_graylist_threshold,
                )?;
                d.set_item("libp2p_score_autoblocks", st.score_autoblocks)?;
                d.set_item("libp2p_score_sweep_ticks", st.score_sweep_ticks)?;
                d.set_item("libp2p_conn_limit_denied", st.conn_limit_denied)?;
                d.set_item("libp2p_block_denied", st.block_denied)?;
                d.set_item("libp2p_allow_denied", st.allow_denied)?;
                d.set_item("libp2p_blocked_peers", st.blocked.len())?;
                d.set_item("libp2p_allowed_peers", st.allowed.len())?;
                d.set_item("libp2p_circuit_addrs", st.circuit_addrs.len())?;
                d.set_item("libp2p_mdns_enabled", st.enable_mdns)?;
                d.set_item("libp2p_wire_timeout_secs", st.wire_timeout_secs)?;
                d.set_item(
                    "libp2p_idle_connection_timeout_secs",
                    st.idle_connection_timeout_secs,
                )?;
                d.set_item("libp2p_idle_timeout_closes", st.idle_timeout_closes)?;
                d.set_item("libp2p_ipv6_listens", st.ipv6_listens)?;
                d.set_item("libp2p_ipv6_dial_ok", st.ipv6_dial_ok)?;
                d.set_item("libp2p_rendezvous_registers", st.rendezvous_registers)?;
                d.set_item(
                    "libp2p_rendezvous_register_fail",
                    st.rendezvous_register_fail,
                )?;
                d.set_item("libp2p_rendezvous_discovers", st.rendezvous_discovers)?;
                d.set_item(
                    "libp2p_rendezvous_discovered_peers",
                    st.rendezvous_discovered_peers,
                )?;
                d.set_item(
                    "libp2p_rendezvous_discover_fail",
                    st.rendezvous_discover_fail,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_registrations",
                    st.rendezvous_server_registrations,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_unregistrations",
                    st.rendezvous_server_unregistrations,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_discover_served",
                    st.rendezvous_server_discover_served,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_discover_not_served",
                    st.rendezvous_server_discover_not_served,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_not_registered",
                    st.rendezvous_server_not_registered,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_registration_expired",
                    st.rendezvous_server_registration_expired,
                )?;
                d.set_item("libp2p_rendezvous_expired", st.rendezvous_expired)?;
                d.set_item("libp2p_dns_dial_ok", st.dns_dial_ok)?;
                d.set_item("libp2p_dns_dial_fail", st.dns_dial_fail)?;
                d.set_item("libp2p_quic_listens", st.quic_listens)?;
                d.set_item("libp2p_quic_dial_ok", st.quic_dial_ok)?;
                d.set_item("libp2p_quic_dial_fail", st.quic_dial_fail)?;
                d.set_item("libp2p_ws_listens", st.ws_listens)?;
                d.set_item("libp2p_ws_dial_ok", st.ws_dial_ok)?;
                d.set_item("libp2p_ws_dial_fail", st.ws_dial_fail)?;
                d.set_item("libp2p_upnp_external_addrs", st.upnp_external_addrs)?;
                d.set_item(
                    "libp2p_upnp_expired_external_addrs",
                    st.upnp_expired_external_addrs,
                )?;
                d.set_item("libp2p_upnp_gateway_not_found", st.upnp_gateway_not_found)?;
                d.set_item(
                    "libp2p_upnp_non_routable_gateway",
                    st.upnp_non_routable_gateway,
                )?;
                if let Some(n) = st.max_established_incoming {
                    d.set_item("libp2p_max_established_incoming", n)?;
                }
                if let Some(n) = st.max_established_outgoing {
                    d.set_item("libp2p_max_established_outgoing", n)?;
                }
                if let Some(n) = st.max_established {
                    d.set_item("libp2p_max_established", n)?;
                }
                if let Some(n) = st.max_established_per_peer {
                    d.set_item("libp2p_max_established_per_peer", n)?;
                }
                if let Some(n) = st.max_pending_incoming {
                    d.set_item("libp2p_max_pending_incoming", n)?;
                }
                if let Some(n) = st.max_pending_outgoing {
                    d.set_item("libp2p_max_pending_outgoing", n)?;
                }
                d.set_item(
                    "libp2p_connection_limits_updates",
                    st.connection_limits_updates,
                )?;
                d.set_item("libp2p_key_path", &st.key_path)?;
                d.set_item("libp2p_bootstrap_path", &st.bootstrap_path)?;
                d.set_item("libp2p_wire_protocol", ABS_WIRE_PROTOCOL)?;
                d.set_item("libp2p_gossip_blocks_topic", ABS_GOSSIP_BLOCKS_TOPIC)?;
                d.set_item("libp2p_kad_protocol", ABS_KAD_PROTOCOL)?;
                d.set_item("libp2p_rendezvous_namespace", ABS_RENDEZVOUS_NAMESPACE)?;
                d.set_item("peer_id", &self.peer_id)?;
                Ok(d.into())
            })
        }

        fn capability_status(&self) -> PyResult<PyObject> {
            Python::with_gil(|py| {
                let st = self
                    .state
                    .lock()
                    .map_err(|e| PyRuntimeError::new_err(format!("state lock poisoned: {e}")))?;
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("available", true)?;
                d.set_item("transport", "libp2p")?;
                d.set_item("phase", 52)?;
                d.set_item("noise", true)?;
                d.set_item("yamux", true)?;
                d.set_item("gossipsub", true)?;
                d.set_item("peer_score", true)?;
                d.set_item("score_autoblock", st.enable_score_autoblock)?;
                d.set_item("peerstore", !st.peerstore_path.is_empty())?;
                d.set_item("peerstore_reconnect", st.enable_reconnect)?;
                d.set_item("ping", true)?;
                d.set_item("ping_fail_events", true)?;
                d.set_item(
                    "ping_unhealthy_disconnect",
                    st.enable_ping_unhealthy_disconnect,
                )?;
                d.set_item("mdns", st.enable_mdns)?;
                d.set_item("mdns_events", true)?;
                d.set_item("kademlia", true)?;
                d.set_item("kad_events", true)?;
                d.set_item("relay", true)?;
                d.set_item("relay_events", true)?;
                d.set_item("relay_client_events", true)?;
                d.set_item("autonat", st.enable_autonat)?;
                d.set_item("autonat_events", true)?;
                d.set_item("upnp", st.enable_upnp)?;
                d.set_item("dcutr", true)?;
                d.set_item("rendezvous", true)?;
                d.set_item("rendezvous_events", true)?;
                d.set_item("dns", true)?;
                d.set_item("quic", true)?;
                d.set_item("websocket", true)?;
                d.set_item("prometheus", true)?;
                d.set_item("bandwidth", true)?;
                d.set_item("external_addrs", true)?;
                d.set_item("connection_lifecycle", true)?;
                d.set_item("connection_close_causes", true)?;
                d.set_item("listener_lifecycle", true)?;
                d.set_item("connection_attempts", true)?;
                d.set_item("dial_fail_events", true)?;
                d.set_item("dial_deny_events", true)?;
                d.set_item("deny_cause_events", true)?;
                d.set_item("incoming_fail_events", true)?;
                d.set_item("identify_events", true)?;
                d.set_item("gossip_subscription_events", true)?;
                d.set_item("gossip_validation_events", true)?;
                d.set_item("gossip_defer_validation", st.enable_gossip_defer_validation)?;
                d.set_item("wire_rr_events", true)?;
                d.set_item("wire_fail_events", true)?;
                d.set_item("connection_manager", true)?;
                d.set_item("bootstrap", true)?;
                d.set_item("reconnect", st.enable_reconnect)?;
                d.set_item("idle_connection_timeout", true)?;
                d.set_item("ipv6", true)?;
                d.set_item("connection_limits", true)?;
                d.set_item("block_list", true)?;
                d.set_item("allow_list", st.enable_allow_list)?;
                d.set_item("abs_wire_codecs", true)?;
                d.set_item("wire_timeout_secs", st.wire_timeout_secs)?;
                d.set_item(
                    "idle_connection_timeout_secs",
                    st.idle_connection_timeout_secs,
                )?;
                d.set_item(
                    "autonat_status",
                    match st.autonat_status {
                        1 => "public",
                        2 => "private",
                        _ => "unknown",
                    },
                )?;
                d.set_item("persistent_identity", !st.key_path.is_empty())?;
                d.set_item("persistent_bootstrap", !st.bootstrap_path.is_empty())?;
                d.set_item("bootstrap_path", &st.bootstrap_path)?;
                d.set_item("persistent_peerstore", !st.peerstore_path.is_empty())?;
                d.set_item("peerstore_path", &st.peerstore_path)?;
                d.set_item("peerstore_peers", st.peerstore.len())?;
                d.set_item("bootstrap_peers", st.bootstrap.len())?;
                d.set_item("wire_protocol", ABS_WIRE_PROTOCOL)?;
                d.set_item("gossip_blocks_topic", ABS_GOSSIP_BLOCKS_TOPIC)?;
                d.set_item("kad_protocol", ABS_KAD_PROTOCOL)?;
                d.set_item("peer_id", &self.peer_id)?;
                d.set_item("key_path", &st.key_path)?;
                d.set_item("listen_addrs", st.listen_addrs.clone())?;
                d.set_item("circuit_addrs", st.circuit_addrs.clone())?;
                d.set_item("external_addrs", st.external_addrs.clone())?;
                d.set_item("connected", st.connected.len())?;
                d.set_item("libp2p_peers", st.connected.len())?;
                d.set_item("libp2p_dial_ok", st.dial_ok)?;
                d.set_item("libp2p_dial_fail", st.dial_fail)?;
                d.set_item("libp2p_dial_fail_transport", st.dial_fail_transport)?;
                d.set_item("libp2p_dial_fail_wrong_peer_id", st.dial_fail_wrong_peer_id)?;
                d.set_item("libp2p_dial_fail_no_addresses", st.dial_fail_no_addresses)?;
                d.set_item("libp2p_dial_fail_aborted", st.dial_fail_aborted)?;
                d.set_item("libp2p_dial_fail_local_peer_id", st.dial_fail_local_peer_id)?;
                d.set_item("libp2p_dial_fail_condition", st.dial_fail_condition)?;
                d.set_item("libp2p_dial_fail_denied", st.dial_fail_denied)?;
                d.set_item("libp2p_dial_fail_denied_block", st.dial_fail_denied_block)?;
                d.set_item("libp2p_dial_fail_denied_allow", st.dial_fail_denied_allow)?;
                d.set_item("libp2p_dial_fail_denied_limit", st.dial_fail_denied_limit)?;
                d.set_item("libp2p_dialing", st.dialing)?;
                d.set_item(
                    "libp2p_incoming_connection_error",
                    st.incoming_connection_error,
                )?;
                d.set_item("libp2p_incoming_fail_transport", st.incoming_fail_transport)?;
                d.set_item(
                    "libp2p_incoming_fail_wrong_peer_id",
                    st.incoming_fail_wrong_peer_id,
                )?;
                d.set_item("libp2p_incoming_fail_aborted", st.incoming_fail_aborted)?;
                d.set_item(
                    "libp2p_incoming_fail_local_peer_id",
                    st.incoming_fail_local_peer_id,
                )?;
                d.set_item("libp2p_incoming_fail_denied", st.incoming_fail_denied)?;
                d.set_item(
                    "libp2p_incoming_fail_denied_block",
                    st.incoming_fail_denied_block,
                )?;
                d.set_item(
                    "libp2p_incoming_fail_denied_allow",
                    st.incoming_fail_denied_allow,
                )?;
                d.set_item(
                    "libp2p_incoming_fail_denied_limit",
                    st.incoming_fail_denied_limit,
                )?;
                d.set_item("libp2p_peer_external_addr", st.peer_external_addr)?;
                d.set_item("libp2p_wire_sent", st.wire_sent)?;
                d.set_item("libp2p_wire_recv", st.wire_recv)?;
                d.set_item("libp2p_wire_outbound_failure", st.wire_outbound_failure)?;
                d.set_item("libp2p_wire_outbound_fail_dial", st.wire_outbound_fail_dial)?;
                d.set_item(
                    "libp2p_wire_outbound_fail_timeout",
                    st.wire_outbound_fail_timeout,
                )?;
                d.set_item(
                    "libp2p_wire_outbound_fail_connection_closed",
                    st.wire_outbound_fail_connection_closed,
                )?;
                d.set_item(
                    "libp2p_wire_outbound_fail_unsupported",
                    st.wire_outbound_fail_unsupported,
                )?;
                d.set_item("libp2p_wire_outbound_fail_io", st.wire_outbound_fail_io)?;
                d.set_item("libp2p_wire_inbound_failure", st.wire_inbound_failure)?;
                d.set_item(
                    "libp2p_wire_inbound_fail_timeout",
                    st.wire_inbound_fail_timeout,
                )?;
                d.set_item(
                    "libp2p_wire_inbound_fail_connection_closed",
                    st.wire_inbound_fail_connection_closed,
                )?;
                d.set_item(
                    "libp2p_wire_inbound_fail_unsupported",
                    st.wire_inbound_fail_unsupported,
                )?;
                d.set_item(
                    "libp2p_wire_inbound_fail_response_omission",
                    st.wire_inbound_fail_response_omission,
                )?;
                d.set_item("libp2p_wire_inbound_fail_io", st.wire_inbound_fail_io)?;
                d.set_item("libp2p_wire_response_sent", st.wire_response_sent)?;
                d.set_item("libp2p_wire_response_ok", st.wire_response_ok)?;
                d.set_item("libp2p_inbound_established", st.inbound_established)?;
                d.set_item("libp2p_incoming_connections", st.incoming_connections)?;
                d.set_item("libp2p_connection_closed", st.connection_closed)?;
                d.set_item("libp2p_connection_closed_local", st.connection_closed_local)?;
                d.set_item("libp2p_connection_closed_io", st.connection_closed_io)?;
                d.set_item(
                    "libp2p_connection_closed_keep_alive",
                    st.connection_closed_keep_alive,
                )?;
                d.set_item("libp2p_established_in_ms_last", st.established_in_ms_last)?;
                d.set_item("libp2p_established_in_ms_max", st.established_in_ms_max)?;
                d.set_item("libp2p_new_listen_addr", st.new_listen_addr)?;
                d.set_item("libp2p_expired_listen_addr", st.expired_listen_addr)?;
                d.set_item("libp2p_listener_closed", st.listener_closed)?;
                d.set_item("libp2p_listener_error", st.listener_error)?;
                d.set_item("libp2p_bytes_in", st.bytes_in)?;
                d.set_item("libp2p_bytes_out", st.bytes_out)?;
                d.set_item("libp2p_external_addrs", st.external_addrs.len())?;
                d.set_item("libp2p_external_addr_confirmed", st.external_addr_confirmed)?;
                d.set_item("libp2p_external_addr_expired", st.external_addr_expired)?;
                d.set_item(
                    "libp2p_external_addr_candidates",
                    st.external_addr_candidates,
                )?;
                d.set_item("libp2p_abs_wire_v1_sent", st.abs_wire_v1_sent)?;
                d.set_item("libp2p_abs_wire_v2_sent", st.abs_wire_v2_sent)?;
                d.set_item("libp2p_abs_wire_v1_recv", st.abs_wire_v1_recv)?;
                d.set_item("libp2p_abs_wire_v2_recv", st.abs_wire_v2_recv)?;
                d.set_item("libp2p_gossip_pub", st.gossip_pub)?;
                d.set_item("libp2p_gossip_recv", st.gossip_recv)?;
                d.set_item(
                    "libp2p_gossip_validation_accept",
                    st.gossip_validation_accept,
                )?;
                d.set_item(
                    "libp2p_gossip_validation_reject",
                    st.gossip_validation_reject,
                )?;
                d.set_item(
                    "libp2p_gossip_validation_ignore",
                    st.gossip_validation_ignore,
                )?;
                d.set_item(
                    "libp2p_gossip_validation_pending",
                    st.gossip_validation_pending,
                )?;
                d.set_item(
                    "libp2p_gossip_defer_validation",
                    st.enable_gossip_defer_validation,
                )?;
                d.set_item("libp2p_last_gossip_message_id", &st.last_gossip_message_id)?;
                d.set_item(
                    "libp2p_last_gossip_propagation_peer",
                    &st.last_gossip_propagation_peer,
                )?;
                d.set_item("libp2p_gossip_app_score_sets", st.gossip_app_score_sets)?;
                d.set_item("libp2p_gossip_not_supported", st.gossip_not_supported)?;
                d.set_item("libp2p_gossip_peer_subscribed", st.gossip_peer_subscribed)?;
                d.set_item(
                    "libp2p_gossip_peer_unsubscribed",
                    st.gossip_peer_unsubscribed,
                )?;
                d.set_item("libp2p_gossip_peer_score", true)?;
                d.set_item("libp2p_identify_peers", st.identify.len())?;
                d.set_item("libp2p_identify_received", st.identify_received)?;
                d.set_item("libp2p_identify_sent", st.identify_sent)?;
                d.set_item("libp2p_identify_pushed", st.identify_pushed)?;
                d.set_item("libp2p_identify_error", st.identify_error)?;
                d.set_item("libp2p_mdns_discovered", st.mdns_discovered)?;
                d.set_item("libp2p_mdns_expired", st.mdns_expired)?;
                d.set_item("libp2p_mdns_ttl_secs", st.mdns_ttl_secs)?;
                d.set_item("libp2p_kad_peers", st.kad_peers.len())?;
                d.set_item("libp2p_kad_routing_updates", st.kad_routing_updates)?;
                d.set_item("libp2p_kad_queries", st.kad_queries)?;
                d.set_item("libp2p_kad_query_ok", st.kad_query_ok)?;
                d.set_item("libp2p_kad_query_fail", st.kad_query_fail)?;
                d.set_item("libp2p_kad_inbound_requests", st.kad_inbound_requests)?;
                d.set_item("libp2p_kad_unroutable_peer", st.kad_unroutable_peer)?;
                d.set_item("libp2p_kad_routable_peer", st.kad_routable_peer)?;
                d.set_item(
                    "libp2p_kad_pending_routable_peer",
                    st.kad_pending_routable_peer,
                )?;
                d.set_item("libp2p_kad_mode_changed", st.kad_mode_changed)?;
                d.set_item("libp2p_relay_reservations", st.relay_reservations)?;
                d.set_item("libp2p_relay_circuits", st.relay_circuits)?;
                d.set_item(
                    "libp2p_relay_reservation_denied",
                    st.relay_reservation_denied,
                )?;
                d.set_item(
                    "libp2p_relay_reservation_timed_out",
                    st.relay_reservation_timed_out,
                )?;
                d.set_item("libp2p_relay_circuit_denied", st.relay_circuit_denied)?;
                d.set_item("libp2p_relay_circuit_closed", st.relay_circuit_closed)?;
                d.set_item("libp2p_relay_inbound_circuit", st.relay_inbound_circuit)?;
                d.set_item("libp2p_relay_outbound_circuit", st.relay_outbound_circuit)?;
                d.set_item("libp2p_relay_max_reservations", st.relay_max_reservations)?;
                d.set_item("libp2p_autonat_probes", st.autonat_probes)?;
                d.set_item("libp2p_autonat_status_changes", st.autonat_status_changes)?;
                d.set_item("libp2p_autonat_inbound_probe", st.autonat_inbound_probe)?;
                d.set_item("libp2p_autonat_outbound_probe", st.autonat_outbound_probe)?;
                d.set_item(
                    "libp2p_autonat_inbound_probe_error",
                    st.autonat_inbound_probe_error,
                )?;
                d.set_item(
                    "libp2p_autonat_outbound_probe_error",
                    st.autonat_outbound_probe_error,
                )?;
                d.set_item("libp2p_dcutr_upgrade_success", st.dcutr_upgrade_success)?;
                d.set_item("libp2p_dcutr_upgrade_fail", st.dcutr_upgrade_fail)?;
                d.set_item("libp2p_bootstrap_peers", st.bootstrap.len())?;
                d.set_item("libp2p_bootstrap_dials_ok", st.bootstrap_dials_ok)?;
                d.set_item("libp2p_bootstrap_dials_fail", st.bootstrap_dials_fail)?;
                d.set_item("libp2p_bootstrap_dials_timeout", st.bootstrap_dials_timeout)?;
                d.set_item(
                    "libp2p_bootstrap_dials_attempted",
                    st.bootstrap_dials_attempted,
                )?;
                d.set_item("libp2p_peerstore_peers", st.peerstore.len())?;
                d.set_item("libp2p_peerstore_learned", st.peerstore_learned)?;
                d.set_item("libp2p_peerstore_dials_ok", st.peerstore_dials_ok)?;
                d.set_item("libp2p_peerstore_dials_fail", st.peerstore_dials_fail)?;
                d.set_item("libp2p_peerstore_dials_timeout", st.peerstore_dials_timeout)?;
                d.set_item(
                    "libp2p_peerstore_dials_attempted",
                    st.peerstore_dials_attempted,
                )?;
                d.set_item("libp2p_reconnect_enabled", st.enable_reconnect)?;
                d.set_item("libp2p_reconnect_scheduled", st.reconnect_scheduled)?;
                d.set_item("libp2p_reconnect_ok", st.reconnect_ok)?;
                d.set_item("libp2p_reconnect_fail", st.reconnect_fail)?;
                d.set_item("libp2p_reconnect_give_up", st.reconnect_give_up)?;
                d.set_item(
                    "libp2p_reconnect_from_peerstore",
                    st.reconnect_from_peerstore,
                )?;
                d.set_item("libp2p_ping_ok", st.ping_ok)?;
                d.set_item("libp2p_ping_fail", st.ping_fail)?;
                d.set_item("libp2p_ping_fail_timeout", st.ping_fail_timeout)?;
                d.set_item("libp2p_ping_fail_unsupported", st.ping_fail_unsupported)?;
                d.set_item("libp2p_ping_fail_other", st.ping_fail_other)?;
                d.set_item("libp2p_ping_interval_ms", st.ping_interval_ms)?;
                d.set_item("libp2p_ping_timeout_ms", st.ping_timeout_ms)?;
                d.set_item("libp2p_ping_rtt_ms_last", st.ping_rtt_ms_last)?;
                d.set_item("libp2p_ping_rtt_ms_max", st.ping_rtt_ms_max)?;
                d.set_item(
                    "libp2p_ping_unhealthy_disconnects",
                    st.ping_unhealthy_disconnects,
                )?;
                d.set_item(
                    "libp2p_ping_unhealthy_disconnect",
                    st.enable_ping_unhealthy_disconnect,
                )?;
                d.set_item("libp2p_ping_max_fails", st.ping_max_fails)?;
                d.set_item("libp2p_ping_max_rtt_ms", st.ping_max_rtt_ms)?;
                d.set_item("libp2p_score_autoblock", st.enable_score_autoblock)?;
                d.set_item(
                    "libp2p_score_graylist_threshold",
                    st.score_graylist_threshold,
                )?;
                d.set_item("libp2p_score_autoblocks", st.score_autoblocks)?;
                d.set_item("libp2p_score_sweep_ticks", st.score_sweep_ticks)?;
                d.set_item("libp2p_conn_limit_denied", st.conn_limit_denied)?;
                d.set_item("libp2p_block_denied", st.block_denied)?;
                d.set_item("libp2p_allow_denied", st.allow_denied)?;
                d.set_item("libp2p_blocked_peers", st.blocked.len())?;
                d.set_item("libp2p_allowed_peers", st.allowed.len())?;
                d.set_item(
                    "libp2p_idle_connection_timeout_secs",
                    st.idle_connection_timeout_secs,
                )?;
                d.set_item("libp2p_idle_timeout_closes", st.idle_timeout_closes)?;
                d.set_item("libp2p_ipv6_listens", st.ipv6_listens)?;
                d.set_item("libp2p_ipv6_dial_ok", st.ipv6_dial_ok)?;
                d.set_item("libp2p_rendezvous_registers", st.rendezvous_registers)?;
                d.set_item(
                    "libp2p_rendezvous_register_fail",
                    st.rendezvous_register_fail,
                )?;
                d.set_item("libp2p_rendezvous_discovers", st.rendezvous_discovers)?;
                d.set_item(
                    "libp2p_rendezvous_discovered_peers",
                    st.rendezvous_discovered_peers,
                )?;
                d.set_item(
                    "libp2p_rendezvous_discover_fail",
                    st.rendezvous_discover_fail,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_registrations",
                    st.rendezvous_server_registrations,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_unregistrations",
                    st.rendezvous_server_unregistrations,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_discover_served",
                    st.rendezvous_server_discover_served,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_discover_not_served",
                    st.rendezvous_server_discover_not_served,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_not_registered",
                    st.rendezvous_server_not_registered,
                )?;
                d.set_item(
                    "libp2p_rendezvous_server_registration_expired",
                    st.rendezvous_server_registration_expired,
                )?;
                d.set_item("libp2p_rendezvous_expired", st.rendezvous_expired)?;
                d.set_item("libp2p_dns_dial_ok", st.dns_dial_ok)?;
                d.set_item("libp2p_dns_dial_fail", st.dns_dial_fail)?;
                d.set_item("libp2p_quic_listens", st.quic_listens)?;
                d.set_item("libp2p_quic_dial_ok", st.quic_dial_ok)?;
                d.set_item("libp2p_quic_dial_fail", st.quic_dial_fail)?;
                d.set_item("libp2p_ws_listens", st.ws_listens)?;
                d.set_item("libp2p_ws_dial_ok", st.ws_dial_ok)?;
                d.set_item("libp2p_ws_dial_fail", st.ws_dial_fail)?;
                d.set_item("libp2p_upnp_external_addrs", st.upnp_external_addrs)?;
                d.set_item(
                    "libp2p_upnp_expired_external_addrs",
                    st.upnp_expired_external_addrs,
                )?;
                d.set_item("libp2p_upnp_gateway_not_found", st.upnp_gateway_not_found)?;
                d.set_item(
                    "libp2p_upnp_non_routable_gateway",
                    st.upnp_non_routable_gateway,
                )?;
                d.set_item(
                    "libp2p_connection_limits_updates",
                    st.connection_limits_updates,
                )?;
                d.set_item("default_mesh", false)?;
                d.set_item("honesty", "ADR0019_rust_libp2p_lab_not_prod_mesh")?;
                d.set_item("error", st.last_error.clone())?;
                Ok(d.into())
            })
        }

        fn close(&self) -> PyResult<()> {
            let (tx, rx) = oneshot::channel();
            let _ = self.cmd_tx.send(Cmd::Shutdown { reply: tx });
            let _ = rx.blocking_recv();
            Ok(())
        }
    }

    fn resolve_enable_mdns(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_MDNS") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                !matches!(t.as_str(), "0" | "false" | "off" | "no")
            }
            Err(_) => true,
        }
    }

    fn resolve_mdns_ttl_secs(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_MDNS_TTL_SECS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_MDNS_TTL_SECS)
                .max(1),
            Err(_) => DEFAULT_MDNS_TTL_SECS,
        }
    }

    /// AutoNAT default off — probe dials interfere with reconnect labs (Slice U).
    fn resolve_enable_autonat(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_AUTONAT") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    /// UPnP default off — needs IGD; CI/labs without gateway expect GatewayNotFound (Slice AD).
    fn resolve_enable_upnp(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_UPNP") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    /// Allow-list default off — empty set denies all peers (Slice AE).
    fn resolve_enable_allow_list(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_ALLOW_LIST") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    /// Slice AA: optional u32 limit; ``0`` / empty env = unlimited (None).
    fn resolve_u32_limit(explicit: Option<u32>, env_key: &str) -> Option<u32> {
        if let Some(v) = explicit {
            return if v == 0 { None } else { Some(v) };
        }
        match std::env::var(env_key) {
            Ok(s) => {
                let t = s.trim();
                if t.is_empty() {
                    return None;
                }
                let lower = t.to_ascii_lowercase();
                if matches!(lower.as_str(), "0" | "none" | "off" | "unlimited") {
                    return None;
                }
                t.parse::<u32>().ok().filter(|n| *n > 0)
            }
            Err(_) => None,
        }
    }

    fn resolve_wire_timeout_secs(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_WIRE_TIMEOUT_SECS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_WIRE_TIMEOUT_SECS)
                .max(1),
            Err(_) => DEFAULT_WIRE_TIMEOUT_SECS,
        }
    }

    fn resolve_idle_connection_timeout_secs(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_IDLE_CONNECTION_TIMEOUT_SECS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_IDLE_CONNECTION_TIMEOUT_SECS)
                .max(1),
            Err(_) => DEFAULT_IDLE_CONNECTION_TIMEOUT_SECS,
        }
    }

    fn resolve_bootstrap_path(explicit: Option<String>) -> Option<String> {
        if let Some(p) = explicit {
            let t = p.trim().to_string();
            if !t.is_empty() {
                return Some(t);
            }
        }
        match std::env::var("ABS_LIBP2P_BOOTSTRAP_PATH") {
            Ok(s) => {
                let t = s.trim().to_string();
                if t.is_empty() {
                    None
                } else {
                    Some(t)
                }
            }
            Err(_) => None,
        }
    }

    fn resolve_peerstore_path(explicit: Option<String>) -> Option<String> {
        if let Some(p) = explicit {
            let t = p.trim().to_string();
            if !t.is_empty() {
                return Some(t);
            }
        }
        match std::env::var("ABS_LIBP2P_PEERSTORE_PATH") {
            Ok(s) => {
                let t = s.trim().to_string();
                if t.is_empty() {
                    None
                } else {
                    Some(t)
                }
            }
            Err(_) => None,
        }
    }

    fn resolve_bootstrap_dial_timeout_secs(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_BOOTSTRAP_DIAL_TIMEOUT_SECS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_BOOTSTRAP_DIAL_TIMEOUT_SECS)
                .max(1),
            Err(_) => DEFAULT_BOOTSTRAP_DIAL_TIMEOUT_SECS,
        }
    }

    fn resolve_enable_reconnect(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_RECONNECT") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                !matches!(t.as_str(), "0" | "false" | "off" | "no")
            }
            // Default on: industrial bootstrap mesh expects auto-redial.
            Err(_) => true,
        }
    }

    fn resolve_ping_interval_secs(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_PING_INTERVAL_SECS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_PING_INTERVAL_SECS)
                .max(1),
            Err(_) => DEFAULT_PING_INTERVAL_SECS,
        }
    }

    fn resolve_ping_timeout_secs(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_PING_TIMEOUT_SECS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_PING_TIMEOUT_SECS)
                .max(1),
            Err(_) => DEFAULT_PING_TIMEOUT_SECS,
        }
    }

    /// Slice AY: lab-friendly ms override via ``ABS_LIBP2P_PING_INTERVAL_MS``.
    fn resolve_ping_interval() -> Duration {
        if let Ok(s) = std::env::var("ABS_LIBP2P_PING_INTERVAL_MS") {
            if let Ok(ms) = s.trim().parse::<u64>() {
                return Duration::from_millis(ms.max(1));
            }
        }
        Duration::from_secs(resolve_ping_interval_secs(None))
    }

    /// Slice AY: lab-friendly ms override via ``ABS_LIBP2P_PING_TIMEOUT_MS``.
    /// ``0`` keeps ``Duration::ZERO`` so labs can force ``Failure::Timeout``.
    fn resolve_ping_timeout() -> Duration {
        if let Ok(s) = std::env::var("ABS_LIBP2P_PING_TIMEOUT_MS") {
            if let Ok(ms) = s.trim().parse::<u64>() {
                return Duration::from_millis(ms);
            }
        }
        Duration::from_secs(resolve_ping_timeout_secs(None))
    }

    fn resolve_ping_unhealthy_disconnect(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_PING_UNHEALTHY_DISCONNECT") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                !matches!(t.as_str(), "0" | "false" | "off" | "no")
            }
            Err(_) => true,
        }
    }

    fn resolve_ping_max_fails(explicit: Option<u32>) -> u32 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_PING_MAX_FAILS") {
            Ok(s) => s
                .trim()
                .parse::<u32>()
                .ok()
                .unwrap_or(DEFAULT_PING_MAX_FAILS)
                .max(1),
            Err(_) => DEFAULT_PING_MAX_FAILS,
        }
    }

    fn resolve_ping_max_rtt_ms(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_PING_MAX_RTT_MS") {
            Ok(s) => s.trim().parse::<u64>().ok().unwrap_or(0),
            Err(_) => 0,
        }
    }

    /// Slice BA: defer gossip Accept until ``report_gossip_validation``.
    fn resolve_gossip_defer_validation(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_GOSSIP_DEFER_VALIDATION") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    fn resolve_score_autoblock(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_SCORE_AUTOBLOCK") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            // Default off so Slice Q labs are not surprise-blocked.
            Err(_) => false,
        }
    }

    fn resolve_score_graylist_threshold(explicit: Option<f64>) -> f64 {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_SCORE_GRAYLIST_THRESHOLD") {
            Ok(s) => s
                .trim()
                .parse::<f64>()
                .ok()
                .unwrap_or(DEFAULT_SCORE_GRAYLIST_THRESHOLD),
            Err(_) => DEFAULT_SCORE_GRAYLIST_THRESHOLD,
        }
    }

    #[pyfunction]
    #[pyo3(signature = (
        max_dials = DEFAULT_MAX_DIALS,
        key_path = None,
        max_established_incoming = None,
        max_established_outgoing = None,
        max_established = None,
        max_established_per_peer = None,
        max_pending_incoming = None,
        max_pending_outgoing = None,
        enable_mdns = None,
        wire_timeout_secs = None,
        bootstrap_path = None,
        enable_reconnect = None,
        peerstore_path = None,
        enable_autonat = None,
        enable_upnp = None,
        enable_allow_list = None,
        idle_connection_timeout_secs = None,
        relay_max_reservations = None,
        mdns_ttl_secs = None
    ))]
    fn libp2p_node_new(
        max_dials: u32,
        key_path: Option<String>,
        max_established_incoming: Option<u32>,
        max_established_outgoing: Option<u32>,
        max_established: Option<u32>,
        max_established_per_peer: Option<u32>,
        max_pending_incoming: Option<u32>,
        max_pending_outgoing: Option<u32>,
        enable_mdns: Option<bool>,
        wire_timeout_secs: Option<u64>,
        bootstrap_path: Option<String>,
        enable_reconnect: Option<bool>,
        peerstore_path: Option<String>,
        enable_autonat: Option<bool>,
        enable_upnp: Option<bool>,
        enable_allow_list: Option<bool>,
        idle_connection_timeout_secs: Option<u64>,
        relay_max_reservations: Option<u32>,
        mdns_ttl_secs: Option<u64>,
    ) -> PyResult<Libp2pNode> {
        Libp2pNode::spawn(
            max_dials,
            key_path,
            resolve_u32_limit(
                max_established_incoming,
                "ABS_LIBP2P_MAX_ESTABLISHED_INCOMING",
            ),
            resolve_u32_limit(
                max_established_outgoing,
                "ABS_LIBP2P_MAX_ESTABLISHED_OUTGOING",
            ),
            resolve_u32_limit(max_established, "ABS_LIBP2P_MAX_ESTABLISHED"),
            resolve_u32_limit(
                max_established_per_peer,
                "ABS_LIBP2P_MAX_ESTABLISHED_PER_PEER",
            ),
            resolve_u32_limit(max_pending_incoming, "ABS_LIBP2P_MAX_PENDING_INCOMING"),
            resolve_u32_limit(max_pending_outgoing, "ABS_LIBP2P_MAX_PENDING_OUTGOING"),
            resolve_enable_mdns(enable_mdns),
            resolve_wire_timeout_secs(wire_timeout_secs),
            resolve_bootstrap_path(bootstrap_path),
            resolve_enable_reconnect(enable_reconnect),
            resolve_peerstore_path(peerstore_path),
            resolve_enable_autonat(enable_autonat),
            resolve_enable_upnp(enable_upnp),
            resolve_enable_allow_list(enable_allow_list),
            resolve_idle_connection_timeout_secs(idle_connection_timeout_secs),
            resolve_u32_limit(relay_max_reservations, "ABS_LIBP2P_RELAY_MAX_RESERVATIONS"),
            resolve_mdns_ttl_secs(mdns_ttl_secs),
        )
    }

    /// Classify Absolute ADR 0008 codec on `/abs/wire` payload (Slice M).
    #[pyfunction]
    fn libp2p_classify_abs_wire(data: &[u8]) -> &'static str {
        super::classify_abs_wire_codec(data)
    }

    /// Encode a minimal Absolute lab wire frame: msg_type\\0 + payload.
    /// Slice B lab helper; Absolute ADR 0008 v1/v2 uses wire_bridge / encode_p2p_wire (Slice M).
    #[pyfunction]
    fn libp2p_pack_wire(msg_type: &str, payload: &[u8]) -> PyResult<PyObject> {
        let mut out = Vec::with_capacity(msg_type.len() + 1 + payload.len());
        out.extend_from_slice(msg_type.as_bytes());
        out.push(0);
        out.extend_from_slice(payload);
        Python::with_gil(|py| Ok(PyBytes::new_bound(py, &out).into()))
    }

    #[pyfunction]
    fn libp2p_unpack_wire(data: &[u8]) -> PyResult<(String, PyObject)> {
        let pos = data
            .iter()
            .position(|b| *b == 0)
            .ok_or_else(|| PyValueError::new_err("missing msg_type separator"))?;
        let msg_type = std::str::from_utf8(&data[..pos])
            .map_err(|e| PyValueError::new_err(format!("msg_type utf8: {e}")))?
            .to_string();
        let payload = &data[pos + 1..];
        Python::with_gil(|py| Ok((msg_type, PyBytes::new_bound(py, payload).into())))
    }

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(libp2p_available, m)?)?;
        m.add_class::<Libp2pNode>()?;
        m.add_function(wrap_pyfunction!(libp2p_node_new, m)?)?;
        m.add_function(wrap_pyfunction!(libp2p_classify_abs_wire, m)?)?;
        m.add_function(wrap_pyfunction!(libp2p_pack_wire, m)?)?;
        m.add_function(wrap_pyfunction!(libp2p_unpack_wire, m)?)?;
        m.add("ABS_WIRE_PROTOCOL", ABS_WIRE_PROTOCOL)?;
        m.add("ABS_GOSSIP_BLOCKS_TOPIC", ABS_GOSSIP_BLOCKS_TOPIC)?;
        m.add("ABS_KAD_PROTOCOL", ABS_KAD_PROTOCOL)?;
        m.add("ABS_RENDEZVOUS_NAMESPACE", ABS_RENDEZVOUS_NAMESPACE)?;
        Ok(())
    }
}

#[cfg(feature = "libp2p")]
pub use enabled::register;

#[cfg(test)]
mod tests {
    use super::classify_abs_wire_codec;

    #[test]
    fn classify_v1_ndjson() {
        assert_eq!(classify_abs_wire_codec(b"{\"type\":\"ping\"}\n"), "v1");
    }

    #[test]
    fn classify_v2_ab2() {
        assert_eq!(classify_abs_wire_codec(b"AB2:deadbeef\n"), "v2");
    }

    #[test]
    fn classify_lab_pack() {
        assert_eq!(classify_abs_wire_codec(b"ping\0slice-b"), "lab");
    }
}
