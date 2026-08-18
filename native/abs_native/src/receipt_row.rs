//! Typed Rocks receipt-row value codec (v1.3.151).
//!
//! New writes use a compact binary blob; reads accept binary **or** legacy JSON.
//! Soft industrial slice — not full Rocks rewrite / tip proof.

use pyo3::prelude::*;
use serde_json::{Map, Number, Value};

pub const RECEIPT_ROW_MAGIC: &[u8; 4] = b"ATXR";
pub const RECEIPT_ROW_VERSION: u8 = 1;
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
                            return Err(format!("receipt field {k} is not finite"));
                        }
                        return Ok(f);
                    }
                }
                Value::String(s) => {
                    let f: f64 = s.trim().parse().unwrap_or(default);
                    if !f.is_finite() {
                        return Err(format!("receipt field {k} is not finite"));
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

fn write_len_str(out: &mut Vec<u8>, s: &str) -> Result<(), String> {
    if s.len() > u16::MAX as usize {
        return Err("string too long for u16".to_string());
    }
    write_u16(out, s.len() as u16);
    out.extend_from_slice(s.as_bytes());
    Ok(())
}

fn read_len_str(buf: &[u8], off: &mut usize) -> Result<String, String> {
    let len = read_u16(buf, off).ok_or("receipt_row_truncated")? as usize;
    let bytes = read_bytes(buf, off, len).ok_or("receipt_row_truncated")?;
    std::str::from_utf8(bytes)
        .map(|s| s.to_string())
        .map_err(|_| "receipt_row_bad_utf8".to_string())
}

/// Pack a JSON-shaped receipt object into ATXR binary.
pub fn pack_receipt_row_value(receipt: &Value) -> Result<Vec<u8>, String> {
    let obj = receipt
        .as_object()
        .ok_or_else(|| "receipt row must be an object".to_string())?;
    let tx_hash = json_string(obj, &["tx_hash", "hash"]).trim().to_string();
    if tx_hash.is_empty() {
        return Err("receipt row missing tx_hash".to_string());
    }
    let block_height = json_u64(obj, &["block_height"], 0);
    let block_hash = json_string(obj, &["block_hash"]).trim().to_string();
    let from_addr = json_string(obj, &["from_addr", "from"])
        .trim()
        .to_ascii_lowercase();
    let to_addr = json_string(obj, &["to_addr", "to"])
        .trim()
        .to_ascii_lowercase();
    let value = json_f64(obj, &["value", "amount"], 0.0)?;
    let fee = json_f64(obj, &["fee"], 0.0)?;
    let burned = json_f64(obj, &["burned"], 0.0)?;
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
    let status = normalize_status(obj);
    let created_at = json_u64(obj, &["created_at", "timestamp"], 0);

    let mut out =
        Vec::with_capacity(64 + tx_hash.len() + block_hash.len() + from_addr.len() + to_addr.len());
    out.extend_from_slice(RECEIPT_ROW_MAGIC);
    out.push(RECEIPT_ROW_VERSION);
    out.push(flags);
    write_len_str(&mut out, &tx_hash)?;
    write_u64(&mut out, block_height);
    write_len_str(&mut out, &block_hash)?;
    write_len_str(&mut out, &from_addr)?;
    write_len_str(&mut out, &to_addr)?;
    write_f64(&mut out, value);
    write_f64(&mut out, fee);
    write_f64(&mut out, burned);
    write_u64(&mut out, gas_used);
    out.push(status);
    write_u64(&mut out, created_at);
    Ok(out)
}

/// Unpack ATXR binary into a JSON object (same logical shape as legacy rows).
pub fn unpack_receipt_row_bytes(blob: &[u8]) -> Result<Value, String> {
    if blob.len() < 4 + 1 + 1 + 2 {
        return Err("receipt_row_too_short".to_string());
    }
    if &blob[0..4] != RECEIPT_ROW_MAGIC {
        return Err("receipt_row_bad_magic".to_string());
    }
    let mut off = 4usize;
    let ver = *blob.get(off).ok_or("receipt_row_truncated")?;
    off += 1;
    if ver != RECEIPT_ROW_VERSION {
        return Err(format!("receipt_row_bad_version:{ver}"));
    }
    let _flags = *blob.get(off).ok_or("receipt_row_truncated")?;
    off += 1;
    let gas_used_unobserved = (_flags & FLAG_GAS_USED_UNOBSERVED) != 0;

    let tx_hash = read_len_str(blob, &mut off)?;
    let block_height = read_u64(blob, &mut off).ok_or("receipt_row_truncated")?;
    let block_hash = read_len_str(blob, &mut off)?;
    let from_addr = read_len_str(blob, &mut off)?;
    let to_addr = read_len_str(blob, &mut off)?;
    let value = read_f64(blob, &mut off).ok_or("receipt_row_truncated")?;
    let fee = read_f64(blob, &mut off).ok_or("receipt_row_truncated")?;
    let burned = read_f64(blob, &mut off).ok_or("receipt_row_truncated")?;
    let gas_used = read_u64(blob, &mut off).ok_or("receipt_row_truncated")?;
    let status = *blob.get(off).ok_or("receipt_row_truncated")?;
    off += 1;
    let created_at = read_u64(blob, &mut off).ok_or("receipt_row_truncated")?;

    if !value.is_finite() || !fee.is_finite() || !burned.is_finite() {
        return Err("receipt_row_non_finite".to_string());
    }

    let mut map = Map::new();
    map.insert("tx_hash".into(), Value::String(tx_hash));
    map.insert(
        "block_height".into(),
        Value::Number(Number::from(block_height)),
    );
    map.insert("block_hash".into(), Value::String(block_hash));
    map.insert("from_addr".into(), Value::String(from_addr));
    map.insert("to_addr".into(), Value::String(to_addr));
    map.insert(
        "value".into(),
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| "receipt value is not finite".to_string())?,
    );
    map.insert(
        "fee".into(),
        Number::from_f64(fee)
            .map(Value::Number)
            .ok_or_else(|| "receipt fee is not finite".to_string())?,
    );
    map.insert(
        "burned".into(),
        Number::from_f64(burned)
            .map(Value::Number)
            .ok_or_else(|| "receipt burned is not finite".to_string())?,
    );
    if gas_used_unobserved {
        map.insert("gas_used".into(), Value::Null);
    } else {
        map.insert("gas_used".into(), Value::Number(Number::from(gas_used)));
    }
    map.insert(
        "status".into(),
        Value::Number(Number::from(u64::from(status.min(1)))),
    );
    map.insert("created_at".into(), Value::Number(Number::from(created_at)));
    Ok(Value::Object(map))
}

/// Dual-decode: ATXR binary or legacy JSON object bytes.
pub fn receipt_blob_to_value(blob: &[u8]) -> Result<Value, String> {
    if blob.is_empty() {
        return Err("empty_receipt_blob".to_string());
    }
    if blob.len() >= 4 && &blob[0..4] == RECEIPT_ROW_MAGIC {
        return unpack_receipt_row_bytes(blob);
    }
    serde_json::from_slice(blob).map_err(|e| format!("receipt_blob_json_invalid:{e}"))
}

pub fn is_receipt_row_binary(blob: &[u8]) -> bool {
    blob.len() >= 4 && &blob[0..4] == RECEIPT_ROW_MAGIC
}

#[pyfunction]
#[pyo3(name = "pack_receipt_row")]
fn pack_receipt_row_py(receipt_json: &str) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let parsed: Value = serde_json::from_str(receipt_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("receipt_json invalid: {e}"))
        })?;
        let blob =
            pack_receipt_row_value(&parsed).map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(pyo3::types::PyBytes::new_bound(py, &blob).into())
    })
}

#[pyfunction]
#[pyo3(name = "unpack_receipt_row")]
fn unpack_receipt_row_py(py: Python<'_>, blob: &[u8]) -> PyResult<String> {
    let _ = py;
    let value = unpack_receipt_row_bytes(blob).map_err(pyo3::exceptions::PyValueError::new_err)?;
    serde_json::to_string(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("receipt_row encode failed: {e}"))
    })
}

#[pyfunction]
#[pyo3(name = "receipt_blob_to_json")]
fn receipt_blob_to_json_py(blob: &[u8]) -> PyResult<String> {
    let value = receipt_blob_to_value(blob).map_err(pyo3::exceptions::PyValueError::new_err)?;
    serde_json::to_string(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("receipt_blob encode failed: {e}"))
    })
}

#[pyfunction]
#[pyo3(name = "is_receipt_row_binary")]
fn is_receipt_row_binary_py(blob: &[u8]) -> bool {
    is_receipt_row_binary(blob)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pack_receipt_row_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack_receipt_row_py, m)?)?;
    m.add_function(wrap_pyfunction!(receipt_blob_to_json_py, m)?)?;
    m.add_function(wrap_pyfunction!(is_receipt_row_binary_py, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn roundtrip_receipt() {
        let row = json!({
            "tx_hash": "0xabc",
            "block_height": 9,
            "block_hash": "0xblock",
            "from_addr": "0xAAA",
            "to_addr": "0xBBB",
            "value": 1.5,
            "fee": 0.01,
            "burned": 0.0,
            "gas_used": 21000,
            "status": 1,
            "created_at": 1700000000
        });
        let blob = pack_receipt_row_value(&row).unwrap();
        assert!(is_receipt_row_binary(&blob));
        let back = unpack_receipt_row_bytes(&blob).unwrap();
        assert_eq!(back["tx_hash"], "0xabc");
        assert_eq!(back["from_addr"], "0xaaa");
        assert_eq!(back["block_height"], 9);
        assert_eq!(back["status"], 1);
    }

    #[test]
    fn omitted_gas_used_unpacks_null() {
        let row = json!({
            "tx_hash": "0xabc",
            "block_height": 1,
            "block_hash": "0xblock",
            "from_addr": "0xaaa",
            "to_addr": "0xbbb",
            "value": 1.0,
            "fee": 0.01,
            "burned": 0.0,
            "status": 1,
            "created_at": 1
        });
        let blob = pack_receipt_row_value(&row).unwrap();
        let back = unpack_receipt_row_bytes(&blob).unwrap();
        assert!(back["gas_used"].is_null());
    }

    #[test]
    fn dual_read_json() {
        let row = json!({
            "tx_hash":"0x11","block_height":1,"block_hash":"0xb",
            "from_addr":"0x1","to_addr":"0x2","value":0.0,"fee":0.0,"burned":0.0,
            "gas_used":21000,"status":0,"created_at":1
        });
        let blob = serde_json::to_vec(&row).unwrap();
        let v = receipt_blob_to_value(&blob).unwrap();
        assert_eq!(v["tx_hash"], "0x11");
    }
}
