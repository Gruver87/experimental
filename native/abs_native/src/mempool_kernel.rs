//! ADR 0021 phase 1 — mempool post-signature validation kernels.
//!
//! Stateless checks only. Caller supplies a read-only `{nonce, balance_sat}`
//! snapshot **after** signature verify. This module must never open Rocks/SQLite.

use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde_json::{Map, Number, Value};

/// Pure kernel used by PyO3 and Rust unit tests.
pub(crate) fn validate_post_sig_inner(
    snapshot_nonce: i64,
    balance_sat: i64,
    from_addr: &str,
    to_addr: &str,
    tx_nonce: i64,
    value_sat: i64,
    fee_sat: i64,
    gas_limit: i64,
) -> Result<(), &'static str> {
    if from_addr.trim().is_empty() || to_addr.trim().is_empty() {
        return Err("missing_address");
    }
    if value_sat < 0 {
        return Err("negative_value");
    }
    if fee_sat < 0 {
        return Err("negative_fee");
    }
    if gas_limit < 0 {
        return Err("negative_gas");
    }
    if snapshot_nonce < 0 || balance_sat < 0 {
        return Err("invalid_snapshot");
    }
    if tx_nonce != snapshot_nonce {
        return Err("nonce_mismatch");
    }
    let need = value_sat.checked_add(fee_sat).ok_or("cost_overflow")?;
    if balance_sat < need {
        return Err("insufficient_balance");
    }
    Ok(())
}

fn parse_bytecode_hex(raw: &str) -> Result<Vec<u8>, &'static str> {
    let mut s = raw.trim();
    if let Some(rest) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
        s = rest;
    }
    let s = s.replace(' ', "");
    if s.is_empty() {
        return Err("empty_bytecode");
    }
    if !s.len().is_multiple_of(2) {
        return Err("invalid_hex_length");
    }
    let mut out = Vec::with_capacity(s.len() / 2);
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let hi = (bytes[i] as char)
            .to_digit(16)
            .ok_or("invalid_hex_length")?;
        let lo = (bytes[i + 1] as char)
            .to_digit(16)
            .ok_or("invalid_hex_length")?;
        out.push(((hi << 4) | lo) as u8);
        i += 2;
    }
    Ok(out)
}

fn opcode_name(op: u8) -> String {
    match op {
        0x00 => "STOP".into(),
        0xF1 => "CALL".into(),
        0xF3 => "RETURN".into(),
        0xFD => "REVERT".into(),
        o if (0x60..=0x7F).contains(&o) => format!("PUSH{}", o - 0x5F),
        o if (0x80..=0x8F).contains(&o) => format!("DUP{}", o - 0x7F),
        o if (0x90..=0x9F).contains(&o) => format!("SWAP{}", o - 0x8F),
        o => format!("0x{o:02X}"),
    }
}

/// ADR 0021 phase 3 — deploy admit. Reason strings match TxPipeline.
pub(crate) fn admit_evm_deploy_inner(bytecode_hex: &str) -> Result<(), String> {
    let code = parse_bytecode_hex(bytecode_hex).map_err(|e| e.to_string())?;
    if code.len() >= 2 && code[0] == 0xEF && code[1] == 0x00 {
        return Err("unsupported_evm_bytecode:eof_container_not_supported".into());
    }
    if code[0] == 0xEF {
        return Err("unsupported_evm_bytecode:legacy_bytecode_may_not_start_with_0xef".into());
    }
    let issues = crate::evm_scan_bytecode_inner(&code);
    if let Some((_pc, op)) = issues.first() {
        return Err(format!("unsupported_evm_bytecode:{}", opcode_name(*op)));
    }
    Ok(())
}

fn i64_field(map: &Map<String, Value>, key: &str) -> PyResult<i64> {
    match map.get(key) {
        Some(Value::Number(n)) => n
            .as_i64()
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(format!("bad_i64:{key}"))),
        Some(Value::String(s)) => s
            .parse::<i64>()
            .map_err(|_| pyo3::exceptions::PyValueError::new_err(format!("bad_i64:{key}"))),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "missing_field:{key}"
        ))),
    }
}

fn str_field(map: &Map<String, Value>, key: &str) -> PyResult<String> {
    match map.get(key) {
        Some(Value::String(s)) => Ok(s.clone()),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "missing_field:{key}"
        ))),
    }
}

fn dict_to_map(dict: &Bound<'_, PyDict>) -> PyResult<Map<String, Value>> {
    let mut out = Map::new();
    for (k, v) in dict.iter() {
        let key: String = k.extract()?;
        if let Ok(i) = v.extract::<i64>() {
            out.insert(key, Value::Number(Number::from(i)));
        } else if let Ok(s) = v.extract::<String>() {
            out.insert(key, Value::String(s));
        } else {
            return Err(pyo3::exceptions::PyTypeError::new_err(format!(
                "unsupported_field_type:{key}"
            )));
        }
    }
    Ok(out)
}

/// Validate transfer fields against a post-sig account snapshot.
///
/// Returns `{accept: bool, reason: Optional[str]}` matching ADR 0021 fixtures.
#[pyfunction]
fn mempool_validate_post_sig(
    py: Python<'_>,
    snapshot: Bound<'_, PyDict>,
    tx: Bound<'_, PyDict>,
) -> PyResult<PyObject> {
    let snap = dict_to_map(&snapshot)?;
    let txm = dict_to_map(&tx)?;
    let snapshot_nonce = i64_field(&snap, "nonce")?;
    let balance_sat = i64_field(&snap, "balance_sat")?;
    let from_addr = str_field(&txm, "from_addr")?;
    let to_addr = str_field(&txm, "to_addr")?;
    let tx_nonce = i64_field(&txm, "nonce")?;
    let value_sat = i64_field(&txm, "value_sat")?;
    let fee_sat = i64_field(&txm, "fee_sat")?;
    let gas_limit = i64_field(&txm, "gas_limit")?;

    let outcome = validate_post_sig_inner(
        snapshot_nonce,
        balance_sat,
        &from_addr,
        &to_addr,
        tx_nonce,
        value_sat,
        fee_sat,
        gas_limit,
    );

    let out = PyDict::new_bound(py);
    match outcome {
        Ok(()) => {
            out.set_item("accept", true)?;
            out.set_item("reason", py.None())?;
        }
        Err(reason) => {
            out.set_item("accept", false)?;
            out.set_item("reason", reason)?;
        }
    }
    Ok(out.into())
}

/// ADR 0021 phase 3 — EVM deploy admit (EOF / unsupported opcode).
///
/// Returns `{accept: bool, reason: Optional[str]}` where reason is the full
/// TxPipeline error string (`unsupported_evm_bytecode:...`).
#[pyfunction]
fn mempool_admit_evm_deploy(py: Python<'_>, bytecode_hex: &str) -> PyResult<PyObject> {
    let out = PyDict::new_bound(py);
    match admit_evm_deploy_inner(bytecode_hex) {
        Ok(()) => {
            out.set_item("accept", true)?;
            out.set_item("reason", py.None())?;
        }
        Err(reason) => {
            out.set_item("accept", false)?;
            out.set_item("reason", reason)?;
        }
    }
    Ok(out.into())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(mempool_validate_post_sig, m)?)?;
    m.add_function(wrap_pyfunction!(mempool_admit_evm_deploy, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{admit_evm_deploy_inner, validate_post_sig_inner};

    #[test]
    fn accept_within_balance() {
        assert!(validate_post_sig_inner(
            0,
            5_000_000,
            "0x1111111111111111111111111111111111111111",
            "0x2222222222222222222222222222222222222222",
            0,
            1_000_000,
            50_000,
            21_000
        )
        .is_ok());
    }

    #[test]
    fn refuse_nonce_mismatch() {
        assert_eq!(
            validate_post_sig_inner(
                2,
                5_000_000,
                "0x1111111111111111111111111111111111111111",
                "0x2222222222222222222222222222222222222222",
                5,
                0,
                50_000,
                21_000
            ),
            Err("nonce_mismatch")
        );
    }

    #[test]
    fn refuse_insufficient_balance() {
        assert_eq!(
            validate_post_sig_inner(
                0,
                100_000,
                "0x1111111111111111111111111111111111111111",
                "0x2222222222222222222222222222222222222222",
                0,
                90_000,
                50_000,
                21_000
            ),
            Err("insufficient_balance")
        );
    }

    #[test]
    fn refuse_empty_address() {
        assert_eq!(
            validate_post_sig_inner(0, 1, "", "0x2", 0, 0, 0, 21_000),
            Err("missing_address")
        );
    }

    #[test]
    fn admit_refuse_eof() {
        assert_eq!(
            admit_evm_deploy_inner("0xEF0000").unwrap_err(),
            "unsupported_evm_bytecode:eof_container_not_supported"
        );
    }

    #[test]
    fn admit_refuse_bad_opcode() {
        assert_eq!(
            admit_evm_deploy_inner("0x5C").unwrap_err(),
            "unsupported_evm_bytecode:0x5C"
        );
    }

    #[test]
    fn admit_accept_stop() {
        assert!(admit_evm_deploy_inner("0x00").is_ok());
    }
}
