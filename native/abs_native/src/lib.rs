// PyO3 false positives / intentional host-kernel surface under clippy -D warnings.
#![allow(clippy::useless_conversion)]
#![allow(clippy::too_many_arguments)]
#![allow(clippy::type_complexity)]

mod account_row;
mod account_view;
mod amount;
mod block_row;
mod consensus_ffg;
mod consensus_ghost;
mod consensus_select;
mod eth_tx;
mod evm_pure_runner;
mod evm_writeback;
mod fuzz_api;
mod hotpath;
mod libp2p_swarm;
mod p2p_frame;
mod p2p_ingress;
mod p2p_rate_limit;
mod p2p_transport;
mod p2p_wire;

pub use fuzz_api::{
    fuzz_p2p_frame_feed, fuzz_p2p_governor_sequence, fuzz_p2p_rate_limit_sequence,
    fuzz_p2p_wire_parse, fuzz_p2p_wire_parse_allowlist, fuzz_p2p_wire_roundtrip,
};
mod receipt_row;
mod rlp;
mod rocks_keycodec;
mod state_trie;
mod storage;
mod tx_row;

use k256::ecdsa::signature::hazmat::PrehashVerifier;
use k256::ecdsa::{RecoveryId, Signature, VerifyingKey};
use primitive_types::{U256, U512};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyList};
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use tiny_keccak::{Hasher, Keccak};

pub(crate) const MAX_IMPORTED_BLOCKS: usize = 20_000;
pub(crate) const MAX_PEER_HEADERS: usize = 20_000;
pub(crate) const MAX_BLOCK_JSON_BYTES: usize = 2 * 1024 * 1024;
pub(crate) const MAX_ACCOUNTS_JSON_BYTES: usize = 64 * 1024 * 1024;
pub(crate) const MAX_STATE_ROOT_ACCOUNTS: usize = 1_000_000;
pub(crate) const MAX_STATE_ROOT_BLOBS: usize = 1_000_000;
pub(crate) const MAX_ACCOUNT_BLOB_BYTES: usize = 2 * 1024 * 1024;
pub(crate) const MAX_CONSENSUS_VALIDATORS: usize = 10_000;

fn sha256_hex_bytes(data: &[u8]) -> String {
    hex::encode(Sha256::digest(data))
}

pub(crate) fn hash_string(data: &str) -> String {
    sha256_hex_bytes(data.as_bytes())
}

fn block_header_hash_payload(
    number: i64,
    parent_hash: &str,
    proposer: &str,
    state_root: &str,
    tx_root: &str,
    timestamp: i64,
    extra_data: &str,
) -> String {
    format!("{number}{parent_hash}{proposer}{state_root}{tx_root}{timestamp}{extra_data}")
}

fn block_header_hash_inner(
    number: i64,
    parent_hash: &str,
    proposer: &str,
    state_root: &str,
    tx_root: &str,
    timestamp: i64,
    extra_data: &str,
) -> String {
    hash_string(&block_header_hash_payload(
        number,
        parent_hash,
        proposer,
        state_root,
        tx_root,
        timestamp,
        extra_data,
    ))
}

fn merkle_root_strings(items: &[String]) -> String {
    if items.is_empty() {
        return hash_string("empty");
    }

    let mut layer: Vec<String> = items.iter().map(|item| hash_string(item)).collect();

    while layer.len() > 1 {
        if layer.len() % 2 == 1 {
            let last = layer[layer.len() - 1].clone();
            layer.push(last);
        }

        let mut next = Vec::with_capacity(layer.len() / 2);
        let mut i = 0;
        while i < layer.len() {
            let combined = format!("{}{}", layer[i], layer[i + 1]);
            next.push(hash_string(&combined));
            i += 2;
        }
        layer = next;
    }

    layer[0].clone()
}

fn merkle_proof_strings(items: &[String], target_index: usize) -> Vec<String> {
    if items.is_empty() || target_index >= items.len() {
        return Vec::new();
    }

    let mut layer: Vec<String> = items.iter().map(|item| hash_string(item)).collect();
    let mut proof = Vec::new();
    let mut index = target_index;

    while layer.len() > 1 {
        if layer.len() % 2 == 1 {
            let last = layer[layer.len() - 1].clone();
            layer.push(last);
        }

        let sibling_index = if index.is_multiple_of(2) {
            index + 1
        } else {
            index - 1
        };
        if sibling_index < layer.len() {
            proof.push(layer[sibling_index].clone());
        }

        let mut next = Vec::with_capacity(layer.len() / 2);
        let mut i = 0;
        while i < layer.len() {
            let combined = format!("{}{}", layer[i], layer[i + 1]);
            next.push(hash_string(&combined));
            i += 2;
        }

        layer = next;
        index /= 2;
    }

    proof
}

fn merkle_root_from_proof_string(item: &str, proof: &[String], target_index: usize) -> String {
    let mut current_hash = hash_string(item);
    let mut index = target_index;

    for sibling_hash in proof {
        let combined = if index.is_multiple_of(2) {
            format!("{current_hash}{sibling_hash}")
        } else {
            format!("{sibling_hash}{current_hash}")
        };
        current_hash = hash_string(&combined);
        index /= 2;
    }

    current_hash
}

pub(crate) fn value_to_string(value: Option<&Value>, default_value: &str) -> String {
    match value {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => default_value.to_string(),
        Some(v) => v.to_string(),
    }
}

fn value_to_i64(value: Option<&Value>) -> i64 {
    match value {
        Some(Value::Number(n)) => n
            .as_i64()
            .or_else(|| n.as_u64().map(|v| v as i64))
            .unwrap_or(0),
        Some(Value::String(s)) => s.parse::<i64>().unwrap_or(0),
        _ => 0,
    }
}

fn value_to_f64(value: Option<&Value>) -> f64 {
    match value {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0),
        Some(Value::String(s)) => s.parse::<f64>().unwrap_or(0.0),
        _ => 0.0,
    }
}

pub(crate) fn account_payload_row(account: &Value) -> PyResult<Value> {
    // Wave C tip+apply: tip leaves commit integer satoshi (b_satoshi), never float "b".
    // 1 ABS = 1_000_000 satoshi (matches runtime.amount.SATOSHI_MULTIPLIER).
    const SATOSHI_MULTIPLIER: f64 = 1_000_000.0;
    let obj = account.as_object().ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err("account row must be a JSON object")
    })?;

    let address = value_to_string(obj.get("address"), "");
    let balance_satoshi = if obj.contains_key("balance_satoshi")
        && !obj
            .get("balance_satoshi")
            .map(|v| v.is_null())
            .unwrap_or(true)
    {
        value_to_i64(obj.get("balance_satoshi")).max(0)
    } else {
        let bal = value_to_f64(obj.get("balance"));
        if !bal.is_finite() || bal < 0.0 {
            0
        } else {
            (bal * SATOSHI_MULTIPLIER).floor() as i64
        }
    };
    let nonce = value_to_i64(obj.get("nonce"));
    let code = value_to_string(obj.get("code"), "");
    let storage = value_to_string(obj.get("storage"), "{}");
    let storage = if storage.is_empty() {
        "{}".to_string()
    } else {
        storage
    };

    let code_hash = if code.is_empty() {
        String::new()
    } else {
        hash_string(&code)
    };
    let storage_hash = if storage.is_empty() {
        String::new()
    } else {
        hash_string(&storage)
    };

    let mut row = Map::new();
    row.insert("a".to_string(), Value::String(address));
    row.insert(
        "b_satoshi".to_string(),
        Value::Number(Number::from(balance_satoshi)),
    );
    row.insert("c".to_string(), Value::String(code_hash));
    row.insert("n".to_string(), Value::Number(Number::from(nonce)));
    row.insert("s".to_string(), Value::String(storage_hash));
    Ok(Value::Object(row))
}

fn format_py_float_component(value: f64) -> String {
    if !value.is_finite() {
        return value.to_string();
    }
    let mut rendered = format!("{value}");
    if value.fract() == 0.0
        && !rendered.contains('.')
        && !rendered.contains('e')
        && !rendered.contains('E')
    {
        rendered.push_str(".0");
    }
    rendered
}

fn transaction_hash_inner(
    from_addr: &str,
    to_addr: &str,
    value: f64,
    nonce: i64,
    gas: i64,
    data: &str,
    timestamp: i64,
) -> String {
    let raw = format!(
        "{from_addr}{to_addr}{}{nonce}{gas}{data}{timestamp}",
        format_py_float_component(value)
    );
    hash_string(&raw)
}

fn canonicalize_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut sorted = Map::new();
            let mut keys: Vec<String> = map.keys().cloned().collect();
            keys.sort();
            for key in keys {
                if let Some(item) = map.get(&key) {
                    sorted.insert(key, canonicalize_value(item));
                }
            }
            Value::Object(sorted)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonicalize_value).collect()),
        Value::Number(number) => {
            if number.is_f64() {
                let float_value = number.as_f64().unwrap_or(0.0);
                Value::Number(Number::from((float_value * 1_000_000.0) as i64))
            } else {
                value.clone()
            }
        }
        _ => value.clone(),
    }
}

fn canonical_serialize_json(value: &Value) -> PyResult<String> {
    let canonical = canonicalize_value(value);
    serde_json::to_string(&canonical)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

fn sort_block_transactions(block: &mut Value) {
    let Some(transactions) = block
        .as_object_mut()
        .and_then(|obj| obj.get_mut("transactions"))
        .and_then(|value| value.as_array_mut())
    else {
        return;
    };

    transactions.sort_by(|left, right| {
        let left_hash = left
            .as_object()
            .and_then(|obj| obj.get("hash"))
            .and_then(|value| value.as_str())
            .unwrap_or("");
        let right_hash = right
            .as_object()
            .and_then(|obj| obj.get("hash"))
            .and_then(|value| value.as_str())
            .unwrap_or("");
        left_hash.cmp(right_hash)
    });
}

fn block_canonical_hash_inner(block_json: &str) -> PyResult<String> {
    let mut block: Value = serde_json::from_str(block_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    sort_block_transactions(&mut block);
    let canonical = canonical_serialize_json(&block)?;
    Ok(hash_string(&canonical))
}

fn keccak256_hex_bytes(data: &[u8]) -> String {
    let mut hasher = Keccak::v256();
    hasher.update(data);
    let mut out = [0u8; 32];
    hasher.finalize(&mut out);
    hex::encode(out)
}

pub(crate) fn keccak256_digest_bytes(data: &[u8]) -> [u8; 32] {
    let mut hasher = Keccak::v256();
    hasher.update(data);
    let mut out = [0u8; 32];
    hasher.finalize(&mut out);
    out
}

pub(crate) fn recover_eth_address_keccak_inner(
    prehash: &[u8; 32],
    r: &[u8],
    s: &[u8],
    rec_id: u8,
) -> Result<String, String> {
    if r.len() != 32 || s.len() != 32 {
        return Err("bad_signature_length".into());
    }
    let mut sig_bytes = [0u8; 64];
    sig_bytes[..32].copy_from_slice(r);
    sig_bytes[32..].copy_from_slice(s);
    let mut signature = Signature::from_slice(&sig_bytes).map_err(|e| e.to_string())?;
    signature = signature.normalize_s().unwrap_or(signature);
    let rid = RecoveryId::from_byte(rec_id).ok_or_else(|| "bad_recovery_id".to_string())?;
    let vk =
        VerifyingKey::recover_from_prehash(prehash, &signature, rid).map_err(|e| e.to_string())?;
    let point = vk.to_encoded_point(false);
    let pub_bytes = &point.as_bytes()[1..];
    let hash = keccak256_digest_bytes(pub_bytes);
    Ok(format!("0x{}", hex::encode(&hash[12..])))
}

#[pyfunction]
fn recover_eth_address_keccak(
    prehash: &[u8],
    r: Vec<u8>,
    s: Vec<u8>,
    rec_id: u8,
) -> PyResult<String> {
    if prehash.len() != 32 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "prehash_must_be_32_bytes",
        ));
    }
    let mut hash = [0u8; 32];
    hash.copy_from_slice(prehash);
    recover_eth_address_keccak_inner(&hash, &r, &s, rec_id)
        .map_err(pyo3::exceptions::PyValueError::new_err)
}

#[pyfunction]
fn pubkey_to_eth_address(public_key: &[u8]) -> PyResult<String> {
    let pk: &[u8] = match public_key.len() {
        64 => public_key,
        65 if public_key.first() == Some(&0x04) => &public_key[1..],
        n => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "public_key must be 64 bytes uncompressed or 65 with 0x04 prefix, got {n}"
            )))
        }
    };
    let hash = keccak256_digest_bytes(pk);
    Ok(format!("0x{}", hex::encode(&hash[12..])))
}

pub(crate) fn u256_from_be32(bytes: [u8; 32]) -> U256 {
    U256::from_big_endian(&bytes)
}

pub(crate) fn u256_to_be32(value: U256) -> [u8; 32] {
    let mut out = [0u8; 32];
    value.to_big_endian(&mut out);
    out
}

pub(crate) fn evm_keccak256_memory_inner(memory: &[u8], offset: usize, size: usize) -> [u8; 32] {
    if size == 0 {
        return keccak256_digest_bytes(&[]);
    }
    let mut data = vec![0u8; size];
    if offset < memory.len() {
        let copied = usize::min(size, memory.len() - offset);
        data[..copied].copy_from_slice(&memory[offset..offset + copied]);
    }
    keccak256_digest_bytes(&data)
}

fn extract_canonical_transaction(tx: &Value) -> PyResult<Value> {
    let obj = tx.as_object().ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err("transaction row must be a JSON object")
    })?;

    let hash = value_to_string(obj.get("hash").or(obj.get("tx_hash")), "");
    let from_addr = value_to_string(obj.get("from").or(obj.get("from_addr")), "");
    let to_addr = value_to_string(obj.get("to").or(obj.get("to_addr")), "");
    let amount = value_to_f64(obj.get("amount").or(obj.get("value")));
    let fee = value_to_f64(obj.get("fee"));
    let nonce = value_to_i64(obj.get("nonce"));
    let timestamp = value_to_i64(obj.get("timestamp"));

    let mut row = Map::new();
    row.insert(
        "amount".to_string(),
        Value::Number(Number::from_f64(amount).unwrap_or(Number::from(0))),
    );
    row.insert(
        "fee".to_string(),
        Value::Number(Number::from_f64(fee).unwrap_or(Number::from(0))),
    );
    row.insert("from".to_string(), Value::String(from_addr));
    row.insert("hash".to_string(), Value::String(hash));
    row.insert("nonce".to_string(), Value::Number(Number::from(nonce)));
    row.insert(
        "timestamp".to_string(),
        Value::Number(Number::from(timestamp)),
    );
    row.insert("to".to_string(), Value::String(to_addr));
    Ok(Value::Object(row))
}

fn extract_canonical_block(block: &Value) -> PyResult<Value> {
    let obj = block
        .as_object()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("block must be a JSON object"))?;

    let height = value_to_i64(obj.get("height").or(obj.get("number")));
    let parent_hash = value_to_string(obj.get("parent_hash").or(obj.get("parent")), "");
    let miner = value_to_string(obj.get("miner").or(obj.get("proposer")), "");
    let timestamp = value_to_i64(obj.get("timestamp"));
    let extra_data = value_to_string(obj.get("extra_data"), "");
    let state_root = value_to_string(obj.get("state_root"), "");

    let mut tx_rows = Vec::new();
    if let Some(transactions) = obj.get("transactions").and_then(|value| value.as_array()) {
        for tx in transactions {
            tx_rows.push(extract_canonical_transaction(tx)?);
        }
    }
    tx_rows.sort_by(|left, right| {
        let left_hash = left
            .as_object()
            .and_then(|row| row.get("hash"))
            .and_then(|value| value.as_str())
            .unwrap_or("");
        let right_hash = right
            .as_object()
            .and_then(|row| row.get("hash"))
            .and_then(|value| value.as_str())
            .unwrap_or("");
        left_hash.cmp(right_hash)
    });

    let mut canonical = Map::new();
    canonical.insert("extra_data".to_string(), Value::String(extra_data));
    canonical.insert("height".to_string(), Value::Number(Number::from(height)));
    canonical.insert("miner".to_string(), Value::String(miner));
    canonical.insert("parent_hash".to_string(), Value::String(parent_hash));
    canonical.insert("state_root".to_string(), Value::String(state_root));
    canonical.insert(
        "timestamp".to_string(),
        Value::Number(Number::from(timestamp)),
    );
    canonical.insert("transactions".to_string(), Value::Array(tx_rows));
    Ok(Value::Object(canonical))
}

/// Parity with import_block / Block._compute_hash (strip wire extras, then hash).
pub(crate) fn recomputed_canonical_block_hash(block: &Value) -> Result<String, String> {
    let canonical = extract_canonical_block(block).map_err(|e| e.to_string())?;
    let encoded = canonical_serialize_json(&canonical).map_err(|e| e.to_string())?;
    Ok(hash_string(&encoded))
}

fn validate_imported_block_chain_inner(
    blocks_json: &[String],
    expected_parent_hash: &str,
    start_height: i64,
) -> PyResult<bool> {
    if blocks_json.len() > MAX_IMPORTED_BLOCKS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_blocks: {} > {}",
            blocks_json.len(),
            MAX_IMPORTED_BLOCKS
        )));
    }
    let mut previous_hash = expected_parent_hash.to_string();
    let mut previous_height = start_height;

    for block_json in blocks_json {
        if block_json.len() > MAX_BLOCK_JSON_BYTES {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "block_json_too_large: {} > {} bytes",
                block_json.len(),
                MAX_BLOCK_JSON_BYTES
            )));
        }
        let block: Value = serde_json::from_str(block_json)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let obj = block.as_object().ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err("block must be a JSON object")
        })?;

        let height = value_to_i64(obj.get("height").or(obj.get("number")));
        let block_hash = value_to_string(obj.get("hash").or(obj.get("block_hash")), "");
        let parent_hash = value_to_string(obj.get("parent_hash").or(obj.get("parent")), "");

        if block_hash.is_empty() || height != previous_height + 1 {
            return Ok(false);
        }
        if !previous_hash.is_empty() && parent_hash != previous_hash {
            return Ok(false);
        }

        let canonical_block = extract_canonical_block(&block)?;
        let recomputed = hash_string(&canonical_serialize_json(&canonical_block)?);
        if recomputed != block_hash {
            return Ok(false);
        }

        previous_hash = block_hash;
        previous_height = height;
    }

    Ok(true)
}

fn validate_peer_header_chain_inner(
    headers: &[(i64, String, String, String, String, String, i64, String)],
    expected_parent_hash: &str,
    start_height: i64,
) -> bool {
    let mut previous_hash = expected_parent_hash.to_string();
    let mut previous_height = start_height;

    for (number, hash, parent_hash, proposer, state_root, tx_root, timestamp, extra_data) in headers
    {
        if hash.is_empty() || *number != previous_height + 1 {
            return false;
        }
        if !previous_hash.is_empty() && parent_hash != &previous_hash {
            return false;
        }
        let recomputed = block_header_hash_inner(
            *number,
            parent_hash,
            proposer,
            state_root,
            tx_root,
            *timestamp,
            extra_data,
        );
        if recomputed != *hash {
            return false;
        }
        previous_hash = hash.clone();
        previous_height = *number;
    }

    true
}

pub(crate) fn verify_secp256k1_sha256_inner(
    message: &[u8],
    signature_der: &[u8],
    public_key_xy: &[u8],
) -> bool {
    if public_key_xy.len() != 64 {
        return false;
    }

    let signature = match Signature::from_der(signature_der) {
        Ok(sig) => sig,
        Err(_) => return false,
    };
    let signature = signature.normalize_s().unwrap_or(signature);

    let mut sec1_public_key = Vec::with_capacity(65);
    sec1_public_key.push(0x04);
    sec1_public_key.extend_from_slice(public_key_xy);

    let verifying_key = match VerifyingKey::from_sec1_bytes(&sec1_public_key) {
        Ok(key) => key,
        Err(_) => return false,
    };

    let digest = Sha256::digest(message);
    verifying_key.verify_prehash(&digest, &signature).is_ok()
}

pub(crate) fn evm_deploy_address_create_inner(
    deployer: &str,
    block_number: u64,
    init_code_len: usize,
) -> String {
    let seed = format!("{deployer}{block_number}{init_code_len}");
    format!("0x{}", &hash_string(&seed)[..40])
}

pub(crate) fn evm_deploy_address_create2_legacy_inner(
    deployer: &str,
    salt: &str,
    init_code: &[u8],
) -> String {
    let seed = format!("create2:{deployer}:{salt}:{}", hex::encode(init_code));
    format!("0x{}", &hash_string(&seed)[..40])
}

pub(crate) fn parse_address_20(deployer: &str) -> PyResult<[u8; 20]> {
    let raw = deployer
        .trim()
        .trim_start_matches("0x")
        .trim_start_matches("0X");
    if raw.len() != 40 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "deployer must be a 20-byte hex address",
        ));
    }
    let bytes =
        hex::decode(raw).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let mut out = [0u8; 20];
    out.copy_from_slice(&bytes);
    Ok(out)
}

fn parse_bytes32(value: &[u8]) -> PyResult<[u8; 32]> {
    if value.len() != 32 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "salt must be exactly 32 bytes",
        ));
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(value);
    Ok(out)
}

pub(crate) fn evm_create2_address_eip1014_inner(
    deployer: &[u8; 20],
    salt: &[u8; 32],
    init_code_hash: &[u8; 32],
) -> [u8; 20] {
    let mut buf = [0u8; 85];
    buf[0] = 0xff;
    buf[1..21].copy_from_slice(deployer);
    buf[21..53].copy_from_slice(salt);
    buf[53..85].copy_from_slice(init_code_hash);
    let hash = keccak256_digest_bytes(&buf);
    let mut out = [0u8; 20];
    out.copy_from_slice(&hash[12..32]);
    out
}

#[pyfunction]
fn evm_deploy_address_create(
    deployer: String,
    block_number: u64,
    init_code_len: usize,
) -> PyResult<String> {
    Ok(evm_deploy_address_create_inner(
        &deployer,
        block_number,
        init_code_len,
    ))
}

#[pyfunction]
fn evm_deploy_address_create2_legacy(
    deployer: String,
    salt: String,
    init_code: Vec<u8>,
) -> PyResult<String> {
    Ok(evm_deploy_address_create2_legacy_inner(
        &deployer, &salt, &init_code,
    ))
}

#[pyfunction]
fn evm_create2_address_eip1014(
    deployer: String,
    salt: Vec<u8>,
    init_code: Vec<u8>,
) -> PyResult<Vec<u8>> {
    let deployer = parse_address_20(&deployer)?;
    let salt = parse_bytes32(&salt)?;
    let init_code_hash = keccak256_digest_bytes(&init_code);
    Ok(evm_create2_address_eip1014_inner(&deployer, &salt, &init_code_hash).to_vec())
}

#[pyfunction]
fn keccak256_digest(data: &[u8]) -> PyResult<[u8; 32]> {
    Ok(keccak256_digest_bytes(data))
}

#[pyfunction]
fn keccak256_digest_batch(items: Vec<Vec<u8>>) -> PyResult<Vec<[u8; 32]>> {
    Ok(items
        .iter()
        .map(|item| keccak256_digest_bytes(item))
        .collect())
}

#[pyfunction]
fn evm_keccak256_memory(memory: &[u8], offset: usize, size: usize) -> PyResult<[u8; 32]> {
    Ok(evm_keccak256_memory_inner(memory, offset, size))
}

#[pyfunction]
fn evm_u256_add(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(
        u256_from_be32(a).overflowing_add(u256_from_be32(b)).0,
    ))
}

#[pyfunction]
fn evm_u256_mul(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(
        u256_from_be32(a).overflowing_mul(u256_from_be32(b)).0,
    ))
}

#[pyfunction]
fn evm_u256_sub(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(
        u256_from_be32(a).overflowing_sub(u256_from_be32(b)).0,
    ))
}

#[pyfunction]
fn evm_u256_div(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    let denom = u256_from_be32(b);
    if denom.is_zero() {
        return Ok([0u8; 32]);
    }
    Ok(u256_to_be32(u256_from_be32(a) / denom))
}

#[pyfunction]
fn evm_u256_mod(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    let denom = u256_from_be32(b);
    if denom.is_zero() {
        return Ok([0u8; 32]);
    }
    Ok(u256_to_be32(u256_from_be32(a) % denom))
}

#[pyfunction]
fn evm_u256_and(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(u256_from_be32(a) & u256_from_be32(b)))
}

#[pyfunction]
fn evm_u256_or(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(u256_from_be32(a) | u256_from_be32(b)))
}

#[pyfunction]
fn evm_u256_xor(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(u256_from_be32(a) ^ u256_from_be32(b)))
}

#[pyfunction]
fn evm_u256_not(a: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(!u256_from_be32(a)))
}

#[pyfunction]
fn evm_u256_shl(a: [u8; 32], shift: u32) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(u256_from_be32(a) << shift))
}

#[pyfunction]
fn evm_u256_shr(a: [u8; 32], shift: u32) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(u256_from_be32(a) >> shift))
}

pub(crate) fn evm_u256_slt_inner(a: U256, b: U256) -> U256 {
    let a_neg = u256_is_negative(a);
    let b_neg = u256_is_negative(b);
    let truthy = if a_neg == b_neg { a < b } else { a_neg };
    if truthy {
        U256::one()
    } else {
        U256::zero()
    }
}

pub(crate) fn evm_u256_sar_inner(value: U256, shift: u32) -> U256 {
    if shift >= 256 {
        return if u256_is_negative(value) {
            U256::MAX
        } else {
            U256::zero()
        };
    }
    if u256_is_negative(value) {
        let fill = U256::MAX << (256 - shift);
        (value >> shift) | fill
    } else {
        value >> shift
    }
}

#[pyfunction]
fn evm_u256_slt(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_slt_inner(
        u256_from_be32(a),
        u256_from_be32(b),
    )))
}

#[pyfunction]
fn evm_u256_sgt(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_slt_inner(
        u256_from_be32(b),
        u256_from_be32(a),
    )))
}

#[pyfunction]
fn evm_u256_sar(a: [u8; 32], shift: u32) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_sar_inner(u256_from_be32(a), shift)))
}

fn u256_is_negative(v: U256) -> bool {
    v.bit(255)
}

fn u256_abs(v: U256) -> U256 {
    if u256_is_negative(v) {
        (!v).overflowing_add(U256::one()).0
    } else {
        v
    }
}

fn u256_negate(v: U256) -> U256 {
    (!v).overflowing_add(U256::one()).0
}

pub(crate) fn evm_u256_sdiv_inner(a: U256, b: U256) -> U256 {
    if b.is_zero() {
        return U256::zero();
    }
    let min_i256 = U256::one() << 255;
    if a == min_i256 && b == U256::MAX {
        return min_i256;
    }
    let a_neg = u256_is_negative(a);
    let b_neg = u256_is_negative(b);
    let mut quot = u256_abs(a) / u256_abs(b);
    if a_neg ^ b_neg {
        quot = u256_negate(quot);
    }
    quot
}

pub(crate) fn evm_u256_smod_inner(a: U256, b: U256) -> U256 {
    if b.is_zero() {
        return U256::zero();
    }
    let a_neg = u256_is_negative(a);
    let mut rem = u256_abs(a) % u256_abs(b);
    if a_neg {
        rem = u256_negate(rem);
    }
    rem
}

pub(crate) fn evm_u256_addmod_inner(a: U256, b: U256, modulo: U256) -> U256 {
    if modulo.is_zero() {
        return U256::zero();
    }
    let sum = U512::from(a) + U512::from(b);
    U256::try_from(sum % U512::from(modulo)).unwrap_or(U256::zero())
}

pub(crate) fn evm_u256_mulmod_inner(a: U256, b: U256, modulo: U256) -> U256 {
    if modulo.is_zero() {
        return U256::zero();
    }
    let prod = U512::from(a) * U512::from(b);
    U256::try_from(prod % U512::from(modulo)).unwrap_or(U256::zero())
}

pub(crate) fn evm_u256_exp_inner(base: U256, exp: U256) -> U256 {
    if exp.is_zero() {
        return if base.is_zero() {
            U256::zero()
        } else {
            U256::one()
        };
    }
    let mut result = U256::one();
    let mut b = base;
    let mut e = exp;
    loop {
        if e.bit(0) {
            result = result.overflowing_mul(b).0;
        }
        e >>= 1;
        if e.is_zero() {
            break;
        }
        b = b.overflowing_mul(b).0;
    }
    result
}

pub(crate) fn evm_u256_signextend_inner(k: u32, x: U256) -> U256 {
    if k >= 32 {
        return x;
    }
    let bit = 8 * k + 7;
    let lower_mask = (U256::one() << (bit + 1)) - U256::one();
    if x.bit(bit as usize) {
        x | !lower_mask
    } else {
        x & lower_mask
    }
}

#[pyfunction]
fn evm_u256_sdiv(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_sdiv_inner(
        u256_from_be32(a),
        u256_from_be32(b),
    )))
}

#[pyfunction]
fn evm_u256_smod(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_smod_inner(
        u256_from_be32(a),
        u256_from_be32(b),
    )))
}

#[pyfunction]
fn evm_u256_addmod(a: [u8; 32], b: [u8; 32], modulo: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_addmod_inner(
        u256_from_be32(a),
        u256_from_be32(b),
        u256_from_be32(modulo),
    )))
}

#[pyfunction]
fn evm_u256_mulmod(a: [u8; 32], b: [u8; 32], modulo: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_mulmod_inner(
        u256_from_be32(a),
        u256_from_be32(b),
        u256_from_be32(modulo),
    )))
}

#[pyfunction]
fn evm_u256_exp(base: [u8; 32], exp: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_exp_inner(
        u256_from_be32(base),
        u256_from_be32(exp),
    )))
}

#[pyfunction]
fn evm_u256_signextend(k: u32, x: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(u256_to_be32(evm_u256_signextend_inner(
        k,
        u256_from_be32(x),
    )))
}

fn evm_u256_bool_word(truthy: bool) -> [u8; 32] {
    if truthy {
        let mut out = [0u8; 32];
        out[31] = 1;
        out
    } else {
        [0u8; 32]
    }
}

#[pyfunction]
fn evm_u256_lt(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(evm_u256_bool_word(u256_from_be32(a) < u256_from_be32(b)))
}

#[pyfunction]
fn evm_u256_gt(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(evm_u256_bool_word(u256_from_be32(a) > u256_from_be32(b)))
}

#[pyfunction]
fn evm_u256_eq(a: [u8; 32], b: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(evm_u256_bool_word(u256_from_be32(a) == u256_from_be32(b)))
}

#[pyfunction]
fn evm_u256_iszero(a: [u8; 32]) -> PyResult<[u8; 32]> {
    Ok(evm_u256_bool_word(u256_from_be32(a).is_zero()))
}

#[pyfunction]
fn evm_u256_byte(index: u32, word: [u8; 32]) -> PyResult<[u8; 32]> {
    let value = u256_from_be32(word);
    if index >= 32 {
        return Ok([0u8; 32]);
    }
    let shift = 8 * (31 - index);
    let byte = if shift >= 256 {
        0
    } else {
        ((value >> shift).low_u32() & 0xff) as u64
    };
    Ok(u256_to_be32(U256::from(byte)))
}

pub(crate) fn evm_memory_read_word_inner(memory: &[u8], offset: usize) -> [u8; 32] {
    let mut out = [0u8; 32];
    if offset < memory.len() {
        let end = usize::min(offset + 32, memory.len());
        out[..end - offset].copy_from_slice(&memory[offset..end]);
    }
    out
}

#[pyfunction]
fn evm_memory_read_word(memory: &[u8], offset: usize) -> PyResult<[u8; 32]> {
    Ok(evm_memory_read_word_inner(memory, offset))
}

pub(crate) fn evm_calldataload_inner(calldata: &[u8], offset: usize) -> [u8; 32] {
    let mut out = [0u8; 32];
    if offset < calldata.len() {
        let end = usize::min(offset + 32, calldata.len());
        out[..end - offset].copy_from_slice(&calldata[offset..end]);
    }
    out
}

#[pyfunction]
fn evm_calldataload(calldata: &[u8], offset: usize) -> PyResult<[u8; 32]> {
    Ok(evm_calldataload_inner(calldata, offset))
}

#[pyfunction]
fn evm_memory_copy(
    py_memory: &Bound<'_, PyByteArray>,
    dest: usize,
    src: &[u8],
    src_offset: usize,
    size: usize,
) -> PyResult<()> {
    let memory = unsafe { py_memory.as_bytes_mut() };
    for i in 0..size {
        let byte = src.get(src_offset + i).copied().unwrap_or(0);
        let idx = dest + i;
        if idx < memory.len() {
            memory[idx] = byte;
        }
    }
    Ok(())
}

#[pyfunction]
fn evm_memory_write_word(
    py_memory: &Bound<'_, PyByteArray>,
    offset: usize,
    value: [u8; 32],
) -> PyResult<()> {
    let memory = unsafe { py_memory.as_bytes_mut() };
    for (i, byte) in value.iter().enumerate() {
        let idx = offset + i;
        if idx < memory.len() {
            memory[idx] = *byte;
        }
    }
    Ok(())
}

#[pyfunction]
fn evm_memory_write_byte(
    py_memory: &Bound<'_, PyByteArray>,
    offset: usize,
    value: u32,
) -> PyResult<()> {
    let memory = unsafe { py_memory.as_bytes_mut() };
    if offset < memory.len() {
        memory[offset] = (value & 0xff) as u8;
    }
    Ok(())
}

pub(crate) fn evm_read_push_inner(bytecode: &[u8], pc: usize, n: usize) -> [u8; 32] {
    let n = n.min(32);
    let mut out = [0u8; 32];
    if n == 0 {
        return out;
    }
    let start = pc.saturating_add(1);
    if start >= bytecode.len() {
        return out;
    }
    let available = usize::min(n, bytecode.len() - start);
    out[32 - n..32 - n + available].copy_from_slice(&bytecode[start..start + available]);
    out
}

#[pyfunction]
fn evm_read_push(bytecode: &[u8], pc: usize, n: usize) -> PyResult<[u8; 32]> {
    Ok(evm_read_push_inner(bytecode, pc, n))
}

pub(crate) fn evm_build_jumpdest_table_inner(bytecode: &[u8]) -> Vec<u8> {
    let mut table = vec![0u8; bytecode.len().div_ceil(8)];
    let mut pc = 0usize;
    while pc < bytecode.len() {
        let op = bytecode[pc];
        if op == 0x5B {
            table[pc / 8] |= 1u8 << (pc % 8);
        }
        if (0x60..=0x7F).contains(&op) {
            pc += 1 + (op - 0x5F) as usize;
        } else {
            pc += 1;
        }
    }
    table
}

pub(crate) fn evm_is_jumpdest_inner(table: &[u8], dest: usize, bytecode_len: usize) -> bool {
    if dest >= bytecode_len {
        return false;
    }
    (table[dest / 8] >> (dest % 8)) & 1 == 1
}

#[pyfunction]
fn evm_build_jumpdest_table(bytecode: &[u8]) -> PyResult<Vec<u8>> {
    Ok(evm_build_jumpdest_table_inner(bytecode))
}

#[pyfunction]
fn evm_is_jumpdest(table: &[u8], dest: usize, bytecode_len: usize) -> PyResult<bool> {
    Ok(evm_is_jumpdest_inner(table, dest, bytecode_len))
}

#[pyfunction]
fn evm_word_to_address(word: [u8; 32]) -> PyResult<String> {
    let value = u256_from_be32(word);
    let mask = (U256::one() << 160) - U256::one();
    Ok(format!("0x{:040x}", value & mask))
}

#[pyfunction]
fn evm_call_gas_cap(remaining: u64, requested: u64) -> PyResult<u64> {
    let cap = remaining.saturating_mul(63) / 64;
    if requested == 0 {
        Ok(cap)
    } else {
        Ok(cap.min(requested))
    }
}

/// Pure nested-CALL effects planner (policy only — Python still runs bytecode / DB).
/// kind: call | callcode | delegatecall | staticcall
#[pyfunction]
fn evm_plan_nested_call_effects(
    kind: String,
    parent_read_only: bool,
    caller: String,
    target: String,
    value_wei: i64,
    success: bool,
) -> PyResult<String> {
    let kind = kind.trim().to_ascii_lowercase();
    let kind = match kind.as_str() {
        "call" | "callcode" | "delegatecall" | "staticcall" => kind,
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "kind must be call|callcode|delegatecall|staticcall",
            ))
        }
    };
    let value_wei = value_wei.max(0);
    let nested_read_only = parent_read_only || kind == "staticcall";
    let mut persist_storage = false;
    let mut persist_value = false;
    let mut persist_logs = false;
    let mut storage_owner = "target";
    let mut exec_address = "target";
    let mut value_from = "";
    let mut value_to = "";
    let mut effective_value_wei: i64 = 0;
    let reject_create = nested_read_only;

    if kind == "delegatecall" || kind == "callcode" {
        storage_owner = "caller";
        exec_address = "caller";
    }

    if success && !nested_read_only {
        persist_storage = true;
        if kind == "delegatecall" || kind == "callcode" {
            persist_logs = true;
        }
        if (kind == "call" || kind == "callcode") && value_wei > 0 {
            persist_value = true;
            value_from = "caller";
            value_to = "target";
            effective_value_wei = value_wei;
        }
        // delegatecall / staticcall: no value transfer
    }

    let mut out = Map::new();
    out.insert("kind".into(), Value::String(kind));
    out.insert("caller".into(), Value::String(caller));
    out.insert("target".into(), Value::String(target));
    out.insert("nested_read_only".into(), Value::Bool(nested_read_only));
    out.insert("persist_storage".into(), Value::Bool(persist_storage));
    out.insert("persist_value".into(), Value::Bool(persist_value));
    out.insert("persist_logs".into(), Value::Bool(persist_logs));
    out.insert(
        "storage_owner".into(),
        Value::String(storage_owner.to_string()),
    );
    out.insert(
        "exec_address".into(),
        Value::String(exec_address.to_string()),
    );
    out.insert("value_from".into(), Value::String(value_from.to_string()));
    out.insert("value_to".into(), Value::String(value_to.to_string()));
    out.insert(
        "effective_value_wei".into(),
        Value::Number(effective_value_wei.into()),
    );
    out.insert("reject_create".into(), Value::Bool(reject_create));
    out.insert("success".into(), Value::Bool(success));
    out.insert("native_plan".into(), Value::Bool(true));
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Nested CALL gas planner: EIP-150 63/64 + 2300 stipend for value-bearing CALL/CALLCODE.
#[pyfunction]
fn evm_plan_nested_call_gas(
    remaining: u64,
    requested: u64,
    value_wei: i64,
    kind: String,
) -> PyResult<String> {
    let kind = kind.trim().to_ascii_lowercase();
    let kind = match kind.as_str() {
        "call" | "callcode" | "delegatecall" | "staticcall" => kind,
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "kind must be call|callcode|delegatecall|staticcall",
            ))
        }
    };
    let base_cap = if requested == 0 {
        remaining.saturating_mul(63) / 64
    } else {
        (remaining.saturating_mul(63) / 64).min(requested)
    };
    let stipend_applied = value_wei > 0 && (kind == "call" || kind == "callcode");
    let call_gas = if stipend_applied {
        remaining.min(base_cap.saturating_add(2300))
    } else {
        base_cap
    };
    let mut out = Map::new();
    out.insert("kind".into(), Value::String(kind));
    out.insert("remaining".into(), Value::Number(remaining.into()));
    out.insert("requested".into(), Value::Number(requested.into()));
    out.insert("base_cap".into(), Value::Number(base_cap.into()));
    out.insert("stipend_applied".into(), Value::Bool(stipend_applied));
    out.insert("call_gas".into(), Value::Number(call_gas.into()));
    out.insert("stipend".into(), Value::Number(2300u64.into()));
    out.insert("native_plan".into(), Value::Bool(true));
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

fn parse_stack_word(raw: &str) -> PyResult<U256> {
    let s = raw.trim();
    if s.is_empty() {
        return Ok(U256::zero());
    }
    if let Some(hex) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
        return U256::from_str_radix(hex, 16)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()));
    }
    U256::from_dec_str(s).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Decode CALL/CALLCODE/DELEGATECALL/STATICCALL stack frame (gas-on-top Absolute layout).
#[pyfunction]
#[pyo3(signature = (op, stack_words, memory=None))]
fn evm_decode_nested_call_frame(
    op: u8,
    stack_words: Vec<String>,
    memory: Option<Vec<u8>>,
) -> PyResult<String> {
    let (kind, consume, has_value) = match op {
        0xF1 => ("call", 7usize, true),
        0xF2 => ("callcode", 7, true),
        0xF4 => ("delegatecall", 6, false),
        0xFA => ("staticcall", 6, false),
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "op must be CALL/CALLCODE/DELEGATECALL/STATICCALL",
            ))
        }
    };
    if stack_words.len() < consume {
        return Err(pyo3::exceptions::PyValueError::new_err("stack underflow"));
    }
    let start = stack_words.len() - consume;
    let frame = &stack_words[start..];
    // Absolute layout: top (last) = gas, then to, [value], args_off, args_size, ret_off, ret_size
    let gas = parse_stack_word(&frame[consume - 1])?;
    let to_word = parse_stack_word(&frame[consume - 2])?;
    let (value, args_offset, args_size, ret_offset, ret_size) = if has_value {
        (
            parse_stack_word(&frame[consume - 3])?,
            parse_stack_word(&frame[consume - 4])?,
            parse_stack_word(&frame[consume - 5])?,
            parse_stack_word(&frame[consume - 6])?,
            parse_stack_word(&frame[consume - 7])?,
        )
    } else {
        (
            U256::zero(),
            parse_stack_word(&frame[consume - 3])?,
            parse_stack_word(&frame[consume - 4])?,
            parse_stack_word(&frame[consume - 5])?,
            parse_stack_word(&frame[consume - 6])?,
        )
    };
    let mask = (U256::one() << 160) - U256::one();
    let to_address = format!("0x{:040x}", to_word & mask);
    let mut out = Map::new();
    out.insert("op".into(), Value::Number(op.into()));
    out.insert("kind".into(), Value::String(kind.to_string()));
    out.insert("stack_consumed".into(), Value::Number(consume.into()));
    out.insert("gas".into(), Value::String(gas.to_string()));
    out.insert("to_word".into(), Value::String(to_word.to_string()));
    out.insert("to_address".into(), Value::String(to_address));
    out.insert("value".into(), Value::String(value.to_string()));
    out.insert("args_offset".into(), Value::String(args_offset.to_string()));
    out.insert("args_size".into(), Value::String(args_size.to_string()));
    out.insert("ret_offset".into(), Value::String(ret_offset.to_string()));
    out.insert("ret_size".into(), Value::String(ret_size.to_string()));
    out.insert("delegate".into(), Value::Bool(kind == "delegatecall"));
    out.insert("static".into(), Value::Bool(kind == "staticcall"));
    out.insert("callcode".into(), Value::Bool(kind == "callcode"));
    if let Some(mem) = memory {
        let off = args_offset.low_u64() as usize;
        let size = args_size.low_u64() as usize;
        let data = evm_memory_slice_inner(&mem, off, size);
        out.insert("call_data_hex".into(), Value::String(hex::encode(data)));
    }
    out.insert("native_plan".into(), Value::Bool(true));
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

pub(crate) fn evm_memory_slice_inner(memory: &[u8], offset: usize, size: usize) -> Vec<u8> {
    let mut out = vec![0u8; size];
    if offset < memory.len() {
        let copied = usize::min(size, memory.len() - offset);
        out[..copied].copy_from_slice(&memory[offset..offset + copied]);
    }
    out
}

#[pyfunction]
fn evm_memory_slice(memory: &[u8], offset: usize, size: usize) -> PyResult<Vec<u8>> {
    Ok(evm_memory_slice_inner(memory, offset, size))
}

#[pyfunction]
fn evm_stack_dup(stack: &Bound<'_, PyList>, depth: usize) -> PyResult<()> {
    let len = stack.len();
    if depth == 0 || depth > len {
        return Err(pyo3::exceptions::PyValueError::new_err("stack underflow"));
    }
    let item = stack.get_item(len - depth)?;
    stack.append(item)?;
    Ok(())
}

#[pyfunction]
fn evm_stack_swap(stack: &Bound<'_, PyList>, depth: usize) -> PyResult<()> {
    let len = stack.len();
    if depth == 0 || depth >= len {
        return Err(pyo3::exceptions::PyValueError::new_err("stack underflow"));
    }
    let top = len - 1;
    let other = len - 1 - depth;
    let top_item = stack.get_item(top)?;
    let other_item = stack.get_item(other)?;
    stack.set_item(top, other_item)?;
    stack.set_item(other, top_item)?;
    Ok(())
}

fn evm_opcode_supported(op: u8) -> bool {
    matches!(
        op,
        0x00 | 0x01
            | 0x02
            | 0x03
            | 0x04
            | 0x05
            | 0x06
            | 0x07
            | 0x08
            | 0x09
            | 0x0A
            | 0x0B
            | 0x10
            | 0x11
            | 0x12
            | 0x14
            | 0x15
            | 0x16
            | 0x17
            | 0x18
            | 0x19
            | 0x1A
            | 0x1B
            | 0x1C
            | 0x1D
            | 0x20
            | 0x30
            | 0x31
            | 0x32
            | 0x33
            | 0x34
            | 0x35
            | 0x36
            | 0x37
            | 0x38
            | 0x39
            | 0x3A
            | 0x3B
            | 0x3C
            | 0x3D
            | 0x3E
            | 0x3F
            | 0x40
            | 0x41
            | 0x42
            | 0x43
            | 0x44
            | 0x45
            | 0x46
            | 0x47
            | 0x48
            | 0x50
            | 0x51
            | 0x52
            | 0x53
            | 0x54
            | 0x55
            | 0x56
            | 0x57
            | 0x58
            | 0x59
            | 0x5A
            | 0x5B
            | 0x5F
            | 0xF0
            | 0xF1
            | 0xF2
            | 0xF3
            | 0xF4
            | 0xF5
            | 0xFA
            | 0xFD
            | 0xFE
            | 0xFF
    ) || (0x60..=0x7F).contains(&op)
        || (0x80..=0x8F).contains(&op)
        || (0x90..=0x9F).contains(&op)
        || (0xA0..=0xA4).contains(&op)
}

fn evm_scan_bytecode_inner(bytecode: &[u8]) -> Vec<(usize, u8)> {
    let mut issues = Vec::new();
    let mut pc = 0usize;
    while pc < bytecode.len() {
        let op = bytecode[pc];
        if !evm_opcode_supported(op) {
            issues.push((pc, op));
        }
        if (0x60..=0x7F).contains(&op) {
            pc += 1 + (op - 0x5F) as usize;
        } else {
            pc += 1;
        }
    }
    issues
}

#[pyfunction]
fn evm_scan_bytecode(bytecode: &[u8]) -> PyResult<Vec<(usize, u8)>> {
    Ok(evm_scan_bytecode_inner(bytecode))
}

#[pyfunction]
fn evm_gas_remaining(gas_limit: u64, gas_used: u64) -> PyResult<u64> {
    Ok(gas_limit.saturating_sub(gas_used))
}

#[pyfunction]
fn keccak256_hex(data: &[u8]) -> PyResult<String> {
    Ok(keccak256_hex_bytes(data))
}

#[pyfunction]
fn validate_imported_block_chain(
    blocks_json: Vec<String>,
    expected_parent_hash: String,
    start_height: i64,
) -> PyResult<bool> {
    validate_imported_block_chain_inner(&blocks_json, &expected_parent_hash, start_height)
}

#[pyfunction]
fn validate_peer_header_chain(
    headers: Vec<(i64, String, String, String, String, String, i64, String)>,
    expected_parent_hash: String,
    start_height: i64,
) -> PyResult<bool> {
    if headers.len() > MAX_PEER_HEADERS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_headers: {} > {}",
            headers.len(),
            MAX_PEER_HEADERS
        )));
    }
    Ok(validate_peer_header_chain_inner(
        &headers,
        &expected_parent_hash,
        start_height,
    ))
}

#[pyfunction]
fn transaction_hash(
    from_addr: String,
    to_addr: String,
    value: f64,
    nonce: i64,
    gas: i64,
    data: String,
    timestamp: i64,
) -> PyResult<String> {
    Ok(transaction_hash_inner(
        &from_addr, &to_addr, value, nonce, gas, &data, timestamp,
    ))
}

#[pyfunction]
fn transaction_hash_batch(
    transactions: Vec<(String, String, f64, i64, i64, String, i64)>,
) -> PyResult<Vec<String>> {
    Ok(transactions
        .iter()
        .map(|(from_addr, to_addr, value, nonce, gas, data, timestamp)| {
            transaction_hash_inner(from_addr, to_addr, *value, *nonce, *gas, data, *timestamp)
        })
        .collect())
}

#[pyfunction]
fn canonical_hash_json(obj_json: String) -> PyResult<String> {
    let value: Value = serde_json::from_str(&obj_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let canonical = canonical_serialize_json(&value)?;
    Ok(hash_string(&canonical))
}

#[pyfunction]
fn block_canonical_hash_json(block_json: String) -> PyResult<String> {
    block_canonical_hash_inner(&block_json)
}

#[pyfunction]
fn block_canonical_hash_batch(block_json_items: Vec<String>) -> PyResult<Vec<String>> {
    block_json_items
        .iter()
        .map(|item| block_canonical_hash_inner(item))
        .collect()
}

#[pyfunction]
fn hash_text(text: String) -> PyResult<String> {
    Ok(hash_string(&text))
}

#[pyfunction]
fn hash_text_batch(items: Vec<String>) -> PyResult<Vec<String>> {
    Ok(items.iter().map(|item| hash_string(item)).collect())
}

#[pyfunction]
fn block_header_hash(
    number: i64,
    parent_hash: String,
    proposer: String,
    state_root: String,
    tx_root: String,
    timestamp: i64,
    extra_data: String,
) -> PyResult<String> {
    Ok(block_header_hash_inner(
        number,
        &parent_hash,
        &proposer,
        &state_root,
        &tx_root,
        timestamp,
        &extra_data,
    ))
}

#[pyfunction]
fn block_header_hash_batch(
    headers: Vec<(i64, String, String, String, String, i64, String)>,
) -> PyResult<Vec<String>> {
    Ok(headers
        .iter()
        .map(
            |(number, parent_hash, proposer, state_root, tx_root, timestamp, extra_data)| {
                block_header_hash_inner(
                    *number,
                    parent_hash,
                    proposer,
                    state_root,
                    tx_root,
                    *timestamp,
                    extra_data,
                )
            },
        )
        .collect())
}

#[pyfunction]
fn sha256_hex(data: &[u8]) -> PyResult<String> {
    Ok(sha256_hex_bytes(data))
}

#[pyfunction]
fn sha256_hex_batch(items: Vec<Vec<u8>>) -> PyResult<Vec<String>> {
    Ok(items.iter().map(|item| sha256_hex_bytes(item)).collect())
}

#[pyfunction]
fn double_sha256_hex(data: &[u8]) -> PyResult<String> {
    let first = Sha256::digest(data);
    Ok(hex::encode(Sha256::digest(first)))
}

#[pyfunction]
fn merkle_root(items: Vec<String>) -> PyResult<String> {
    Ok(merkle_root_strings(&items))
}

#[pyfunction]
fn generate_proof(items: Vec<String>, target_index: usize) -> PyResult<Vec<String>> {
    Ok(merkle_proof_strings(&items, target_index))
}

#[pyfunction]
fn verify_proof(
    item: String,
    proof: Vec<String>,
    expected_root: String,
    target_index: usize,
) -> PyResult<bool> {
    Ok(merkle_root_from_proof_string(&item, &proof, target_index) == expected_root)
}

#[pyfunction]
fn merkle_root_from_proof(
    item: String,
    proof: Vec<String>,
    target_index: usize,
) -> PyResult<String> {
    Ok(merkle_root_from_proof_string(&item, &proof, target_index))
}

#[pyfunction]
fn state_root_from_accounts_json(accounts_json: String) -> PyResult<String> {
    if accounts_json.len() > MAX_ACCOUNTS_JSON_BYTES {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "accounts_json_too_large: {} > {} bytes",
            accounts_json.len(),
            MAX_ACCOUNTS_JSON_BYTES
        )));
    }
    let accounts: Value = serde_json::from_str(&accounts_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let accounts = accounts
        .as_array()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("accounts_json must be an array"))?;
    if accounts.len() > MAX_STATE_ROOT_ACCOUNTS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_accounts: {} > {}",
            accounts.len(),
            MAX_STATE_ROOT_ACCOUNTS
        )));
    }

    let mut payload = Vec::with_capacity(accounts.len());
    for account in accounts {
        payload.push(account_payload_row(account)?);
    }

    let encoded = serde_json::to_string(&payload)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    Ok(hash_string(&encoded))
}

#[pyfunction]
fn state_root_from_account_blobs(blobs: Vec<Vec<u8>>) -> PyResult<String> {
    if blobs.len() > MAX_STATE_ROOT_BLOBS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_account_blobs: {} > {}",
            blobs.len(),
            MAX_STATE_ROOT_BLOBS
        )));
    }
    for blob in &blobs {
        if blob.len() > MAX_ACCOUNT_BLOB_BYTES {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "account_blob_too_large: {} > {} bytes",
                blob.len(),
                MAX_ACCOUNT_BLOB_BYTES
            )));
        }
    }
    state_trie::compute_state_root_from_account_blobs(blobs)
}

#[pyfunction]
fn verify_secp256k1_sha256(
    message: &[u8],
    signature_der: &[u8],
    public_key_xy: &[u8],
) -> PyResult<bool> {
    Ok(verify_secp256k1_sha256_inner(
        message,
        signature_der,
        public_key_xy,
    ))
}

#[pyfunction]
fn verify_secp256k1_sha256_batch(items: Vec<(Vec<u8>, Vec<u8>, Vec<u8>)>) -> PyResult<Vec<bool>> {
    Ok(items
        .iter()
        .map(|(message, signature_der, public_key_xy)| {
            verify_secp256k1_sha256_inner(message, signature_der, public_key_xy)
        })
        .collect())
}

#[pyfunction]
fn validate_hash_chain(
    headers: Vec<(i64, String, String)>,
    expected_parent_hash: String,
    start_height: i64,
) -> PyResult<bool> {
    let mut previous_hash = expected_parent_hash;
    let mut previous_height = start_height;

    for (height, block_hash, parent_hash) in headers {
        if block_hash.is_empty() || height != previous_height + 1 {
            return Ok(false);
        }
        if !previous_hash.is_empty() && parent_hash != previous_hash {
            return Ok(false);
        }
        previous_hash = block_hash;
        previous_height = height;
    }

    Ok(true)
}

#[pymodule]
fn abs_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(evm_deploy_address_create, m)?)?;
    m.add_function(wrap_pyfunction!(evm_deploy_address_create2_legacy, m)?)?;
    m.add_function(wrap_pyfunction!(evm_create2_address_eip1014, m)?)?;
    m.add_function(wrap_pyfunction!(keccak256_digest, m)?)?;
    m.add_function(wrap_pyfunction!(keccak256_digest_batch, m)?)?;
    m.add_function(wrap_pyfunction!(evm_keccak256_memory, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_add, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_mul, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_sub, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_div, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_mod, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_sdiv, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_smod, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_addmod, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_mulmod, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_exp, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_signextend, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_and, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_or, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_xor, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_not, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_shl, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_shr, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_slt, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_sgt, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_sar, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_lt, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_gt, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_eq, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_iszero, m)?)?;
    m.add_function(wrap_pyfunction!(evm_u256_byte, m)?)?;
    m.add_function(wrap_pyfunction!(evm_memory_read_word, m)?)?;
    m.add_function(wrap_pyfunction!(evm_memory_write_word, m)?)?;
    m.add_function(wrap_pyfunction!(evm_memory_write_byte, m)?)?;
    m.add_function(wrap_pyfunction!(evm_calldataload, m)?)?;
    m.add_function(wrap_pyfunction!(evm_memory_copy, m)?)?;
    m.add_function(wrap_pyfunction!(evm_read_push, m)?)?;
    m.add_function(wrap_pyfunction!(evm_build_jumpdest_table, m)?)?;
    m.add_function(wrap_pyfunction!(evm_is_jumpdest, m)?)?;
    m.add_function(wrap_pyfunction!(evm_word_to_address, m)?)?;
    m.add_function(wrap_pyfunction!(evm_call_gas_cap, m)?)?;
    m.add_function(wrap_pyfunction!(evm_plan_nested_call_effects, m)?)?;
    m.add_function(wrap_pyfunction!(evm_plan_nested_call_gas, m)?)?;
    m.add_function(wrap_pyfunction!(evm_decode_nested_call_frame, m)?)?;
    m.add_function(wrap_pyfunction!(evm_memory_slice, m)?)?;
    m.add_function(wrap_pyfunction!(evm_stack_dup, m)?)?;
    m.add_function(wrap_pyfunction!(evm_stack_swap, m)?)?;
    m.add_function(wrap_pyfunction!(evm_scan_bytecode, m)?)?;
    m.add_function(wrap_pyfunction!(evm_gas_remaining, m)?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_opcode_is_bridge_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(evm_pure_runner::evm_opcode_is_host_py, m)?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_bytecode_is_nested_native_eligible_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_bytecode_is_inline_call_frame_eligible_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(evm_pure_runner::evm_run_until_halt_py, m)?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_run_pure_until_host_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_run_nested_pure_frame_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_run_nested_host_frame_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_host_snapshot_storage_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(
        evm_pure_runner::evm_host_restore_storage_py,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(keccak256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(recover_eth_address_keccak, m)?)?;
    m.add_function(wrap_pyfunction!(pubkey_to_eth_address, m)?)?;
    m.add_function(wrap_pyfunction!(rlp::rlp_encode, m)?)?;
    m.add_function(wrap_pyfunction!(rlp::rlp_decode, m)?)?;
    m.add_function(wrap_pyfunction!(rlp::rlp_decode_single, m)?)?;
    m.add_function(wrap_pyfunction!(validate_imported_block_chain, m)?)?;
    m.add_function(wrap_pyfunction!(validate_peer_header_chain, m)?)?;
    m.add_function(wrap_pyfunction!(transaction_hash, m)?)?;
    m.add_function(wrap_pyfunction!(transaction_hash_batch, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_hash_json, m)?)?;
    m.add_function(wrap_pyfunction!(block_canonical_hash_json, m)?)?;
    m.add_function(wrap_pyfunction!(block_canonical_hash_batch, m)?)?;
    m.add_function(wrap_pyfunction!(hash_text, m)?)?;
    m.add_function(wrap_pyfunction!(hash_text_batch, m)?)?;
    m.add_function(wrap_pyfunction!(block_header_hash, m)?)?;
    m.add_function(wrap_pyfunction!(block_header_hash_batch, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_hex_batch, m)?)?;
    m.add_function(wrap_pyfunction!(double_sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(merkle_root, m)?)?;
    m.add_function(wrap_pyfunction!(generate_proof, m)?)?;
    m.add_function(wrap_pyfunction!(verify_proof, m)?)?;
    m.add_function(wrap_pyfunction!(merkle_root_from_proof, m)?)?;
    m.add_function(wrap_pyfunction!(state_root_from_accounts_json, m)?)?;
    m.add_function(wrap_pyfunction!(state_root_from_account_blobs, m)?)?;
    m.add_function(wrap_pyfunction!(verify_secp256k1_sha256, m)?)?;
    m.add_function(wrap_pyfunction!(verify_secp256k1_sha256_batch, m)?)?;
    m.add_function(wrap_pyfunction!(validate_hash_chain, m)?)?;
    storage::register(m)?;
    account_row::register(m)?;
    tx_row::register(m)?;
    block_row::register(m)?;
    receipt_row::register(m)?;
    account_view::register(m)?;
    evm_writeback::register(m)?;
    state_trie::register(m)?;
    consensus_select::register(m)?;
    consensus_ghost::register(m)?;
    consensus_ffg::register(m)?;
    eth_tx::register(m)?;
    rocks_keycodec::register(m)?;
    p2p_frame::register(m)?;
    p2p_ingress::register(m)?;
    p2p_transport::register(m)?;
    p2p_rate_limit::register(m)?;
    p2p_wire::register(m)?;
    libp2p_swarm::register(m)?;
    hotpath::register(m)?;
    amount::register(m)?;
    Ok(())
}

/// Fail-closed evidence that `cargo test --no-default-features` actually linked CPython.
/// Skipped when `extension-module` is on (that feature deliberately does not link libpython).
#[cfg(all(test, not(feature = "extension-module")))]
mod pyo3_link_tests {
    #[test]
    fn cpython_is_linked_and_initialized() {
        pyo3::prepare_freethreaded_python();
        pyo3::Python::with_gil(|py| {
            assert_eq!(py.version_info().major, 3);
            assert!(
                py.version_info().minor >= 10,
                "abi3-py310 requires CPython >= 3.10, got {}.{}",
                py.version_info().major,
                py.version_info().minor
            );
        });
    }
}
