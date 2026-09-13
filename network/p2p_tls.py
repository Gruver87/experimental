#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TLS wrappers for P2P TCP (prod mesh: TLS 1.2+ + mTLS by default)."""

from __future__ import annotations

import os
import ssl
from typing import Any, Optional, Set, Tuple

from crypto import native


def p2p_tls_enabled(config) -> bool:
    return bool(getattr(config, "p2p_tls_enabled", False))


def p2p_tls_fail_closed(config) -> bool:
    """When TLS is on, never use CERT_NONE (default true in prod)."""
    if hasattr(config, "p2p_tls_fail_closed"):
        return bool(getattr(config, "p2p_tls_fail_closed"))
    return bool(getattr(config, "is_production", False)) or bool(
        getattr(config, "p2p_tls_require_client_cert", False)
    )


def _resolve_path(config, attr: str) -> str:
    raw = getattr(config, attr, "") or ""
    return os.path.expanduser(str(raw).strip())


def validate_p2p_tls_config(config) -> Tuple[list[str], list[str]]:
    """Return (errors, warnings) for TLS material when enabled."""
    errors: list[str] = []
    warnings: list[str] = []
    if not p2p_tls_enabled(config):
        return errors, warnings
    cert = _resolve_path(config, "p2p_tls_cert_path")
    key = _resolve_path(config, "p2p_tls_key_path")
    ca = _resolve_path(config, "p2p_tls_ca_path")
    if not cert or not os.path.isfile(cert):
        errors.append(f"p2p_tls_cert_path missing: {cert or '(unset)'}")
    if not key or not os.path.isfile(key):
        errors.append(f"p2p_tls_key_path missing: {key or '(unset)'}")
    # Fail-closed: CA required whenever TLS is enabled (client must verify peers).
    if not ca or not os.path.isfile(ca):
        errors.append(f"p2p_tls_ca_path required when TLS enabled: {ca or '(unset)'}")
    if bool(getattr(config, "p2p_tls_require_client_cert", False)) and (
        not ca or not os.path.isfile(ca)
    ):
        errors.append(f"p2p_tls_ca_path required for mTLS: {ca or '(unset)'}")
    return errors, warnings


def build_p2p_server_ssl_context(config) -> Optional[ssl.SSLContext]:
    if not p2p_tls_enabled(config):
        return None
    errors, _warnings = validate_p2p_tls_config(config)
    if errors:
        raise RuntimeError("P2P TLS server config invalid: " + "; ".join(errors))
    cert = _resolve_path(config, "p2p_tls_cert_path")
    key = _resolve_path(config, "p2p_tls_key_path")
    ca = _resolve_path(config, "p2p_tls_ca_path")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    # Industrial default: always mTLS-style peer cert verify when TLS is on.
    # CERT_NONE is never used (fail-closed).
    ctx.load_verify_locations(cafile=ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def build_p2p_client_ssl_context(config) -> Optional[ssl.SSLContext]:
    if not p2p_tls_enabled(config):
        return None
    errors, _warnings = validate_p2p_tls_config(config)
    if errors:
        raise RuntimeError("P2P TLS client config invalid: " + "; ".join(errors))
    cert = _resolve_path(config, "p2p_tls_cert_path")
    key = _resolve_path(config, "p2p_tls_key_path")
    ca = _resolve_path(config, "p2p_tls_ca_path")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if cert and key and os.path.isfile(cert) and os.path.isfile(key):
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    # Always CERT_REQUIRED when TLS is enabled (no CERT_NONE client path).
    ctx.load_verify_locations(cafile=ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    # CA still CERT_REQUIRED. Hostname check off because peers dial by IP;
    # identity is bound via CN/SAN ↔ node_id (not verify=False / CERT_NONE).
    ctx.check_hostname = False
    return ctx


def peer_cert_identities(ssl_obj: Optional[ssl.SSLObject]) -> Set[str]:
    """CN + SAN DNS/URI names from peer certificate (empty if none)."""
    out: Set[str] = set()
    if ssl_obj is None:
        return out
    try:
        cert = ssl_obj.getpeercert()
    except Exception:
        return out
    if not cert:
        return out
    for rdn in cert.get("subject", ()):
        for key, value in rdn:
            if str(key).lower() == "commonname" and value:
                out.add(str(value).strip())
    for typ, value in cert.get("subjectAltName", ()):
        if typ in ("DNS", "URI") and value:
            # URI may be like spiffe://... or dns-style; take last path segment if needed
            v = str(value).strip()
            out.add(v)
            if "/" in v:
                out.add(v.rstrip("/").rsplit("/", 1)[-1])
    return {x for x in out if x}


def peer_cert_fingerprint_sha256(ssl_obj: Optional[ssl.SSLObject]) -> str:
    """SHA-256 hex of DER peer cert, or empty string."""
    if ssl_obj is None:
        return ""
    try:
        der = ssl_obj.getpeercert(binary_form=True)
    except Exception:
        return ""
    if not der:
        return ""
    return native.sha256_hex(der)


def handshake_node_id_matches_cert(node_id: str, identities: Set[str]) -> bool:
    claimed = str(node_id or "").strip()
    if not claimed or not identities:
        return False
    if claimed in identities:
        return True
    # Allow CN with optional prefix match only for exact equality (strict).
    return False


def fingerprint_allowlist(config) -> Set[str]:
    raw = getattr(config, "p2p_tls_peer_fingerprints", None)
    if raw is None:
        env = os.environ.get("P2P_TLS_PEER_FINGERPRINTS", "").strip()
        if not env:
            return set()
        raw = env
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.replace(";", ",").split(",") if p.strip()]
        return set(parts)
    if isinstance(raw, (list, tuple, set)):
        return {str(p).strip().lower() for p in raw if str(p).strip()}
    return set()


def _normalize_bootstrap_addr(addr: str) -> str:
    s = str(addr or "").strip()
    if not s or ":" not in s:
        return ""
    host, port_s = s.rsplit(":", 1)
    host = host.strip().strip("[]").lower()
    try:
        port = int(port_s)
    except (TypeError, ValueError):
        return ""
    if not host or port <= 0:
        return ""
    return f"{host}:{port}"


def bootstrap_pin_map(config) -> dict:
    """Parse per-seed TLS pins: host:port=sha256hex[@node_id] (csv / ;).

    v1.3.133: addr→identity binding for bootstrap seeds only.
    Empty map ⇒ pins disabled (host/port coverage unchanged).
    """
    raw = getattr(config, "p2p_bootstrap_pins", None)
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        env = os.environ.get("P2P_BOOTSTRAP_PINS", "").strip()
        raw = env
    out: dict = {}
    if isinstance(raw, dict):
        items = list(raw.items())
        for k, v in items:
            addr = _normalize_bootstrap_addr(str(k))
            if not addr:
                continue
            if isinstance(v, dict):
                fp = str(v.get("fingerprint") or v.get("fp") or "").strip().lower()
                nid = str(v.get("node_id") or v.get("id") or "").strip()
            else:
                fp = str(v or "").strip().lower()
                nid = ""
            if fp:
                entry = {"fingerprint": fp}
                if nid:
                    entry["node_id"] = nid
                out[addr] = entry
        return out
    text = str(raw or "").strip()
    if not text:
        return out
    for part in text.replace(";", ",").split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        addr_s, rest = item.split("=", 1)
        addr = _normalize_bootstrap_addr(addr_s)
        if not addr:
            continue
        rest = rest.strip()
        node_id = ""
        if "@" in rest:
            fp_s, node_id = rest.rsplit("@", 1)
            fp_s = fp_s.strip()
            node_id = node_id.strip()
        else:
            fp_s = rest
        fp = fp_s.strip().lower().replace(":", "")
        if not fp:
            continue
        entry = {"fingerprint": fp}
        if node_id:
            entry["node_id"] = node_id
        out[addr] = entry
    return out


def p2p_tls_status(config) -> dict:
    enabled = p2p_tls_enabled(config)
    errors, warnings = validate_p2p_tls_config(config) if enabled else ([], [])
    allow = fingerprint_allowlist(config)
    require_mtls = bool(getattr(config, "p2p_tls_require_client_cert", False))
    fail_closed = p2p_tls_fail_closed(config)
    bind_id = bool(getattr(config, "p2p_tls_bind_identity", True))
    return {
        "enabled": enabled,
        "require_client_cert": require_mtls,
        "fail_closed": fail_closed,
        "cert_configured": bool(_resolve_path(config, "p2p_tls_cert_path")),
        "ca_configured": bool(_resolve_path(config, "p2p_tls_ca_path")),
        "identity_binding": "cn_san_match" if (enabled and bind_id) else "none",
        "fingerprint_allowlist": bool(allow),
        "fingerprint_allowlist_size": len(allow),
        "client_verify_mode": "CERT_REQUIRED" if enabled else "n/a",
        "server_verify_mode": "CERT_REQUIRED" if enabled else "n/a",
        "ready": enabled and not errors,
        "errors": errors[:5],
        "warnings": warnings[:5],
    }


def extract_peer_tls_meta(writer: Any) -> dict:
    """Best-effort TLS peer metadata from asyncio StreamWriter."""
    ssl_obj = None
    try:
        ssl_obj = writer.get_extra_info("ssl_object")
    except Exception:
        ssl_obj = None
    identities = peer_cert_identities(ssl_obj)
    fp = peer_cert_fingerprint_sha256(ssl_obj)
    return {
        "ssl": ssl_obj is not None,
        "identities": sorted(identities),
        "fingerprint_sha256": fp,
    }
