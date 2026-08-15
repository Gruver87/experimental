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
//! Slice BB: wire omit-response lab path (`ResponseOmission` inbound fail).
//! Slice BC: identify push API + agent version + listen-addr push toggle.
//! Slice BD: identify interval + identify error taxonomy.
//! Slice BE: peerstore remove (forget peer) + removed counter.
//! Slice BF: peerstore_allow_learn (clear forget → re-learn allowed).
//! Slice BG: identify observed-addr surface + confirm_observed_addr.
//! Slice BH: bootstrap_remove returns bool + removed counter.
//! Slice BI: auto-confirm observed-addr (`ABS_LIBP2P_CONFIRM_OBSERVED_ADDR`).
//! Slice BJ: bootstrap_clear (wipe book + persist; returns peers cleared).
//! Slice BK: peerstore_clear returns peers cleared + cleared counter.
//! Slice BL: clear_observed_addr (wipe last_observed surface + counter).
//! Slice BM: clear_external_addrs (wipe external book + counter).
//! Slice BN: remove_external_address returns bool (present) + expired only when present.
//! Slice BO: add_external_address returns bool (fresh) + confirmed only when newly inserted.
//! Slice BP: persistent advertised external addrs JSON (`external_addrs_path`).
//! Slice BQ: atomic persist (same-dir `.tmp` + fsync + rename; dest not truncated in place).
//! Slice BR: hard max on advertised externals (refuse over limit; no silent truncate).
//! Slice BS: same max on listen-derived externals (refuse listen over limit; no silent truncate).
//! Slice BT: shared advertised cap — operator + listen-derived sum ≤ max (not 64).
//! Slice BU: observed / UPnP / rendezvous advertise through the same shared cap.
//! Slice BV: Identify omits uncharged listen addrs (no leak past advertised cap).
//! Slice BW: mDNS omits uncharged listen addrs (same shared cap; no LAN leak).
//! Slice BX: Kademlia omits uncharged listen addrs (no DHT leak past advertised cap).
//! Slice BY: AutoNAT omits uncharged listen addrs (no probe leak past advertised cap).
//! Slice BZ: UPnP omits uncharged listen addrs (no IGD map past advertised cap).
//! Slice CA: advertised unique cap ≤ rust-libp2p ExternalAddresses book (20).
//! Slice CB: DCUtR omits uncharged hole-punch candidates (no punch past advertised cap).
//! Slice CC: Identify omits uncharged NewExternalAddrCandidate (no swarm-wide leak).
//! Slice CD: persist replace without unlink-then-rename (Windows MoveFileEx).
//! Slice CE: bootstrap + peerstore JSON use the same atomic replace (no truncate-in-place).
//! Slice CF: identity keystore first-create uses atomic replace (no truncate-in-place).
//! Slice CG: fsync parent directory after replace (POSIX dirent durability).
//! Slice CH: identity keystore Unix mode 0o600; world-readable existing key refuses spawn.
//! Slice CI: identity keystore Windows protected DACL (no Users/Everyone).
//! Slice CJ: fsync newly created persist dirs (mkdir dirent durability).
//! Slice CK: identity first-create refuses dest clobber (exclusive replace).
//! Slice CL: identity tmp is born restricted (Unix 0600 / Windows DACL at create).
//! Slice CM: existing identity with weak ACL refuses spawn (no silent rewrite).
//! Slice CN: existing identity NULL/absent DACL refuses spawn (grants everyone).
//! Slice CS: mkdir identity parent then recheck ACL (inherit-only ancestor write).
//! Slice CT: identity parent ACL is always attested (relative→cwd; volume root refuse).
//! Slice CU: persist staging tmp is per-thread (`dest.{pid}.{tid}.tmp`).
//! Slice CV: sweep stale other-tid persist tmp; skip in-flight writers.
//! Slice CW: circuit `/p2p-circuit` never occupies rust-libp2p ExternalAddresses.
//! Slice CX: relay-client circuit ExternalAddrConfirmed is omitted (crate book).
//! Slice CY: AutoNAT/UPnP ExternalAddrConfirmed is admit-canonical-or-omit.
//! Slice CZ: observed / SwarmEvent confirm charges the canonical key (no `/p2p` suffix).
//! Slice DA: add/remove/expire use the canonical key (suffix cannot miss crate slot).
//! Slice DB: persist JSON load/restore collapses `/p2p/<peer>` to the charge key.
//!
//! Honesty: compiled swarm ≠ prod industrial mesh (TCP+TLS remains default).

use pyo3::prelude::*;

// Used under feature=libp2p; default Hybrid clippy build has feature off.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const ABS_WIRE_PROTOCOL: &str = "/abs/wire/1.0.0";
/// Identify protocol family version advertised on the wire (Slice BC).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const ABS_IDENTIFY_PROTOCOL_VERSION: &str = "/absolute/1.0.0";
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
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
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
/// Slice BD: default identify re-request interval (libp2p identify default = 5 min).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const DEFAULT_IDENTIFY_INTERVAL_MS: u64 = 5 * 60 * 1000;
/// rust-libp2p 0.45 `ExternalAddresses` (Identify / Kad / Relay) silently
/// evicts the oldest confirmed external past this count. Slice CA: our
/// advertised unique cap must not exceed this book — refuse, not silent drop.
pub const LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX: usize = 20;
/// Slice BR/BS/BT/BU/CA/CW: hard ceiling on advertised externals. Unique charged
/// addrs (operator + listen-derived + observed/UPnP/rendezvous aux) ≤ this
/// value. Circuit `/p2p-circuit` is not counted **and** is never inserted into
/// the crate ExternalAddresses book (silent eviction of a charged addr).
/// Env/arg may only lower this; values above refuse spawn. Must equal
/// `LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX`.
pub const MAX_ADVERTISED_EXTERNAL_ADDRS: usize = LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX;

const _: () = assert!(
    MAX_ADVERTISED_EXTERNAL_ADDRS == LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX,
    "advertised cap must equal rust-libp2p ExternalAddresses book"
);

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

/// Slice BP: parse advertised external multiaddr JSON (fail-closed).
///
/// Slice DB: trailing `/p2p/<peer>` is the same unique as the transport prefix.
/// Circuit tokens are refused before this runs. Empty strip is refused by caller.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn advertised_json_charge_key(s: &str) -> String {
    let parts: Vec<&str> = s.split('/').collect();
    if parts.len() >= 3
        && parts[parts.len() - 2] == "p2p"
        && parts[parts.len() - 1] != "p2p-circuit"
        && !parts[parts.len() - 1].is_empty()
    {
        let joined = parts[..parts.len() - 2].join("/");
        if joined.is_empty() || joined == "/" {
            return s.to_string();
        }
        return joined;
    }
    s.to_string()
}

/// Slice DB: persist load collapses suffix variants so JSON cannot occupy a
/// second unique advertised slot (crate ExternalAddresses silent eviction).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_external_charge_key_strategy() -> &'static str {
    "load_canonical_charge_key"
}

/// Expected shape: `{"version":1,"addrs":["/ip4/.../tcp/..."]}`.
/// Missing file is handled by [`load_external_addrs_file`]. Corrupt JSON,
/// missing `addrs` array, non-string entries, or non-multiaddr strings error.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn parse_external_addrs_json(raw: &str) -> Result<Vec<String>, String> {
    let v: serde_json::Value =
        serde_json::from_str(raw).map_err(|e| format!("external addrs json: {e}"))?;
    let arr = v
        .get("addrs")
        .and_then(|a| a.as_array())
        .ok_or_else(|| "external addrs json: missing addrs array".to_string())?;
    let mut out: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for x in arr {
        let s = x
            .as_str()
            .ok_or_else(|| "external addrs json: addr must be string".to_string())?
            .trim();
        if s.is_empty() {
            return Err("external addrs json: empty addr".into());
        }
        if !s.starts_with('/') {
            return Err(format!("external addrs json: not a multiaddr: {s}"));
        }
        if multiaddr_is_p2p_circuit(s) {
            return Err(CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_MSG.into());
        }
        let key = advertised_json_charge_key(s);
        if !key.starts_with('/') {
            return Err(format!("external addrs json: not a multiaddr: {s}"));
        }
        if seen.insert(key.clone()) {
            out.push(key);
        }
    }
    if out.len() > MAX_ADVERTISED_EXTERNAL_ADDRS {
        return Err(format!(
            "external addrs json: {} addrs exceeds hard max {}",
            out.len(),
            MAX_ADVERTISED_EXTERNAL_ADDRS
        ));
    }
    Ok(out)
}

/// Slice BP: load advertised externals. Missing file → empty. Corrupt → error.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn load_external_addrs_file(path: &std::path::Path) -> Result<Vec<String>, String> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let raw = std::fs::read_to_string(path).map_err(|e| format!("read external addrs: {e}"))?;
    parse_external_addrs_json(&raw)
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn encode_external_addrs_json(addrs: &[String]) -> Result<String, String> {
    let doc = serde_json::json!({
        "version": 1,
        "addrs": addrs,
    });
    serde_json::to_string_pretty(&doc).map_err(|e| format!("external addrs encode: {e}"))
}

/// Slice BQ/CK/CU: sibling tmp next to dest.
///
/// `foo.json` → `foo.json.{pid}.{tid}.tmp` so two processes (CK) and two
/// threads in one process (CU) do not share the staging file. A shared `.tmp`
/// can mix writer bytes, then dest replace still "succeeds" with a torn
/// snapshot. Same-thread sequential persist reuses the name so leftover tmp
/// from a failed attempt is cleaned (CL).
///
/// Persist also unlinks unused CK leftover `dest.{pid}.tmp` (not used for
/// staging). Python labs plant that name because persist runs on the swarm
/// task thread, whose tid is not the caller thread. Concurrent staging is
/// only `{pid}.{tid}`.
///
/// Slice CV: a crash on tokio worker A leaves `dest.{pid}.{tidA}.tmp`. A
/// retry on worker B must unlink that leftover. Glob-unlink of every
/// `{pid}.*.tmp` would steal an in-flight writer (unsafe on POSIX: unlink of
/// an open path). Sweep skips paths in a process-wide in-flight set.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_tmp_strategy() -> &'static str {
    "pid_tid_tmp"
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_tmp_stale_tid_strategy() -> &'static str {
    "unlink_not_in_flight"
}

/// Slice CW: `/p2p-circuit` must not occupy rust-libp2p `ExternalAddresses`
/// slots. Circuit is excluded from the unique advertised cap, so
/// `Swarm::add_external_address(circuit)` after 20 charged unique addrs
/// silently evicts a charged operator/listen addr (crate book = 20).
/// Protocol component is the exact token `p2p-circuit` (not a DNS label).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn multiaddr_is_p2p_circuit(s: &str) -> bool {
    s.split('/').any(|p| p == "p2p-circuit")
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub const CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_MSG: &str =
    "circuit /p2p-circuit excluded from ExternalAddresses book";

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn circuit_excluded_from_external_book_strategy() -> &'static str {
    "never_add_external_address"
}

/// Slice CX: `libp2p-relay` client emits `ToSwarm::ExternalAddrConfirmed`
/// on reservation accept. Swarm maps that to `add_external_address`, which
/// occupies Identify/Kad/Relay `ExternalAddresses` (silent eviction past 20).
/// Circuit confirm/expire from the client are omitted; listen + reservation
/// events still complete `listen_relay`.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn relay_client_circuit_external_strategy() -> &'static str {
    "omit_circuit_external_confirmed"
}

/// Slice CY: AutoNAT / UPnP emit `ToSwarm::ExternalAddrConfirmed` which Swarm
/// maps to `add_external_address` (crate book of 20, silent eviction). Forward
/// only after the unique advertised cap admits the charge key; rewrite to the
/// canonical key so `/p2p/<peer>` suffix cannot occupy a second slot.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn behaviour_external_confirmed_strategy() -> &'static str {
    "admit_canonical_or_omit"
}

/// Slice CZ: Identify observed addrs often append `/p2p/<peer>`. Charge and
/// crate-book insert use the canonical key (suffix stripped) so a suffix
/// variant cannot occupy a second unique slot or evict a charged listen.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn observed_external_charge_key_strategy() -> &'static str {
    "admit_canonical_charge_key"
}

/// Slice DA: AutoNAT/UPnP/relay-client `ExternalAddrExpired` must address the
/// crate slot we inserted at confirm (canonical key). Operator add/remove of a
/// `/p2p/<peer>` suffix must match the same unique, not occupy or miss a slot.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn behaviour_external_expired_strategy() -> &'static str {
    "expire_canonical_charge_key"
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn persist_tmp_thread_tag() -> String {
    let tag: String = format!("{:?}", std::thread::current().id())
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect();
    if tag.is_empty() {
        "t".into()
    } else {
        tag
    }
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn persist_tmp_join(path: &std::path::Path, suffix_after_name: &str) -> std::path::PathBuf {
    let fname = path.file_name().map_or_else(
        || std::ffi::OsString::from(format!("external_addrs.{suffix_after_name}")),
        |n| {
            let mut s = n.to_os_string();
            s.push(".");
            s.push(suffix_after_name);
            s
        },
    );
    match path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.join(fname),
        _ => std::path::PathBuf::from(fname),
    }
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_tmp_path_pid_only(path: &std::path::Path) -> std::path::PathBuf {
    persist_tmp_join(path, &format!("{}.tmp", std::process::id()))
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn external_addrs_tmp_path(path: &std::path::Path) -> std::path::PathBuf {
    persist_tmp_join(
        path,
        &format!("{}.{}.tmp", std::process::id(), persist_tmp_thread_tag()),
    )
}

fn persist_tmp_parent_dir(dest: &std::path::Path) -> std::path::PathBuf {
    match dest.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.to_path_buf(),
        _ => std::path::PathBuf::from("."),
    }
}

fn persist_tmp_name_is_ours(
    file_name: &std::ffi::OsStr,
    dest_name: &std::ffi::OsStr,
    pid: &str,
) -> bool {
    let name = file_name.to_string_lossy();
    if !name.ends_with(".tmp") {
        return false;
    }
    let mut prefix = dest_name.to_os_string();
    prefix.push(".");
    prefix.push(pid);
    prefix.push(".");
    name.starts_with(prefix.to_string_lossy().as_ref())
}

fn persist_tmp_in_flight(
) -> &'static std::sync::Mutex<std::collections::HashSet<std::path::PathBuf>> {
    static SET: std::sync::OnceLock<
        std::sync::Mutex<std::collections::HashSet<std::path::PathBuf>>,
    > = std::sync::OnceLock::new();
    SET.get_or_init(|| std::sync::Mutex::new(std::collections::HashSet::new()))
}

struct PersistTmpInFlight {
    path: std::path::PathBuf,
}

impl PersistTmpInFlight {
    fn claim(path: std::path::PathBuf) -> Self {
        let mut g = persist_tmp_in_flight()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        g.insert(path.clone());
        Self { path }
    }
}

impl Drop for PersistTmpInFlight {
    fn drop(&mut self) {
        let mut g = persist_tmp_in_flight()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        g.remove(&self.path);
    }
}

fn persist_tmp_in_flight_contains(path: &std::path::Path) -> bool {
    persist_tmp_in_flight()
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .contains(path)
}

fn unlink_one_persist_tmp_leftover(path: &std::path::Path) {
    let _ = restrict_identity_key_acl(path);
    let _ = std::fs::remove_file(path);
}

/// Slice CU/CV: drop unused CK `dest.{pid}.tmp` and stale `{pid}.{otherTid}.tmp`.
/// Skip `current_tmp` and any path claimed in-flight (concurrent writer).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn unlink_stale_persist_tmps(dest: &std::path::Path, current_tmp: &std::path::Path) {
    let legacy = persist_tmp_path_pid_only(dest);
    if legacy != *current_tmp && legacy.exists() && !persist_tmp_in_flight_contains(&legacy) {
        unlink_one_persist_tmp_leftover(&legacy);
    }
    let Some(dest_name) = dest.file_name() else {
        return;
    };
    let pid = std::process::id().to_string();
    let parent = persist_tmp_parent_dir(dest);
    let Ok(entries) = std::fs::read_dir(&parent) else {
        return;
    };
    for ent in entries.flatten() {
        let name = ent.file_name();
        if !persist_tmp_name_is_ours(&name, dest_name, &pid) {
            continue;
        }
        let candidate = parent.join(&name);
        if candidate == *current_tmp {
            continue;
        }
        if persist_tmp_in_flight_contains(&candidate) {
            continue;
        }
        unlink_one_persist_tmp_leftover(&candidate);
    }
}

/// Slice CD: how dest is replaced after tmp+fsync.
///
/// - POSIX: `rename(2)` replaces atomically (no unlink-then-rename).
/// - Windows: `MoveFileExW(MOVEFILE_REPLACE_EXISTING | WRITE_THROUGH)`.
///   Dest is never `remove_file`'d first. Still **not** POSIX inode-atomic.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn external_addrs_replace_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_movefileex_replace"
    } else {
        "posix_rename"
    }
}

/// Slice CG: how the parent directory is made durable after replace.
///
/// POSIX: `fsync` on the directory fd so the dirent survives a crash.
/// Windows: `FlushFileBuffers` on a directory handle (`FILE_FLAG_BACKUP_SEMANTICS`).
/// Still **not** POSIX inode-atomic on NTFS.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_parent_dir_fsync_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_dir_flushfilebuffers"
    } else {
        "posix_dir_fsync"
    }
}

/// Slice CJ: same dir-fsync primitive as CG, applied to mkdir ancestors.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_mkdir_fsync_strategy() -> &'static str {
    persist_parent_dir_fsync_strategy()
}

/// Slice CQ: JSON persist (externals / bootstrap / peerstore) uses the same
/// restricted tmp as identity (Unix `0o600` at open / Windows CreateFile DACL).
/// Existing JSON is not refused at load (not key material). Dest ACL is
/// replaced on persist (CD still last-writer-wins). NTFS replace remains
/// **not** POSIX inode-atomic.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn persist_json_acl_strategy() -> &'static str {
    identity_key_tmp_restrict_strategy()
}

/// Slice CH/CI: identity private-key file mode.
///
/// Unix first-create uses `0o600`. Existing keys with group/other bits refuse
/// spawn (OpenSSH-style; no silent chmod). Windows first-create sets a
/// protected DACL (owner + SYSTEM + Administrators; no Users/Everyone) —
/// not POSIX `0600`. Existing Windows ACLs are not silently rewritten.
pub const IDENTITY_KEY_UNIX_MODE: u32 = 0o600;

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_mode_strategy() -> &'static str {
    if cfg!(unix) {
        "unix_0600"
    } else {
        "windows_owner_only_dacl"
    }
}

/// Slice CK: how identity first-create lands dest without clobber.
///
/// JSON persist still uses replace (CD). Identity first-create must not
/// overwrite a dest that appeared after `exists()` (two processes both saw
/// missing). Windows: `MoveFileExW` **without** `MOVEFILE_REPLACE_EXISTING`.
/// POSIX: `link(tmp, dest)` then unlink tmp — `rename` would replace dest.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_create_exclusive_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_movefileex_noreplace"
    } else {
        "posix_hardlink_exclusive"
    }
}

/// Slice CL: how identity staging tmp is born restricted (before key bytes).
///
/// Unix: `OpenOptions.mode(0o600)` at create (CH). Windows CI applied DACL
/// *after* `File::create` + write — inherited Users/Everyone could read the
/// tmp. Slice CL creates the tmp with the protected DACL on `CreateFileW`.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_tmp_restrict_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_createfile_owner_dacl"
    } else {
        "unix_0600_at_create"
    }
}

/// Slice CM: existing identity ACL is checked at load (no silent repair).
///
/// Unix: group/other bits refuse (CH). Windows: allow ACEs other than
/// owner/SYSTEM/Administrators refuse (Users/Everyone). First-create DACL
/// is still Slice CI/CL; existing dest ACLs are never rewritten.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_existing_acl_strategy() -> &'static str {
    identity_key_mode_strategy()
}

/// Slice CN: NULL DACL (everyone) is refused at load. Unix has no NULL DACL;
/// world-readable is already Slice CH.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_null_dacl_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_null_dacl_refuse"
    } else {
        "unix_mode_covers"
    }
}

/// Slice CO: callback/conditional allow ACEs (XA/ZA/XU) grant access but CM
/// only walked A/OA. Unknown ACE types refuse (fail-closed). Unix mode bits
/// already cover world-readable (CH). Dest ACL is never rewritten.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_callback_ace_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_callback_ace_refuse"
    } else {
        "unix_mode_covers"
    }
}

/// Slice CP: CI first-create is a *protected* DACL (`D:P` / `SE_DACL_PROTECTED`)
/// so parent inheritance cannot add Users. Load used to accept owner-only ACEs
/// without the protected bit. Spawn now refuses. Dest ACL is never rewritten.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_protected_dacl_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_protected_dacl_refuse"
    } else {
        "unix_mode_covers"
    }
}

/// Slice CR: file ACL (CI–CP) is bypassed if Users can write the parent
/// directory (replace/unlink the key). Spawn refuses a world-writable
/// parent. Directory ACL is never rewritten. Volume roots are skipped.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_parent_dir_strategy() -> &'static str {
    if cfg!(windows) {
        "windows_dir_no_users_write"
    } else {
        "unix_dir_no_group_other_write"
    }
}

/// Slice CS: CR walked a missing parent to the first existing ancestor and
/// skipped inherit-only ACEs. `create_dir_all` then inherited Users write onto
/// the new directory. Spawn now mkdir's first and rechecks the created parent.
/// Directory ACL is never rewritten.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_parent_mkdir_recheck_strategy() -> &'static str {
    "mkdir_then_recheck_parent_acl"
}

/// Slice CT: CR/CS reused `should_fsync_dir`, which skips volume roots and
/// relative one-component parents. Identity parent ACL is never skipped:
/// relative paths resolve against cwd; volume-root parents refuse.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn identity_key_parent_unattested_strategy() -> &'static str {
    "absolute_cwd_refuse_volume_root"
}

#[cfg(windows)]
fn wide_path(path: &std::path::Path) -> Result<Vec<u16>, String> {
    use std::os::windows::ffi::OsStrExt;
    let mut w: Vec<u16> = path.as_os_str().encode_wide().collect();
    if w.iter().any(|c| *c == 0) {
        return Err("path contains NUL".into());
    }
    w.push(0);
    Ok(w)
}

#[cfg(windows)]
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn replace_file(
    tmp: &std::path::Path,
    dest: &std::path::Path,
    exclusive: bool,
) -> Result<(), String> {
    windows_replace_file(tmp, dest, exclusive)
}

#[cfg(not(windows))]
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn replace_file(
    tmp: &std::path::Path,
    dest: &std::path::Path,
    exclusive: bool,
) -> Result<(), String> {
    if exclusive {
        std::fs::hard_link(tmp, dest).map_err(|e| {
            if e.kind() == std::io::ErrorKind::AlreadyExists {
                format!("exclusive persist dest exists (refusing clobber): {e}")
            } else {
                format!("exclusive persist link: {e}")
            }
        })?;
        let _ = std::fs::remove_file(tmp);
        Ok(())
    } else {
        std::fs::rename(tmp, dest).map_err(|e| format!("rename tmp: {e}"))
    }
}

#[cfg(windows)]
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn windows_replace_file(
    tmp: &std::path::Path,
    dest: &std::path::Path,
    exclusive: bool,
) -> Result<(), String> {
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(
            lp_existing_file_name: *const u16,
            lp_new_file_name: *const u16,
            dw_flags: u32,
        ) -> i32;
    }
    const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x8;
    const ERROR_FILE_EXISTS: i32 = 80;
    const ERROR_ALREADY_EXISTS: i32 = 183;

    let src = wide_path(tmp)?;
    let dst = wide_path(dest)?;
    let flags = if exclusive {
        MOVEFILE_WRITE_THROUGH
    } else {
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
    };
    // Fail-closed: no unlink-dest fallback. If MoveFileEx fails, persist fails.
    let ok = unsafe { MoveFileExW(src.as_ptr(), dst.as_ptr(), flags) };
    if ok == 0 {
        let err = std::io::Error::last_os_error();
        let dest_exists = matches!(
            err.raw_os_error(),
            Some(ERROR_FILE_EXISTS) | Some(ERROR_ALREADY_EXISTS)
        ) || (err.kind() == std::io::ErrorKind::AlreadyExists);
        if exclusive && dest_exists {
            Err(format!(
                "exclusive persist dest exists (refusing clobber): {err}"
            ))
        } else {
            Err(format!("MoveFileExW replace: {err}"))
        }
    } else {
        Ok(())
    }
}

/// Slice CG: fsync the directory that holds `path` so the replace dirent is durable.
fn fsync_parent_dir(path: &std::path::Path) -> Result<(), String> {
    let parent = match path.parent() {
        Some(p) if !p.as_os_str().is_empty() => p,
        _ => std::path::Path::new("."),
    };
    fsync_dir(parent)
}

#[cfg(not(windows))]
fn fsync_dir(dir: &std::path::Path) -> Result<(), String> {
    let f = std::fs::File::open(dir).map_err(|e| format!("open persist parent dir: {e}"))?;
    f.sync_all()
        .map_err(|e| format!("sync persist parent dir: {e}"))?;
    Ok(())
}

#[cfg(windows)]
fn fsync_dir(dir: &std::path::Path) -> Result<(), String> {
    windows_fsync_dir(dir)
}

fn should_fsync_dir(p: &std::path::Path) -> bool {
    use std::path::Component;
    p.components().any(|c| matches!(c, Component::Normal(_))) && p.components().count() >= 2
}

/// Volume root (`C:\` / `/`) has no `Normal` component. Fsync still skips
/// these via [`should_fsync_dir`]; identity ACL must not.
fn identity_parent_is_volume_root(p: &std::path::Path) -> bool {
    use std::path::Component;
    !p.components().any(|c| matches!(c, Component::Normal(_)))
}

/// Slice CT: relative identity paths are resolved against cwd so parent ACL
/// cannot skip a one-component relative dir.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn identity_key_absolute_path(key_path: &std::path::Path) -> Result<std::path::PathBuf, String> {
    if key_path.as_os_str().is_empty() {
        return Err("identity key path is empty".into());
    }
    if key_path.is_absolute() {
        return Ok(key_path.to_path_buf());
    }
    let cwd = std::env::current_dir().map_err(|e| format!("cwd for identity key: {e}"))?;
    Ok(cwd.join(key_path))
}

/// Slice CR: identity key parent must not be world-writable.
/// Slice CT: never skip this check (no fsync heuristic; volume roots refuse).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn identity_key_parent_dir_ok(key_path: &std::path::Path) -> Result<(), String> {
    let abs = identity_key_absolute_path(key_path)?;
    let Some(parent) = abs.parent().filter(|p| !p.as_os_str().is_empty()) else {
        return Err("identity key path has no parent directory".into());
    };
    let target = if parent.exists() {
        parent.to_path_buf()
    } else {
        let mut cur = parent.to_path_buf();
        loop {
            if cur.exists() {
                break;
            }
            match cur.parent() {
                Some(p) if !p.as_os_str().is_empty() => cur = p.to_path_buf(),
                _ => {
                    return Err("key parent cannot be attested (no existing ancestor)".into());
                }
            }
        }
        cur
    };
    if identity_parent_is_volume_root(&target) {
        return Err("key parent is a volume root (refusing unattested parent ACL)".into());
    }
    identity_persist_dir_acl_ok(&target)
}

/// Slice CS: create a missing identity parent, then CR-check that directory
/// (not an ancestor whose inherit-only write ACEs skip the object itself).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn ensure_identity_key_parent(key_path: &std::path::Path) -> Result<(), String> {
    let abs = identity_key_absolute_path(key_path)?;
    if let Some(parent) = abs.parent() {
        if !parent.as_os_str().is_empty() {
            durable_create_dir_all(parent)?;
        }
    }
    identity_key_parent_dir_ok(&abs)
}

#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn identity_persist_dir_acl_ok(dir: &std::path::Path) -> Result<(), String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(dir)
            .map_err(|e| format!("stat key parent dir: {e}"))?
            .permissions()
            .mode();
        if mode & 0o1000 != 0 {
            return Ok(());
        }
        if mode & 0o022 != 0 {
            return Err(format!(
                "key parent dir mode {:o} allows group/other write",
                mode & 0o777
            ));
        }
        Ok(())
    }
    #[cfg(windows)]
    {
        windows_identity_parent_acl_ok(dir)
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = dir;
        Ok(())
    }
}

/// Slice CJ: `create_dir_all` then fsync created dirs and the first existing
/// ancestor so a crash cannot drop the new dirent. Volume roots are skipped.
fn durable_create_dir_all(dir: &std::path::Path) -> Result<(), String> {
    if dir.as_os_str().is_empty() {
        return Ok(());
    }
    if dir.exists() {
        return Ok(());
    }
    let mut chain: Vec<std::path::PathBuf> = Vec::new();
    let mut cur = dir.to_path_buf();
    loop {
        chain.push(cur.clone());
        if cur.exists() {
            break;
        }
        match cur.parent() {
            Some(p) if !p.as_os_str().is_empty() => cur = p.to_path_buf(),
            _ => break,
        }
    }
    std::fs::create_dir_all(dir).map_err(|e| format!("create persist dir: {e}"))?;
    for p in &chain {
        if should_fsync_dir(p) && p.exists() {
            fsync_dir(p)?;
        }
    }
    Ok(())
}

#[cfg(windows)]
fn windows_fsync_dir(dir: &std::path::Path) -> Result<(), String> {
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateFileW(
            lp_file_name: *const u16,
            dw_desired_access: u32,
            dw_share_mode: u32,
            lp_security_attributes: *const core::ffi::c_void,
            dw_creation_disposition: u32,
            dw_flags_and_attributes: u32,
            h_template_file: *mut core::ffi::c_void,
        ) -> *mut core::ffi::c_void;
        fn FlushFileBuffers(h_file: *mut core::ffi::c_void) -> i32;
        fn CloseHandle(h_object: *mut core::ffi::c_void) -> i32;
    }
    const GENERIC_READ: u32 = 0x8000_0000;
    const GENERIC_WRITE: u32 = 0x4000_0000;
    const FILE_SHARE_READ: u32 = 0x1;
    const FILE_SHARE_WRITE: u32 = 0x2;
    const FILE_SHARE_DELETE: u32 = 0x4;
    const OPEN_EXISTING: u32 = 3;
    const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
    const INVALID_HANDLE_VALUE: isize = -1;

    let w = wide_path(dir)?;
    let handle = unsafe {
        CreateFileW(
            w.as_ptr(),
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            core::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            core::ptr::null_mut(),
        )
    };
    if handle as isize == INVALID_HANDLE_VALUE {
        return Err(format!(
            "CreateFileW persist parent dir: {}",
            std::io::Error::last_os_error()
        ));
    }
    let flushed = unsafe { FlushFileBuffers(handle) };
    let flush_err = std::io::Error::last_os_error();
    unsafe {
        CloseHandle(handle);
    }
    if flushed == 0 {
        return Err(format!("FlushFileBuffers persist parent dir: {flush_err}"));
    }
    Ok(())
}

/// Slice BQ/CD/CE/CG: write tmp + fsync + replace + parent-dir fsync.
/// Destination is never truncated in place and never unlinked before the
/// replacement lands. Parent-dir fsync fail is fail-closed (dest may already
/// be the new file; callers that roll back memory stay conservative).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn atomic_write_file(path: &std::path::Path, body: &[u8]) -> Result<(), String> {
    atomic_write_file_with_mode(path, body, None)
}

/// Like [`atomic_write_file`], with an optional Unix file mode applied to tmp
/// before replace (Slice CH). `None` keeps `File::create` defaults. Windows
/// first-create DACL is Slice CI (`restrict_identity_key_acl` when mode is set).
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn atomic_write_file_with_mode(
    path: &std::path::Path,
    body: &[u8],
    unix_mode: Option<u32>,
) -> Result<(), String> {
    atomic_write_file_inner(path, body, unix_mode, false)
}

/// Slice CK: identity first-create. Same tmp+fsync+parent-dir fsync as
/// [`atomic_write_file_with_mode`], but dest replace is exclusive: fails if
/// dest exists (no clobber). JSON persist still uses replace.
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn atomic_write_file_exclusive(
    path: &std::path::Path,
    body: &[u8],
    unix_mode: Option<u32>,
) -> Result<(), String> {
    atomic_write_file_inner(path, body, unix_mode, true)
}

fn atomic_write_file_inner(
    path: &std::path::Path,
    body: &[u8],
    unix_mode: Option<u32>,
    exclusive: bool,
) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            durable_create_dir_all(parent)?;
        }
    }
    let tmp = external_addrs_tmp_path(path);
    let _inflight = PersistTmpInFlight::claim(tmp.clone());
    unlink_stale_persist_tmps(path, &tmp);
    let write_tmp = (|| -> Result<(), String> {
        let mut f = create_persist_tmp(&tmp, unix_mode)?;
        use std::io::Write;
        f.write_all(body)
            .map_err(|e| format!("write persist tmp: {e}"))?;
        f.sync_all().map_err(|e| format!("sync persist tmp: {e}"))?;
        drop(f);
        // Slice CQ: JSON persist tmp is restricted too (CL covered identity only).
        apply_unix_mode(&tmp, Some(unix_mode.unwrap_or(IDENTITY_KEY_UNIX_MODE)))?;
        restrict_identity_key_acl(&tmp)?;
        Ok(())
    })();
    if let Err(e) = write_tmp {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    if let Err(e) = replace_file(&tmp, path, exclusive) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    if let Err(e) = restrict_identity_key_acl(path) {
        let _ = std::fs::remove_file(path);
        return Err(e);
    }
    fsync_parent_dir(path)
}

fn create_persist_tmp(
    tmp: &std::path::Path,
    unix_mode: Option<u32>,
) -> Result<std::fs::File, String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mode = unix_mode.unwrap_or(IDENTITY_KEY_UNIX_MODE);
        std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(mode)
            .open(tmp)
            .map_err(|e| format!("create persist tmp: {e}"))
    }
    #[cfg(windows)]
    {
        let _ = unix_mode;
        windows_create_identity_tmp(tmp, false)
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = unix_mode;
        std::fs::File::create(tmp).map_err(|e| format!("create persist tmp: {e}"))
    }
}

fn apply_unix_mode(path: &std::path::Path, unix_mode: Option<u32>) -> Result<(), String> {
    #[cfg(unix)]
    {
        if let Some(mode) = unix_mode {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
                .map_err(|e| format!("chmod persist tmp: {e}"))?;
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = (path, unix_mode);
        Ok(())
    }
}

/// Slice CI: Windows identity key gets a protected DACL. Unix is already 0o600.
fn restrict_identity_key_acl(path: &std::path::Path) -> Result<(), String> {
    #[cfg(windows)]
    {
        windows_restrict_owner_dacl(path)
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        Ok(())
    }
}

/// Owner + SYSTEM + Administrators; protected (no Users/Everyone inherit).
#[cfg(windows)]
const IDENTITY_KEY_WINDOWS_SDDL: &str = "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)";

#[cfg(windows)]
fn windows_restrict_owner_dacl(path: &std::path::Path) -> Result<(), String> {
    windows_set_dacl_from_sddl(path, IDENTITY_KEY_WINDOWS_SDDL, true)
}

/// Apply a DACL from SDDL. `protected` sets `PROTECTED_DACL` vs `UNPROTECTED_DACL`.
#[cfg(windows)]
fn windows_set_dacl_from_sddl(
    path: &std::path::Path,
    sddl: &str,
    protected: bool,
) -> Result<(), String> {
    use std::ptr;

    #[link(name = "advapi32")]
    extern "system" {
        fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
            string_security_descriptor: *const u16,
            string_sd_revision: u32,
            security_descriptor: *mut *mut core::ffi::c_void,
            security_descriptor_size: *mut u32,
        ) -> i32;
        fn GetSecurityDescriptorDacl(
            p_security_descriptor: *mut core::ffi::c_void,
            lpb_dacl_present: *mut i32,
            p_dacl: *mut *mut core::ffi::c_void,
            lpb_dacl_defaulted: *mut i32,
        ) -> i32;
        fn SetNamedSecurityInfoW(
            p_object_name: *mut u16,
            object_type: u32,
            security_info: u32,
            psid_owner: *mut core::ffi::c_void,
            psid_group: *mut core::ffi::c_void,
            p_dacl: *mut core::ffi::c_void,
            p_sacl: *mut core::ffi::c_void,
        ) -> u32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn LocalFree(h_mem: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
    }

    const SDDL_REVISION_1: u32 = 1;
    const SE_FILE_OBJECT: u32 = 1;
    const DACL_SECURITY_INFORMATION: u32 = 0x4;
    const PROTECTED_DACL_SECURITY_INFORMATION: u32 = 0x8000_0000;
    const UNPROTECTED_DACL_SECURITY_INFORMATION: u32 = 0x2000_0000;
    const ERROR_SUCCESS: u32 = 0;
    let protect_flag = if protected {
        PROTECTED_DACL_SECURITY_INFORMATION
    } else {
        UNPROTECTED_DACL_SECURITY_INFORMATION
    };

    let mut sddl_w: Vec<u16> = sddl.encode_utf16().collect();
    sddl_w.push(0);
    let mut sd: *mut core::ffi::c_void = ptr::null_mut();
    let ok = unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl_w.as_ptr(),
            SDDL_REVISION_1,
            &mut sd,
            ptr::null_mut(),
        )
    };
    if ok == 0 || sd.is_null() {
        return Err(format!(
            "ConvertStringSecurityDescriptor: {}",
            std::io::Error::last_os_error()
        ));
    }
    let mut dacl_present: i32 = 0;
    let mut dacl_defaulted: i32 = 0;
    let mut dacl: *mut core::ffi::c_void = ptr::null_mut();
    let got =
        unsafe { GetSecurityDescriptorDacl(sd, &mut dacl_present, &mut dacl, &mut dacl_defaulted) };
    if got == 0 || dacl_present == 0 || dacl.is_null() {
        unsafe {
            LocalFree(sd);
        }
        return Err("identity key DACL missing from SDDL".into());
    }
    let mut wpath = wide_path(path)?;
    let err = unsafe {
        SetNamedSecurityInfoW(
            wpath.as_mut_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | protect_flag,
            ptr::null_mut(),
            ptr::null_mut(),
            dacl,
            ptr::null_mut(),
        )
    };
    unsafe {
        LocalFree(sd);
    }
    if err != ERROR_SUCCESS {
        return Err(format!(
            "SetNamedSecurityInfoW identity DACL: {}",
            std::io::Error::from_raw_os_error(err as i32)
        ));
    }
    Ok(())
}

/// Slice CL: create identity tmp with the protected DACL on the create
/// syscall so key bytes are never written under an inherited Users ACL.
/// Leftover tmp is locked down and unlinked, then CREATE_NEW (one retry).
#[cfg(windows)]
fn windows_create_identity_tmp(
    tmp: &std::path::Path,
    retried: bool,
) -> Result<std::fs::File, String> {
    use std::os::windows::io::{FromRawHandle, RawHandle};
    use std::ptr;

    #[repr(C)]
    struct SecurityAttributes {
        n_length: u32,
        lp_security_descriptor: *mut core::ffi::c_void,
        b_inherit_handle: i32,
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateFileW(
            lp_file_name: *const u16,
            dw_desired_access: u32,
            dw_share_mode: u32,
            lp_security_attributes: *const core::ffi::c_void,
            dw_creation_disposition: u32,
            dw_flags_and_attributes: u32,
            h_template_file: *mut core::ffi::c_void,
        ) -> *mut core::ffi::c_void;
        fn LocalFree(h_mem: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
    }
    #[link(name = "advapi32")]
    extern "system" {
        fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
            string_security_descriptor: *const u16,
            string_sd_revision: u32,
            security_descriptor: *mut *mut core::ffi::c_void,
            security_descriptor_size: *mut u32,
        ) -> i32;
    }

    const GENERIC_WRITE: u32 = 0x4000_0000;
    const CREATE_NEW: u32 = 1;
    const FILE_ATTRIBUTE_NORMAL: u32 = 0x80;
    const INVALID_HANDLE_VALUE: isize = -1;
    const SDDL_REVISION_1: u32 = 1;
    const ERROR_FILE_EXISTS: i32 = 80;
    const ERROR_ALREADY_EXISTS: i32 = 183;

    let mut sddl: Vec<u16> = IDENTITY_KEY_WINDOWS_SDDL.encode_utf16().collect();
    sddl.push(0);
    let mut sd: *mut core::ffi::c_void = ptr::null_mut();
    let ok = unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl.as_ptr(),
            SDDL_REVISION_1,
            &mut sd,
            ptr::null_mut(),
        )
    };
    if ok == 0 || sd.is_null() {
        return Err(format!(
            "ConvertStringSecurityDescriptor identity tmp: {}",
            std::io::Error::last_os_error()
        ));
    }
    let sa = SecurityAttributes {
        n_length: std::mem::size_of::<SecurityAttributes>() as u32,
        lp_security_descriptor: sd,
        b_inherit_handle: 0,
    };
    let w = match wide_path(tmp) {
        Ok(w) => w,
        Err(e) => {
            unsafe {
                LocalFree(sd);
            }
            return Err(e);
        }
    };
    let handle = unsafe {
        CreateFileW(
            w.as_ptr(),
            GENERIC_WRITE,
            0,
            &sa as *const SecurityAttributes as *const core::ffi::c_void,
            CREATE_NEW,
            FILE_ATTRIBUTE_NORMAL,
            ptr::null_mut(),
        )
    };
    unsafe {
        LocalFree(sd);
    }
    if handle as isize == INVALID_HANDLE_VALUE {
        let err = std::io::Error::last_os_error();
        let exists = matches!(
            err.raw_os_error(),
            Some(ERROR_FILE_EXISTS) | Some(ERROR_ALREADY_EXISTS)
        ) || (err.kind() == std::io::ErrorKind::AlreadyExists);
        if exists && !retried {
            windows_restrict_owner_dacl(tmp)?;
            std::fs::remove_file(tmp).map_err(|e| format!("unlink leftover identity tmp: {e}"))?;
            return windows_create_identity_tmp(tmp, true);
        }
        return Err(format!("CreateFileW identity tmp: {err}"));
    }
    Ok(unsafe { std::fs::File::from_raw_handle(handle as RawHandle) })
}

#[cfg(windows)]
struct WindowsNamedDacl {
    sddl: String,
    owner_sid: String,
    dacl_missing: bool,
    protected: bool,
}

/// Slice CM: existing Windows identity must not grant Users/Everyone.
/// Reads DACL as SDDL; never rewrites the file.
#[cfg(windows)]
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn windows_identity_acl_ok(path: &std::path::Path) -> Result<(), String> {
    let info = windows_read_named_dacl(path)?;
    if info.dacl_missing {
        return Err("key file DACL missing (NULL DACL grants everyone)".into());
    }
    if !info.protected {
        return Err("key file DACL is not protected (inheritance can grant Users)".into());
    }
    windows_identity_dacl_sddl_ok(&info.sddl, &info.owner_sid)
}

/// Slice CR: parent directory must not grant Users/Everyone write/delete-child.
#[cfg(windows)]
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn windows_identity_parent_acl_ok(path: &std::path::Path) -> Result<(), String> {
    let info = windows_read_named_dacl(path)?;
    if info.dacl_missing {
        return Err("key parent dir NULL DACL (grants everyone write)".into());
    }
    windows_identity_dir_sddl_ok(&info.sddl, &info.owner_sid)
}

#[cfg(windows)]
fn windows_read_named_dacl(path: &std::path::Path) -> Result<WindowsNamedDacl, String> {
    use std::ptr;

    #[link(name = "advapi32")]
    extern "system" {
        fn GetNamedSecurityInfoW(
            p_object_name: *mut u16,
            object_type: u32,
            security_info: u32,
            ppsid_owner: *mut *mut core::ffi::c_void,
            ppsid_group: *mut *mut core::ffi::c_void,
            pp_dacl: *mut *mut core::ffi::c_void,
            pp_sacl: *mut *mut core::ffi::c_void,
            pp_security_descriptor: *mut *mut core::ffi::c_void,
        ) -> u32;
        fn ConvertSecurityDescriptorToStringSecurityDescriptorW(
            security_descriptor: *mut core::ffi::c_void,
            requested_string_sd_revision: u32,
            security_information: u32,
            string_security_descriptor: *mut *mut u16,
            string_security_descriptor_len: *mut u32,
        ) -> i32;
        fn ConvertSidToStringSidW(sid: *mut core::ffi::c_void, string_sid: *mut *mut u16) -> i32;
        fn GetSecurityDescriptorDacl(
            p_security_descriptor: *mut core::ffi::c_void,
            lpb_dacl_present: *mut i32,
            p_dacl: *mut *mut core::ffi::c_void,
            lpb_dacl_defaulted: *mut i32,
        ) -> i32;
        fn GetSecurityDescriptorControl(
            p_security_descriptor: *mut core::ffi::c_void,
            p_control: *mut u16,
            lpdw_revision: *mut u32,
        ) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn LocalFree(h_mem: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
    }

    const SE_FILE_OBJECT: u32 = 1;
    const OWNER_SECURITY_INFORMATION: u32 = 0x1;
    const DACL_SECURITY_INFORMATION: u32 = 0x4;
    const SDDL_REVISION_1: u32 = 1;
    const ERROR_SUCCESS: u32 = 0;
    const SE_DACL_PROTECTED: u16 = 0x1000;

    let mut wpath = wide_path(path)?;
    let mut owner: *mut core::ffi::c_void = ptr::null_mut();
    let mut sd: *mut core::ffi::c_void = ptr::null_mut();
    let err = unsafe {
        GetNamedSecurityInfoW(
            wpath.as_mut_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            &mut sd,
        )
    };
    if err != ERROR_SUCCESS || sd.is_null() {
        return Err(format!(
            "GetNamedSecurityInfoW identity DACL: {}",
            std::io::Error::from_raw_os_error(err as i32)
        ));
    }
    let mut owner_sid = String::new();
    if !owner.is_null() {
        let mut p: *mut u16 = ptr::null_mut();
        if unsafe { ConvertSidToStringSidW(owner, &mut p) } != 0 && !p.is_null() {
            owner_sid = utf16_ptr_to_string(p);
            unsafe {
                LocalFree(p as *mut core::ffi::c_void);
            }
        }
    }
    let mut dacl_present: i32 = 0;
    let mut dacl_defaulted: i32 = 0;
    let mut dacl: *mut core::ffi::c_void = ptr::null_mut();
    let got =
        unsafe { GetSecurityDescriptorDacl(sd, &mut dacl_present, &mut dacl, &mut dacl_defaulted) };
    if got == 0 || dacl_present == 0 || dacl.is_null() {
        unsafe {
            LocalFree(sd);
        }
        return Ok(WindowsNamedDacl {
            sddl: String::new(),
            owner_sid,
            dacl_missing: true,
            protected: false,
        });
    }
    let mut control: u16 = 0;
    let mut revision: u32 = 0;
    let ctl = unsafe { GetSecurityDescriptorControl(sd, &mut control, &mut revision) };
    if ctl == 0 {
        unsafe {
            LocalFree(sd);
        }
        return Err(format!(
            "GetSecurityDescriptorControl identity DACL: {}",
            std::io::Error::last_os_error()
        ));
    }
    let protected = control & SE_DACL_PROTECTED != 0;
    let mut sddl_ptr: *mut u16 = ptr::null_mut();
    let ok = unsafe {
        ConvertSecurityDescriptorToStringSecurityDescriptorW(
            sd,
            SDDL_REVISION_1,
            DACL_SECURITY_INFORMATION,
            &mut sddl_ptr,
            ptr::null_mut(),
        )
    };
    if ok == 0 || sddl_ptr.is_null() {
        unsafe {
            LocalFree(sd);
        }
        return Err(format!(
            "ConvertSecurityDescriptorToString identity DACL: {}",
            std::io::Error::last_os_error()
        ));
    }
    let sddl = utf16_ptr_to_string(sddl_ptr);
    unsafe {
        LocalFree(sddl_ptr as *mut core::ffi::c_void);
        LocalFree(sd);
    }
    Ok(WindowsNamedDacl {
        sddl,
        owner_sid,
        dacl_missing: false,
        protected,
    })
}

#[cfg(windows)]
fn utf16_ptr_to_string(p: *const u16) -> String {
    if p.is_null() {
        return String::new();
    }
    let mut len = 0usize;
    while unsafe { *p.add(len) } != 0 {
        len += 1;
    }
    String::from_utf16_lossy(unsafe { std::slice::from_raw_parts(p, len) })
}

/// Allow ACEs must be owner / SYSTEM / Administrators only (CI SDDL).
/// Slice CO: callback/conditional allow (XA/ZA/XU) grant access — same walk.
/// Unknown ACE types and unparseable ACEs refuse (fail-closed).
/// Slice CP: DACL header must include protected flag `P` (CI invariant).
#[cfg(windows)]
fn windows_identity_dacl_sddl_ok(sddl: &str, owner_sid: &str) -> Result<(), String> {
    if sddl.to_ascii_uppercase().contains("NO_ACCESS_CONTROL") {
        return Err("key file NULL DACL (grants everyone)".into());
    }
    let flags = identity_dacl_header_flags(sddl)?;
    if !flags.to_ascii_uppercase().contains('P') {
        return Err("key file DACL is not protected (inheritance can grant Users)".into());
    }
    for ace in identity_dacl_ace_bodies(sddl)? {
        let parts: Vec<&str> = ace.split(';').collect();
        if parts.len() < 6 {
            return Err(format!("key file DACL ACE unparseable: {ace}"));
        }
        let kind = parts[0].trim().to_ascii_uppercase();
        if identity_ace_kind_is_audit_or_deny(&kind) {
            continue;
        }
        if !identity_ace_kind_grants(&kind) {
            return Err(format!("key file DACL unknown ACE type {kind}"));
        }
        let trustee = parts[5].trim();
        if identity_trustee_allowed(trustee, owner_sid) {
            continue;
        }
        return Err(format!(
            "key file DACL allows {trustee} via {kind} (need owner+SYSTEM+Admin only)"
        ));
    }
    Ok(())
}

/// Flags between `D:` and the first ACE `(`. First-create Convert emits `PAI`.
#[cfg(windows)]
fn identity_dacl_header_flags(sddl: &str) -> Result<&str, String> {
    let u = sddl.to_ascii_uppercase();
    let Some(idx) = u.find("D:") else {
        return Err("key file SDDL missing DACL".into());
    };
    let rest = &sddl[idx + 2..];
    let end = rest.find('(').unwrap_or(rest.len());
    Ok(&rest[..end])
}

/// SDDL DACL ACEs are `(ace)` groups; callback conditions nest extra `(...)`.
#[cfg(windows)]
fn identity_dacl_ace_bodies(sddl: &str) -> Result<Vec<&str>, String> {
    let bytes = sddl.as_bytes();
    let mut aces = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'(' {
            i += 1;
            continue;
        }
        let start = i + 1;
        let mut depth = 1usize;
        i += 1;
        while i < bytes.len() && depth > 0 {
            match bytes[i] {
                b'(' => depth += 1,
                b')' => depth -= 1,
                _ => {}
            }
            i += 1;
        }
        if depth != 0 {
            return Err("key file DACL ACE parentheses unbalanced".into());
        }
        aces.push(&sddl[start..i - 1]);
    }
    Ok(aces)
}

#[cfg(windows)]
fn identity_ace_kind_grants(kind: &str) -> bool {
    matches!(kind, "A" | "OA" | "XA" | "ZA" | "XU")
}

#[cfg(windows)]
fn identity_ace_kind_is_audit_or_deny(kind: &str) -> bool {
    matches!(
        kind,
        "D" | "OD" | "XD" | "AU" | "AL" | "OU" | "OL" | "ML" | "RA" | "SP"
    )
}

#[cfg(windows)]
fn identity_trustee_allowed(trustee: &str, owner_sid: &str) -> bool {
    let t = trustee.trim();
    if t.eq_ignore_ascii_case("OW")
        || t.eq_ignore_ascii_case("SY")
        || t.eq_ignore_ascii_case("BA")
        || t.eq_ignore_ascii_case("CO")
        || t.eq_ignore_ascii_case("S-1-5-18")
        || t.eq_ignore_ascii_case("S-1-5-32-544")
    {
        return true;
    }
    !owner_sid.is_empty() && t.eq_ignore_ascii_case(owner_sid)
}

/// Slice CR: parent-dir threat is world/Users write, not "only owner".
/// A user Temp dir commonly grants the current user FA while owner is
/// Administrators — that must pass. Users/Everyone/AU write must not.
#[cfg(windows)]
fn identity_trustee_is_world(trustee: &str) -> bool {
    let t = trustee.trim();
    t.eq_ignore_ascii_case("WD")
        || t.eq_ignore_ascii_case("BU")
        || t.eq_ignore_ascii_case("AU")
        || t.eq_ignore_ascii_case("AN")
        || t.eq_ignore_ascii_case("BG")
        || t.eq_ignore_ascii_case("S-1-1-0")
        || t.eq_ignore_ascii_case("S-1-5-32-545")
        || t.eq_ignore_ascii_case("S-1-5-11")
        || t.eq_ignore_ascii_case("S-1-5-7")
        || t.eq_ignore_ascii_case("S-1-5-32-546")
}

/// Inherit-only ACEs do not apply to the directory object itself.
/// Flags are concatenated two-letter codes (`OI`/`CI`/`IO`); substring
/// `"IO"` must not match `"OI"` or `"CI"+"OI"` (`CIOI`).
#[cfg(windows)]
fn identity_ace_flags_inherit_only(flags: &str) -> bool {
    let u = flags.trim().to_ascii_uppercase();
    if u.len() % 2 != 0 {
        return false;
    }
    u.as_bytes().chunks(2).any(|c| c == b"IO")
}

/// Directory write/delete-child bits that let Users replace a child key file.
#[cfg(windows)]
fn identity_sddl_rights_grant_dir_write(rights: &str) -> bool {
    let r = rights.trim().to_ascii_uppercase();
    if let Some(hex) = r.strip_prefix("0X") {
        if let Ok(v) = u32::from_str_radix(hex, 16) {
            const FILE_WRITE_DATA: u32 = 0x0000_0002;
            const FILE_APPEND_DATA: u32 = 0x0000_0004;
            const FILE_DELETE_CHILD: u32 = 0x0000_0040;
            const DELETE: u32 = 0x0001_0000;
            const WRITE_DAC: u32 = 0x0004_0000;
            const WRITE_OWNER: u32 = 0x0008_0000;
            const GENERIC_WRITE: u32 = 0x4000_0000;
            const GENERIC_ALL: u32 = 0x1000_0000;
            let mask = FILE_WRITE_DATA
                | FILE_APPEND_DATA
                | FILE_DELETE_CHILD
                | DELETE
                | WRITE_DAC
                | WRITE_OWNER
                | GENERIC_WRITE
                | GENERIC_ALL;
            return v & mask != 0;
        }
    }
    ["FA", "FW", "GA", "GW", "WD", "WO", "SD", "DC", "CC"]
        .iter()
        .any(|code| r.contains(code))
}

/// Slice CR: parent dir may grant the current user / owner FA, and Users RX
/// (list), but not Users/Everyone/AU write/delete-child.
#[cfg(windows)]
fn windows_identity_dir_sddl_ok(sddl: &str, _owner_sid: &str) -> Result<(), String> {
    if sddl.to_ascii_uppercase().contains("NO_ACCESS_CONTROL") {
        return Err("key parent dir NULL DACL (grants everyone write)".into());
    }
    for ace in identity_dacl_ace_bodies(sddl)? {
        let parts: Vec<&str> = ace.split(';').collect();
        if parts.len() < 6 {
            return Err(format!("key parent dir DACL ACE unparseable: {ace}"));
        }
        let kind = parts[0].trim().to_ascii_uppercase();
        if identity_ace_kind_is_audit_or_deny(&kind) {
            continue;
        }
        if !identity_ace_kind_grants(&kind) {
            return Err(format!("key parent dir DACL unknown ACE type {kind}"));
        }
        if identity_ace_flags_inherit_only(parts[1]) {
            continue;
        }
        let trustee = parts[5].trim();
        if !identity_trustee_is_world(trustee) {
            continue;
        }
        if identity_sddl_rights_grant_dir_write(parts[2]) {
            return Err(format!(
                "key parent dir DACL grants {trustee} write via {kind}"
            ));
        }
    }
    Ok(())
}

/// Test/lab helper: write a NULL DACL (everyone). Not used on the spawn path.
#[cfg(windows)]
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
fn windows_set_null_dacl(path: &std::path::Path) -> Result<(), String> {
    #[link(name = "advapi32")]
    extern "system" {
        fn SetNamedSecurityInfoW(
            p_object_name: *mut u16,
            object_type: u32,
            security_info: u32,
            psid_owner: *mut core::ffi::c_void,
            psid_group: *mut core::ffi::c_void,
            p_dacl: *mut core::ffi::c_void,
            p_sacl: *mut core::ffi::c_void,
        ) -> u32;
    }
    const SE_FILE_OBJECT: u32 = 1;
    const DACL_SECURITY_INFORMATION: u32 = 0x4;
    const ERROR_SUCCESS: u32 = 0;
    let mut wpath = wide_path(path)?;
    let err = unsafe {
        SetNamedSecurityInfoW(
            wpath.as_mut_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            core::ptr::null_mut(),
        )
    };
    if err != ERROR_SUCCESS {
        return Err(format!(
            "SetNamedSecurityInfoW NULL DACL: {}",
            std::io::Error::from_raw_os_error(err as i32)
        ));
    }
    Ok(())
}

/// Slice BQ/CD: advertised-externals JSON via [`atomic_write_file`].
#[cfg_attr(not(feature = "libp2p"), allow(dead_code))]
pub fn save_external_addrs_file(path: &std::path::Path, addrs: &[String]) -> Result<(), String> {
    if addrs.len() > MAX_ADVERTISED_EXTERNAL_ADDRS {
        return Err(format!(
            "advertised externals: {} exceeds hard max {}",
            addrs.len(),
            MAX_ADVERTISED_EXTERNAL_ADDRS
        ));
    }
    if addrs.iter().any(|a| multiaddr_is_p2p_circuit(a)) {
        return Err(CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_MSG.into());
    }
    let body = encode_external_addrs_json(addrs)?;
    atomic_write_file(path, body.as_bytes())
}

#[cfg(feature = "libp2p")]
fn persist_external_addrs_file(path: &str, addrs: &[String]) -> Result<(), String> {
    if path.is_empty() {
        return Ok(());
    }
    save_external_addrs_file(std::path::Path::new(path), addrs)
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
        atomic_write_file, atomic_write_file_exclusive, behaviour_external_confirmed_strategy,
        behaviour_external_expired_strategy, circuit_excluded_from_external_book_strategy,
        external_addrs_replace_strategy, identity_create_exclusive_strategy,
        identity_key_callback_ace_strategy, identity_key_existing_acl_strategy,
        identity_key_mode_strategy, identity_key_null_dacl_strategy,
        identity_key_parent_dir_strategy, identity_key_parent_mkdir_recheck_strategy,
        identity_key_parent_unattested_strategy, identity_key_protected_dacl_strategy,
        identity_key_tmp_restrict_strategy, libp2p_available,
        observed_external_charge_key_strategy, persist_external_charge_key_strategy,
        persist_json_acl_strategy, persist_mkdir_fsync_strategy, persist_parent_dir_fsync_strategy,
        persist_tmp_stale_tid_strategy, persist_tmp_strategy,
        relay_client_circuit_external_strategy, ABS_GOSSIP_BLOCKS_TOPIC,
        ABS_IDENTIFY_PROTOCOL_VERSION, ABS_KAD_PROTOCOL, ABS_RENDEZVOUS_NAMESPACE,
        ABS_WIRE_PROTOCOL, CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_MSG,
        DEFAULT_BOOTSTRAP_DIAL_TIMEOUT_SECS, DEFAULT_IDENTIFY_INTERVAL_MS,
        DEFAULT_IDLE_CONNECTION_TIMEOUT_SECS, DEFAULT_MAX_DIALS, DEFAULT_MDNS_TTL_SECS,
        DEFAULT_PING_INTERVAL_SECS, DEFAULT_PING_MAX_FAILS, DEFAULT_PING_TIMEOUT_SECS,
        DEFAULT_RECONNECT_BASE_MS, DEFAULT_RECONNECT_DIAL_TIMEOUT_SECS,
        DEFAULT_RECONNECT_MAX_ATTEMPTS, DEFAULT_RECONNECT_MAX_MS, DEFAULT_SCORE_GRAYLIST_THRESHOLD,
        DEFAULT_WIRE_TIMEOUT_SECS, IDENTITY_KEY_UNIX_MODE, LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX,
        MAX_ADVERTISED_EXTERNAL_ADDRS, MAX_WIRE_BYTES,
    };
    use async_trait::async_trait;
    use futures::prelude::*;
    #[allow(deprecated)]
    use libp2p::bandwidth::BandwidthSinks;
    use libp2p::core::transport::ListenerId;
    use libp2p::core::transport::PortUse;
    use libp2p::core::{ConnectedPoint, Endpoint};
    use libp2p::multiaddr::Protocol;
    use libp2p::{
        allow_block_list,
        allow_block_list::{AllowedPeers, BlockedPeers},
        autonat, connection_limits, dcutr, gossipsub, identify,
        identity::Keypair,
        kad::{self, store::MemoryStore},
        mdns, noise, ping, relay, rendezvous, request_response,
        swarm::{
            behaviour::toggle::Toggle, ConnectionDenied, ConnectionError, ConnectionId, DialError,
            FromSwarm, ListenError, NetworkBehaviour, StreamUpgradeError, SwarmEvent, ToSwarm,
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
    use std::ops::{Deref, DerefMut};
    use std::path::Path;
    use std::sync::{Arc, Mutex};
    use std::task::{Context, Poll};
    use std::time::Duration;
    use tokio::sync::{mpsc, oneshot};

    fn identity_key_mode_ok(path: &Path) -> Result<(), String> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(path)
                .map_err(|e| format!("stat key: {e}"))?
                .permissions()
                .mode();
            if mode & 0o077 != 0 {
                return Err(format!(
                    "key file mode {:o} allows group/other (need 0600)",
                    mode & 0o777
                ));
            }
            Ok(())
        }
        #[cfg(windows)]
        {
            super::windows_identity_acl_ok(path)
        }
        #[cfg(not(any(unix, windows)))]
        {
            let _ = path;
            Ok(())
        }
    }

    fn load_or_create_keypair(path: &Path) -> Result<Keypair, String> {
        // Slice CT: relative paths resolve against cwd; volume-root parents refuse.
        let path = super::identity_key_absolute_path(path)?;
        // Slice CR/CS: world-writable parent can replace a locked key file.
        // Mkdir first so the check sees the created dir, not an ancestor.
        super::ensure_identity_key_parent(&path)?;
        if path.exists() {
            // Slice CH: existing world-readable key refuses spawn (no silent chmod).
            // Slice CM: existing Windows Users/Everyone DACL refuses spawn (no silent rewrite).
            identity_key_mode_ok(&path)?;
            let bytes = std::fs::read(&path).map_err(|e| format!("read key: {e}"))?;
            Keypair::from_protobuf_encoding(&bytes).map_err(|e| format!("decode key: {e}"))
        } else {
            let kp = Keypair::generate_ed25519();
            let enc = kp
                .to_protobuf_encoding()
                .map_err(|e| format!("encode key: {e}"))?;
            // Slice CF: dest is created via tmp+fsync+replace. Existing files are
            // never overwritten (corrupt key must fail closed, not mint a new PeerId).
            // Slice CH: Unix first-create is 0o600 (tmp mode before replace).
            // Slice CK: exclusive dest create — REPLACE_EXISTING / rename would
            // clobber a dest that appeared after exists() (two first-creates).
            atomic_write_file_exclusive(&path, &enc, Some(IDENTITY_KEY_UNIX_MODE))
                .map_err(|e| format!("write key: {e}"))?;
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
        atomic_write_file(path, body.as_bytes())
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
            // Slice BE: honor explicit forget until clear / restart.
            if st.peerstore_forgotten.contains(peer_id) {
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
            entry.push(ma.clone());
            st.peerstore_learned = st.peerstore_learned.saturating_add(1);
            (st.peerstore_path.clone(), st.peerstore.clone())
        } else {
            return;
        };
        // Slice CE: fail-closed persist — do not keep a learned addr that never landed on disk.
        if let Err(e) = save_bootstrap_peers(Path::new(&persist.0), &persist.1) {
            if let Ok(mut st) = state.lock() {
                if let Some(entry) = st.peerstore.get_mut(peer_id) {
                    entry.retain(|a| a != &ma);
                    if entry.is_empty() {
                        st.peerstore.remove(peer_id);
                    }
                }
                st.peerstore_learned = st.peerstore_learned.saturating_sub(1);
                st.last_error = format!("peerstore persist: {e}");
            }
        }
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

    /// Slice CW: circuit `/p2p-circuit` must not occupy rust-libp2p
    /// `ExternalAddresses` (Identify / Kad / Relay / rendezvous PeerRecord).
    /// Circuit is excluded from the unique advertised cap, so adding it to the
    /// crate book of 20 after 20 charged unique addrs silently evicts a charged
    /// addr. Advertise circuit via Capped* `NewListenAddr` only.
    fn swarm_may_add_external_address(ma: &Multiaddr) -> bool {
        !ma.iter().any(|p| matches!(p, Protocol::P2pCircuit))
    }

    fn swarm_add_external_if_charged<B: NetworkBehaviour>(
        swarm: &mut libp2p::Swarm<B>,
        ma: Multiaddr,
    ) {
        if swarm_may_add_external_address(&ma) {
            swarm.add_external_address(ma);
        }
    }

    /// Slice CY: AutoNAT/UPnP `ExternalAddrConfirmed` occupies the crate book
    /// unless we admit first. Circuit never occupies. Canonical charge key
    /// (no trailing `/p2p/<peer>`) so suffix variants cannot evict a charged
    /// listen/operator addr.
    fn gated_external_confirmed(st: &mut NodeState, ma: &Multiaddr) -> Option<Multiaddr> {
        if !swarm_may_add_external_address(ma) {
            return None;
        }
        let key = advertised_charge_key(ma);
        if advertised_already_charged(st, &key) || admit_aux_advertised_external(st, &key).is_ok() {
            key.parse().ok()
        } else {
            None
        }
    }

    /// Identify / DCUtR candidates often append `/p2p/<local>`. Charge against the
    /// same unique key as listen-derived / operator books (no trailing peer id).
    /// Lives next to Capped* wrappers (same `mod enabled` scope as the call sites).
    fn advertised_charge_key(addr: &Multiaddr) -> String {
        let mut ma = addr.clone();
        if matches!(ma.iter().last(), Some(Protocol::P2p(_))) {
            let _ = ma.pop();
        }
        ma.to_string()
    }

    fn advertised_query_key(s: &str) -> String {
        s.parse::<Multiaddr>()
            .map(|ma| advertised_charge_key(&ma))
            .unwrap_or_else(|_| s.to_string())
    }

    /// Slice DA: expire the crate slot we occupied at confirm (canonical key).
    /// Circuit never occupies the book — omit expire as well.
    fn gated_external_expired(ma: &Multiaddr) -> Option<Multiaddr> {
        if !swarm_may_add_external_address(ma) {
            return None;
        }
        advertised_charge_key(ma).parse().ok()
    }

    fn swarm_remove_charged<B: NetworkBehaviour>(swarm: &mut libp2p::Swarm<B>, ma: Multiaddr) {
        let key = advertised_charge_key(&ma);
        if let Ok(kma) = key.parse::<Multiaddr>() {
            if kma != ma {
                swarm.remove_external_address(&kma);
            }
        }
        swarm.remove_external_address(&ma);
    }

    /// Slice BV: Identify 0.45 has no `hide_listen_addrs`. Forward NewListenAddr
    /// into identify only when the addr is circuit (uncapped) or charged against
    /// the shared advertised cap. Slice CC: also omit uncharged
    /// `NewExternalAddrCandidate` from Identify poll (no swarm-wide leak).
    struct CappedIdentify {
        inner: identify::Behaviour,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedIdentify {
        fn new(inner: identify::Behaviour, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }

        fn push(&mut self, peers: Vec<PeerId>) {
            self.inner.push(peers);
        }
    }

    impl NetworkBehaviour for CappedIdentify {
        type ConnectionHandler = <identify::Behaviour as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = identify::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            let forward = match &event {
                FromSwarm::NewListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    let is_circuit = ev.addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                    if is_circuit {
                        true
                    } else {
                        match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &s)
                                    || admit_listen_derived_external(&mut st, &s).is_ok()
                                {
                                    true
                                } else {
                                    st.identify_listen_addr_omitted =
                                        st.identify_listen_addr_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        }
                    }
                }
                _ => true,
            };
            if forward {
                self.inner.on_swarm_event(event);
            }
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            loop {
                match self.inner.poll(cx) {
                    Poll::Ready(ToSwarm::NewExternalAddrCandidate(addr)) => {
                        let is_circuit = addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                        if is_circuit {
                            return Poll::Ready(ToSwarm::NewExternalAddrCandidate(addr));
                        }
                        let key = advertised_charge_key(&addr);
                        let forward = match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &key) {
                                    true
                                } else {
                                    st.identify_candidate_omitted =
                                        st.identify_candidate_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        };
                        if forward {
                            let emit = key.parse::<Multiaddr>().unwrap_or(addr);
                            return Poll::Ready(ToSwarm::NewExternalAddrCandidate(emit));
                        }
                    }
                    other => return other,
                }
            }
        }
    }

    /// Slice BW: mDNS 0.46 advertises every NewListenAddr via DNS-SD.
    /// Forward into mdns only when the addr is circuit (uncapped) or charged
    /// against the shared advertised cap. Uncharged expansion sockets stay
    /// listening but are omitted from mDNS (not a silent LAN leak).
    struct CappedMdns {
        inner: mdns::tokio::Behaviour,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedMdns {
        fn new(inner: mdns::tokio::Behaviour, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }
    }

    impl NetworkBehaviour for CappedMdns {
        type ConnectionHandler = <mdns::tokio::Behaviour as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = mdns::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            let forward = match &event {
                FromSwarm::NewListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    let is_circuit = ev.addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                    if is_circuit {
                        true
                    } else {
                        match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &s)
                                    || admit_listen_derived_external(&mut st, &s).is_ok()
                                {
                                    if !st.mdns_advertised_listen.iter().any(|a| a == &s) {
                                        st.mdns_advertised_listen.push(s);
                                    }
                                    true
                                } else {
                                    st.mdns_listen_addr_omitted =
                                        st.mdns_listen_addr_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        }
                    }
                }
                FromSwarm::ExpiredListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    if let Ok(mut st) = self.state.lock() {
                        st.mdns_advertised_listen.retain(|a| a != &s);
                    }
                    true
                }
                _ => true,
            };
            if forward {
                self.inner.on_swarm_event(event);
            }
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            self.inner.poll(cx)
        }
    }

    /// Slice BX: kad 0.46 fills `ListenAddresses` from every NewListenAddr
    /// and may return them as local provider addrs. Forward into Kademlia
    /// only when circuit (uncapped) or charged against the shared advertised
    /// cap. Uncharged expansion sockets stay listening but are omitted from
    /// DHT local addrs (not a silent leak).
    struct CappedKad {
        inner: kad::Behaviour<MemoryStore>,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedKad {
        fn new(inner: kad::Behaviour<MemoryStore>, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }
    }

    impl Deref for CappedKad {
        type Target = kad::Behaviour<MemoryStore>;
        fn deref(&self) -> &Self::Target {
            &self.inner
        }
    }

    impl DerefMut for CappedKad {
        fn deref_mut(&mut self) -> &mut Self::Target {
            &mut self.inner
        }
    }

    impl NetworkBehaviour for CappedKad {
        type ConnectionHandler =
            <kad::Behaviour<MemoryStore> as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = kad::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            let forward = match &event {
                FromSwarm::NewListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    let is_circuit = ev.addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                    if is_circuit {
                        true
                    } else {
                        match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &s)
                                    || admit_listen_derived_external(&mut st, &s).is_ok()
                                {
                                    if !st.kad_advertised_listen.iter().any(|a| a == &s) {
                                        st.kad_advertised_listen.push(s);
                                    }
                                    true
                                } else {
                                    st.kad_listen_addr_omitted =
                                        st.kad_listen_addr_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        }
                    }
                }
                FromSwarm::ExpiredListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    if let Ok(mut st) = self.state.lock() {
                        st.kad_advertised_listen.retain(|a| a != &s);
                    }
                    true
                }
                _ => true,
            };
            if forward {
                self.inner.on_swarm_event(event);
            }
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            self.inner.poll(cx)
        }
    }

    /// Slice BY: AutoNAT v1 probes every listen addr (plus candidates).
    /// Forward NewListenAddr into autonat only when circuit (uncapped) or
    /// charged against the shared advertised cap. Uncharged expansion sockets
    /// stay listening but are omitted from AutoNAT probes (not a silent leak).
    /// Slice CY: ExternalAddrConfirmed is admit-canonical-or-omit (crate book).
    struct CappedAutonat {
        inner: autonat::Behaviour,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedAutonat {
        fn new(inner: autonat::Behaviour, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }
    }

    impl Deref for CappedAutonat {
        type Target = autonat::Behaviour;
        fn deref(&self) -> &Self::Target {
            &self.inner
        }
    }

    impl DerefMut for CappedAutonat {
        fn deref_mut(&mut self) -> &mut Self::Target {
            &mut self.inner
        }
    }

    impl NetworkBehaviour for CappedAutonat {
        type ConnectionHandler = <autonat::Behaviour as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = autonat::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            let forward = match &event {
                FromSwarm::NewListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    let is_circuit = ev.addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                    if is_circuit {
                        true
                    } else {
                        match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &s)
                                    || admit_listen_derived_external(&mut st, &s).is_ok()
                                {
                                    if !st.autonat_advertised_listen.iter().any(|a| a == &s) {
                                        st.autonat_advertised_listen.push(s);
                                    }
                                    true
                                } else {
                                    st.autonat_listen_addr_omitted =
                                        st.autonat_listen_addr_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        }
                    }
                }
                FromSwarm::ExpiredListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    if let Ok(mut st) = self.state.lock() {
                        st.autonat_advertised_listen.retain(|a| a != &s);
                    }
                    true
                }
                _ => true,
            };
            if forward {
                self.inner.on_swarm_event(event);
            }
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            loop {
                match self.inner.poll(cx) {
                    Poll::Ready(ToSwarm::ExternalAddrConfirmed(addr)) => {
                        let canonical = match self.state.lock() {
                            Ok(mut st) => {
                                let next = gated_external_confirmed(&mut st, &addr);
                                if next.is_none() {
                                    st.autonat_external_confirmed_omitted =
                                        st.autonat_external_confirmed_omitted.saturating_add(1);
                                }
                                next
                            }
                            Err(_) => None,
                        };
                        if let Some(canonical) = canonical {
                            return Poll::Ready(ToSwarm::ExternalAddrConfirmed(canonical));
                        }
                    }
                    Poll::Ready(ToSwarm::ExternalAddrExpired(addr)) => {
                        if let Some(canonical) = gated_external_expired(&addr) {
                            return Poll::Ready(ToSwarm::ExternalAddrExpired(canonical));
                        }
                    }
                    other => return other,
                }
            }
        }
    }

    /// Slice BZ: UPnP 0.3 maps a port on every NewListenAddr (even before
    /// the gateway is found: Inactive mapping queued). Forward into UPnP
    /// only when circuit (uncapped) or charged against the shared advertised
    /// cap. Uncharged expansion sockets stay listening but are omitted from
    /// IGD map requests (not a silent leak).
    /// Slice CY: ExternalAddrConfirmed is admit-canonical-or-omit (crate book).
    struct CappedUpnp {
        inner: upnp::tokio::Behaviour,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedUpnp {
        fn new(inner: upnp::tokio::Behaviour, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }
    }

    impl NetworkBehaviour for CappedUpnp {
        type ConnectionHandler = <upnp::tokio::Behaviour as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = upnp::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            let forward = match &event {
                FromSwarm::NewListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    let is_circuit = ev.addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                    if is_circuit {
                        true
                    } else {
                        match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &s)
                                    || admit_listen_derived_external(&mut st, &s).is_ok()
                                {
                                    if !st.upnp_advertised_listen.iter().any(|a| a == &s) {
                                        st.upnp_advertised_listen.push(s);
                                    }
                                    true
                                } else {
                                    st.upnp_listen_addr_omitted =
                                        st.upnp_listen_addr_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        }
                    }
                }
                FromSwarm::ExpiredListenAddr(ev) => {
                    let s = ev.addr.to_string();
                    if let Ok(mut st) = self.state.lock() {
                        st.upnp_advertised_listen.retain(|a| a != &s);
                    }
                    true
                }
                _ => true,
            };
            if forward {
                self.inner.on_swarm_event(event);
            }
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            loop {
                match self.inner.poll(cx) {
                    Poll::Ready(ToSwarm::ExternalAddrConfirmed(addr)) => {
                        let canonical = match self.state.lock() {
                            Ok(mut st) => {
                                let next = gated_external_confirmed(&mut st, &addr);
                                if next.is_none() {
                                    st.upnp_external_confirmed_omitted =
                                        st.upnp_external_confirmed_omitted.saturating_add(1);
                                }
                                next
                            }
                            Err(_) => None,
                        };
                        if let Some(canonical) = canonical {
                            return Poll::Ready(ToSwarm::ExternalAddrConfirmed(canonical));
                        }
                    }
                    Poll::Ready(ToSwarm::ExternalAddrExpired(addr)) => {
                        if let Some(canonical) = gated_external_expired(&addr) {
                            return Poll::Ready(ToSwarm::ExternalAddrExpired(canonical));
                        }
                    }
                    other => return other,
                }
            }
        }
    }

    /// Slice CB: DCUtR 0.12 hole-punch CONNECT uses every
    /// `NewExternalAddrCandidate` (Identify observed / translated listen).
    /// Forward into DCUtR only when circuit (uncapped) or already charged.
    /// Do not aux-admit from candidates (that would bypass the listen cap).
    /// Uncharged expansion / ephemeral sockets are omitted from punch.
    struct CappedDcutr {
        inner: dcutr::Behaviour,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedDcutr {
        fn new(inner: dcutr::Behaviour, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }
    }

    impl NetworkBehaviour for CappedDcutr {
        type ConnectionHandler = <dcutr::Behaviour as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = dcutr::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            let forward = match &event {
                FromSwarm::NewExternalAddrCandidate(ev) => {
                    let is_circuit = ev.addr.iter().any(|p| matches!(p, Protocol::P2pCircuit));
                    if is_circuit {
                        true
                    } else {
                        let key = advertised_charge_key(ev.addr);
                        match self.state.lock() {
                            Ok(mut st) => {
                                if advertised_already_charged(&st, &key) {
                                    if !st.dcutr_advertised_candidates.iter().any(|a| a == &key) {
                                        st.dcutr_advertised_candidates.push(key);
                                    }
                                    true
                                } else {
                                    st.dcutr_candidate_omitted =
                                        st.dcutr_candidate_omitted.saturating_add(1);
                                    false
                                }
                            }
                            Err(_) => false,
                        }
                    }
                }
                FromSwarm::ExpiredListenAddr(ev) => {
                    let key = advertised_charge_key(ev.addr);
                    if let Ok(mut st) = self.state.lock() {
                        st.dcutr_advertised_candidates.retain(|a| a != &key);
                    }
                    true
                }
                FromSwarm::ExternalAddrExpired(ev) => {
                    let key = advertised_charge_key(ev.addr);
                    if let Ok(mut st) = self.state.lock() {
                        st.dcutr_advertised_candidates.retain(|a| a != &key);
                    }
                    true
                }
                _ => true,
            };
            if forward {
                self.inner.on_swarm_event(event);
            }
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            self.inner.poll(cx)
        }
    }

    /// Slice CX: `libp2p-relay` client confirms the circuit listen as an
    /// external addr (`ToSwarm::ExternalAddrConfirmed`). Swarm then
    /// `add_external_address`, occupying Identify/Kad/Relay books (silent
    /// eviction past 20 charged). Omit circuit confirm/expire; reservation
    /// and `NewListenAddr` still complete `listen_relay`.
    struct CappedRelayClient {
        inner: relay::client::Behaviour,
        state: Arc<Mutex<NodeState>>,
    }

    impl CappedRelayClient {
        fn new(inner: relay::client::Behaviour, state: Arc<Mutex<NodeState>>) -> Self {
            Self { inner, state }
        }
    }

    impl NetworkBehaviour for CappedRelayClient {
        type ConnectionHandler = <relay::client::Behaviour as NetworkBehaviour>::ConnectionHandler;
        type ToSwarm = relay::client::Event;

        fn handle_pending_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<(), ConnectionDenied> {
            self.inner
                .handle_pending_inbound_connection(connection_id, local_addr, remote_addr)
        }

        fn handle_established_inbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            local_addr: &Multiaddr,
            remote_addr: &Multiaddr,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_inbound_connection(
                connection_id,
                peer,
                local_addr,
                remote_addr,
            )
        }

        fn handle_pending_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            maybe_peer: Option<PeerId>,
            addresses: &[Multiaddr],
            effective_role: Endpoint,
        ) -> Result<Vec<Multiaddr>, ConnectionDenied> {
            self.inner.handle_pending_outbound_connection(
                connection_id,
                maybe_peer,
                addresses,
                effective_role,
            )
        }

        fn handle_established_outbound_connection(
            &mut self,
            connection_id: ConnectionId,
            peer: PeerId,
            addr: &Multiaddr,
            role_override: Endpoint,
            port_use: PortUse,
        ) -> Result<Self::ConnectionHandler, ConnectionDenied> {
            self.inner.handle_established_outbound_connection(
                connection_id,
                peer,
                addr,
                role_override,
                port_use,
            )
        }

        fn on_swarm_event(&mut self, event: FromSwarm<'_>) {
            self.inner.on_swarm_event(event);
        }

        fn on_connection_handler_event(
            &mut self,
            peer_id: PeerId,
            connection_id: ConnectionId,
            event: <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::ToBehaviour,
        ) {
            self.inner
                .on_connection_handler_event(peer_id, connection_id, event);
        }

        fn poll(
            &mut self,
            cx: &mut Context<'_>,
        ) -> Poll<
            ToSwarm<
                Self::ToSwarm,
                <Self::ConnectionHandler as libp2p::swarm::ConnectionHandler>::FromBehaviour,
            >,
        > {
            loop {
                match self.inner.poll(cx) {
                    Poll::Ready(ToSwarm::ExternalAddrConfirmed(addr)) => {
                        let is_circuit = !swarm_may_add_external_address(&addr);
                        let canonical = match self.state.lock() {
                            Ok(mut st) => {
                                let next = gated_external_confirmed(&mut st, &addr);
                                if next.is_none() && is_circuit {
                                    st.relay_client_circuit_external_omitted =
                                        st.relay_client_circuit_external_omitted.saturating_add(1);
                                }
                                next
                            }
                            Err(_) => None,
                        };
                        if let Some(canonical) = canonical {
                            return Poll::Ready(ToSwarm::ExternalAddrConfirmed(canonical));
                        }
                    }
                    Poll::Ready(ToSwarm::ExternalAddrExpired(addr)) => {
                        if let Some(canonical) = gated_external_expired(&addr) {
                            return Poll::Ready(ToSwarm::ExternalAddrExpired(canonical));
                        }
                    }
                    other => return other,
                }
            }
        }
    }

    #[derive(NetworkBehaviour)]
    struct AbsBehaviour {
        ping: ping::Behaviour,
        identify: CappedIdentify,
        wire: request_response::Behaviour<AbsWireCodec>,
        gossipsub: gossipsub::Behaviour,
        mdns: Toggle<CappedMdns>,
        kademlia: CappedKad,
        relay: relay::Behaviour,
        relay_client: CappedRelayClient,
        /// Slice N: off by default — AutoNAT probe dials raced reconnect (Slice U).
        autonat: Toggle<CappedAutonat>,
        /// Slice AD: off by default — needs IGD gateway; CI expects GatewayNotFound.
        upnp: Toggle<CappedUpnp>,
        /// Slice AE: off by default — empty allow-list denies all until allow_peer.
        allowed_peers: Toggle<allow_block_list::Behaviour<AllowedPeers>>,
        dcutr: CappedDcutr,
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
        /// Slice AG/BO: mark multiaddr as externally reachable / expire it.
        AddExternalAddress {
            addr: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        RemoveExternalAddress {
            addr: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        /// Slice BM: wipe entire external address book (returns addrs cleared).
        ClearExternalAddrs {
            reply: oneshot::Sender<Result<usize, String>>,
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
        /// Slice BH: forget one bootstrap peer (returns whether it was present).
        BootstrapRemove {
            peer_id: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        /// Slice BJ: wipe entire bootstrap book (returns peers cleared).
        BootstrapClear {
            reply: oneshot::Sender<Result<usize, String>>,
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
        /// Slice BK: wipe learned peerstore (returns peers cleared).
        PeerstoreClear {
            reply: oneshot::Sender<Result<usize, String>>,
        },
        /// Slice BE: forget one learned peer (and persist if path set).
        PeerstoreRemove {
            peer_id: String,
            reply: oneshot::Sender<Result<bool, String>>,
        },
        /// Slice BF: clear runtime forget so identify/connection may re-learn.
        PeerstoreAllowLearn {
            peer_id: String,
            reply: oneshot::Sender<Result<bool, String>>,
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
        /// Slice BC: active identify push to one peer or all connected peers.
        IdentifyPush {
            peer_id: Option<String>,
            reply: oneshot::Sender<Result<usize, String>>,
        },
        /// Slice BG: promote ``last_observed_addr`` via ``add_external_address``.
        ConfirmObservedAddr {
            reply: oneshot::Sender<Result<String, String>>,
        },
        /// Slice BL: wipe ``last_observed_addr`` surface (returns previous value).
        ClearObservedAddr {
            reply: oneshot::Sender<Result<String, String>>,
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
        /// Slice CX: rust-libp2p Swarm::external_addresses crate book.
        SwarmExternalAddrs {
            reply: oneshot::Sender<Vec<String>>,
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
        /// Slice BB: drop RR response channel → ``InboundFailure::ResponseOmission``.
        enable_wire_omit_response: bool,
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
        /// Slice BW: NewListenAddr omitted from mDNS because the shared cap is full.
        mdns_listen_addr_omitted: u64,
        /// Slice BW: non-circuit listen addrs currently forwarded into mDNS.
        mdns_advertised_listen: Vec<String>,
        /// Slice AS: configured mDNS TTL seconds (lab override).
        mdns_ttl_secs: u64,
        /// Slice BX: NewListenAddr omitted from Kademlia because the shared cap is full.
        kad_listen_addr_omitted: u64,
        /// Slice BX: non-circuit listen addrs currently forwarded into Kademlia.
        kad_advertised_listen: Vec<String>,
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
        /// Slice CX: circuit ExternalAddrConfirmed omitted from crate book.
        relay_client_circuit_external_omitted: u64,
        /// Slice AP: optional capacity override (lab deny path); 0 = default.
        relay_max_reservations: u32,
        autonat_probes: u64,
        autonat_status_changes: u64,
        /// Slice AR: AutoNAT probe direction / error taxonomy.
        autonat_inbound_probe: u64,
        autonat_outbound_probe: u64,
        autonat_inbound_probe_error: u64,
        autonat_outbound_probe_error: u64,
        /// Slice BY: NewListenAddr omitted from AutoNAT because the shared cap is full.
        autonat_listen_addr_omitted: u64,
        /// Slice CY: AutoNAT ExternalAddrConfirmed omitted (uncharged / circuit).
        autonat_external_confirmed_omitted: u64,
        /// Slice BY: non-circuit listen addrs currently forwarded into AutoNAT.
        autonat_advertised_listen: Vec<String>,
        /// 0=unknown, 1=public, 2=private (Slice N).
        autonat_status: u8,
        dcutr_upgrade_success: u64,
        dcutr_upgrade_fail: u64,
        /// Slice CB: NewExternalAddrCandidate omitted from DCUtR (uncharged).
        dcutr_candidate_omitted: u64,
        /// Slice CB: candidate keys currently forwarded into DCUtR punch.
        dcutr_advertised_candidates: Vec<String>,
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
        /// Slice BZ: NewListenAddr omitted from UPnP because the shared cap is full.
        upnp_listen_addr_omitted: u64,
        /// Slice CY: UPnP ExternalAddrConfirmed omitted (uncharged / circuit).
        upnp_external_confirmed_omitted: u64,
        /// Slice BZ: non-circuit listen addrs currently forwarded into UPnP.
        upnp_advertised_listen: Vec<String>,
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
        /// Slice BD: identify StreamUpgradeError taxonomy.
        identify_error_timeout: u64,
        identify_error_negotiation: u64,
        identify_error_apply: u64,
        identify_error_io: u64,
        /// Slice BD: configured identify re-request interval.
        identify_interval_ms: u64,
        /// Slice BG: how remotes observe this node (from identify Received).
        last_observed_addr: String,
        observed_addr_updates: u64,
        observed_addr_confirmed: u64,
        /// Slice BL: successful clear_observed_addr (non-empty prior value).
        observed_addr_cleared: u64,
        /// Slice BI: auto ``add_external_address`` on each new observed addr.
        enable_confirm_observed_addr: bool,
        /// Slice BC: push-on-listen-addr-change + branding / API bookkeeping.
        enable_identify_push: bool,
        agent_version: String,
        protocol_version: String,
        identify_push_requests: u64,
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
        /// Slice BM: addrs removed via clear_external_addrs.
        external_addr_cleared: u64,
        /// Slice BP: advertised externals restored from JSON on start.
        external_addr_loaded: u64,
        /// Slice BP: successful persist writes.
        external_addr_persisted: u64,
        /// Slice BP: JSON path (empty = memory-only). Operator-advertised only.
        external_addrs_path: String,
        /// Slice BP: addrs inserted via add_external_address (not listen-derived).
        advertised_external: Vec<String>,
        /// Slice BR/BT/BU: effective advertised cap (<= MAX_ADVERTISED_EXTERNAL_ADDRS).
        /// Shared unique budget: operator + listen-derived + aux (observed/UPnP/rendezvous).
        max_advertised_external: u32,
        /// Slice BR: add/restore refused because the cap would be exceeded.
        /// Slice BS: listen-derived advertise refused.
        /// Slice BT: shared sum refuse (listen / add / restore).
        /// Slice BU: observed / UPnP / rendezvous refuse.
        external_addr_limit_refused: u64,
        /// Slice BS: listen addrs currently in the advertised book (not operator persist).
        listen_derived_external: Vec<String>,
        /// Slice BU: advertised addrs that are not operator persist and not listen-derived
        /// (observed confirm, UPnP, rendezvous).
        aux_advertised_external: Vec<String>,
        /// Slice BV: Identify NewListenAddr omitted because the shared cap is full.
        identify_listen_addr_omitted: u64,
        /// Slice CC: Identify NewExternalAddrCandidate omitted (uncharged).
        identify_candidate_omitted: u64,
        /// Persistent bootstrap book path (Slice O; empty = memory-only).
        bootstrap_path: String,
        bootstrap: HashMap<String, Vec<String>>,
        bootstrap_dials_ok: u64,
        bootstrap_dials_fail: u64,
        bootstrap_dials_timeout: u64,
        bootstrap_dials_attempted: u64,
        /// Slice BH: successful bootstrap_remove calls.
        bootstrap_removed: u64,
        /// Slice BJ: peers removed via bootstrap_clear.
        bootstrap_cleared: u64,
        bootstrap_dial_timeout_secs: u64,
        /// Slice T: learned peer multiaddrs (identify/connection), separate from bootstrap.
        peerstore_path: String,
        peerstore: HashMap<String, Vec<String>>,
        /// Slice BE: runtime suppress re-learn after ``peerstore_remove`` (not persisted).
        peerstore_forgotten: HashSet<String>,
        peerstore_learned: u64,
        /// Slice BE: successful peerstore_remove calls.
        peerstore_removed: u64,
        /// Slice BK: peers removed via peerstore_clear.
        peerstore_cleared: u64,
        /// Slice BF: successful peerstore_allow_learn (was forgotten).
        peerstore_allow_learn: u64,
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
            external_addrs_path: Option<String>,
            max_advertised_external: u32,
        ) -> PyResult<Self> {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .thread_name("abs-libp2p")
                .build()
                .map_err(|e| PyRuntimeError::new_err(format!("tokio runtime: {e}")))?;

            let key_path_str = key_path.unwrap_or_default();
            let bootstrap_path_str = bootstrap_path.unwrap_or_default();
            let peerstore_path_str = peerstore_path.unwrap_or_default();
            let external_addrs_path_str = external_addrs_path.unwrap_or_default();
            let advertised_external = if external_addrs_path_str.is_empty() {
                Vec::new()
            } else {
                super::load_external_addrs_file(Path::new(&external_addrs_path_str))
                    .map_err(|e| PyRuntimeError::new_err(format!("external addrs load: {e}")))?
            };
            for s in &advertised_external {
                s.parse::<Multiaddr>().map_err(|e| {
                    PyRuntimeError::new_err(format!("external addrs load: bad multiaddr {s}: {e}"))
                })?;
            }
            if advertised_external.len() > max_advertised_external as usize {
                return Err(PyRuntimeError::new_err(format!(
                    "external addrs load: {} addrs exceeds max {max_advertised_external}",
                    advertised_external.len()
                )));
            }
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
                external_addrs_path: external_addrs_path_str.clone(),
                advertised_external,
                max_advertised_external,
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
                enable_wire_omit_response: resolve_wire_omit_response(None),
                enable_identify_push: resolve_identify_push(None),
                enable_confirm_observed_addr: resolve_confirm_observed_addr(None),
                agent_version: resolve_agent_version(None),
                protocol_version: ABS_IDENTIFY_PROTOCOL_VERSION.to_string(),
                identify_interval_ms: resolve_identify_interval_ms(None),
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
            let want_identify_push = state
                .lock()
                .map(|st| st.enable_identify_push)
                .unwrap_or(false);
            let identify_agent_version = state
                .lock()
                .map(|st| st.agent_version.clone())
                .unwrap_or_else(|_| format!("absolute-experimental/{}", env!("CARGO_PKG_VERSION")));
            let identify_interval =
                Duration::from_millis(resolve_identify_interval_ms(None).max(1));
            if let Ok(mut st) = state.lock() {
                st.ping_interval_ms = ping_interval.as_millis().min(u128::from(u64::MAX)) as u64;
                st.ping_timeout_ms = ping_timeout.as_millis().min(u128::from(u64::MAX)) as u64;
                st.identify_interval_ms =
                    identify_interval.as_millis().min(u128::from(u64::MAX)) as u64;
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
                        Toggle::from(Some(CappedMdns::new(
                            mdns::tokio::Behaviour::new(
                                mdns::Config {
                                    ttl: Duration::from_secs(mdns_ttl),
                                    query_interval: Duration::from_secs(1),
                                    enable_ipv6: false,
                                },
                                key.public().to_peer_id(),
                            )
                            .map_err(|e| format!("mdns: {e}"))?,
                            Arc::clone(&state_bg),
                        )))
                    } else {
                        Toggle::from(None)
                    };
                    let local = key.public().to_peer_id();
                    let mut kad_cfg = kad::Config::new(StreamProtocol::new(ABS_KAD_PROTOCOL));
                    kad_cfg.set_query_timeout(Duration::from_secs(10));
                    let store = MemoryStore::new(local);
                    let mut kademlia = kad::Behaviour::with_config(local, store, kad_cfg);
                    kademlia.set_mode(Some(kad::Mode::Server));
                    let kademlia = CappedKad::new(kademlia, Arc::clone(&state_bg));
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
                        // Slice BC/BD: branding, listen-addr push, re-identify interval.
                        // Slice BV: wrap identify so uncharged listen addrs are omitted.
                        identify: CappedIdentify::new(
                            identify::Behaviour::new(
                                identify::Config::new(
                                    ABS_IDENTIFY_PROTOCOL_VERSION.into(),
                                    key.public(),
                                )
                                .with_agent_version(identify_agent_version.clone())
                                .with_push_listen_addr_updates(want_identify_push)
                                .with_interval(identify_interval),
                            ),
                            Arc::clone(&state_bg),
                        ),
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
                        relay_client: CappedRelayClient::new(
                            relay_client,
                            Arc::clone(&state_bg),
                        ),
                        autonat: if want_autonat {
                            // Lab-friendly AutoNAT: allow private/loopback peers (Slice N).
                            let cfg = autonat::Config {
                                only_global_ips: false,
                                boot_delay: Duration::from_millis(200),
                                retry_interval: Duration::from_secs(2),
                                refresh_interval: Duration::from_secs(10),
                                throttle_server_period: Duration::from_secs(1),
                                ..Default::default()
                            };
                            Toggle::from(Some(CappedAutonat::new(
                                autonat::Behaviour::new(local, cfg),
                                Arc::clone(&state_bg),
                            )))
                        } else {
                            Toggle::from(None)
                        },
                        upnp: if want_upnp {
                            Toggle::from(Some(CappedUpnp::new(
                                upnp::tokio::Behaviour::default(),
                                Arc::clone(&state_bg),
                            )))
                        } else {
                            Toggle::from(None)
                        },
                        allowed_peers: if want_allow_list {
                            Toggle::from(Some(allow_block_list::Behaviour::default()))
                        } else {
                            Toggle::from(None)
                        },
                        dcutr: CappedDcutr::new(
                            dcutr::Behaviour::new(local),
                            Arc::clone(&state_bg),
                        ),
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

                // Slice BP: restore operator-advertised externals (not listen-derived).
                let restore = state_bg
                    .lock()
                    .map(|st| st.advertised_external.clone())
                    .unwrap_or_default();
                for s in restore {
                    if let Ok(ma) = s.parse::<Multiaddr>() {
                        // Slice CW: circuit never occupies the crate book.
                        if !swarm_may_add_external_address(&ma) {
                            continue;
                        }
                        // Slice DB: restore the canonical key (JSON may still
                        // carry a `/p2p/<peer>` suffix from an older write).
                        let key = advertised_charge_key(&ma);
                        let add_ma = key.parse::<Multiaddr>().unwrap_or(ma);
                        swarm_add_external_if_charged(&mut swarm, add_ma);
                        if let Ok(mut st) = state_bg.lock() {
                            if !st.external_addrs.iter().any(|a| advertised_query_key(a) == key)
                            {
                                st.external_addrs.push(key);
                            }
                            st.external_addr_loaded = st.external_addr_loaded.saturating_add(1);
                        }
                    }
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
                                Some(Cmd::SwarmExternalAddrs { reply }) => {
                                    let addrs = swarm
                                        .external_addresses()
                                        .map(|a| a.to_string())
                                        .collect::<Vec<_>>();
                                    let _ = reply.send(addrs);
                                }
                                Some(Cmd::Shutdown { reply }) => {
                                    let _ = reply.send(());
                                    break;
                                }
                                Some(Cmd::Listen { addr, reply }) => {
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            let is_circuit = ma.iter().any(|p| {
                                                matches!(p, Protocol::P2pCircuit)
                                            });
                                            // Slice BS/BT: shared advertised cap. Circuit
                                            // listens are not advertised into that set.
                                            if !is_circuit {
                                                let at_cap = match state_bg.lock() {
                                                    Ok(st) => advertised_at_cap(&st),
                                                    Err(_) => {
                                                        let _ = reply.send(Err(
                                                            "state lock poisoned".into(),
                                                        ));
                                                        continue;
                                                    }
                                                };
                                                if at_cap {
                                                    if let Ok(mut st) = state_bg.lock() {
                                                        let _ = refuse_advertised_over_cap(
                                                            &mut st,
                                                            "listen-derived externals",
                                                        );
                                                    }
                                                    let _ = reply.send(Err(
                                                        "listen-derived externals: at max"
                                                            .into(),
                                                    ));
                                                    continue;
                                                }
                                            }
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
                                            if topics.contains(&&want) {
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
                                            // Slice CW: circuit stays on listen; do not occupy
                                            // rust-libp2p ExternalAddresses (silent eviction).
                                            if !swarm_may_add_external_address(&ma) {
                                                continue;
                                            }
                                            let admit = match state_bg.lock() {
                                                Ok(mut st) => {
                                                    if advertised_already_charged(&st, &a) {
                                                        Ok(false)
                                                    } else {
                                                        admit_aux_advertised_external(&mut st, &a)
                                                    }
                                                }
                                                Err(_) => Err("state lock poisoned".into()),
                                            };
                                            match admit {
                                                Ok(_) => {
                                                    swarm_add_external_if_charged(&mut swarm, ma);
                                                    if let Ok(mut st) = state_bg.lock() {
                                                        if !st.external_addrs.contains(&a) {
                                                            st.external_addrs.push(a);
                                                        }
                                                    }
                                                }
                                                Err(_) => {
                                                    // Slice BU: do not advertise uncharged addrs over cap.
                                                }
                                            }
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
                                    // Slice BO: bool = newly inserted; bump confirmed only then.
                                    // Slice BP: persist operator-advertised addrs (fail-closed).
                                    // Slice CW: circuit never occupies rust-libp2p ExternalAddresses.
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            if !swarm_may_add_external_address(&ma) {
                                                let _ = reply.send(Err(
                                                    CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_MSG.into(),
                                                ));
                                                continue;
                                            }
                                            let key = advertised_charge_key(&ma);
                                            let present = match state_bg.lock() {
                                                Ok(st) => {
                                                    advertised_already_charged(&st, &key)
                                                        || st.external_addrs.iter().any(|a| {
                                                            advertised_query_key(a) == key
                                                        })
                                                }
                                                Err(_) => {
                                                    let _ = reply.send(Err(
                                                        "state lock poisoned".into(),
                                                    ));
                                                    continue;
                                                }
                                            };
                                            if present {
                                                let _ = reply.send(Ok(false));
                                                continue;
                                            }
                                            let persist = match state_bg.lock() {
                                                Ok(mut st) => {
                                                    if !st.advertised_external.iter().any(|a| {
                                                        advertised_query_key(a) == key
                                                    }) {
                                                        if advertised_at_cap(&st) {
                                                            let msg = refuse_advertised_over_cap(
                                                                &mut st,
                                                                "advertised externals",
                                                            );
                                                            let _ = reply.send(Err(msg));
                                                            continue;
                                                        }
                                                        st.advertised_external.push(key.clone());
                                                    }
                                                    (
                                                        st.external_addrs_path.clone(),
                                                        st.advertised_external.clone(),
                                                    )
                                                }
                                                Err(_) => {
                                                    let _ = reply.send(Err(
                                                        "state lock poisoned".into(),
                                                    ));
                                                    continue;
                                                }
                                            };
                                            if let Err(e) = super::persist_external_addrs_file(
                                                &persist.0,
                                                &persist.1,
                                            ) {
                                                if let Ok(mut st) = state_bg.lock() {
                                                    st.advertised_external.retain(|a| {
                                                        advertised_query_key(a) != key
                                                    });
                                                }
                                                let _ = reply.send(Err(e));
                                                continue;
                                            }
                                            let add_ma = key.parse::<Multiaddr>().unwrap_or(ma);
                                            swarm_add_external_if_charged(&mut swarm, add_ma);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.external_addr_confirmed = st
                                                    .external_addr_confirmed
                                                    .saturating_add(1);
                                                if !st.external_addrs.iter().any(|a| {
                                                    advertised_query_key(a) == key
                                                }) {
                                                    st.external_addrs.push(key);
                                                }
                                                if !persist.0.is_empty() {
                                                    st.external_addr_persisted = st
                                                        .external_addr_persisted
                                                        .saturating_add(1);
                                                }
                                            }
                                            let _ = reply.send(Ok(true));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::RemoveExternalAddress { addr, reply }) => {
                                    // Slice BN: bool = was present in our book; bump expired only then.
                                    // Slice DA: `/p2p/<peer>` suffix matches the canonical charged key.
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            let key = advertised_charge_key(&ma);
                                            let present = match state_bg.lock() {
                                                Ok(st) => {
                                                    advertised_already_charged(&st, &key)
                                                        || st.external_addrs.iter().any(|a| {
                                                            advertised_query_key(a) == key
                                                        })
                                                }
                                                Err(_) => {
                                                    let _ = reply.send(Err(
                                                        "state lock poisoned".into(),
                                                    ));
                                                    continue;
                                                }
                                            };
                                            if !present {
                                                swarm_remove_charged(&mut swarm, ma);
                                                let _ = reply.send(Ok(false));
                                                continue;
                                            }
                                            let persist = match state_bg.lock() {
                                                Ok(mut st) => {
                                                    let was_advertised = st
                                                        .advertised_external
                                                        .iter()
                                                        .any(|a| advertised_query_key(a) == key);
                                                    st.advertised_external.retain(|a| {
                                                        advertised_query_key(a) != key
                                                    });
                                                    (
                                                        st.external_addrs_path.clone(),
                                                        st.advertised_external.clone(),
                                                        was_advertised,
                                                    )
                                                }
                                                Err(_) => {
                                                    let _ = reply.send(Err(
                                                        "state lock poisoned".into(),
                                                    ));
                                                    continue;
                                                }
                                            };
                                            if let Err(e) = super::persist_external_addrs_file(
                                                &persist.0,
                                                &persist.1,
                                            ) {
                                                if persist.2 {
                                                    if let Ok(mut st) = state_bg.lock() {
                                                        if !st.advertised_external.iter().any(|a| {
                                                            advertised_query_key(a) == key
                                                        }) {
                                                            st.advertised_external.push(key.clone());
                                                        }
                                                    }
                                                }
                                                let _ = reply.send(Err(e));
                                                continue;
                                            }
                                            swarm_remove_charged(&mut swarm, ma);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.external_addr_expired = st
                                                    .external_addr_expired
                                                    .saturating_add(1);
                                                st.external_addrs.retain(|a| {
                                                    advertised_query_key(a) != key
                                                });
                                                st.listen_derived_external.retain(|a| {
                                                    advertised_query_key(a) != key
                                                });
                                                st.aux_advertised_external.retain(|a| {
                                                    advertised_query_key(a) != key
                                                });
                                                if !persist.0.is_empty() {
                                                    st.external_addr_persisted = st
                                                        .external_addr_persisted
                                                        .saturating_add(1);
                                                }
                                            }
                                            let _ = reply.send(Ok(true));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!("bad multiaddr: {e}")));
                                        }
                                    }
                                }
                                Some(Cmd::ClearExternalAddrs { reply }) => {
                                    // Slice BM: wipe external book (+ swarm remove each).
                                    // Slice BP: persist empty advertised set.
                                    let snap = match state_bg.lock() {
                                        Ok(st) => st.external_addrs.clone(),
                                        Err(_) => {
                                            let _ = reply
                                                .send(Err("state lock poisoned".into()));
                                            continue;
                                        }
                                    };
                                    let persist = match state_bg.lock() {
                                        Ok(mut st) => {
                                            let advertised_snap = st.advertised_external.clone();
                                            st.advertised_external.clear();
                                            (
                                                st.external_addrs_path.clone(),
                                                st.advertised_external.clone(),
                                                advertised_snap,
                                            )
                                        }
                                        Err(_) => {
                                            let _ = reply
                                                .send(Err("state lock poisoned".into()));
                                            continue;
                                        }
                                    };
                                    if let Err(e) = super::persist_external_addrs_file(
                                        &persist.0,
                                        &persist.1,
                                    ) {
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.advertised_external = persist.2;
                                        }
                                        let _ = reply.send(Err(e));
                                        continue;
                                    }
                                    let n = snap.len();
                                    for s in &snap {
                                        if let Ok(ma) = s.parse::<Multiaddr>() {
                                            swarm_remove_charged(&mut swarm, ma);
                                        }
                                    }
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.external_addrs.clear();
                                        st.listen_derived_external.clear();
                                        st.aux_advertised_external.clear();
                                        if n > 0 {
                                            st.external_addr_cleared =
                                                st.external_addr_cleared.saturating_add(n as u64);
                                        }
                                        if !persist.0.is_empty() {
                                            st.external_addr_persisted = st
                                                .external_addr_persisted
                                                .saturating_add(1);
                                        }
                                    }
                                    let _ = reply.send(Ok(n));
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
                                    // Slice BH: forget one bootstrap peer (+ persist).
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        let removed = st.bootstrap.remove(&peer_id).is_some();
                                        if removed {
                                            st.bootstrap_removed =
                                                st.bootstrap_removed.saturating_add(1);
                                        }
                                        (
                                            removed,
                                            st.bootstrap_path.clone(),
                                            st.bootstrap.clone(),
                                        )
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    if !persist.0 {
                                        let _ = reply.send(Ok(false));
                                        continue;
                                    }
                                    let res = if persist.1.is_empty() {
                                        Ok(true)
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.1), &persist.2)
                                            .map(|_| true)
                                    };
                                    let _ = reply.send(res);
                                }
                                Some(Cmd::BootstrapClear { reply }) => {
                                    // Slice BJ: wipe bootstrap book (+ persist).
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        let n = st.bootstrap.len();
                                        st.bootstrap.clear();
                                        if n > 0 {
                                            st.bootstrap_cleared =
                                                st.bootstrap_cleared.saturating_add(n as u64);
                                        }
                                        (n, st.bootstrap_path.clone(), st.bootstrap.clone())
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    if persist.0 == 0 {
                                        let _ = reply.send(Ok(0));
                                        continue;
                                    }
                                    let res = if persist.1.is_empty() {
                                        Ok(persist.0)
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.1), &persist.2)
                                            .map(|_| persist.0)
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
                                    // Slice BK: wipe learned peerstore (+ persist).
                                    // Cleared peer ids enter the forget set so identify
                                    // cannot re-learn while still connected (BE parity).
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        let keys: Vec<String> =
                                            st.peerstore.keys().cloned().collect();
                                        let n = keys.len();
                                        st.peerstore.clear();
                                        for k in &keys {
                                            st.peerstore_forgotten.insert(k.clone());
                                        }
                                        if n > 0 {
                                            st.peerstore_cleared =
                                                st.peerstore_cleared.saturating_add(n as u64);
                                        }
                                        (n, st.peerstore_path.clone(), st.peerstore.clone())
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    if persist.0 == 0 {
                                        let _ = reply.send(Ok(0));
                                        continue;
                                    }
                                    let res = if persist.1.is_empty() {
                                        Ok(persist.0)
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.1), &persist.2)
                                            .map(|_| persist.0)
                                    };
                                    let _ = reply.send(res);
                                }
                                Some(Cmd::PeerstoreRemove { peer_id, reply }) => {
                                    // Slice BE: forget one learned peer (+ suppress re-learn).
                                    let persist = if let Ok(mut st) = state_bg.lock() {
                                        let removed = st.peerstore.remove(&peer_id).is_some();
                                        st.peerstore_forgotten.insert(peer_id.clone());
                                        if removed {
                                            st.peerstore_removed =
                                                st.peerstore_removed.saturating_add(1);
                                        }
                                        (
                                            removed,
                                            st.peerstore_path.clone(),
                                            st.peerstore.clone(),
                                        )
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    if !persist.0 {
                                        let _ = reply.send(Ok(false));
                                        continue;
                                    }
                                    let res = if persist.1.is_empty() {
                                        Ok(true)
                                    } else {
                                        save_bootstrap_peers(Path::new(&persist.1), &persist.2)
                                            .map(|_| true)
                                    };
                                    let _ = reply.send(res);
                                }
                                Some(Cmd::PeerstoreAllowLearn { peer_id, reply }) => {
                                    // Slice BF: lift forget so peerstore_note_addr may run again.
                                    let cleared = if let Ok(mut st) = state_bg.lock() {
                                        let was = st.peerstore_forgotten.remove(&peer_id);
                                        if was {
                                            st.peerstore_allow_learn =
                                                st.peerstore_allow_learn.saturating_add(1);
                                        }
                                        was
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    let _ = reply.send(Ok(cleared));
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
                                Some(Cmd::IdentifyPush { peer_id, reply }) => {
                                    // Slice BC: active identify push.
                                    let peers: Result<Vec<PeerId>, String> = match peer_id {
                                        Some(pid) => pid
                                            .parse::<PeerId>()
                                            .map(|p| vec![p])
                                            .map_err(|e| format!("bad peer_id: {e}")),
                                        None => Ok(state_bg
                                            .lock()
                                            .map(|st| {
                                                st.connected
                                                    .iter()
                                                    .filter_map(|s| s.parse::<PeerId>().ok())
                                                    .collect::<Vec<_>>()
                                            })
                                            .unwrap_or_default()),
                                    };
                                    match peers {
                                        Ok(list) => {
                                            let n = list.len();
                                            swarm.behaviour_mut().identify.push(list);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.identify_push_requests = st
                                                    .identify_push_requests
                                                    .saturating_add(1);
                                            }
                                            let _ = reply.send(Ok(n));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(e));
                                        }
                                    }
                                }
                                Some(Cmd::ConfirmObservedAddr { reply }) => {
                                    // Slice BG: trust last identify observed addr as external.
                                    // Slice BU: same shared advertised cap; refuse over limit.
                                    let addr = state_bg
                                        .lock()
                                        .map(|st| st.last_observed_addr.clone())
                                        .unwrap_or_default();
                                    if addr.trim().is_empty() {
                                        let _ = reply.send(Err(
                                            "no observed addr yet (wait for identify)".into(),
                                        ));
                                        continue;
                                    }
                                    match addr.parse::<Multiaddr>() {
                                        Ok(ma) => {
                                            let s = ma.to_string();
                                            if !swarm_may_add_external_address(&ma) {
                                                let _ = reply.send(Err(
                                                    CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_MSG.into(),
                                                ));
                                                continue;
                                            }
                                            let key = advertised_charge_key(&ma);
                                            let admit = match state_bg.lock() {
                                                Ok(mut st) => {
                                                    if advertised_already_charged(&st, &key) {
                                                        Ok(false)
                                                    } else {
                                                        admit_aux_advertised_external(
                                                            &mut st, &key,
                                                        )
                                                    }
                                                }
                                                Err(_) => {
                                                    Err("state lock poisoned".into())
                                                }
                                            };
                                            if let Err(msg) = admit {
                                                let _ = reply.send(Err(msg));
                                                continue;
                                            }
                                            match key.parse::<Multiaddr>() {
                                                Ok(canonical) => {
                                                    swarm_add_external_if_charged(
                                                        &mut swarm,
                                                        canonical,
                                                    );
                                                }
                                                Err(e) => {
                                                    let _ = reply.send(Err(format!(
                                                        "bad observed charge key: {e}"
                                                    )));
                                                    continue;
                                                }
                                            }
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.external_addr_confirmed = st
                                                    .external_addr_confirmed
                                                    .saturating_add(1);
                                                st.observed_addr_confirmed = st
                                                    .observed_addr_confirmed
                                                    .saturating_add(1);
                                                if !st.external_addrs.contains(&key) {
                                                    st.external_addrs.push(key);
                                                }
                                            }
                                            let _ = reply.send(Ok(s));
                                        }
                                        Err(e) => {
                                            let _ = reply.send(Err(format!(
                                                "bad observed multiaddr: {e}"
                                            )));
                                        }
                                    }
                                }
                                Some(Cmd::ClearObservedAddr { reply }) => {
                                    // Slice BL: wipe last_observed surface (not external book).
                                    let prev = if let Ok(mut st) = state_bg.lock() {
                                        let prev = st.last_observed_addr.clone();
                                        if !prev.trim().is_empty() {
                                            st.last_observed_addr.clear();
                                            st.observed_addr_cleared =
                                                st.observed_addr_cleared.saturating_add(1);
                                        }
                                        prev
                                    } else {
                                        let _ = reply.send(Err("state lock poisoned".into()));
                                        continue;
                                    };
                                    let _ = reply.send(Ok(prev));
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
                                    let key = advertised_charge_key(&address);
                                    let is_circuit = address
                                        .iter()
                                        .any(|p| matches!(p, Protocol::P2pCircuit));
                                    let is_ip6 = s.contains("/ip6/");
                                    let is_quic =
                                        s.contains("/quic-v1") || s.contains("/quic/");
                                    let is_ws = s.contains("/ws");
                                    listen_ids.insert(s.clone(), listener_id);
                                    // Slice X/AG: listen addrs become external so register has material.
                                    // Slice BS: same advertised cap as operator persist; refuse over max.
                                    // Do not remove_listener on refuse — one ListenerId can emit
                                    // several NewListenAddr (dual-stack); tearing it down would
                                    // drop already-admitted siblings.
                                    let advertise_listen = if !is_circuit {
                                        match state_bg.lock() {
                                            Ok(mut st) => {
                                                admit_listen_derived_external(&mut st, &key).is_ok()
                                            }
                                            Err(_) => false,
                                        }
                                    } else {
                                        false
                                    };
                                    if advertise_listen {
                                        let add_ma = key.parse::<Multiaddr>().unwrap_or(address.clone());
                                        swarm_add_external_if_charged(&mut swarm, add_ma);
                                    }
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.new_listen_addr =
                                            st.new_listen_addr.saturating_add(1);
                                        if !st.listen_addrs.contains(&s) {
                                            st.listen_addrs.push(s.clone());
                                        }
                                        if advertise_listen {
                                            st.external_addr_confirmed = st
                                                .external_addr_confirmed
                                                .saturating_add(1);
                                            if !st.external_addrs.iter().any(|a| {
                                                advertised_query_key(a) == key
                                            }) {
                                                st.external_addrs.push(key.clone());
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
                                        st.listen_derived_external.retain(|a| a != &s);
                                        st.aux_advertised_external.retain(|a| a != &s);
                                        st.mdns_advertised_listen.retain(|a| a != &s);
                                        st.kad_advertised_listen.retain(|a| a != &s);
                                        st.autonat_advertised_listen.retain(|a| a != &s);
                                        st.upnp_advertised_listen.retain(|a| a != &s);
                                        st.dcutr_advertised_candidates.retain(|a| a != &s);
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
                                            st.listen_derived_external.retain(|x| x != &a);
                                            st.aux_advertised_external.retain(|x| x != &a);
                                            st.mdns_advertised_listen.retain(|x| x != &a);
                                            st.kad_advertised_listen.retain(|x| x != &a);
                                            st.autonat_advertised_listen.retain(|x| x != &a);
                                            st.upnp_advertised_listen.retain(|x| x != &a);
                                            st.dcutr_advertised_candidates.retain(|x| x != &a);
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
                                    let key = advertised_charge_key(&address);
                                    let is_circuit = address
                                        .iter()
                                        .any(|p| matches!(p, Protocol::P2pCircuit));
                                    if let Ok(mut st) = state_bg.lock() {
                                        let listen_derived = st.listen_addrs.iter().any(|a| {
                                            a == &s || a == &key
                                        });
                                        let admit_ok = if is_circuit {
                                            false
                                        } else if listen_derived {
                                            admit_listen_derived_external(&mut st, &key).is_ok()
                                        } else {
                                            advertised_already_charged(&st, &key)
                                                || admit_aux_advertised_external(&mut st, &key)
                                                    .is_ok()
                                        };
                                        if admit_ok {
                                            st.external_addr_confirmed = st
                                                .external_addr_confirmed
                                                .saturating_add(1);
                                            if !st.external_addrs.contains(&key) {
                                                st.external_addrs.push(key.clone());
                                            }
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
                                    let key = advertised_charge_key(&address);
                                    if let Ok(mut st) = state_bg.lock() {
                                        st.external_addr_expired =
                                            st.external_addr_expired.saturating_add(1);
                                        st.external_addrs.retain(|a| a != &s && a != &key);
                                        st.listen_derived_external
                                            .retain(|a| a != &s && a != &key);
                                        st.aux_advertised_external
                                            .retain(|a| a != &s && a != &key);
                                        st.dcutr_advertised_candidates
                                            .retain(|a| a != &s && a != &key);
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
                                            let obs = info.observed_addr.to_string();
                                            let auto_confirm = state_bg
                                                .lock()
                                                .map(|st| st.enable_confirm_observed_addr)
                                                .unwrap_or(false);
                                            if let Ok(mut st) = state_bg.lock() {
                                                st.identify_received =
                                                    st.identify_received.saturating_add(1);
                                                st.identify.insert(peer_id.to_string(), snap);
                                                // Slice BG: remote's view of our dialable address.
                                                if !obs.is_empty() {
                                                    st.last_observed_addr = obs.clone();
                                                    st.observed_addr_updates = st
                                                        .observed_addr_updates
                                                        .saturating_add(1);
                                                }
                                            }
                                            // Slice BI: opt-in trust observed addr as external.
                                            // Slice BU: same shared cap; skip swarm add over limit.
                                            if auto_confirm && !obs.is_empty() {
                                                if let Ok(ma) = obs.parse::<Multiaddr>() {
                                                    let key = advertised_charge_key(&ma);
                                                    let admit_ok = swarm_may_add_external_address(
                                                        &ma,
                                                    ) && match state_bg.lock() {
                                                            Ok(mut st) => {
                                                                advertised_already_charged(
                                                                    &st, &key,
                                                                ) || admit_aux_advertised_external(
                                                                    &mut st, &key,
                                                                )
                                                                .is_ok()
                                                            }
                                                            Err(_) => false,
                                                        };
                                                    if admit_ok {
                                                        if let Ok(canonical) =
                                                            key.parse::<Multiaddr>()
                                                        {
                                                            swarm_add_external_if_charged(
                                                                &mut swarm, canonical,
                                                            );
                                                        }
                                                        if let Ok(mut st) = state_bg.lock() {
                                                            st.external_addr_confirmed = st
                                                                .external_addr_confirmed
                                                                .saturating_add(1);
                                                            st.observed_addr_confirmed = st
                                                                .observed_addr_confirmed
                                                                .saturating_add(1);
                                                            if !st.external_addrs.contains(&key)
                                                            {
                                                                st.external_addrs.push(key);
                                                            }
                                                        }
                                                    }
                                                }
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
                                                // Slice BD: StreamUpgradeError taxonomy.
                                                match &error {
                                                    StreamUpgradeError::Timeout => {
                                                        st.identify_error_timeout = st
                                                            .identify_error_timeout
                                                            .saturating_add(1);
                                                    }
                                                    StreamUpgradeError::NegotiationFailed => {
                                                        st.identify_error_negotiation = st
                                                            .identify_error_negotiation
                                                            .saturating_add(1);
                                                    }
                                                    StreamUpgradeError::Apply(_) => {
                                                        st.identify_error_apply = st
                                                            .identify_error_apply
                                                            .saturating_add(1);
                                                    }
                                                    StreamUpgradeError::Io(_) => {
                                                        st.identify_error_io = st
                                                            .identify_error_io
                                                            .saturating_add(1);
                                                    }
                                                }
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
                                        let key = advertised_charge_key(&addr);
                                        let admit_ok = match state_bg.lock() {
                                            Ok(mut st) => {
                                                gated_external_confirmed(&mut st, &addr).is_some()
                                            }
                                            Err(_) => false,
                                        };
                                        if admit_ok {
                                            if let Ok(canonical) = key.parse::<Multiaddr>() {
                                                swarm_add_external_if_charged(
                                                    &mut swarm,
                                                    canonical,
                                                );
                                            }
                                        }
                                        if let Ok(mut st) = state_bg.lock() {
                                            st.upnp_external_addrs =
                                                st.upnp_external_addrs.saturating_add(1);
                                            if admit_ok && !st.external_addrs.contains(&key) {
                                                st.external_addrs.push(key.clone());
                                            }
                                            if !st.listen_addrs.contains(&key) {
                                                st.listen_addrs.push(key);
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
                                                let omit = state_bg
                                                    .lock()
                                                    .map(|st| st.enable_wire_omit_response)
                                                    .unwrap_or(false);
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
                                                if omit {
                                                    // Slice BB: drop channel → ResponseOmission.
                                                    drop(channel);
                                                } else {
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
            mdns_ttl_secs = None,
            external_addrs_path = None,
            max_advertised_external = None
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
            external_addrs_path: Option<String>,
            max_advertised_external: Option<u32>,
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
                resolve_external_addrs_path(external_addrs_path),
                resolve_max_advertised_external(max_advertised_external)
                    .map_err(PyRuntimeError::new_err)?,
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

        /// Slice BH: forget one bootstrap peer. Returns true if the peer was present.
        fn bootstrap_remove(&self, peer_id: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BootstrapRemove {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(removed)) => Ok(removed),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("bootstrap_remove reply dropped")),
            }
        }

        /// Slice BJ: wipe the bootstrap book. Returns the number of peers cleared.
        fn bootstrap_clear(&self) -> PyResult<usize> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::BootstrapClear { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(n)) => Ok(n),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("bootstrap_clear reply dropped")),
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

        /// Slice BK: wipe the learned peerstore. Returns the number of peers cleared.
        fn peerstore_clear(&self) -> PyResult<usize> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PeerstoreClear { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(n)) => Ok(n),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("peerstore_clear reply dropped")),
            }
        }

        /// Slice BE: forget one learned peer. Returns true if the peer was present.
        fn peerstore_remove(&self, peer_id: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PeerstoreRemove {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(removed)) => Ok(removed),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("peerstore_remove reply dropped")),
            }
        }

        /// Slice BF: allow re-learning a forgotten peer. Returns true if it was forgotten.
        fn peerstore_allow_learn(&self, peer_id: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::PeerstoreAllowLearn {
                    peer_id: peer_id.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(cleared)) => Ok(cleared),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "peerstore_allow_learn reply dropped",
                )),
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

        /// Slice BC: push local identify info to ``peer_id`` or all connected peers.
        ///
        /// Returns the number of peers targeted (connected filter may drop some).
        #[pyo3(signature = (peer_id=None))]
        fn identify_push(&self, peer_id: Option<&str>) -> PyResult<usize> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::IdentifyPush {
                    peer_id: peer_id.map(|s| s.to_string()),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(n)) => Ok(n),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("identify_push reply dropped")),
            }
        }

        /// Slice BG: promote ``last_observed_addr`` into the external address book.
        ///
        /// Returns the confirmed multiaddr string.
        fn confirm_observed_addr(&self) -> PyResult<String> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::ConfirmObservedAddr { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(addr)) => Ok(addr),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "confirm_observed_addr reply dropped",
                )),
            }
        }

        /// Slice BL: wipe ``last_observed_addr``. Returns the previous value ("" if empty).
        ///
        /// Does not remove confirmed external addresses.
        fn clear_observed_addr(&self) -> PyResult<String> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::ClearObservedAddr { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(addr)) => Ok(addr),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err("clear_observed_addr reply dropped")),
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

        /// Slice CX: rust-libp2p `Swarm::external_addresses` crate book.
        ///
        /// Identify / Kad / Relay occupancy. Distinct from ``external_addrs``
        /// (our charged book). Circuit must not appear here.
        fn swarm_external_addrs(&self) -> PyResult<Vec<String>> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::SwarmExternalAddrs { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(addrs) => Ok(addrs),
                Err(_) => Err(PyRuntimeError::new_err(
                    "swarm_external_addrs reply dropped",
                )),
            }
        }

        /// Slice AG/BO: mark multiaddr as externally reachable.
        ///
        /// Returns true if the addr was newly inserted into the local book.
        fn add_external_address(&self, multiaddr: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::AddExternalAddress {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(fresh)) => Ok(fresh),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "add_external_address reply dropped",
                )),
            }
        }

        /// Slice AG/BN: expire a previously confirmed external multiaddr.
        ///
        /// Returns true if the addr was present in the local book.
        fn remove_external_address(&self, multiaddr: &str) -> PyResult<bool> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::RemoveExternalAddress {
                    addr: multiaddr.to_string(),
                    reply: tx,
                })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(removed)) => Ok(removed),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "remove_external_address reply dropped",
                )),
            }
        }

        /// Slice BM: wipe the external address book. Returns the number of addrs cleared.
        fn clear_external_addrs(&self) -> PyResult<usize> {
            let (tx, rx) = oneshot::channel();
            self.cmd_tx
                .send(Cmd::ClearExternalAddrs { reply: tx })
                .map_err(|_| PyRuntimeError::new_err("libp2p swarm stopped"))?;
            match rx.blocking_recv() {
                Ok(Ok(n)) => Ok(n),
                Ok(Err(e)) => Err(PyValueError::new_err(e)),
                Err(_) => Err(PyRuntimeError::new_err(
                    "clear_external_addrs reply dropped",
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
                d.set_item("libp2p_external_addr_cleared", st.external_addr_cleared)?;
                d.set_item("libp2p_external_addr_loaded", st.external_addr_loaded)?;
                d.set_item("libp2p_external_addr_persisted", st.external_addr_persisted)?;
                d.set_item("libp2p_max_advertised_external", st.max_advertised_external)?;
                d.set_item(
                    "libp2p_listen_derived_externals",
                    st.listen_derived_external.len(),
                )?;
                d.set_item(
                    "libp2p_aux_advertised_externals",
                    st.aux_advertised_external.len(),
                )?;
                d.set_item("libp2p_advertised_externals_used", advertised_used(&st))?;
                d.set_item(
                    "libp2p_external_addr_limit_refused",
                    st.external_addr_limit_refused,
                )?;
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
                d.set_item("libp2p_wire_omit_response", st.enable_wire_omit_response)?;
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
                d.set_item(
                    "libp2p_identify_listen_addr_omitted",
                    st.identify_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_identify_candidate_omitted",
                    st.identify_candidate_omitted,
                )?;
                d.set_item("libp2p_identify_sent", st.identify_sent)?;
                d.set_item("libp2p_identify_pushed", st.identify_pushed)?;
                d.set_item("libp2p_identify_error", st.identify_error)?;
                d.set_item("libp2p_identify_error_timeout", st.identify_error_timeout)?;
                d.set_item(
                    "libp2p_identify_error_negotiation",
                    st.identify_error_negotiation,
                )?;
                d.set_item("libp2p_identify_error_apply", st.identify_error_apply)?;
                d.set_item("libp2p_identify_error_io", st.identify_error_io)?;
                d.set_item("libp2p_identify_interval_ms", st.identify_interval_ms)?;
                d.set_item("libp2p_identify_push", st.enable_identify_push)?;
                d.set_item("libp2p_identify_push_requests", st.identify_push_requests)?;
                d.set_item("libp2p_last_observed_addr", &st.last_observed_addr)?;
                d.set_item("libp2p_observed_addr_updates", st.observed_addr_updates)?;
                d.set_item("libp2p_observed_addr_confirmed", st.observed_addr_confirmed)?;
                d.set_item("libp2p_observed_addr_cleared", st.observed_addr_cleared)?;
                d.set_item(
                    "libp2p_confirm_observed_addr",
                    st.enable_confirm_observed_addr,
                )?;
                d.set_item("libp2p_agent_version", &st.agent_version)?;
                d.set_item("libp2p_protocol_version", &st.protocol_version)?;
                d.set_item("libp2p_mdns_discovered", st.mdns_discovered)?;
                d.set_item("libp2p_mdns_expired", st.mdns_expired)?;
                d.set_item(
                    "libp2p_mdns_listen_addr_omitted",
                    st.mdns_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_mdns_advertised_listen",
                    st.mdns_advertised_listen.len(),
                )?;
                d.set_item("libp2p_mdns_ttl_secs", st.mdns_ttl_secs)?;
                d.set_item("libp2p_discovered_peers", st.discovered.len())?;
                d.set_item("libp2p_kad_peers", st.kad_peers.len())?;
                d.set_item("libp2p_kad_listen_addr_omitted", st.kad_listen_addr_omitted)?;
                d.set_item(
                    "libp2p_kad_advertised_listen",
                    st.kad_advertised_listen.len(),
                )?;
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
                d.set_item(
                    "libp2p_relay_client_circuit_external_omitted",
                    st.relay_client_circuit_external_omitted,
                )?;
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
                d.set_item(
                    "libp2p_autonat_listen_addr_omitted",
                    st.autonat_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_autonat_external_confirmed_omitted",
                    st.autonat_external_confirmed_omitted,
                )?;
                d.set_item(
                    "libp2p_autonat_advertised_listen",
                    st.autonat_advertised_listen.len(),
                )?;
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
                d.set_item("libp2p_dcutr_candidate_omitted", st.dcutr_candidate_omitted)?;
                d.set_item(
                    "libp2p_dcutr_advertised_candidates",
                    st.dcutr_advertised_candidates.len(),
                )?;
                d.set_item("libp2p_bootstrap_peers", st.bootstrap.len())?;
                d.set_item("libp2p_bootstrap_dials_ok", st.bootstrap_dials_ok)?;
                d.set_item("libp2p_bootstrap_dials_fail", st.bootstrap_dials_fail)?;
                d.set_item("libp2p_bootstrap_dials_timeout", st.bootstrap_dials_timeout)?;
                d.set_item(
                    "libp2p_bootstrap_dials_attempted",
                    st.bootstrap_dials_attempted,
                )?;
                d.set_item("libp2p_bootstrap_removed", st.bootstrap_removed)?;
                d.set_item("libp2p_bootstrap_cleared", st.bootstrap_cleared)?;
                d.set_item(
                    "libp2p_bootstrap_dial_timeout_secs",
                    st.bootstrap_dial_timeout_secs,
                )?;
                d.set_item("libp2p_peerstore_peers", st.peerstore.len())?;
                d.set_item("libp2p_peerstore_learned", st.peerstore_learned)?;
                d.set_item("libp2p_peerstore_removed", st.peerstore_removed)?;
                d.set_item("libp2p_peerstore_cleared", st.peerstore_cleared)?;
                d.set_item("libp2p_peerstore_allow_learn", st.peerstore_allow_learn)?;
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
                    "libp2p_upnp_listen_addr_omitted",
                    st.upnp_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_upnp_external_confirmed_omitted",
                    st.upnp_external_confirmed_omitted,
                )?;
                d.set_item(
                    "libp2p_upnp_advertised_listen",
                    st.upnp_advertised_listen.len(),
                )?;
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
                d.set_item("phase", 105)?;
                d.set_item("noise", true)?;
                d.set_item("yamux", true)?;
                d.set_item("gossipsub", true)?;
                d.set_item("peer_score", true)?;
                d.set_item("score_autoblock", st.enable_score_autoblock)?;
                d.set_item("peerstore", !st.peerstore_path.is_empty())?;
                d.set_item("peerstore_remove", true)?;
                d.set_item("peerstore_clear", true)?;
                d.set_item("peerstore_allow_learn", true)?;
                d.set_item("peerstore_reconnect", st.enable_reconnect)?;
                d.set_item("bootstrap_peerstore_atomic_persist", true)?;
                d.set_item("identity_atomic_persist", true)?;
                d.set_item("persist_parent_dir_fsync", true)?;
                d.set_item(
                    "persist_parent_dir_fsync_strategy",
                    persist_parent_dir_fsync_strategy(),
                )?;
                d.set_item("persist_mkdir_fsync", true)?;
                d.set_item(
                    "persist_mkdir_fsync_strategy",
                    persist_mkdir_fsync_strategy(),
                )?;
                d.set_item("persist_json_acl_restrict", true)?;
                d.set_item("persist_json_acl_strategy", persist_json_acl_strategy())?;
                d.set_item("identity_key_mode_restrict", true)?;
                d.set_item("identity_key_mode_strategy", identity_key_mode_strategy())?;
                d.set_item("identity_key_windows_owner_dacl", cfg!(windows))?;
                d.set_item("identity_create_exclusive", true)?;
                d.set_item(
                    "identity_create_exclusive_strategy",
                    identity_create_exclusive_strategy(),
                )?;
                d.set_item("identity_key_tmp_restrict_at_create", true)?;
                d.set_item(
                    "identity_key_tmp_restrict_strategy",
                    identity_key_tmp_restrict_strategy(),
                )?;
                d.set_item("identity_key_existing_acl_refuse", true)?;
                d.set_item(
                    "identity_key_existing_acl_strategy",
                    identity_key_existing_acl_strategy(),
                )?;
                d.set_item("identity_key_null_dacl_refuse", cfg!(windows))?;
                d.set_item(
                    "identity_key_null_dacl_strategy",
                    identity_key_null_dacl_strategy(),
                )?;
                d.set_item("identity_key_callback_ace_refuse", cfg!(windows))?;
                d.set_item(
                    "identity_key_callback_ace_strategy",
                    identity_key_callback_ace_strategy(),
                )?;
                d.set_item("identity_key_protected_dacl_refuse", cfg!(windows))?;
                d.set_item(
                    "identity_key_protected_dacl_strategy",
                    identity_key_protected_dacl_strategy(),
                )?;
                d.set_item("identity_key_parent_dir_refuse", true)?;
                d.set_item(
                    "identity_key_parent_dir_strategy",
                    identity_key_parent_dir_strategy(),
                )?;
                d.set_item("identity_key_parent_mkdir_recheck", true)?;
                d.set_item(
                    "identity_key_parent_mkdir_recheck_strategy",
                    identity_key_parent_mkdir_recheck_strategy(),
                )?;
                d.set_item("identity_key_parent_unattested_refuse", true)?;
                d.set_item(
                    "identity_key_parent_unattested_strategy",
                    identity_key_parent_unattested_strategy(),
                )?;
                d.set_item("persist_tmp_per_thread", true)?;
                d.set_item("persist_tmp_strategy", persist_tmp_strategy())?;
                d.set_item("persist_tmp_stale_tid_sweep", true)?;
                d.set_item(
                    "persist_tmp_stale_tid_strategy",
                    persist_tmp_stale_tid_strategy(),
                )?;
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
                d.set_item("add_external_address", true)?;
                d.set_item("remove_external_address", true)?;
                d.set_item("clear_external_addrs", true)?;
                d.set_item("external_addrs_persist", !st.external_addrs_path.is_empty())?;
                d.set_item("external_addrs_atomic_persist", true)?;
                d.set_item("external_addrs_replace_no_unlink", true)?;
                d.set_item(
                    "external_addrs_replace_strategy",
                    external_addrs_replace_strategy(),
                )?;
                d.set_item("external_addrs_max", true)?;
                d.set_item("listen_derived_external_max", true)?;
                d.set_item("advertised_externals_shared_max", true)?;
                d.set_item("advertised_externals_all_paths_max", true)?;
                d.set_item("identify_listen_addrs_capped", true)?;
                d.set_item("mdns_listen_addrs_capped", true)?;
                d.set_item("kad_listen_addrs_capped", true)?;
                d.set_item("autonat_listen_addrs_capped", true)?;
                d.set_item("upnp_listen_addrs_capped", true)?;
                d.set_item("advertised_externals_libp2p_book_aligned", true)?;
                d.set_item("circuit_excluded_from_external_book", true)?;
                d.set_item(
                    "circuit_excluded_from_external_book_strategy",
                    circuit_excluded_from_external_book_strategy(),
                )?;
                d.set_item("relay_client_circuit_not_in_external_book", true)?;
                d.set_item(
                    "relay_client_circuit_external_strategy",
                    relay_client_circuit_external_strategy(),
                )?;
                d.set_item("behaviour_external_confirmed_capped", true)?;
                d.set_item(
                    "behaviour_external_confirmed_strategy",
                    behaviour_external_confirmed_strategy(),
                )?;
                d.set_item("observed_external_charge_key", true)?;
                d.set_item(
                    "observed_external_charge_key_strategy",
                    observed_external_charge_key_strategy(),
                )?;
                d.set_item("behaviour_external_expired_canonical", true)?;
                d.set_item(
                    "behaviour_external_expired_strategy",
                    behaviour_external_expired_strategy(),
                )?;
                d.set_item("persist_external_charge_key", true)?;
                d.set_item(
                    "persist_external_charge_key_strategy",
                    persist_external_charge_key_strategy(),
                )?;
                d.set_item("swarm_external_addrs", true)?;
                d.set_item("dcutr_candidates_capped", true)?;
                d.set_item("identify_candidates_capped", true)?;
                d.set_item(
                    "libp2p_swarm_external_addresses_max",
                    LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX as u32,
                )?;
                d.set_item("max_advertised_external", st.max_advertised_external)?;
                d.set_item(
                    "max_advertised_external_hard",
                    MAX_ADVERTISED_EXTERNAL_ADDRS as u32,
                )?;
                d.set_item("external_addrs_path", &st.external_addrs_path)?;
                d.set_item("connection_lifecycle", true)?;
                d.set_item("connection_close_causes", true)?;
                d.set_item("listener_lifecycle", true)?;
                d.set_item("connection_attempts", true)?;
                d.set_item("dial_fail_events", true)?;
                d.set_item("dial_deny_events", true)?;
                d.set_item("deny_cause_events", true)?;
                d.set_item("incoming_fail_events", true)?;
                d.set_item("identify_events", true)?;
                d.set_item("identify_push", true)?;
                d.set_item("identify_push_listen_addr", st.enable_identify_push)?;
                d.set_item("identify_interval", true)?;
                d.set_item("identify_fail_events", true)?;
                d.set_item("identify_observed_addr", true)?;
                d.set_item("confirm_observed_addr", true)?;
                d.set_item("clear_observed_addr", true)?;
                d.set_item(
                    "confirm_observed_addr_auto",
                    st.enable_confirm_observed_addr,
                )?;
                d.set_item("identify_interval_ms", st.identify_interval_ms)?;
                d.set_item("last_observed_addr", &st.last_observed_addr)?;
                d.set_item("agent_version", &st.agent_version)?;
                d.set_item("protocol_version", &st.protocol_version)?;
                d.set_item("gossip_subscription_events", true)?;
                d.set_item("gossip_validation_events", true)?;
                d.set_item("gossip_defer_validation", st.enable_gossip_defer_validation)?;
                d.set_item("wire_rr_events", true)?;
                d.set_item("wire_fail_events", true)?;
                d.set_item("wire_omit_response", st.enable_wire_omit_response)?;
                d.set_item("connection_manager", true)?;
                d.set_item("bootstrap", true)?;
                d.set_item("bootstrap_remove", true)?;
                d.set_item("bootstrap_clear", true)?;
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
                d.set_item("libp2p_external_addr_cleared", st.external_addr_cleared)?;
                d.set_item("libp2p_external_addr_loaded", st.external_addr_loaded)?;
                d.set_item("libp2p_external_addr_persisted", st.external_addr_persisted)?;
                d.set_item("libp2p_max_advertised_external", st.max_advertised_external)?;
                d.set_item(
                    "libp2p_listen_derived_externals",
                    st.listen_derived_external.len(),
                )?;
                d.set_item(
                    "libp2p_aux_advertised_externals",
                    st.aux_advertised_external.len(),
                )?;
                d.set_item("libp2p_advertised_externals_used", advertised_used(&st))?;
                d.set_item(
                    "libp2p_external_addr_limit_refused",
                    st.external_addr_limit_refused,
                )?;
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
                d.set_item("libp2p_wire_omit_response", st.enable_wire_omit_response)?;
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
                d.set_item(
                    "libp2p_identify_listen_addr_omitted",
                    st.identify_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_identify_candidate_omitted",
                    st.identify_candidate_omitted,
                )?;
                d.set_item("libp2p_identify_sent", st.identify_sent)?;
                d.set_item("libp2p_identify_pushed", st.identify_pushed)?;
                d.set_item("libp2p_identify_error", st.identify_error)?;
                d.set_item("libp2p_identify_error_timeout", st.identify_error_timeout)?;
                d.set_item(
                    "libp2p_identify_error_negotiation",
                    st.identify_error_negotiation,
                )?;
                d.set_item("libp2p_identify_error_apply", st.identify_error_apply)?;
                d.set_item("libp2p_identify_error_io", st.identify_error_io)?;
                d.set_item("libp2p_identify_interval_ms", st.identify_interval_ms)?;
                d.set_item("libp2p_identify_push", st.enable_identify_push)?;
                d.set_item("libp2p_identify_push_requests", st.identify_push_requests)?;
                d.set_item("libp2p_last_observed_addr", &st.last_observed_addr)?;
                d.set_item("libp2p_observed_addr_updates", st.observed_addr_updates)?;
                d.set_item("libp2p_observed_addr_confirmed", st.observed_addr_confirmed)?;
                d.set_item("libp2p_observed_addr_cleared", st.observed_addr_cleared)?;
                d.set_item(
                    "libp2p_confirm_observed_addr",
                    st.enable_confirm_observed_addr,
                )?;
                d.set_item("libp2p_agent_version", &st.agent_version)?;
                d.set_item("libp2p_protocol_version", &st.protocol_version)?;
                d.set_item("libp2p_mdns_discovered", st.mdns_discovered)?;
                d.set_item("libp2p_mdns_expired", st.mdns_expired)?;
                d.set_item(
                    "libp2p_mdns_listen_addr_omitted",
                    st.mdns_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_mdns_advertised_listen",
                    st.mdns_advertised_listen.len(),
                )?;
                d.set_item("libp2p_mdns_ttl_secs", st.mdns_ttl_secs)?;
                d.set_item("libp2p_kad_peers", st.kad_peers.len())?;
                d.set_item("libp2p_kad_listen_addr_omitted", st.kad_listen_addr_omitted)?;
                d.set_item(
                    "libp2p_kad_advertised_listen",
                    st.kad_advertised_listen.len(),
                )?;
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
                d.set_item(
                    "libp2p_relay_client_circuit_external_omitted",
                    st.relay_client_circuit_external_omitted,
                )?;
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
                d.set_item(
                    "libp2p_autonat_listen_addr_omitted",
                    st.autonat_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_autonat_external_confirmed_omitted",
                    st.autonat_external_confirmed_omitted,
                )?;
                d.set_item(
                    "libp2p_autonat_advertised_listen",
                    st.autonat_advertised_listen.len(),
                )?;
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
                d.set_item("libp2p_dcutr_candidate_omitted", st.dcutr_candidate_omitted)?;
                d.set_item(
                    "libp2p_dcutr_advertised_candidates",
                    st.dcutr_advertised_candidates.len(),
                )?;
                d.set_item("libp2p_bootstrap_peers", st.bootstrap.len())?;
                d.set_item("libp2p_bootstrap_dials_ok", st.bootstrap_dials_ok)?;
                d.set_item("libp2p_bootstrap_dials_fail", st.bootstrap_dials_fail)?;
                d.set_item("libp2p_bootstrap_dials_timeout", st.bootstrap_dials_timeout)?;
                d.set_item(
                    "libp2p_bootstrap_dials_attempted",
                    st.bootstrap_dials_attempted,
                )?;
                d.set_item("libp2p_bootstrap_removed", st.bootstrap_removed)?;
                d.set_item("libp2p_bootstrap_cleared", st.bootstrap_cleared)?;
                d.set_item("libp2p_peerstore_peers", st.peerstore.len())?;
                d.set_item("libp2p_peerstore_learned", st.peerstore_learned)?;
                d.set_item("libp2p_peerstore_removed", st.peerstore_removed)?;
                d.set_item("libp2p_peerstore_cleared", st.peerstore_cleared)?;
                d.set_item("libp2p_peerstore_allow_learn", st.peerstore_allow_learn)?;
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
                    "libp2p_upnp_listen_addr_omitted",
                    st.upnp_listen_addr_omitted,
                )?;
                d.set_item(
                    "libp2p_upnp_external_confirmed_omitted",
                    st.upnp_external_confirmed_omitted,
                )?;
                d.set_item(
                    "libp2p_upnp_advertised_listen",
                    st.upnp_advertised_listen.len(),
                )?;
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

    fn resolve_external_addrs_path(explicit: Option<String>) -> Option<String> {
        if let Some(p) = explicit {
            let t = p.trim().to_string();
            if !t.is_empty() {
                return Some(t);
            }
        }
        match std::env::var("ABS_LIBP2P_EXTERNAL_ADDRS_PATH") {
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

    fn resolve_max_advertised_external(explicit: Option<u32>) -> Result<u32, String> {
        let raw = if let Some(v) = explicit {
            v
        } else {
            match std::env::var("ABS_LIBP2P_MAX_ADVERTISED_EXTERNAL_ADDRS") {
                Ok(s) => {
                    let t = s.trim();
                    if t.is_empty() {
                        MAX_ADVERTISED_EXTERNAL_ADDRS as u32
                    } else {
                        t.parse::<u32>()
                            .map_err(|e| format!("ABS_LIBP2P_MAX_ADVERTISED_EXTERNAL_ADDRS: {e}"))?
                    }
                }
                Err(_) => MAX_ADVERTISED_EXTERNAL_ADDRS as u32,
            }
        };
        if raw == 0 {
            return Err("max_advertised_external must be >= 1".into());
        }
        let hard = MAX_ADVERTISED_EXTERNAL_ADDRS as u32;
        if raw > hard {
            return Err(format!(
                "max_advertised_external {raw} exceeds hard max {hard}"
            ));
        }
        Ok(raw)
    }

    /// Slice BT/BU: unique charged advertised slots (operator + listen-derived + aux).
    /// Circuit addrs are never stored in these three sets.
    fn advertised_used(st: &NodeState) -> usize {
        let mut seen = HashSet::new();
        for a in st
            .advertised_external
            .iter()
            .chain(st.listen_derived_external.iter())
            .chain(st.aux_advertised_external.iter())
        {
            seen.insert(a.as_str());
        }
        seen.len()
    }

    fn advertised_already_charged(st: &NodeState, s: &str) -> bool {
        let q = advertised_query_key(s);
        st.advertised_external
            .iter()
            .any(|a| advertised_query_key(a) == q)
            || st
                .listen_derived_external
                .iter()
                .any(|a| advertised_query_key(a) == q)
            || st
                .aux_advertised_external
                .iter()
                .any(|a| advertised_query_key(a) == q)
    }

    fn advertised_at_cap(st: &NodeState) -> bool {
        advertised_used(st) >= st.max_advertised_external as usize
    }

    /// Bump refuse counter + last_error. Caller sends the returned message.
    fn refuse_advertised_over_cap(st: &mut NodeState, kind: &str) -> String {
        st.external_addr_limit_refused = st.external_addr_limit_refused.saturating_add(1);
        let msg = format!(
            "{kind}: {} exceeds max {}",
            advertised_used(st) + 1,
            st.max_advertised_external
        );
        st.last_error = msg.clone();
        msg
    }

    /// Slice BU: charge an observed/UPnP/rendezvous addr, or refuse.
    /// `Ok(true)` = newly charged; `Ok(false)` = already in the shared budget.
    fn admit_aux_advertised_external(st: &mut NodeState, s: &str) -> Result<bool, String> {
        if advertised_already_charged(st, s) {
            return Ok(false);
        }
        if advertised_at_cap(st) {
            return Err(refuse_advertised_over_cap(st, "advertised externals"));
        }
        st.aux_advertised_external.push(s.to_string());
        Ok(true)
    }

    /// Slice BS/BT: admit a listen-derived addr into the advertised book, or refuse.
    /// Shared cap (BT/BU): unique charged addrs ≤ max. Circuit is not counted.
    /// `Ok(true)` = newly counted; `Ok(false)` = already in the listen-derived set.
    fn admit_listen_derived_external(st: &mut NodeState, s: &str) -> Result<bool, String> {
        if st.listen_derived_external.iter().any(|a| a == s) {
            return Ok(false);
        }
        if advertised_already_charged(st, s) {
            st.listen_derived_external.push(s.to_string());
            return Ok(false);
        }
        if advertised_at_cap(st) {
            return Err(refuse_advertised_over_cap(st, "listen-derived externals"));
        }
        st.listen_derived_external.push(s.to_string());
        Ok(true)
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

    /// Slice BB: omit wire RR responses (lab path for ``ResponseOmission``).
    fn resolve_wire_omit_response(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_WIRE_OMIT_RESPONSE") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    /// Slice BI: auto-confirm identify observed addrs into external book.
    fn resolve_confirm_observed_addr(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_CONFIRM_OBSERVED_ADDR") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    /// Slice BC: push identify on local listen-addr changes.
    fn resolve_identify_push(explicit: Option<bool>) -> bool {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_IDENTIFY_PUSH") {
            Ok(s) => {
                let t = s.trim().to_ascii_lowercase();
                matches!(t.as_str(), "1" | "true" | "on" | "yes")
            }
            Err(_) => false,
        }
    }

    /// Slice BC: identify ``agent_version`` (User-Agent analogue).
    fn resolve_agent_version(explicit: Option<String>) -> String {
        if let Some(v) = explicit {
            return v;
        }
        match std::env::var("ABS_LIBP2P_AGENT_VERSION") {
            Ok(s) => {
                let t = s.trim();
                if t.is_empty() {
                    format!("absolute-experimental/{}", env!("CARGO_PKG_VERSION"))
                } else {
                    t.to_string()
                }
            }
            Err(_) => format!("absolute-experimental/{}", env!("CARGO_PKG_VERSION")),
        }
    }

    /// Slice BD: identify re-request interval after the first exchange.
    fn resolve_identify_interval_ms(explicit: Option<u64>) -> u64 {
        if let Some(v) = explicit {
            return v.max(1);
        }
        match std::env::var("ABS_LIBP2P_IDENTIFY_INTERVAL_MS") {
            Ok(s) => s
                .trim()
                .parse::<u64>()
                .ok()
                .unwrap_or(DEFAULT_IDENTIFY_INTERVAL_MS)
                .max(1),
            Err(_) => DEFAULT_IDENTIFY_INTERVAL_MS,
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
        mdns_ttl_secs = None,
        external_addrs_path = None,
        max_advertised_external = None
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
        external_addrs_path: Option<String>,
        max_advertised_external: Option<u32>,
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
            resolve_external_addrs_path(external_addrs_path),
            resolve_max_advertised_external(max_advertised_external)
                .map_err(PyRuntimeError::new_err)?,
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
        m.add(
            "ABS_IDENTIFY_PROTOCOL_VERSION",
            ABS_IDENTIFY_PROTOCOL_VERSION,
        )?;
        m.add("ABS_GOSSIP_BLOCKS_TOPIC", ABS_GOSSIP_BLOCKS_TOPIC)?;
        m.add("ABS_KAD_PROTOCOL", ABS_KAD_PROTOCOL)?;
        m.add("ABS_RENDEZVOUS_NAMESPACE", ABS_RENDEZVOUS_NAMESPACE)?;
        m.add(
            "MAX_ADVERTISED_EXTERNAL_ADDRS",
            MAX_ADVERTISED_EXTERNAL_ADDRS,
        )?;
        m.add(
            "LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX",
            LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX,
        )?;
        m.add(
            "EXTERNAL_ADDRS_REPLACE_STRATEGY",
            external_addrs_replace_strategy(),
        )?;
        m.add(
            "PERSIST_PARENT_DIR_FSYNC_STRATEGY",
            persist_parent_dir_fsync_strategy(),
        )?;
        m.add(
            "PERSIST_MKDIR_FSYNC_STRATEGY",
            persist_mkdir_fsync_strategy(),
        )?;
        m.add("PERSIST_JSON_ACL_STRATEGY", persist_json_acl_strategy())?;
        m.add("IDENTITY_KEY_UNIX_MODE", IDENTITY_KEY_UNIX_MODE)?;
        m.add("IDENTITY_KEY_MODE_STRATEGY", identity_key_mode_strategy())?;
        m.add(
            "IDENTITY_CREATE_EXCLUSIVE_STRATEGY",
            identity_create_exclusive_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_TMP_RESTRICT_STRATEGY",
            identity_key_tmp_restrict_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_EXISTING_ACL_STRATEGY",
            identity_key_existing_acl_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_NULL_DACL_STRATEGY",
            identity_key_null_dacl_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_CALLBACK_ACE_STRATEGY",
            identity_key_callback_ace_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_PROTECTED_DACL_STRATEGY",
            identity_key_protected_dacl_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_PARENT_DIR_STRATEGY",
            identity_key_parent_dir_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_PARENT_MKDIR_RECHECK_STRATEGY",
            identity_key_parent_mkdir_recheck_strategy(),
        )?;
        m.add(
            "IDENTITY_KEY_PARENT_UNATTESTED_STRATEGY",
            identity_key_parent_unattested_strategy(),
        )?;
        m.add("PERSIST_TMP_STRATEGY", persist_tmp_strategy())?;
        m.add(
            "PERSIST_TMP_STALE_TID_STRATEGY",
            persist_tmp_stale_tid_strategy(),
        )?;
        m.add(
            "CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_STRATEGY",
            circuit_excluded_from_external_book_strategy(),
        )?;
        m.add(
            "RELAY_CLIENT_CIRCUIT_EXTERNAL_STRATEGY",
            relay_client_circuit_external_strategy(),
        )?;
        m.add(
            "BEHAVIOUR_EXTERNAL_CONFIRMED_STRATEGY",
            behaviour_external_confirmed_strategy(),
        )?;
        m.add(
            "OBSERVED_EXTERNAL_CHARGE_KEY_STRATEGY",
            observed_external_charge_key_strategy(),
        )?;
        m.add(
            "BEHAVIOUR_EXTERNAL_EXPIRED_STRATEGY",
            behaviour_external_expired_strategy(),
        )?;
        m.add(
            "PERSIST_EXTERNAL_CHARGE_KEY_STRATEGY",
            persist_external_charge_key_strategy(),
        )?;
        Ok(())
    }
}

#[cfg(feature = "libp2p")]
pub use enabled::register;

#[cfg(test)]
mod tests {
    use super::{classify_abs_wire_codec, parse_external_addrs_json};

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

    #[test]
    fn parse_external_addrs_ok() {
        let v = parse_external_addrs_json(r#"{"version":1,"addrs":["/ip4/203.0.113.8/tcp/4001"]}"#)
            .expect("parse");
        assert_eq!(v, vec!["/ip4/203.0.113.8/tcp/4001".to_string()]);
    }

    #[test]
    fn parse_external_addrs_collapses_p2p_suffix() {
        let raw = r#"{"version":1,"addrs":[
            "/ip4/203.0.113.8/tcp/4001",
            "/ip4/203.0.113.8/tcp/4001/p2p/12D3KooWDpJ7As7BWAwRMfu1VU2WCqNjvq387JEYKDBj4kx6nXTN"
        ]}"#;
        let v = parse_external_addrs_json(raw).expect("parse");
        assert_eq!(v, vec!["/ip4/203.0.113.8/tcp/4001".to_string()]);
        assert_eq!(
            super::advertised_json_charge_key(
                "/ip4/203.0.113.8/tcp/4001/p2p/12D3KooWDpJ7As7BWAwRMfu1VU2WCqNjvq387JEYKDBj4kx6nXTN"
            ),
            "/ip4/203.0.113.8/tcp/4001"
        );
    }

    #[test]
    fn parse_external_addrs_rejects_garbage() {
        assert!(parse_external_addrs_json("{nope").is_err());
    }

    #[test]
    fn parse_external_addrs_rejects_missing_array() {
        assert!(parse_external_addrs_json("{}").is_err());
    }

    #[test]
    fn parse_external_addrs_rejects_non_multiaddr() {
        assert!(parse_external_addrs_json(r#"{"addrs":["not-an-addr"]}"#).is_err());
    }

    #[test]
    fn parse_external_addrs_rejects_empty_addr() {
        assert!(parse_external_addrs_json(r#"{"addrs":["  "]}"#).is_err());
    }

    #[test]
    fn advertised_cap_matches_libp2p_external_addresses_book() {
        assert_eq!(
            super::MAX_ADVERTISED_EXTERNAL_ADDRS,
            super::LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX
        );
        assert_eq!(super::LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX, 20);
    }

    #[test]
    fn multiaddr_is_p2p_circuit_token_only() {
        assert!(super::multiaddr_is_p2p_circuit(
            "/ip4/192.0.2.1/tcp/4001/p2p-circuit"
        ));
        assert!(super::multiaddr_is_p2p_circuit(
            "/ip4/127.0.0.1/tcp/4001/p2p-circuit/p2p/12D3KooWabcdef"
        ));
        assert!(!super::multiaddr_is_p2p_circuit("/ip4/192.0.2.1/tcp/4001"));
        assert!(
            !super::multiaddr_is_p2p_circuit("/dns4/p2p-circuit.example/tcp/4001"),
            "DNS label must not count as the circuit protocol"
        );
        assert_eq!(
            super::circuit_excluded_from_external_book_strategy(),
            "never_add_external_address"
        );
        assert_eq!(
            super::relay_client_circuit_external_strategy(),
            "omit_circuit_external_confirmed"
        );
        assert_eq!(
            super::behaviour_external_confirmed_strategy(),
            "admit_canonical_or_omit"
        );
        assert_eq!(
            super::observed_external_charge_key_strategy(),
            "admit_canonical_charge_key"
        );
        assert_eq!(
            super::behaviour_external_expired_strategy(),
            "expire_canonical_charge_key"
        );
        assert_eq!(
            super::persist_external_charge_key_strategy(),
            "load_canonical_charge_key"
        );
    }

    #[test]
    fn parse_external_addrs_rejects_circuit() {
        let err = parse_external_addrs_json(r#"{"addrs":["/ip4/192.0.2.1/tcp/4001/p2p-circuit"]}"#)
            .expect_err("circuit");
        assert!(
            err.contains("p2p-circuit"),
            "refuse text must name circuit: {err}"
        );
    }

    #[test]
    fn save_external_addrs_refuses_circuit() {
        let dest = std::env::temp_dir().join(format!(
            "abs-ext-circuit-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(23)
        ));
        let err =
            super::save_external_addrs_file(&dest, &["/ip4/192.0.2.1/tcp/4001/p2p-circuit".into()])
                .expect_err("circuit");
        assert!(err.contains("p2p-circuit"), "{err}");
        assert!(!dest.exists());
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn parse_external_addrs_rejects_over_hard_max() {
        let n = super::MAX_ADVERTISED_EXTERNAL_ADDRS + 1;
        let addrs: Vec<String> = (0..n)
            .map(|i| format!("\"/ip4/203.0.113.1/tcp/{}\"", 4000 + i))
            .collect();
        let raw = format!("{{\"addrs\":[{}]}}", addrs.join(","));
        let err = parse_external_addrs_json(&raw).expect_err("over max");
        assert!(err.contains("exceeds hard max"), "{err}");
    }

    #[test]
    fn save_external_addrs_refuses_over_hard_max() {
        let n = super::MAX_ADVERTISED_EXTERNAL_ADDRS + 1;
        let addrs: Vec<String> = (0..n)
            .map(|i| format!("/ip4/203.0.113.1/tcp/{}", 5000 + i))
            .collect();
        let dest = std::env::temp_dir().join("abs-ext-overmax.json");
        let err = super::save_external_addrs_file(&dest, &addrs).expect_err("over max");
        assert!(err.contains("exceeds hard max"), "{err}");
        assert!(!dest.exists() || dest.metadata().map(|m| m.len()).unwrap_or(0) == 0);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(super::external_addrs_tmp_path(&dest));
    }

    #[test]
    fn encode_external_addrs_roundtrip() {
        let raw =
            super::encode_external_addrs_json(&["/ip4/203.0.113.9/tcp/1".into()]).expect("encode");
        let v = parse_external_addrs_json(&raw).expect("parse");
        assert_eq!(v, vec!["/ip4/203.0.113.9/tcp/1".to_string()]);
    }

    #[test]
    fn load_external_addrs_missing_file_is_empty() {
        let p = std::path::Path::new("definitely-missing-abs-external-addrs.json");
        let v = super::load_external_addrs_file(p).expect("missing");
        assert!(v.is_empty());
    }

    #[test]
    fn save_external_addrs_atomic_no_leftover_tmp() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-ext-atomic-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        super::save_external_addrs_file(&dest, &["/ip4/203.0.113.1/tcp/1".into()]).expect("save");
        assert!(dest.is_file(), "dest missing");
        assert!(!tmp.exists(), "tmp leftover: {tmp:?}");
        let v = super::load_external_addrs_file(&dest).expect("load");
        assert_eq!(v, vec!["/ip4/203.0.113.1/tcp/1".to_string()]);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn save_external_addrs_replaces_existing_and_cleans_stale_tmp() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-ext-replace-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(1)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        std::fs::write(
            &dest,
            "{\"version\":1,\"addrs\":[\"/ip4/203.0.113.2/tcp/2\"]}",
        )
        .expect("seed");
        std::fs::write(&tmp, "{stale").expect("stale tmp");
        super::save_external_addrs_file(&dest, &["/ip4/203.0.113.3/tcp/3".into()]).expect("save");
        assert!(!tmp.exists(), "stale tmp not cleaned");
        let v = super::load_external_addrs_file(&dest).expect("load");
        assert_eq!(v, vec!["/ip4/203.0.113.3/tcp/3".to_string()]);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn external_addrs_replace_strategy_matches_os() {
        let s = super::external_addrs_replace_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_movefileex_replace");
        } else {
            assert_eq!(s, "posix_rename");
        }
    }

    #[test]
    fn persist_parent_dir_fsync_strategy_matches_os() {
        let s = super::persist_parent_dir_fsync_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_dir_flushfilebuffers");
        } else {
            assert_eq!(s, "posix_dir_fsync");
        }
    }

    #[test]
    fn persist_mkdir_fsync_strategy_matches_parent_dir() {
        assert_eq!(
            super::persist_mkdir_fsync_strategy(),
            super::persist_parent_dir_fsync_strategy()
        );
    }

    #[test]
    fn persist_json_acl_strategy_matches_tmp_restrict() {
        assert_eq!(
            super::persist_json_acl_strategy(),
            super::identity_key_tmp_restrict_strategy()
        );
    }

    #[test]
    fn identity_key_parent_dir_strategy_matches_os() {
        let s = super::identity_key_parent_dir_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_dir_no_users_write");
        } else {
            assert_eq!(s, "unix_dir_no_group_other_write");
        }
    }

    #[test]
    fn identity_key_parent_mkdir_recheck_strategy_is_mkdir_then_recheck() {
        assert_eq!(
            super::identity_key_parent_mkdir_recheck_strategy(),
            "mkdir_then_recheck_parent_acl"
        );
    }

    #[test]
    fn identity_key_parent_unattested_strategy_is_absolute_cwd_refuse_volume_root() {
        assert_eq!(
            super::identity_key_parent_unattested_strategy(),
            "absolute_cwd_refuse_volume_root"
        );
    }

    #[test]
    fn identity_key_absolute_path_joins_cwd_for_relative() {
        let p = super::identity_key_absolute_path(std::path::Path::new("node.key"))
            .expect("absolute relative key");
        assert!(p.is_absolute(), "{p:?}");
        assert_eq!(p.file_name().unwrap(), "node.key");
        let err = super::identity_key_absolute_path(std::path::Path::new(""))
            .expect_err("empty key path");
        assert!(err.contains("empty"), "{err}");
    }

    #[test]
    fn identity_key_parent_dir_ok_relative_filename_uses_cwd() {
        super::identity_key_parent_dir_ok(std::path::Path::new("abs-ct-relative-only.key"))
            .expect("cwd parent must be attested for a relative identity path");
    }

    #[test]
    fn identity_parent_is_volume_root_matches_os_root() {
        #[cfg(windows)]
        {
            assert!(super::identity_parent_is_volume_root(std::path::Path::new(
                r"C:\"
            )));
            assert!(!super::identity_parent_is_volume_root(
                std::path::Path::new(r"C:\Users")
            ));
        }
        #[cfg(unix)]
        {
            assert!(super::identity_parent_is_volume_root(std::path::Path::new(
                "/"
            )));
            assert!(!super::identity_parent_is_volume_root(
                std::path::Path::new("/tmp")
            ));
        }
    }

    #[test]
    fn identity_key_parent_dir_ok_refuses_volume_root() {
        let dest = {
            #[cfg(windows)]
            {
                use std::path::{Component, PathBuf};
                let tmp = std::env::temp_dir();
                let mut root = PathBuf::new();
                for c in tmp.components() {
                    match c {
                        Component::Prefix(_) | Component::RootDir => root.push(c),
                        _ => break,
                    }
                }
                root.join(format!(
                    "abs-ct-volroot-{}-{}.key",
                    std::process::id(),
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_nanos())
                        .unwrap_or(18)
                ))
            }
            #[cfg(unix)]
            {
                std::path::PathBuf::from(format!(
                    "/abs-ct-volroot-{}-{}.key",
                    std::process::id(),
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_nanos())
                        .unwrap_or(18)
                ))
            }
            #[cfg(not(any(unix, windows)))]
            {
                return;
            }
        };
        let err = super::identity_key_parent_dir_ok(&dest)
            .expect_err("volume-root identity parent must refuse");
        let low = err.to_ascii_lowercase();
        assert!(
            low.contains("volume root") || low.contains("unattested"),
            "volume-root error too vague: {err}"
        );
        assert!(!dest.exists(), "volume-root key must not be created");
    }

    #[test]
    fn identity_key_parent_dir_ok_temp_parent() {
        let dest = std::env::temp_dir().join(format!(
            "abs-id-parent-temp-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(14)
        ));
        super::identity_key_parent_dir_ok(&dest)
            .expect("user temp parent must be an allowed identity keystore dir");
    }

    #[test]
    fn atomic_write_file_json_born_restricted() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-json-acl-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(13)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        super::atomic_write_file(&dest, b"{\"v\":1}").expect("json persist");
        assert_eq!(std::fs::read(&dest).expect("read"), b"{\"v\":1}");
        assert!(!tmp.exists(), "tmp leftover");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&dest).expect("stat").permissions().mode();
            assert_eq!(mode & 0o777, 0o600, "JSON persist mode {:o}", mode & 0o777);
        }
        #[cfg(windows)]
        {
            super::windows_identity_acl_ok(&dest)
                .expect("JSON persist dest DACL must be protected owner-only");
        }
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn identity_key_mode_strategy_matches_os() {
        let s = super::identity_key_mode_strategy();
        if cfg!(unix) {
            assert_eq!(s, "unix_0600");
        } else {
            assert_eq!(s, "windows_owner_only_dacl");
        }
        assert_eq!(super::IDENTITY_KEY_UNIX_MODE, 0o600);
    }

    #[test]
    fn identity_create_exclusive_strategy_matches_os() {
        let s = super::identity_create_exclusive_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_movefileex_noreplace");
        } else {
            assert_eq!(s, "posix_hardlink_exclusive");
        }
    }

    #[test]
    fn identity_key_tmp_restrict_strategy_matches_os() {
        let s = super::identity_key_tmp_restrict_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_createfile_owner_dacl");
        } else {
            assert_eq!(s, "unix_0600_at_create");
        }
    }

    #[test]
    fn identity_key_existing_acl_strategy_matches_mode() {
        assert_eq!(
            super::identity_key_existing_acl_strategy(),
            super::identity_key_mode_strategy()
        );
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dacl_sddl_refuses_users_everyone() {
        assert!(super::windows_identity_dacl_sddl_ok(
            "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)",
            ""
        )
        .is_ok());
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(A;;FR;;;BU)", "").is_err());
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(A;;FR;;;WD)", "").is_err());
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(A;;FR;;;AU)", "").is_err());
        assert!(super::windows_identity_dacl_sddl_ok(
            "D:P(A;;FA;;;S-1-5-21-1-2-3-1001)",
            "S-1-5-21-1-2-3-1001"
        )
        .is_ok());
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(D;;FA;;;WD)", "").is_ok());
        assert!(super::windows_identity_dacl_sddl_ok(
            "D:PAI(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)",
            ""
        )
        .is_ok());
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_acl_ok_refuses_inherited_then_accepts_restricted() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-id-acl-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(9)
        ));
        let _ = std::fs::remove_file(&dest);
        std::fs::write(&dest, b"not-a-key").expect("seed");
        let grant = std::process::Command::new("icacls")
            .arg(&dest)
            .arg("/grant")
            .arg("*S-1-5-32-545:R")
            .output()
            .expect("icacls grant");
        assert!(grant.status.success(), "icacls grant Users failed");
        let err = super::windows_identity_acl_ok(&dest).expect_err("Users ACE must refuse");
        assert!(
            err.contains("DACL")
                || err.contains("BU")
                || err.contains("Users")
                || err.contains("S-1-5-32-545"),
            "acl refuse too vague: {err}"
        );
        super::windows_restrict_owner_dacl(&dest).expect("restrict");
        super::windows_identity_acl_ok(&dest).expect("restricted DACL must load");
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn identity_key_null_dacl_strategy_matches_os() {
        let s = super::identity_key_null_dacl_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_null_dacl_refuse");
        } else {
            assert_eq!(s, "unix_mode_covers");
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dacl_sddl_refuses_null_dacl_token() {
        assert!(super::windows_identity_dacl_sddl_ok("D:NO_ACCESS_CONTROL", "").is_err());
        assert!(super::windows_identity_dacl_sddl_ok("d:no_access_control", "").is_err());
    }

    #[test]
    fn identity_key_callback_ace_strategy_matches_os() {
        let s = super::identity_key_callback_ace_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_callback_ace_refuse");
        } else {
            assert_eq!(s, "unix_mode_covers");
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dacl_sddl_refuses_callback_and_unknown_ace() {
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(XA;;FR;;;WD)", "").is_err());
        assert!(
            super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(ZA;;FA;;;WD;(TRUE))", "")
                .is_err()
        );
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(XU;;FR;;;AU)", "").is_err());
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(QQ;;FR;;;SY)", "").is_err());
        assert!(super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(A;;FA)", "").is_err());
        assert!(
            super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(XA;;FR;;;WD;(TRUE))", "")
                .is_err()
        );
        assert!(
            super::windows_identity_dacl_sddl_ok("D:P(A;;FA;;;OW)(XA;;FA;;;OW;(TRUE))", "").is_ok()
        );
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_acl_ok_refuses_null_dacl() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-id-nulldacl-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(10)
        ));
        let _ = std::fs::remove_file(&dest);
        std::fs::write(&dest, b"not-a-key").expect("seed");
        super::windows_set_null_dacl(&dest).expect("set NULL DACL");
        let err = super::windows_identity_acl_ok(&dest).expect_err("NULL DACL must refuse");
        assert!(
            err.to_ascii_uppercase().contains("NULL") || err.contains("DACL"),
            "null DACL error too vague: {err}"
        );
        let _ = std::fs::remove_file(&dest);
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_acl_ok_refuses_callback_everyone() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-id-cbace-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(11)
        ));
        let _ = std::fs::remove_file(&dest);
        std::fs::write(&dest, b"not-a-key").expect("seed");
        super::windows_set_dacl_from_sddl(
            &dest,
            "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)(XA;;FR;;;WD;(TRUE))",
            true,
        )
        .expect("set callback Everyone ACE");
        let err = super::windows_identity_acl_ok(&dest).expect_err("callback Everyone must refuse");
        let low = err.to_ascii_lowercase();
        assert!(
            low.contains("wd")
                || low.contains("xa")
                || low.contains("callback")
                || low.contains("dacl")
                || low.contains("everyone"),
            "callback ACE error too vague: {err}"
        );
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn identity_key_protected_dacl_strategy_matches_os() {
        let s = super::identity_key_protected_dacl_strategy();
        if cfg!(windows) {
            assert_eq!(s, "windows_protected_dacl_refuse");
        } else {
            assert_eq!(s, "unix_mode_covers");
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dacl_sddl_refuses_unprotected() {
        assert!(
            super::windows_identity_dacl_sddl_ok("D:(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)", "")
                .is_err()
        );
        assert!(super::windows_identity_dacl_sddl_ok(
            "D:AI(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)",
            ""
        )
        .is_err());
        assert!(super::windows_identity_dacl_sddl_ok(
            "D:PAI(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)",
            ""
        )
        .is_ok());
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_acl_ok_refuses_unprotected_owner_only() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-id-unprot-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(12)
        ));
        let _ = std::fs::remove_file(&dest);
        std::fs::write(&dest, b"not-a-key").expect("seed");
        super::windows_set_dacl_from_sddl(&dest, "D:(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)", false)
            .expect("set unprotected owner-only DACL");
        let err = super::windows_identity_acl_ok(&dest).expect_err("unprotected DACL must refuse");
        let low = err.to_ascii_lowercase();
        assert!(
            low.contains("protect") || low.contains("inherit") || low.contains("dacl"),
            "unprotected DACL error too vague: {err}"
        );
        let _ = std::fs::remove_file(&dest);
    }

    #[cfg(windows)]
    #[test]
    fn identity_ace_flags_inherit_only_is_pairwise() {
        assert!(!super::identity_ace_flags_inherit_only("OI"));
        assert!(!super::identity_ace_flags_inherit_only("OICI"));
        assert!(!super::identity_ace_flags_inherit_only("CIOI"));
        assert!(super::identity_ace_flags_inherit_only("IO"));
        assert!(super::identity_ace_flags_inherit_only("OIIO"));
        assert!(!super::identity_ace_flags_inherit_only("ID"));
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dir_sddl_users_rx_ok() {
        super::windows_identity_dir_sddl_ok("D:(A;OICI;0x1200a9;;;BU)(A;;FA;;;SY)(A;;FA;;;BA)", "")
            .expect("Users RX on a directory must pass");
        super::windows_identity_dir_sddl_ok(
            "D:(A;;FA;;;S-1-5-21-1-2-3-1004)(A;;FA;;;SY)(A;;FA;;;BA)",
            "",
        )
        .expect("named user FA on a directory must pass");
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dir_sddl_users_write_refuse() {
        assert!(super::windows_identity_dir_sddl_ok("D:(A;;FW;;;BU)", "").is_err());
        assert!(super::windows_identity_dir_sddl_ok("D:(A;;FA;;;BU)", "").is_err());
        assert!(super::windows_identity_dir_sddl_ok("D:(A;;0x2;;;BU)", "").is_err());
        assert!(super::windows_identity_dir_sddl_ok("D:(A;;DC;;;WD)", "").is_err());
        assert!(super::windows_identity_dir_sddl_ok("D:(A;;FW;;;AU)", "").is_err());
        assert!(super::windows_identity_dir_sddl_ok("D:NO_ACCESS_CONTROL", "").is_err());
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_dir_sddl_inherit_only_users_fa_skipped() {
        super::windows_identity_dir_sddl_ok("D:(A;OIIO;FA;;;BU)(A;;FA;;;SY)(A;;FA;;;BA)", "")
            .expect("inherit-only Users FA must not apply to the directory object");
        assert!(
            super::windows_identity_dir_sddl_ok("D:(A;OICIID;FW;;;BU)(A;;FA;;;SY)", "").is_err(),
            "inherited Users write on the created child must refuse"
        );
    }

    #[cfg(windows)]
    #[test]
    fn ensure_identity_key_parent_refuses_inherited_users_write() {
        let anc = std::env::temp_dir().join(format!(
            "abs-id-parent-io-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(17)
        ));
        let _ = std::fs::remove_dir_all(&anc);
        std::fs::create_dir_all(&anc).expect("mkdir ancestor");
        super::identity_key_parent_dir_ok(&anc.join("dummy.key"))
            .expect("ancestor before inherit-only grant");
        let grant = std::process::Command::new("icacls")
            .arg(&anc)
            .arg("/grant")
            .arg("*S-1-5-32-545:(OI)(CI)(IO)(W)")
            .output()
            .expect("icacls");
        assert!(
            grant.status.success(),
            "icacls inherit-only Users write on ancestor failed"
        );
        super::identity_key_parent_dir_ok(&anc.join("dummy.key"))
            .expect("inherit-only Users write must not apply to the ancestor object");
        let dest = anc.join("keystore").join("node.key");
        let err = super::ensure_identity_key_parent(&dest)
            .expect_err("created child inheriting Users write must refuse");
        let low = err.to_ascii_lowercase();
        assert!(
            low.contains("parent")
                || low.contains("write")
                || low.contains("dacl")
                || low.contains("dir"),
            "inherited parent write error too vague: {err}"
        );
        assert!(
            !dest.exists(),
            "key must not be written before parent recheck"
        );
        let _ = std::fs::remove_dir_all(&anc);
    }

    #[cfg(windows)]
    #[test]
    fn windows_identity_parent_acl_ok_refuses_users_write() {
        let dir = std::env::temp_dir().join(format!(
            "abs-id-parent-w-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(15)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("mkdir");
        let dest = dir.join("node.key");
        super::identity_key_parent_dir_ok(&dest).expect("nested temp parent must pass");
        let grant = std::process::Command::new("icacls")
            .arg(&dir)
            .arg("/grant")
            .arg("*S-1-5-32-545:(W)")
            .output()
            .expect("icacls");
        assert!(
            grant.status.success(),
            "icacls grant Users write on parent failed"
        );
        let err = super::identity_key_parent_dir_ok(&dest)
            .expect_err("Users write on parent must refuse");
        let low = err.to_ascii_lowercase();
        assert!(
            low.contains("parent")
                || low.contains("write")
                || low.contains("dacl")
                || low.contains("dir"),
            "parent write error too vague: {err}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn identity_key_parent_dir_refuses_group_other_write() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!(
            "abs-id-parent-mode-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(16)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("mkdir");
        let dest = dir.join("node.key");
        super::identity_key_parent_dir_ok(&dest).expect("0700 parent");
        let mut perms = std::fs::metadata(&dir).expect("stat").permissions();
        perms.set_mode(0o0777);
        std::fs::set_permissions(&dir, perms.clone()).expect("chmod 0777");
        let err = super::identity_key_parent_dir_ok(&dest).expect_err("0777 parent must refuse");
        assert!(
            err.contains("group/other write") || err.contains("mode"),
            "unix parent error too vague: {err}"
        );
        perms.set_mode(0o1777);
        std::fs::set_permissions(&dir, perms).expect("chmod sticky");
        super::identity_key_parent_dir_ok(&dest).expect("sticky parent must pass");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn create_persist_tmp_identity_overwrites_leftover_without_leaking_stale() {
        use std::io::Write;
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-id-tmp-left-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(8)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        std::fs::write(&tmp, b"stale-key-material").expect("seed leftover tmp");
        let mut f = super::create_persist_tmp(&tmp, Some(0o600)).expect("create restricted tmp");
        f.write_all(b"new-secret").expect("write");
        drop(f);
        assert_eq!(std::fs::read(&tmp).expect("read tmp"), b"new-secret");
        #[cfg(windows)]
        {
            let out = std::process::Command::new("icacls")
                .arg(&tmp)
                .output()
                .expect("icacls");
            let text = String::from_utf8_lossy(&out.stdout).to_lowercase();
            assert!(out.status.success(), "icacls failed");
            assert!(
                !text.contains("everyone:") && !text.contains("builtin\\users:"),
                "identity tmp born with inherited Users/Everyone ACL"
            );
        }
        let _ = std::fs::remove_file(&tmp);
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn persist_tmp_path_includes_pid() {
        let dest = std::path::Path::new("foo.json");
        let tmp = super::external_addrs_tmp_path(dest);
        let name = tmp.file_name().unwrap().to_string_lossy();
        let pid = std::process::id().to_string();
        let tid = super::persist_tmp_thread_tag();
        assert!(name.starts_with("foo.json."), "tmp name {name}");
        assert!(name.contains(&pid), "tmp name {name} missing pid");
        assert!(name.contains(&tid), "tmp name {name} missing tid");
        assert!(name.ends_with(".tmp"), "tmp name {name}");
        assert_eq!(
            super::external_addrs_tmp_path(dest),
            tmp,
            "same-thread tmp must be stable for leftover cleanup"
        );
    }

    #[test]
    fn persist_tmp_strategy_is_pid_tid() {
        assert_eq!(super::persist_tmp_strategy(), "pid_tid_tmp");
        assert_eq!(
            super::persist_tmp_stale_tid_strategy(),
            "unlink_not_in_flight"
        );
    }

    #[test]
    fn persist_tmp_name_is_ours_requires_this_pid() {
        let dest = std::ffi::OsStr::new("foo.json");
        assert!(super::persist_tmp_name_is_ours(
            std::ffi::OsStr::new("foo.json.1234.ThreadId1.tmp"),
            dest,
            "1234",
        ));
        assert!(super::persist_tmp_name_is_ours(
            std::ffi::OsStr::new("foo.json.1234.tmp"),
            dest,
            "1234",
        ));
        assert!(!super::persist_tmp_name_is_ours(
            std::ffi::OsStr::new("foo.json.12345.ThreadId1.tmp"),
            dest,
            "1234",
        ));
        assert!(!super::persist_tmp_name_is_ours(
            std::ffi::OsStr::new("foo.json.bak"),
            dest,
            "1234",
        ));
    }

    #[test]
    fn atomic_write_file_sweeps_stale_other_tid_tmp() {
        let dest = std::env::temp_dir().join(format!(
            "abs-tmp-cv-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(22)
        ));
        let pid = std::process::id();
        let stale = super::persist_tmp_join(&dest, &format!("{pid}.StaleTid.tmp"));
        let foreign = super::persist_tmp_join(&dest, "999999999.OtherPid.tmp");
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&stale);
        let _ = std::fs::remove_file(&foreign);
        std::fs::write(&stale, "{stale-tid").expect("stale other tid");
        std::fs::write(&foreign, "{other-pid").expect("other pid tmp");
        super::atomic_write_file(&dest, b"{\"version\":1,\"addrs\":[]}").expect("persist");
        assert!(!stale.exists(), "stale other-tid tmp not swept");
        assert!(
            foreign.exists(),
            "must not unlink another process pid staging"
        );
        assert!(dest.is_file(), "dest missing");
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&foreign);
    }

    #[test]
    fn atomic_write_file_skips_in_flight_other_tid() {
        let dest = std::env::temp_dir().join(format!(
            "abs-tmp-cv-hold-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(23)
        ));
        let pid = std::process::id();
        let held = super::persist_tmp_join(&dest, &format!("{pid}.HeldTid.tmp"));
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&held);
        std::fs::write(&held, b"in-flight").expect("held tmp");
        let _guard = super::PersistTmpInFlight::claim(held.clone());
        super::atomic_write_file(&dest, b"{\"version\":1,\"addrs\":[]}").expect("persist");
        assert!(held.is_file(), "in-flight other-tid tmp was stolen");
        assert_eq!(std::fs::read(&held).expect("read held"), b"in-flight");
        drop(_guard);
        let _ = std::fs::remove_file(&held);
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn persist_tmp_pid_only_differs_from_tid_path() {
        let dest = std::path::Path::new("foo.json");
        let tid = super::external_addrs_tmp_path(dest);
        let pid = super::persist_tmp_path_pid_only(dest);
        assert_ne!(tid, pid);
        let pid_s = std::process::id().to_string();
        let name = pid.file_name().unwrap().to_string_lossy();
        assert_eq!(name.as_ref(), format!("foo.json.{pid_s}.tmp"));
    }

    #[test]
    fn atomic_write_file_cleans_ck_pid_only_leftover() {
        let dest = std::env::temp_dir().join(format!(
            "abs-tmp-ck-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(21)
        ));
        let tid_tmp = super::external_addrs_tmp_path(&dest);
        let pid_tmp = super::persist_tmp_path_pid_only(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tid_tmp);
        let _ = std::fs::remove_file(&pid_tmp);
        std::fs::write(&pid_tmp, "{stale").expect("ck leftover");
        super::atomic_write_file(&dest, b"{\"version\":1,\"addrs\":[]}").expect("persist");
        assert!(
            !pid_tmp.exists(),
            "CK dest.{{pid}}.tmp leftover not cleaned"
        );
        assert!(!tid_tmp.exists(), "tid tmp leftover");
        assert!(dest.is_file(), "dest missing");
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn persist_tmp_path_differs_across_threads() {
        let dest = std::path::Path::new("foo.json");
        let main = super::external_addrs_tmp_path(dest);
        let other =
            std::thread::spawn(|| super::external_addrs_tmp_path(std::path::Path::new("foo.json")))
                .join()
                .expect("thread");
        assert_ne!(
            main, other,
            "two threads must not share dest.{{pid}}.tmp staging"
        );
    }

    #[test]
    fn atomic_write_file_two_threads_dest_is_single_snapshot() {
        let dest = std::env::temp_dir().join(format!(
            "abs-tmp-tid-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(19)
        ));
        let _ = std::fs::remove_file(&dest);
        let a = vec![0xA5u8; 32 * 1024];
        let b = vec![0x5Au8; 32 * 1024];
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let dest_a = dest.clone();
        let dest_b = dest.clone();
        let body_a = a.clone();
        let body_b = b.clone();
        let ba = barrier.clone();
        let bb = barrier.clone();
        let t1 = std::thread::spawn(move || {
            ba.wait();
            super::atomic_write_file(&dest_a, &body_a)
        });
        let t2 = std::thread::spawn(move || {
            bb.wait();
            super::atomic_write_file(&dest_b, &body_b)
        });
        let r1 = t1.join().expect("t1");
        let r2 = t2.join().expect("t2");
        assert!(
            r1.is_ok() || r2.is_ok(),
            "both persists failed: {r1:?} {r2:?}"
        );
        let got = std::fs::read(&dest).expect("dest after concurrent persist");
        assert!(
            got == a || got == b,
            "torn persist snapshot len={} first={} last={}",
            got.len(),
            got.first().copied().unwrap_or(0),
            got.last().copied().unwrap_or(0)
        );
        if let Some(parent) = dest.parent() {
            let prefix = dest.file_name().unwrap().to_string_lossy().into_owned();
            for entry in std::fs::read_dir(parent).expect("parent") {
                let p = entry.expect("entry").path();
                let name = p.file_name().unwrap().to_string_lossy();
                if name.starts_with(&prefix) && name.ends_with(".tmp") {
                    panic!("leftover persist tmp {p:?}");
                }
            }
        }
        let _ = std::fs::remove_file(&dest);
    }

    #[test]
    fn atomic_write_file_exclusive_creates_when_dest_missing() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-excl-create-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(6)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        super::atomic_write_file_exclusive(&dest, b"first-key", Some(0o600))
            .expect("exclusive create");
        assert_eq!(std::fs::read(&dest).expect("read"), b"first-key");
        assert!(!tmp.exists(), "tmp leftover after exclusive create");
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn atomic_write_file_exclusive_refuses_existing_dest() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-excl-keep-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(7)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        std::fs::write(&dest, b"keep-me").expect("seed dest");
        let err = super::atomic_write_file_exclusive(&dest, b"clobber", Some(0o600))
            .expect_err("exclusive must refuse existing dest");
        assert!(
            err.contains("refusing clobber") || err.contains("exists"),
            "exclusive error too vague: {err}"
        );
        assert_eq!(std::fs::read(&dest).expect("dest intact"), b"keep-me");
        assert!(!tmp.exists(), "tmp leftover after exclusive refuse");
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn atomic_write_file_creates_nested_parent_dirs() {
        let dir = std::env::temp_dir().join(format!(
            "abs-mkdir-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(5)
        ));
        let dest = dir.join("a").join("b").join("c.json");
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_dir_all(&dir);
        super::atomic_write_file(&dest, b"{\"nested\":1}").expect("nested write");
        assert_eq!(std::fs::read(&dest).expect("read"), b"{\"nested\":1}");
        assert!(!tmp.exists(), "tmp leftover");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn replace_file_overwrites_existing_dest_without_unlink_fallback() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-ext-nounlink-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(2)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        super::save_external_addrs_file(&dest, &["/ip4/203.0.113.4/tcp/4".into()]).expect("first");
        assert!(dest.is_file());
        super::save_external_addrs_file(&dest, &["/ip4/203.0.113.5/tcp/5".into()]).expect("second");
        assert!(dest.is_file(), "dest missing after replace");
        assert!(!tmp.exists(), "tmp leftover after replace");
        let v = super::load_external_addrs_file(&dest).expect("load");
        assert_eq!(v, vec!["/ip4/203.0.113.5/tcp/5".to_string()]);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn atomic_write_file_replaces_without_truncate_in_place() {
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-atomic-write-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(3)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        super::atomic_write_file(&dest, b"{\"v\":1}").expect("first");
        assert_eq!(std::fs::read(&dest).expect("read1"), b"{\"v\":1}");
        super::atomic_write_file(&dest, b"{\"v\":2}").expect("second");
        assert_eq!(std::fs::read(&dest).expect("read2"), b"{\"v\":2}");
        assert!(!tmp.exists(), "tmp leftover");
        super::fsync_parent_dir(&dest).expect("parent dir fsync");
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }

    #[cfg(unix)]
    #[test]
    fn atomic_write_file_with_mode_sets_0600() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir();
        let dest = dir.join(format!(
            "abs-key-mode-{}-{}.key",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(4)
        ));
        let tmp = super::external_addrs_tmp_path(&dest);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
        super::atomic_write_file_with_mode(&dest, b"secret-key", Some(0o600)).expect("write");
        let mode = std::fs::metadata(&dest).expect("stat").permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        let _ = std::fs::remove_file(&dest);
        let _ = std::fs::remove_file(&tmp);
    }
}
