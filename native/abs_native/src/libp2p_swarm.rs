//! ADR 0019 — optional rust-libp2p swarm (FEATURE_LIBP2P / Cargo feature `libp2p`).
//!
//! Honesty: compiled swarm ≠ prod industrial mesh (TCP+TLS remains default).

use pyo3::prelude::*;

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
    use super::libp2p_available;
    use futures::StreamExt;
    use libp2p::{
        identify, noise, ping,
        swarm::{NetworkBehaviour, SwarmEvent},
        tcp, yamux, Multiaddr, SwarmBuilder,
    };
    use pyo3::exceptions::{PyRuntimeError, PyValueError};
    use pyo3::prelude::*;
    use std::collections::HashSet;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;
    use tokio::sync::{mpsc, oneshot};

    #[derive(NetworkBehaviour)]
    struct AbsBehaviour {
        ping: ping::Behaviour,
        identify: identify::Behaviour,
    }

    enum Cmd {
        Listen {
            addr: String,
            reply: oneshot::Sender<Result<Vec<String>, String>>,
        },
        Dial {
            addr: String,
            reply: oneshot::Sender<Result<String, String>>,
        },
        Shutdown {
            reply: oneshot::Sender<()>,
        },
    }

    #[derive(Default)]
    struct NodeState {
        listen_addrs: Vec<String>,
        connected: HashSet<String>,
        dial_ok: u64,
        last_error: String,
    }

    #[pyclass(name = "Libp2pNode")]
    pub struct Libp2pNode {
        peer_id: String,
        cmd_tx: mpsc::UnboundedSender<Cmd>,
        state: Arc<Mutex<NodeState>>,
        _runtime: tokio::runtime::Runtime,
    }

    impl Libp2pNode {
        fn spawn() -> PyResult<Self> {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .thread_name("abs-libp2p")
                .build()
                .map_err(|e| PyRuntimeError::new_err(format!("tokio runtime: {e}")))?;

            let (cmd_tx, mut cmd_rx) = mpsc::unbounded_channel::<Cmd>();
            let state = Arc::new(Mutex::new(NodeState::default()));
            let state_bg = Arc::clone(&state);

            let peer_id_cell = Arc::new(Mutex::new(String::new()));
            let peer_id_bg = Arc::clone(&peer_id_cell);

            runtime.spawn(async move {
                let built = SwarmBuilder::with_new_identity()
                    .with_tokio()
                    .with_tcp(
                        tcp::Config::default(),
                        noise::Config::new,
                        yamux::Config::default,
                    );

                let builder = match built {
                    Ok(b) => b,
                    Err(e) => {
                        if let Ok(mut st) = state_bg.lock() {
                            st.last_error = format!("tcp transport: {e}");
                        }
                        return;
                    }
                };

                let mut swarm = match builder.with_behaviour(|key| AbsBehaviour {
                    ping: ping::Behaviour::new(ping::Config::new()),
                    identify: identify::Behaviour::new(identify::Config::new(
                        "/absolute/1.0.0".into(),
                        key.public(),
                    )),
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
                let mut pending_dial: Option<(String, oneshot::Sender<Result<String, String>>)> =
                    None;

                loop {
                    tokio::select! {
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
                                Some(Cmd::Dial { addr, reply }) => {
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            if let Err(e) = swarm.dial(ma) {
                                                let _ = reply.send(Err(format!("dial: {e}")));
                                            } else {
                                                pending_dial = Some((addr, reply));
                                            }
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                            }
                        }
                        event = swarm.select_next_some() => {
                            match event {
                                SwarmEvent::NewListenAddr { address, .. } => {
                                    let s = address.to_string();
                                    if let Ok(mut st) = state_bg.lock() {
                                        if !st.listen_addrs.contains(&s) {
                                            st.listen_addrs.push(s.clone());
                                        }
                                    }
                                    if let Some(reply) = pending_listen.take() {
                                        let addrs = state_bg
                                            .lock()
                                            .map(|st| st.listen_addrs.clone())
                                            .unwrap_or_else(|_| vec![s]);
                                        let _ = reply.send(Ok(addrs));
                                    }
                                }
                                SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                                    let pid = peer_id.to_string();
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.connected.insert(pid.clone());
                                        st.dial_ok = st.dial_ok.saturating_add(1);
                                    }
                                    if let Some((_addr, reply)) = pending_dial.take() {
                                        let _ = reply.send(Ok(pid));
                                    }
                                }
                                SwarmEvent::OutgoingConnectionError { error, .. } => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.last_error = format!("outgoing: {error}");
                                    }
                                    if let Some((_addr, reply)) = pending_dial.take() {
                                        let _ = reply.send(Err(format!("outgoing: {error}")));
                                    }
                                }
                                SwarmEvent::ConnectionClosed { peer_id, .. } => {
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.connected.remove(&peer_id.to_string());
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                }
            });

            // Wait briefly for peer id assignment from background task.
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
        fn new_py() -> PyResult<Self> {
            Self::spawn()
        }

        #[getter]
        fn peer_id(&self) -> String {
            self.peer_id.clone()
        }

        /// Listen on a multiaddr (e.g. `/ip4/127.0.0.1/tcp/0`). Returns listen addrs.
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

        /// Dial a multiaddr; returns remote peer id string on connection.
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

        fn capability_status(&self) -> PyResult<PyObject> {
            Python::with_gil(|py| {
                let st = self.state.lock().map_err(|e| {
                    PyRuntimeError::new_err(format!("state lock poisoned: {e}"))
                })?;
                let d = pyo3::types::PyDict::new_bound(py);
                d.set_item("available", true)?;
                d.set_item("transport", "libp2p")?;
                d.set_item("phase", 3)?;
                d.set_item("noise", true)?;
                d.set_item("yamux", true)?;
                d.set_item("peer_id", &self.peer_id)?;
                d.set_item("listen_addrs", st.listen_addrs.clone())?;
                d.set_item("connected", st.connected.len())?;
                d.set_item("dial_ok", st.dial_ok)?;
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

    #[pyfunction]
    fn libp2p_node_new() -> PyResult<Libp2pNode> {
        Libp2pNode::spawn()
    }

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(libp2p_available, m)?)?;
        m.add_class::<Libp2pNode>()?;
        m.add_function(wrap_pyfunction!(libp2p_node_new, m)?)?;
        Ok(())
    }
}

#[cfg(feature = "libp2p")]
pub use enabled::register;
