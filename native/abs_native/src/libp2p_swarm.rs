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
/// Default max concurrent outbound dials (Slice C).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_MAX_DIALS: u32 = 32;
/// Max wire / gossip payload bytes (lab bound).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const MAX_WIRE_BYTES: usize = 1024 * 1024;
/// Default `/abs/wire/1.0.0` request-response timeout (Slice L).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_WIRE_TIMEOUT_SECS: u64 = 10;

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
        libp2p_available, ABS_GOSSIP_BLOCKS_TOPIC, ABS_KAD_PROTOCOL, ABS_WIRE_PROTOCOL,
        DEFAULT_MAX_DIALS, DEFAULT_WIRE_TIMEOUT_SECS, MAX_WIRE_BYTES,
    };
    use async_trait::async_trait;
    use futures::prelude::*;
    use libp2p::core::ConnectedPoint;
    use libp2p::multiaddr::Protocol;
    use libp2p::{
        allow_block_list,
        allow_block_list::BlockedPeers,
        connection_limits, gossipsub, identify,
        identity::Keypair,
        kad::{self, store::MemoryStore},
        mdns, noise, ping, relay, request_response,
        swarm::{behaviour::toggle::Toggle, DialError, ListenError, NetworkBehaviour, SwarmEvent},
        tcp, yamux, Multiaddr, PeerId, StreamProtocol, SwarmBuilder,
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
        dial_inflight: u32,
        dial_refused_budget: u64,
        wire_sent: u64,
        wire_recv: u64,
        /// Absolute ADR 0008 codec counters (Slice M; lab pack_wire stays in wire_* only).
        abs_wire_v1_sent: u64,
        abs_wire_v2_sent: u64,
        abs_wire_v1_recv: u64,
        abs_wire_v2_recv: u64,
        gossip_pub: u64,
        gossip_recv: u64,
        mdns_discovered: u64,
        kad_routing_updates: u64,
        kad_queries: u64,
        relay_reservations: u64,
        relay_circuits: u64,
        conn_limit_denied: u64,
        block_denied: u64,
        blocked: HashSet<String>,
        max_dials: u32,
        max_established_incoming: Option<u32>,
        max_established: Option<u32>,
        enable_mdns: bool,
        wire_timeout_secs: u64,
        last_error: String,
        inbox: VecDeque<(String, Vec<u8>)>,
        gossip_inbox: VecDeque<(String, String, Vec<u8>)>,
        subscribed: HashSet<String>,
        identify: HashMap<String, IdentifySnap>,
        /// peer_id -> last advertised multiaddr from mDNS
        discovered: HashMap<String, String>,
        kad_peers: HashSet<String>,
        key_path: String,
        /// Circuit listen addrs observed after reservation (Slice H).
        circuit_addrs: Vec<String>,
    }

    #[pyclass(name = "Libp2pNode")]
    pub struct Libp2pNode {
        peer_id: String,
        cmd_tx: mpsc::UnboundedSender<Cmd>,
        state: Arc<Mutex<NodeState>>,
        _runtime: tokio::runtime::Runtime,
    }

    impl Libp2pNode {
        fn spawn(
            max_dials: u32,
            key_path: Option<String>,
            max_established_incoming: Option<u32>,
            max_established: Option<u32>,
            enable_mdns: bool,
            wire_timeout_secs: u64,
        ) -> PyResult<Self> {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .thread_name("abs-libp2p")
                .build()
                .map_err(|e| PyRuntimeError::new_err(format!("tokio runtime: {e}")))?;

            let key_path_str = key_path.unwrap_or_default();
            let wire_timeout_secs = wire_timeout_secs.max(1);
            let (cmd_tx, mut cmd_rx) = mpsc::unbounded_channel::<Cmd>();
            let state = Arc::new(Mutex::new(NodeState {
                max_dials: max_dials.max(1),
                max_established_incoming,
                max_established,
                enable_mdns,
                wire_timeout_secs,
                key_path: key_path_str.clone(),
                ..NodeState::default()
            }));
            let state_bg = Arc::clone(&state);

            let peer_id_cell = Arc::new(Mutex::new(String::new()));
            let peer_id_bg = Arc::clone(&peer_id_cell);
            let limits_incoming = max_established_incoming;
            let limits_total = max_established;
            let want_mdns = enable_mdns;
            let wire_timeout = Duration::from_secs(wire_timeout_secs);

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

                let built = SwarmBuilder::with_existing_identity(keypair)
                    .with_tokio()
                    .with_tcp(
                        tcp::Config::default(),
                        noise::Config::new,
                        yamux::Config::default,
                    )
                    .and_then(|b| b.with_relay_client(noise::Config::new, yamux::Config::default));

                let builder = match built {
                    Ok(b) => b,
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("tcp/relay transport: {e}");
                        }
                        return;
                    }
                };

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
                        .message_id_fn(message_id_fn)
                        .build()
                        .map_err(|e| format!("gossipsub config: {e}"))?;
                    let gossipsub = gossipsub::Behaviour::new(
                        gossipsub::MessageAuthenticity::Signed(key.clone()),
                        gs_cfg,
                    )
                    .map_err(|e| format!("gossipsub: {e}"))?;
                    let mdns = if want_mdns {
                        Toggle::from(Some(
                            mdns::tokio::Behaviour::new(
                                mdns::Config {
                                    ttl: Duration::from_secs(60),
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
                    if let Some(n) = limits_total {
                        limits = limits.with_max_established(Some(n));
                    }
                    Ok(AbsBehaviour {
                        ping: ping::Behaviour::new(ping::Config::new()),
                        identify: identify::Behaviour::new(identify::Config::new(
                            "/absolute/1.0.0".into(),
                            key.public(),
                        )),
                        wire,
                        gossipsub,
                        mdns,
                        kademlia,
                        relay: relay::Behaviour::new(local, relay::Config::default()),
                        relay_client,
                        connection_limits: connection_limits::Behaviour::new(limits),
                        blocked_peers: allow_block_list::Behaviour::default(),
                    })
                }) {
                    Ok(b) => b
                        .with_swarm_config(|cfg| {
                            cfg.with_idle_connection_timeout(Duration::from_secs(60))
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
                let mut pending_wire: HashMap<
                    request_response::OutboundRequestId,
                    oneshot::Sender<Result<Vec<u8>, String>>,
                > = HashMap::new();
                let mut pending_kad: HashMap<
                    kad::QueryId,
                    oneshot::Sender<Result<Vec<String>, String>>,
                > = HashMap::new();

                loop {
                    tokio::select! {
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
                                Some(Cmd::Dial { addr, reply }) => {
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
                                                    st.last_error = "peer_blocked".into();
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
                                                }
                                                let _ = reply.send(Err(format!("dial: {e}")));
                                            } else {
                                                pending_dial = Some(reply);
                                            }
                                        }
                                        Err(e) => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.dial_inflight =
                                                    st.dial_inflight.saturating_sub(1);
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
                            }
                        }
                        event = swarm.select_next_some() => {
                            match event {
                                SwarmEvent::NewListenAddr { address, .. } => {
                                    let s = address.to_string();
                                    let is_circuit = address
                                        .iter()
                                        .any(|p| matches!(p, Protocol::P2pCircuit));
                                    if let Ok(mut st) = state_bg.lock() {
                                        if !st.listen_addrs.contains(&s) {
                                            st.listen_addrs.push(s.clone());
                                        }
                                        if is_circuit && !st.circuit_addrs.contains(&s) {
                                            st.circuit_addrs.push(s.clone());
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
                                SwarmEvent::ConnectionEstablished {
                                    peer_id,
                                    endpoint,
                                    ..
                                } => {
                                    let pid = peer_id.to_string();
                                    let is_dialer = endpoint.is_dialer();
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
                                    if let Some(addr) = kad_addr {
                                        swarm
                                            .behaviour_mut()
                                            .kademlia
                                            .add_address(&peer_id, addr);
                                    }
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.connected.insert(pid.clone());
                                        st.kad_peers.insert(pid.clone());
                                        if is_dialer {
                                            st.outbound_peers.insert(pid.clone());
                                            st.dial_ok = st.dial_ok.saturating_add(1);
                                            st.dial_inflight =
                                                st.dial_inflight.saturating_sub(1);
                                        }
                                    }
                                    if is_dialer {
                                        if let Some(reply) = pending_dial.take() {
                                            let _ = reply.send(Ok(pid));
                                        }
                                    }
                                }
                                SwarmEvent::OutgoingConnectionError { error, .. } => {
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
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.last_error = format!("outgoing: {error}");
                                        st.dial_fail = st.dial_fail.saturating_add(1);
                                        st.dial_inflight = st.dial_inflight.saturating_sub(1);
                                        if limit_denied {
                                            st.conn_limit_denied =
                                                st.conn_limit_denied.saturating_add(1);
                                        }
                                        if block_denied {
                                            st.block_denied = st.block_denied.saturating_add(1);
                                        }
                                    }
                                    if let Some(reply) = pending_dial.take() {
                                        let msg = if block_denied {
                                            "peer_blocked".into()
                                        } else {
                                            format!("outgoing: {error}")
                                        };
                                        let _ = reply.send(Err(msg));
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
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.last_error = format!("incoming: {error}");
                                        if limit_denied {
                                            st.conn_limit_denied =
                                                st.conn_limit_denied.saturating_add(1);
                                        }
                                        if block_denied {
                                            st.block_denied = st.block_denied.saturating_add(1);
                                        }
                                    }
                                }
                                SwarmEvent::ExternalAddrConfirmed { address } => {
                                    let s = address.to_string();
                                    if address.iter().any(|p| matches!(p, Protocol::P2pCircuit)) {
                                        if let Ok(mut st) = state_bg.lock() {
                                            if !st.circuit_addrs.contains(&s) {
                                                st.circuit_addrs.push(s.clone());
                                            }
                                            if !st.listen_addrs.contains(&s) {
                                                st.listen_addrs.push(s.clone());
                                            }
                                        }
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
                                SwarmEvent::ConnectionClosed { peer_id, endpoint, .. } => {
                                    let pid = peer_id.to_string();
                                    swarm.behaviour_mut().gossipsub.remove_explicit_peer(&peer_id);
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.connected.remove(&pid);
                                        if endpoint.is_dialer() {
                                            st.outbound_peers.remove(&pid);
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Identify(ev)) => {
                                    if let identify::Event::Received { peer_id, info, .. } = ev {
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
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.identify.insert(peer_id.to_string(), snap);
                                        }
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Gossipsub(ev)) => {
                                    if let gossipsub::Event::Message {
                                        propagation_source,
                                        message,
                                        ..
                                    } = ev
                                    {
                                        let topic = message.topic.to_string();
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.gossip_recv = st.gossip_recv.saturating_add(1);
                                            if st.gossip_inbox.len() < 1024 {
                                                st.gossip_inbox.push_back((
                                                    propagation_source.to_string(),
                                                    topic,
                                                    message.data,
                                                ));
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
                                            if let Ok(mut st) = state_bg.lock() {
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
                                                if let Some(reply) = pending_kad.remove(&id) {
                                                    match res {
                                                        Ok(ok) => {
                                                            let peers: Vec<String> = ok
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
                                        _ => {}
                                    }
                                }
                                SwarmEvent::Behaviour(AbsBehaviourEvent::Relay(ev)) => {
                                    match ev {
                                        relay::Event::ReservationReqAccepted { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_reservations =
                                                    st.relay_reservations.saturating_add(1);
                                            }
                                        }
                                        relay::Event::ReservationReqDenied { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.last_error = "relay reservation denied".into();
                                            }
                                        }
                                        relay::Event::CircuitReqAccepted { .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuits =
                                                    st.relay_circuits.saturating_add(1);
                                            }
                                        }
                                        _ => {}
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
                                        }
                                        | relay::client::Event::OutboundCircuitEstablished {
                                            ..
                                        } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.relay_circuits =
                                                    st.relay_circuits.saturating_add(1);
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
                                            if let Some(reply) = pending_wire.remove(&request_id)
                                            {
                                                let _ = reply
                                                    .send(Err(format!("wire outbound: {error}")));
                                            }
                                        }
                                        Event::InboundFailure { error, .. } => {
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.last_error =
                                                    format!("wire inbound: {error}");
                                            }
                                        }
                                        Event::ResponseSent { .. } => {}
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
            max_established = None,
            enable_mdns = None,
            wire_timeout_secs = None
        ))]
        fn new_py(
            max_dials: u32,
            key_path: Option<String>,
            max_established_incoming: Option<u32>,
            max_established: Option<u32>,
            enable_mdns: Option<bool>,
            wire_timeout_secs: Option<u64>,
        ) -> PyResult<Self> {
            Self::spawn(
                max_dials,
                key_path,
                max_established_incoming,
                max_established,
                resolve_enable_mdns(enable_mdns),
                resolve_wire_timeout_secs(wire_timeout_secs),
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
                let st = self
                    .state
                    .lock()
                    .map_err(|e| PyRuntimeError::new_err(format!("state lock poisoned: {e}")))?;
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("libp2p_peers", st.connected.len())?;
                d.set_item("libp2p_dial_ok", st.dial_ok)?;
                d.set_item("libp2p_dial_fail", st.dial_fail)?;
                d.set_item("libp2p_dial_inflight", st.dial_inflight)?;
                d.set_item("libp2p_outbound_peers", st.outbound_peers.len())?;
                d.set_item("libp2p_dial_refused_budget", st.dial_refused_budget)?;
                d.set_item("libp2p_max_dials", st.max_dials)?;
                d.set_item("libp2p_wire_sent", st.wire_sent)?;
                d.set_item("libp2p_wire_recv", st.wire_recv)?;
                d.set_item("libp2p_abs_wire_v1_sent", st.abs_wire_v1_sent)?;
                d.set_item("libp2p_abs_wire_v2_sent", st.abs_wire_v2_sent)?;
                d.set_item("libp2p_abs_wire_v1_recv", st.abs_wire_v1_recv)?;
                d.set_item("libp2p_abs_wire_v2_recv", st.abs_wire_v2_recv)?;
                d.set_item("libp2p_gossip_pub", st.gossip_pub)?;
                d.set_item("libp2p_gossip_recv", st.gossip_recv)?;
                d.set_item("libp2p_gossip_topics", st.subscribed.len())?;
                d.set_item("libp2p_identify_peers", st.identify.len())?;
                d.set_item("libp2p_mdns_discovered", st.mdns_discovered)?;
                d.set_item("libp2p_discovered_peers", st.discovered.len())?;
                d.set_item("libp2p_kad_peers", st.kad_peers.len())?;
                d.set_item("libp2p_kad_routing_updates", st.kad_routing_updates)?;
                d.set_item("libp2p_kad_queries", st.kad_queries)?;
                d.set_item("libp2p_relay_reservations", st.relay_reservations)?;
                d.set_item("libp2p_relay_circuits", st.relay_circuits)?;
                d.set_item("libp2p_conn_limit_denied", st.conn_limit_denied)?;
                d.set_item("libp2p_block_denied", st.block_denied)?;
                d.set_item("libp2p_blocked_peers", st.blocked.len())?;
                d.set_item("libp2p_circuit_addrs", st.circuit_addrs.len())?;
                d.set_item("libp2p_mdns_enabled", st.enable_mdns)?;
                d.set_item("libp2p_wire_timeout_secs", st.wire_timeout_secs)?;
                if let Some(n) = st.max_established_incoming {
                    d.set_item("libp2p_max_established_incoming", n)?;
                }
                if let Some(n) = st.max_established {
                    d.set_item("libp2p_max_established", n)?;
                }
                d.set_item("libp2p_key_path", &st.key_path)?;
                d.set_item("libp2p_wire_protocol", ABS_WIRE_PROTOCOL)?;
                d.set_item("libp2p_gossip_blocks_topic", ABS_GOSSIP_BLOCKS_TOPIC)?;
                d.set_item("libp2p_kad_protocol", ABS_KAD_PROTOCOL)?;
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
                d.set_item("phase", 12)?;
                d.set_item("noise", true)?;
                d.set_item("yamux", true)?;
                d.set_item("gossipsub", true)?;
                d.set_item("mdns", st.enable_mdns)?;
                d.set_item("kademlia", true)?;
                d.set_item("relay", true)?;
                d.set_item("connection_limits", true)?;
                d.set_item("block_list", true)?;
                d.set_item("abs_wire_codecs", true)?;
                d.set_item("wire_timeout_secs", st.wire_timeout_secs)?;
                d.set_item("persistent_identity", !st.key_path.is_empty())?;
                d.set_item("wire_protocol", ABS_WIRE_PROTOCOL)?;
                d.set_item("gossip_blocks_topic", ABS_GOSSIP_BLOCKS_TOPIC)?;
                d.set_item("kad_protocol", ABS_KAD_PROTOCOL)?;
                d.set_item("peer_id", &self.peer_id)?;
                d.set_item("key_path", &st.key_path)?;
                d.set_item("listen_addrs", st.listen_addrs.clone())?;
                d.set_item("circuit_addrs", st.circuit_addrs.clone())?;
                d.set_item("connected", st.connected.len())?;
                d.set_item("libp2p_peers", st.connected.len())?;
                d.set_item("libp2p_dial_ok", st.dial_ok)?;
                d.set_item("libp2p_dial_fail", st.dial_fail)?;
                d.set_item("libp2p_wire_sent", st.wire_sent)?;
                d.set_item("libp2p_wire_recv", st.wire_recv)?;
                d.set_item("libp2p_abs_wire_v1_sent", st.abs_wire_v1_sent)?;
                d.set_item("libp2p_abs_wire_v2_sent", st.abs_wire_v2_sent)?;
                d.set_item("libp2p_abs_wire_v1_recv", st.abs_wire_v1_recv)?;
                d.set_item("libp2p_abs_wire_v2_recv", st.abs_wire_v2_recv)?;
                d.set_item("libp2p_gossip_pub", st.gossip_pub)?;
                d.set_item("libp2p_gossip_recv", st.gossip_recv)?;
                d.set_item("libp2p_mdns_discovered", st.mdns_discovered)?;
                d.set_item("libp2p_kad_peers", st.kad_peers.len())?;
                d.set_item("libp2p_relay_reservations", st.relay_reservations)?;
                d.set_item("libp2p_conn_limit_denied", st.conn_limit_denied)?;
                d.set_item("libp2p_block_denied", st.block_denied)?;
                d.set_item("libp2p_blocked_peers", st.blocked.len())?;
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

    #[pyfunction]
    #[pyo3(signature = (
        max_dials = DEFAULT_MAX_DIALS,
        key_path = None,
        max_established_incoming = None,
        max_established = None,
        enable_mdns = None,
        wire_timeout_secs = None
    ))]
    fn libp2p_node_new(
        max_dials: u32,
        key_path: Option<String>,
        max_established_incoming: Option<u32>,
        max_established: Option<u32>,
        enable_mdns: Option<bool>,
        wire_timeout_secs: Option<u64>,
    ) -> PyResult<Libp2pNode> {
        Libp2pNode::spawn(
            max_dials,
            key_path,
            max_established_incoming,
            max_established,
            resolve_enable_mdns(enable_mdns),
            resolve_wire_timeout_secs(wire_timeout_secs),
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
