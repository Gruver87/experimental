//! Typed Rocks tx-row value codec (v1.3.148).
//!
//! New writes use a compact binary blob; reads accept binary **or** legacy JSON.
//! Soft industrial slice — not block blob migration / full Rocks rewrite.

use pyo3::prelude::*;
use serde_json::{Map, Number, Value};

pub const TX_ROW_MAGIC: &[u8; 4] = b"ATXV";
pub const TX_ROW_VERSION: u8 = 1;
/// flags bit 0: gas_used was not observed (do not invent 21000 / copy gas limit).
const FLAG_GAS_USED_UNOBSERVED: u8 = 0x01;

fn json_present_non_null(obj: &Map<String, Value>, key: &str) -> bool {
    match obj.get(key) {
        Some(Value::Null) | None => false,
        Some(_) => true,
    }
}

fn read_u16(buf: &[u8], off: &mut usize) -> Option<u16> {
    let end = off.checked_add(2)?;
    let v = u16::from_le_bytes(buf.get(*off..end)?.try_into().ok()?);
    *off = end;
    Some(v)
}

fn read_u32(buf: &[u8], off: &mut usize) -> Option<u32> {
    let end = off.checked_add(4)?;
    let v = u32::from_le_bytes(buf.get(*off..end)?.try_into().ok()?);
    *off = end;
    Some(v)
}

fn read_u64(buf: &[u8], off: &mut usize) -> Option<u64> {
    let end = off.checked_add(8)?;
    let v = u64::from_le_bytes(buf.get(*off..end)?.try_into().ok()?);
    *off = end;
    Some(v)
}

fn read_f64(buf: &[u8], off: &mut usize) -> Option<f64> {
    let end = off.checked_add(8)?;
    let v = f64::from_le_bytes(buf.get(*off..end)?.try_into().ok()?);
    *off = end;
    Some(v)
}

fn read_bytes<'a>(buf: &'a [u8], off: &mut usize, n: usize) -> Option<&'a [u8]> {
    let end = off.checked_add(n)?;
    let slice = buf.get(*off..end)?;
    *off = end;
    Some(slice)
}

fn write_u16(out: &mut Vec<u8>, v: u16) {
    out.extend_from_slice(&v.to_le_bytes());
}
fn write_u32(out: &mut Vec<u8>, v: u32) {
    out.extend_from_slice(&v.to_le_bytes());
}
fn write_u64(out: &mut Vec<u8>, v: u64) {
    out.extend_from_slice(&v.to_le_bytes());
}
fn write_f64(out: &mut Vec<u8>, v: f64) {
    out.extend_from_slice(&v.to_le_bytes());
}

fn json_string(obj: &Map<String, Value>, keys: &[&str]) -> String {
    for k in keys {
        if let Some(v) = obj.get(*k) {
            match v {
                Value::Null => return String::new(),
                Value::String(s) => return s.clone(),
                other => return other.to_string(),
            }
        }
    }
    String::new()
}

fn json_u64(obj: &Map<String, Value>, keys: &[&str], default: u64) -> u64 {
    for k in keys {
        if let Some(v) = obj.get(*k) {
            match v {
                Value::Number(n) => {
                    if let Some(u) = n.as_u64() {
                        return u;
                    }
                    if let Some(i) = n.as_i64() {
                        return i.max(0) as u64;
                    }
                    if let Some(f) = n.as_f64() {
                        return if f.is_finite() && f > 0.0 {
                            f as u64
                        } else {
                            0
                        };
                    }
                }
                Value::String(s) => {
                    if let Ok(u) = s.trim().parse::<u64>() {
                        return u;
                    }
                }
                Value::Bool(b) => return u64::from(*b),
                _ => {}
            }
        }
    }
    default
}

fn json_f64(obj: &Map<String, Value>, keys: &[&str], default: f64) -> Result<f64, String> {
    for k in keys {
        if let Some(v) = obj.get(*k) {
            match v {
                Value::Number(n) => {
                    if let Some(f) = n.as_f64() {
                        if !f.is_finite() {
                            return Err(format!("tx field {k} is not finite"));
                        }
                        return Ok(f);
                    }
                }
                Value::String(s) => {
                    let f: f64 = s.trim().parse().unwrap_or(default);
                    if !f.is_finite() {
                        return Err(format!("tx field {k} is not finite"));
                    }
                    return Ok(f);
                }
                Value::Null => return Ok(default),
                _ => {}
            }
        }
    }
    Ok(default)
}

fn normalize_status(obj: &Map<String, Value>) -> u8 {
    let Some(v) = obj.get("status") else {
        return 0;
    };
    match v {
        Value::Null => 0,
        Value::Bool(b) => u8::from(*b),
        Value::Number(n) => {
            if n.as_i64().unwrap_or(0) != 0 || n.as_u64().unwrap_or(0) != 0 {
                1
            } else {
                0
            }
        }
        Value::String(s) => {
            let s = s.trim().to_ascii_lowercase();
            if s.is_empty() {
                return 0;
            }
            if matches!(
                s.as_str(),
                "1" | "true" | "ok" | "success" | "confirmed" | "mined"
            ) {
                1
            } else if matches!(
                s.as_str(),
                "0" | "false" | "failed" | "reverted" | "pending"
            ) {
                0
            } else if let Ok(n) = s.parse::<i64>() {
                u8::from(n != 0)
            } else {
                0
            }
        }
        _ => 0,
    }
}

fn write_len_str(out: &mut Vec<u8>, s: &str, max_u16: bool) -> Result<(), String> {
    if max_u16 {
        if s.len() > u16::MAX as usize {
            return Err("string too long for u16".to_string());
        }
        write_u16(out, s.len() as u16);
    } else {
        if s.len() > u32::MAX as usize {
            return Err("string too long for u32".to_string());
        }
        write_u32(out, s.len() as u32);
    }
    out.extend_from_slice(s.as_bytes());
    Ok(())
}

fn read_len_str(buf: &[u8], off: &mut usize, max_u16: bool) -> Result<String, String> {
    let len = if max_u16 {
        read_u16(buf, off).ok_or("tx_row_truncated")? as usize
    } else {
        read_u32(buf, off).ok_or("tx_row_truncated")? as usize
    };
    let bytes = read_bytes(buf, off, len).ok_or("tx_row_truncated")?;
    std::str::from_utf8(bytes)
        .map(|s| s.to_string())
        .map_err(|_| "tx_row_bad_utf8".to_string())
}

/// Pack a JSON-shaped tx object into ATXV binary.
pub fn pack_tx_row_value(tx: &Value) -> Result<Vec<u8>, String> {
    let obj = tx
        .as_object()
        .ok_or_else(|| "tx row must be an object".to_string())?;
    let hash = json_string(obj, &["hash", "tx_hash"]).trim().to_string();
    if hash.is_empty() {
        return Err("tx row missing hash".to_string());
    }
    let block_height = json_u64(obj, &["block_height"], 0);
    let from_addr = json_string(obj, &["from_addr", "from"])
        .trim()
        .to_ascii_lowercase();
    let to_addr = json_string(obj, &["to_addr", "to"])
        .trim()
        .to_ascii_lowercase();
    let value = json_f64(obj, &["value", "amount"], 0.0)?;
    let gas = json_u64(obj, &["gas"], 21_000);
    let gas_used_observed = json_present_non_null(obj, "gas_used");
    let gas_used = if gas_used_observed {
        json_u64(obj, &["gas_used"], 0)
    } else {
        0
    };
    let mut flags: u8 = 0;
    if !gas_used_observed {
        flags |= FLAG_GAS_USED_UNOBSERVED;
    }
    let fee = json_f64(obj, &["fee"], 0.0)?;
    let burned = json_f64(obj, &["burned"], 0.0)?;
    let nonce = json_u64(obj, &["nonce"], 0);
    let tx_data = json_string(obj, &["tx_data", "data"]);
    let status = normalize_status(obj);
    let timestamp = json_u64(obj, &["timestamp"], 0);

    let mut out =
        Vec::with_capacity(64 + hash.len() + from_addr.len() + to_addr.len() + tx_data.len());
    out.extend_from_slice(TX_ROW_MAGIC);
    out.push(TX_ROW_VERSION);
    out.push(flags);
    write_len_str(&mut out, &hash, true)?;
    write_u64(&mut out, block_height);
    write_len_str(&mut out, &from_addr, true)?;
    write_len_str(&mut out, &to_addr, true)?;
    write_f64(&mut out, value);
    write_u64(&mut out, gas);
    write_u64(&mut out, gas_used);
    write_f64(&mut out, fee);
    write_f64(&mut out, burned);
    write_u64(&mut out, nonce);
    write_len_str(&mut out, &tx_data, false)?;
    out.push(status);
    write_u64(&mut out, timestamp);
    Ok(out)
}

/// Unpack ATXV binary into a JSON object (same logical shape as legacy rows).
pub fn unpack_tx_row_bytes(blob: &[u8]) -> Result<Value, String> {
    if blob.len() < 4 + 1 + 1 + 2 {
        return Err("tx_row_too_short".to_string());
    }
    if &blob[0..4] != TX_ROW_MAGIC {
        return Err("tx_row_bad_magic".to_string());
    }
    let mut off = 4usize;
    let ver = *blob.get(off).ok_or("tx_row_truncated")?;
    off += 1;
    if ver != TX_ROW_VERSION {
        return Err(format!("tx_row_bad_version:{ver}"));
    }
    let _flags = *blob.get(off).ok_or("tx_row_truncated")?;
    off += 1;
    let gas_used_unobserved = (_flags & FLAG_GAS_USED_UNOBSERVED) != 0;

    let hash = read_len_str(blob, &mut off, true)?;
    let block_height = read_u64(blob, &mut off).ok_or("tx_row_truncated")?;
    let from_addr = read_len_str(blob, &mut off, true)?;
    let to_addr = read_len_str(blob, &mut off, true)?;
    let value = read_f64(blob, &mut off).ok_or("tx_row_truncated")?;
    let gas = read_u64(blob, &mut off).ok_or("tx_row_truncated")?;
    let gas_used = read_u64(blob, &mut off).ok_or("tx_row_truncated")?;
    let fee = read_f64(blob, &mut off).ok_or("tx_row_truncated")?;
    let burned = read_f64(blob, &mut off).ok_or("tx_row_truncated")?;
    let nonce = read_u64(blob, &mut off).ok_or("tx_row_truncated")?;
    let tx_data = read_len_str(blob, &mut off, false)?;
    let status = *blob.get(off).ok_or("tx_row_truncated")?;
    off += 1;
    let timestamp = read_u64(blob, &mut off).ok_or("tx_row_truncated")?;

    if !value.is_finite() || !fee.is_finite() || !burned.is_finite() {
        return Err("tx_row_non_finite".to_string());
    }

    let mut map = Map::new();
    map.insert("hash".into(), Value::String(hash));
    map.insert(
        "block_height".into(),
        Value::Number(Number::from(block_height)),
    );
    map.insert("from_addr".into(), Value::String(from_addr));
    map.insert("to_addr".into(), Value::String(to_addr));
    map.insert(
        "value".into(),
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| "tx value is not finite".to_string())?,
    );
    map.insert("gas".into(), Value::Number(Number::from(gas)));
    if gas_used_unobserved {
        map.insert("gas_used".into(), Value::Null);
    } else {
        map.insert("gas_used".into(), Value::Number(Number::from(gas_used)));
    }
    map.insert(
        "fee".into(),
        Number::from_f64(fee)
            .map(Value::Number)
            .ok_or_else(|| "tx fee is not finite".to_string())?,
    );
    map.insert(
        "burned".into(),
        Number::from_f64(burned)
            .map(Value::Number)
            .ok_or_else(|| "tx burned is not finite".to_string())?,
    );
    map.insert("nonce".into(), Value::Number(Number::from(nonce)));
    map.insert("tx_data".into(), Value::String(tx_data));
    map.insert(
        "status".into(),
        Value::Number(Number::from(u64::from(status.min(1)))),
    );
    map.insert("timestamp".into(), Value::Number(Number::from(timestamp)));
    Ok(Value::Object(map))
}

/// Dual-decode: ATXV binary or legacy JSON object bytes.
pub fn tx_blob_to_value(blob: &[u8]) -> Result<Value, String> {
    if blob.is_empty() {
        return Err("empty_tx_blob".to_string());
    }
    if blob.len() >= 4 && &blob[0..4] == TX_ROW_MAGIC {
        return unpack_tx_row_bytes(blob);
    }
    serde_json::from_slice(blob).map_err(|e| format!("tx_blob_json_invalid:{e}"))
}

pub fn is_tx_row_binary(blob: &[u8]) -> bool {
    blob.len() >= 4 && &blob[0..4] == TX_ROW_MAGIC
}

#[pyfunction]
#[pyo3(name = "pack_tx_row")]
fn pack_tx_row_py(tx_json: &str) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let parsed: Value = serde_json::from_str(tx_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("tx_json invalid: {e}"))
        })?;
        let blob = pack_tx_row_value(&parsed).map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(pyo3::types::PyBytes::new_bound(py, &blob).into())
    })
}

#[pyfunction]
#[pyo3(name = "unpack_tx_row")]
fn unpack_tx_row_py(py: Python<'_>, blob: &[u8]) -> PyResult<String> {
    let _ = py;
    let value = unpack_tx_row_bytes(blob).map_err(pyo3::exceptions::PyValueError::new_err)?;
    serde_json::to_string(&value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("tx_row encode failed: {e}")))
}

#[pyfunction]
#[pyo3(name = "tx_blob_to_json")]
fn tx_blob_to_json_py(blob: &[u8]) -> PyResult<String> {
    let value = tx_blob_to_value(blob).map_err(pyo3::exceptions::PyValueError::new_err)?;
    serde_json::to_string(&value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("tx_blob encode failed: {e}")))
}

#[pyfunction]
#[pyo3(name = "is_tx_row_binary")]
fn is_tx_row_binary_py(blob: &[u8]) -> bool {
    is_tx_row_binary(blob)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pack_tx_row_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack_tx_row_py, m)?)?;
    m.add_function(wrap_pyfunction!(tx_blob_to_json_py, m)?)?;
    m.add_function(wrap_pyfunction!(is_tx_row_binary_py, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn roundtrip_tx() {
        let row = json!({
            "hash": "0xabc",
            "block_height": 12,
            "from_addr": "0xAAA",
            "to_addr": "0xBBB",
            "value": 1.5,
            "gas": 21000,
            "gas_used": 21000,
            "fee": 0.01,
            "burned": 0.0,
            "nonce": 3,
            "tx_data": "",
            "status": 1,
            "timestamp": 1700000000
        });
        let blob = pack_tx_row_value(&row).unwrap();
        assert!(is_tx_row_binary(&blob));
        let back = unpack_tx_row_bytes(&blob).unwrap();
        assert_eq!(back["hash"], "0xabc");
        assert_eq!(back["from_addr"], "0xaaa");
        assert_eq!(back["block_height"], 12);
        assert_eq!(back["status"], 1);
    }

    #[test]
    fn omitted_gas_used_unpacks_null() {
        let row = json!({
            "hash": "0xabc",
            "block_height": 1,
            "from_addr": "0xaaa",
            "to_addr": "0xbbb",
            "value": 1.0,
            "gas": 21000,
            "fee": 0.01,
            "burned": 0.0,
            "nonce": 0,
            "tx_data": "",
            "status": 1,
            "timestamp": 1
        });
        let blob = pack_tx_row_value(&row).unwrap();
        let back = unpack_tx_row_bytes(&blob).unwrap();
        assert!(back["gas_used"].is_null());
    }

    #[test]
    fn dual_read_json() {
        let row = json!({
            "hash":"0x11","block_height":1,"from_addr":"0x1","to_addr":"0x2",
            "value":0.0,"gas":21000,"gas_used":21000,"fee":0.0,"burned":0.0,
            "nonce":0,"tx_data":"","status":0,"timestamp":1
        });
        let blob = serde_json::to_vec(&row).unwrap();
        let v = tx_blob_to_value(&blob).unwrap();
        assert_eq!(v["hash"], "0x11");
    }
}
