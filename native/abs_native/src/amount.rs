//! Canonical ABS amount math (satoshi) + StateEngine batch apply.

use pyo3::prelude::*;
use rust_decimal::prelude::*;
use rust_decimal::{Decimal, RoundingStrategy};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::str::FromStr;

pub(crate) const SATOSHI_MULTIPLIER: i64 = 1_000_000;
pub(crate) const MAX_STATE_ENGINE_ACCOUNTS: usize = 1_000_000;
pub(crate) const MAX_STATE_ENGINE_TXS: usize = 100_000;

fn decimal_from_amount(amount: &str) -> PyResult<Decimal> {
    let trimmed = amount.trim();
    if trimmed.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "invalid amount: empty",
        ));
    }
    Decimal::from_str(trimmed)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid amount: {e}")))
}

pub(crate) fn to_satoshi_inner(amount: &str) -> PyResult<i64> {
    let d = decimal_from_amount(amount)?;
    let scaled = d * Decimal::from(SATOSHI_MULTIPLIER);
    let truncated = scaled.round_dp_with_strategy(0, RoundingStrategy::ToZero);
    truncated
        .to_i64()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("amount out of i64 satoshi range"))
}

pub(crate) fn apply_delta_satoshi_inner(current_sat: i64, delta_abs: &str) -> PyResult<i64> {
    let delta = to_satoshi_inner(delta_abs)?;
    Ok((current_sat.saturating_add(delta)).max(0))
}

pub(crate) fn from_satoshi_float_inner(satoshi: i64) -> PyResult<f64> {
    let d = Decimal::from(satoshi) / Decimal::from(SATOSHI_MULTIPLIER);
    d.to_f64()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("satoshi_to_float_failed"))
}

/// Parse integer satoshi JSON; refuse IEEE float satoshi fields (fail-closed).
fn json_satoshi_int(v: &Value, field: &str) -> PyResult<i64> {
    match v {
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.max(0))
            } else if let Some(u) = n.as_u64() {
                Ok(i64::try_from(u).unwrap_or(i64::MAX).max(0))
            } else {
                Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "{field} must be integer satoshi (not float)"
                )))
            }
        }
        Value::String(s) => {
            let t = s.trim();
            if t.contains('.') || t.contains('e') || t.contains('E') {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "{field} must be integer satoshi string"
                )));
            }
            t.parse::<i64>().map(|i| i.max(0)).map_err(|_| {
                pyo3::exceptions::PyValueError::new_err(format!("{field} must be integer satoshi"))
            })
        }
        Value::Null => Ok(0),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "{field} must be integer satoshi"
        ))),
    }
}

fn account_balance(acc: &Value) -> i64 {
    if let Some(v) = acc.get("balance_satoshi") {
        return v
            .as_i64()
            .or_else(|| v.as_u64().map(|u| u as i64))
            .unwrap_or(0)
            .max(0);
    }
    // StateEngine legacy: ``balance`` held satoshi integers.
    acc.get("balance")
        .and_then(|v| v.as_i64())
        .or_else(|| {
            acc.get("balance")
                .and_then(|v| v.as_u64())
                .map(|u| u as i64)
        })
        .unwrap_or(0)
        .max(0)
}

fn account_nonce(acc: &Value) -> i64 {
    acc.get("nonce")
        .and_then(|v| v.as_i64())
        .or_else(|| acc.get("nonce").and_then(|v| v.as_u64()).map(|u| u as i64))
        .unwrap_or(0)
}

fn empty_account() -> Value {
    let mut row = Map::new();
    row.insert("balance_satoshi".to_string(), Value::Number(0.into()));
    row.insert("balance".to_string(), Value::Number(0.into()));
    row.insert("nonce".to_string(), Value::Number(0.into()));
    Value::Object(row)
}

fn set_account_balance(acc: &mut Value, balance: i64, nonce: i64) -> PyResult<()> {
    let obj = acc
        .as_object_mut()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("account row must be object"))?;
    let bal = balance.max(0);
    obj.insert("balance_satoshi".to_string(), Value::Number(bal.into()));
    // StateEngine legacy field: satoshi integer (not ABS float).
    obj.insert("balance".to_string(), Value::Number(bal.into()));
    obj.insert("nonce".to_string(), Value::Number(nonce.into()));
    Ok(())
}

fn tx_amount_sat(tx: &Value) -> PyResult<i64> {
    let obj = tx
        .as_object()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("tx must be object"))?;
    if let Some(v) = obj.get("amount_satoshi") {
        return json_satoshi_int(v, "amount_satoshi");
    }
    let amount = obj
        .get("amount")
        .or_else(|| obj.get("value"))
        .cloned()
        .unwrap_or(Value::Number(0.into()));
    match amount {
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                to_satoshi_inner(&i.to_string())
            } else if let Some(u) = n.as_u64() {
                to_satoshi_inner(&u.to_string())
            } else if let Some(f) = n.as_f64() {
                if !f.is_finite() {
                    return Err(pyo3::exceptions::PyValueError::new_err("non_finite_amount"));
                }
                to_satoshi_inner(&format!("{f}"))
            } else {
                Ok(0)
            }
        }
        Value::String(s) => to_satoshi_inner(&s),
        _ => Ok(0),
    }
}

fn tx_fee_sat(tx: &Value) -> PyResult<i64> {
    let obj = tx
        .as_object()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("tx must be object"))?;
    if let Some(v) = obj.get("fee_satoshi") {
        return json_satoshi_int(v, "fee_satoshi");
    }
    let fee = obj.get("fee").cloned().unwrap_or(Value::Number(0.into()));
    match fee {
        Value::Null => Ok(0),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                to_satoshi_inner(&i.to_string())
            } else if let Some(u) = n.as_u64() {
                to_satoshi_inner(&u.to_string())
            } else if let Some(f) = n.as_f64() {
                if !f.is_finite() {
                    return Err(pyo3::exceptions::PyValueError::new_err("non_finite_fee"));
                }
                to_satoshi_inner(&format!("{f}"))
            } else {
                Ok(0)
            }
        }
        Value::String(s) => to_satoshi_inner(&s),
        _ => Ok(0),
    }
}

fn apply_one_tx(accounts: &mut BTreeMap<String, Value>, tx: &Value) -> PyResult<()> {
    let obj = tx
        .as_object()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("tx must be object"))?;
    let from_addr = obj
        .get("from")
        .or_else(|| obj.get("from_addr"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let to_addr = obj
        .get("to")
        .or_else(|| obj.get("to_addr"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let amount_sat = tx_amount_sat(tx)?;
    let fee_sat = tx_fee_sat(tx)?;

    if !accounts.contains_key(&from_addr) {
        accounts.insert(from_addr.clone(), empty_account());
    }
    let from_bal = account_balance(
        accounts
            .get(&from_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?,
    );
    let from_nonce = account_nonce(
        accounts
            .get(&from_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?,
    );
    let total = amount_sat.saturating_add(fee_sat);
    if from_bal < total {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
            "Insufficient balance: {from_addr}"
        )));
    }
    let tx_nonce = obj
        .get("nonce")
        .and_then(|v| v.as_i64().or_else(|| v.as_u64().map(|u| u as i64)))
        .unwrap_or(from_nonce);
    if tx_nonce != from_nonce {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
            "Invalid nonce: expected {from_nonce}, got {tx_nonce}"
        )));
    }

    {
        let from = accounts
            .get_mut(&from_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?;
        set_account_balance(from, from_bal - total, from_nonce + 1)?;
    }
    if !accounts.contains_key(&to_addr) {
        accounts.insert(to_addr.clone(), empty_account());
    }
    {
        let to = accounts
            .get_mut(&to_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_to_account"))?;
        let to_bal = account_balance(to);
        let to_nonce = account_nonce(to);
        set_account_balance(to, to_bal + amount_sat, to_nonce)?;
    }
    Ok(())
}

fn parse_accounts_map(accounts_json: &str) -> PyResult<BTreeMap<String, Value>> {
    let value: Value = serde_json::from_str(accounts_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let obj = value.as_object().ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err("accounts_json must be an object")
    })?;
    if obj.len() > MAX_STATE_ENGINE_ACCOUNTS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_accounts: {} > {}",
            obj.len(),
            MAX_STATE_ENGINE_ACCOUNTS
        )));
    }
    let mut map = BTreeMap::new();
    for (addr, row) in obj {
        if !row.is_object() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "account row must be object",
            ));
        }
        map.insert(addr.clone(), row.clone());
    }
    Ok(map)
}

#[pyfunction]
fn amount_to_satoshi(amount_abs: String) -> PyResult<i64> {
    to_satoshi_inner(&amount_abs)
}

#[pyfunction]
fn amount_apply_delta_satoshi(current_sat: i64, delta_abs: String) -> PyResult<i64> {
    apply_delta_satoshi_inner(current_sat, &delta_abs)
}

#[pyfunction]
fn amount_from_satoshi_float(satoshi: i64) -> PyResult<f64> {
    from_satoshi_float_inner(satoshi)
}

/// L1 transfer fee split matching Python float math:
/// fee = gas * gas_price_wei (optionally max with gas_used),
/// burned = fee * burn_rate, miner_fee = fee - burned, total = value + fee.
#[pyfunction]
#[pyo3(signature = (gas, gas_price_wei, burn_rate, value, gas_used=None))]
fn plan_transfer_fees(
    gas: u64,
    gas_price_wei: f64,
    burn_rate: f64,
    value: f64,
    gas_used: Option<u64>,
) -> PyResult<(f64, f64, f64, f64)> {
    // Display wrapper over integer satoshi plan (Wave C).
    let (fee_s, burned_s, miner_s, total_s) = plan_transfer_fees_satoshi_inner(
        gas,
        &gas_price_wei.to_string(),
        &burn_rate.to_string(),
        &value.to_string(),
        gas_used,
    )?;
    Ok((
        from_satoshi_float_inner(fee_s)?,
        from_satoshi_float_inner(burned_s)?,
        from_satoshi_float_inner(miner_s)?,
        from_satoshi_float_inner(total_s)?,
    ))
}

fn plan_transfer_fees_satoshi_inner(
    gas: u64,
    gas_price_wei: &str,
    burn_rate: &str,
    value: &str,
    gas_used: Option<u64>,
) -> PyResult<(i64, i64, i64, i64)> {
    let gp = decimal_from_amount(gas_price_wei)?;
    let br = decimal_from_amount(burn_rate)?;
    if gp.is_sign_negative() || br.is_sign_negative() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "non_finite_fee_inputs",
        ));
    }
    let gas_d = Decimal::from(gas);
    let mut fee_abs = gas_d * gp;
    if let Some(used) = gas_used {
        let used_fee = Decimal::from(used) * gp;
        if used_fee > fee_abs {
            fee_abs = used_fee;
        }
    }
    let fee_scaled = (fee_abs * Decimal::from(SATOSHI_MULTIPLIER))
        .round_dp_with_strategy(0, RoundingStrategy::ToZero);
    let fee_sat = fee_scaled
        .to_i64()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("fee_satoshi out of i64 range"))?;
    let rate = if br > Decimal::ONE {
        Decimal::ONE
    } else if br.is_sign_negative() {
        Decimal::ZERO
    } else {
        br
    };
    let burned_dec =
        (Decimal::from(fee_sat) * rate).round_dp_with_strategy(0, RoundingStrategy::ToZero);
    let burned_sat = burned_dec.to_i64().ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err("burned_satoshi out of i64 range")
    })?;
    let miner_sat = fee_sat - burned_sat;
    let value_sat = to_satoshi_inner(value)?;
    Ok((fee_sat, burned_sat, miner_sat, value_sat + fee_sat))
}

#[pyfunction]
#[pyo3(signature = (gas, gas_price_wei, burn_rate, value, gas_used=None))]
fn plan_transfer_fees_satoshi(
    gas: u64,
    gas_price_wei: &str,
    burn_rate: &str,
    value: &str,
    gas_used: Option<u64>,
) -> PyResult<(i64, i64, i64, i64)> {
    plan_transfer_fees_satoshi_inner(gas, gas_price_wei, burn_rate, value, gas_used)
}

/// True when sender_sat covers to_satoshi(total_cost_abs).
#[pyfunction]
fn can_afford_transfer(sender_sat: i64, total_cost_abs: f64) -> PyResult<bool> {
    if !total_cost_abs.is_finite() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "non_finite_total_cost",
        ));
    }
    if total_cost_abs < 0.0 {
        return Ok(false);
    }
    let need = to_satoshi_inner(&total_cost_abs.to_string())?;
    Ok(sender_sat >= need)
}

#[pyfunction]
fn state_engine_apply_transactions(accounts_json: String, txs_json: String) -> PyResult<String> {
    let mut accounts = parse_accounts_map(&accounts_json)?;
    let txs: Value = serde_json::from_str(&txs_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let txs = txs
        .as_array()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("txs_json must be an array"))?;
    if txs.len() > MAX_STATE_ENGINE_TXS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_txs: {} > {}",
            txs.len(),
            MAX_STATE_ENGINE_TXS
        )));
    }
    for tx in txs {
        apply_one_tx(&mut accounts, tx)?;
    }
    let mut out = Map::new();
    for (addr, row) in accounts {
        out.insert(addr, row);
    }
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

fn tx_has_calldata(tx: &Value) -> bool {
    let obj = match tx.as_object() {
        Some(o) => o,
        None => return false,
    };
    let data = obj
        .get("data")
        .or_else(|| obj.get("input"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    !data.is_empty() && data != "0x" && data != "0X"
}

fn apply_simple_transfer_with_fees(
    accounts: &mut BTreeMap<String, Value>,
    tx: &Value,
    gas_price_wei: f64,
    burn_rate: f64,
    proposer: &str,
    burn_address: &str,
) -> PyResult<i64> {
    if tx_has_calldata(tx) {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            "evm_tx_not_supported",
        ));
    }
    let obj = tx
        .as_object()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("tx must be object"))?;
    let from_addr = obj
        .get("from")
        .or_else(|| obj.get("from_addr"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let to_addr = obj
        .get("to")
        .or_else(|| obj.get("to_addr"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if from_addr.is_empty() || to_addr.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err("missing_address"));
    }

    let value_abs = obj
        .get("value")
        .or_else(|| obj.get("amount"))
        .cloned()
        .unwrap_or(Value::Number(0.into()));
    let value_str = match &value_abs {
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                u.to_string()
            } else if let Some(f) = n.as_f64() {
                if !f.is_finite() {
                    return Err(pyo3::exceptions::PyValueError::new_err("non_finite_value"));
                }
                format!("{f}")
            } else {
                "0".to_string()
            }
        }
        Value::String(s) => s.clone(),
        _ => "0".to_string(),
    };
    let gas = obj
        .get("gas")
        .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i as u64)))
        .unwrap_or(21_000);

    let (fee_sat, burned_sat, miner_fee_sat, total_sat) = plan_transfer_fees_satoshi_inner(
        gas,
        &gas_price_wei.to_string(),
        &burn_rate.to_string(),
        &value_str,
        None,
    )?;
    let value_sat = to_satoshi_inner(&value_str)?;

    if !accounts.contains_key(&from_addr) {
        accounts.insert(from_addr.clone(), empty_account());
    }
    let from_row = accounts
        .get(&from_addr)
        .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?;
    let from_bal = account_balance(from_row);
    let from_nonce = account_nonce(from_row);
    if from_bal < total_sat {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            "insufficient_funds",
        ));
    }
    let tx_nonce = obj
        .get("nonce")
        .and_then(|v| v.as_i64().or_else(|| v.as_u64().map(|u| u as i64)))
        .unwrap_or(from_nonce);
    if tx_nonce != from_nonce {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
            "Invalid nonce: expected {from_nonce}, got {tx_nonce}"
        )));
    }

    {
        let from = accounts
            .get_mut(&from_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?;
        set_account_balance(from, from_bal - total_sat, from_nonce + 1)?;
    }
    if !accounts.contains_key(&to_addr) {
        accounts.insert(to_addr.clone(), empty_account());
    }
    {
        let to = accounts
            .get_mut(&to_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_to_account"))?;
        let to_bal = account_balance(to);
        let to_nonce = account_nonce(to);
        set_account_balance(to, to_bal + value_sat, to_nonce)?;
    }
    if miner_fee_sat > 0 && !proposer.is_empty() {
        if !accounts.contains_key(proposer) {
            accounts.insert(proposer.to_string(), empty_account());
        }
        let row = accounts
            .get_mut(proposer)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_proposer"))?;
        let bal = account_balance(row);
        let nonce = account_nonce(row);
        set_account_balance(row, bal + miner_fee_sat, nonce)?;
    }
    if burned_sat > 0 && !burn_address.is_empty() {
        if !accounts.contains_key(burn_address) {
            accounts.insert(burn_address.to_string(), empty_account());
        }
        let row = accounts
            .get_mut(burn_address)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_burn_address"))?;
        let bal = account_balance(row);
        let nonce = account_nonce(row);
        set_account_balance(row, bal + burned_sat, nonce)?;
    }
    let _ = fee_sat; // fee = miner + burned (satoshi rounding may leave dust burned nowhere)
    Ok(burned_sat)
}

/// Apply EVM-host fee (and optional value) effect after Python host ran storage/code/value.
fn apply_host_fee_effect(
    accounts: &mut BTreeMap<String, Value>,
    effect: &Value,
    gas_price_wei: f64,
    burn_rate: f64,
    proposer: &str,
    burn_address: &str,
) -> PyResult<i64> {
    let obj = effect
        .as_object()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("effect must be object"))?;
    let from_addr = obj
        .get("from")
        .or_else(|| obj.get("from_addr"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if from_addr.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err("missing_from"));
    }
    let apply_value = obj
        .get("apply_value")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let to_addr = obj
        .get("to")
        .or_else(|| obj.get("to_addr"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let value_str = if apply_value {
        let value_abs = obj
            .get("value")
            .or_else(|| obj.get("amount"))
            .cloned()
            .unwrap_or(Value::Number(0.into()));
        match &value_abs {
            Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    i.to_string()
                } else if let Some(u) = n.as_u64() {
                    u.to_string()
                } else if let Some(f) = n.as_f64() {
                    if !f.is_finite() {
                        return Err(pyo3::exceptions::PyValueError::new_err("non_finite_value"));
                    }
                    format!("{f}")
                } else {
                    "0".to_string()
                }
            }
            Value::String(s) => s.clone(),
            _ => "0".to_string(),
        }
    } else {
        "0".to_string()
    };
    let gas = obj
        .get("gas")
        .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i as u64)))
        .unwrap_or(21_000);
    let gas_used = obj
        .get("gas_used")
        .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i as u64)));

    let (_fee_sat, burned_sat, miner_fee_sat, total_sat) = plan_transfer_fees_satoshi_inner(
        gas,
        &gas_price_wei.to_string(),
        &burn_rate.to_string(),
        &value_str,
        gas_used,
    )?;
    let value_sat = if apply_value {
        to_satoshi_inner(&value_str)?
    } else {
        0
    };

    if !accounts.contains_key(&from_addr) {
        accounts.insert(from_addr.clone(), empty_account());
    }
    let from_row = accounts
        .get(&from_addr)
        .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?;
    let from_bal = account_balance(from_row);
    let from_nonce = account_nonce(from_row);
    if from_bal < total_sat {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            "insufficient_funds",
        ));
    }
    let tx_nonce = obj
        .get("nonce")
        .and_then(|v| v.as_i64().or_else(|| v.as_u64().map(|u| u as i64)))
        .unwrap_or(from_nonce);
    if tx_nonce != from_nonce {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
            "Invalid nonce: expected {from_nonce}, got {tx_nonce}"
        )));
    }

    {
        let from = accounts
            .get_mut(&from_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_from_account"))?;
        set_account_balance(from, from_bal - total_sat, from_nonce + 1)?;
    }
    if apply_value {
        if to_addr.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err("missing_to"));
        }
        if !accounts.contains_key(&to_addr) {
            accounts.insert(to_addr.clone(), empty_account());
        }
        let to = accounts
            .get_mut(&to_addr)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_to_account"))?;
        let to_bal = account_balance(to);
        let to_nonce = account_nonce(to);
        set_account_balance(to, to_bal + value_sat, to_nonce)?;
    }
    if miner_fee_sat > 0 && !proposer.is_empty() {
        if !accounts.contains_key(proposer) {
            accounts.insert(proposer.to_string(), empty_account());
        }
        let row = accounts
            .get_mut(proposer)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_proposer"))?;
        let bal = account_balance(row);
        let nonce = account_nonce(row);
        set_account_balance(row, bal + miner_fee_sat, nonce)?;
    }
    if burned_sat > 0 && !burn_address.is_empty() {
        if !accounts.contains_key(burn_address) {
            accounts.insert(burn_address.to_string(), empty_account());
        }
        let row = accounts
            .get_mut(burn_address)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_burn_address"))?;
        let bal = account_balance(row);
        let nonce = account_nonce(row);
        set_account_balance(row, bal + burned_sat, nonce)?;
    }
    Ok(burned_sat)
}

fn apply_block_reward_sat(
    accounts: &mut BTreeMap<String, Value>,
    proposer: &str,
    reward_abs: f64,
    current_supply_sat: i64,
    max_supply_sat: i64,
) -> PyResult<i64> {
    if proposer.is_empty() || reward_abs <= 0.0 {
        return Ok(0);
    }
    if !reward_abs.is_finite() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "non_finite_block_reward",
        ));
    }
    let mut reward_sat = to_satoshi_inner(&reward_abs.to_string())?;
    if current_supply_sat + reward_sat > max_supply_sat {
        reward_sat = (max_supply_sat - current_supply_sat).max(0);
    }
    if reward_sat <= 0 {
        return Ok(0);
    }
    if !accounts.contains_key(proposer) {
        accounts.insert(proposer.to_string(), empty_account());
    }
    let row = accounts
        .get_mut(proposer)
        .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("missing_proposer"))?;
    let bal = account_balance(row);
    let nonce = account_nonce(row);
    set_account_balance(row, bal + reward_sat, nonce)?;
    Ok(reward_sat)
}

fn accounts_to_json(accounts: &BTreeMap<String, Value>) -> PyResult<String> {
    let mut out = Map::new();
    for (addr, row) in accounts {
        out.insert(addr.clone(), row.clone());
    }
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Apply host effects for a block after Python EVM host mutated storage/code/value.
/// Each effect: fee (+ optional value when apply_value=true) + nonce + reward.
#[pyfunction]
#[pyo3(signature = (
    accounts_json,
    effects_json,
    gas_price_wei,
    burn_rate,
    proposer,
    burn_address,
    block_reward_abs,
    current_supply_sat,
    max_supply_sat
))]
fn blockchain_apply_host_effects(
    accounts_json: String,
    effects_json: String,
    gas_price_wei: f64,
    burn_rate: f64,
    proposer: String,
    burn_address: String,
    block_reward_abs: f64,
    current_supply_sat: i64,
    max_supply_sat: i64,
) -> PyResult<String> {
    let mut accounts = parse_accounts_map(&accounts_json)?;
    let effects: Value = serde_json::from_str(&effects_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let effects = effects
        .as_array()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("effects_json must be an array"))?;
    if effects.len() > MAX_STATE_ENGINE_TXS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_effects: {} > {}",
            effects.len(),
            MAX_STATE_ENGINE_TXS
        )));
    }
    let mut total_burned_sat: i64 = 0;
    for effect in effects {
        total_burned_sat = total_burned_sat.saturating_add(apply_host_fee_effect(
            &mut accounts,
            effect,
            gas_price_wei,
            burn_rate,
            &proposer,
            &burn_address,
        )?);
    }
    let reward_sat = apply_block_reward_sat(
        &mut accounts,
        &proposer,
        block_reward_abs,
        current_supply_sat,
        max_supply_sat,
    )?;
    let mut result = Map::new();
    result.insert(
        "accounts".to_string(),
        serde_json::from_str(&accounts_to_json(&accounts)?)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
    );
    result.insert(
        "total_burned_sat".to_string(),
        Value::Number(total_burned_sat.into()),
    );
    result.insert("reward_sat".to_string(), Value::Number(reward_sat.into()));
    result.insert("evm".to_string(), Value::Bool(true));
    result.insert("native_apply".to_string(), Value::Bool(true));
    result.insert("host_effects".to_string(), Value::Bool(true));
    serde_json::to_string(&Value::Object(result))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Apply one block of simple transfers (+ fee burn + proposer fee + block reward).
/// Rejects any tx with calldata (EVM stays on Python host path).
#[pyfunction]
#[pyo3(signature = (
    accounts_json,
    txs_json,
    gas_price_wei,
    burn_rate,
    proposer,
    burn_address,
    block_reward_abs,
    current_supply_sat,
    max_supply_sat
))]
fn blockchain_apply_simple_block(
    accounts_json: String,
    txs_json: String,
    gas_price_wei: f64,
    burn_rate: f64,
    proposer: String,
    burn_address: String,
    block_reward_abs: f64,
    current_supply_sat: i64,
    max_supply_sat: i64,
) -> PyResult<String> {
    let mut accounts = parse_accounts_map(&accounts_json)?;
    let txs: Value = serde_json::from_str(&txs_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let txs = txs
        .as_array()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("txs_json must be an array"))?;
    if txs.len() > MAX_STATE_ENGINE_TXS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_txs: {} > {}",
            txs.len(),
            MAX_STATE_ENGINE_TXS
        )));
    }
    let mut total_burned_sat: i64 = 0;
    for tx in txs {
        total_burned_sat = total_burned_sat.saturating_add(apply_simple_transfer_with_fees(
            &mut accounts,
            tx,
            gas_price_wei,
            burn_rate,
            &proposer,
            &burn_address,
        )?);
    }
    let reward_sat = apply_block_reward_sat(
        &mut accounts,
        &proposer,
        block_reward_abs,
        current_supply_sat,
        max_supply_sat,
    )?;
    let mut result = Map::new();
    result.insert(
        "accounts".to_string(),
        serde_json::from_str(&accounts_to_json(&accounts)?)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
    );
    result.insert(
        "total_burned_sat".to_string(),
        Value::Number(total_burned_sat.into()),
    );
    result.insert("reward_sat".to_string(), Value::Number(reward_sat.into()));
    result.insert("evm".to_string(), Value::Bool(false));
    result.insert("native_apply".to_string(), Value::Bool(true));
    serde_json::to_string(&Value::Object(result))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Replay multiple simple blocks from an account snapshot (reorg/tip-repair assist).
#[pyfunction]
#[pyo3(signature = (
    accounts_json,
    blocks_json,
    gas_price_wei,
    burn_rate,
    burn_address,
    block_reward_abs,
    current_supply_sat,
    max_supply_sat
))]
fn blockchain_replay_simple_blocks(
    accounts_json: String,
    blocks_json: String,
    gas_price_wei: f64,
    burn_rate: f64,
    burn_address: String,
    block_reward_abs: f64,
    current_supply_sat: i64,
    max_supply_sat: i64,
) -> PyResult<String> {
    let mut accounts = parse_accounts_map(&accounts_json)?;
    let blocks: Value = serde_json::from_str(&blocks_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let blocks = blocks
        .as_array()
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("blocks_json must be an array"))?;
    if blocks.len() > MAX_STATE_ENGINE_TXS {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "too_many_blocks: {} > {}",
            blocks.len(),
            MAX_STATE_ENGINE_TXS
        )));
    }
    let mut supply = current_supply_sat;
    let mut total_burned_sat: i64 = 0;
    let mut blocks_applied: i64 = 0;
    for block in blocks {
        let obj = block
            .as_object()
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("block must be object"))?;
        let proposer = obj
            .get("miner")
            .or_else(|| obj.get("proposer"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let txs = obj
            .get("transactions")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        if txs.len() > MAX_STATE_ENGINE_TXS {
            return Err(pyo3::exceptions::PyValueError::new_err("too_many_txs"));
        }
        for tx in &txs {
            total_burned_sat = total_burned_sat.saturating_add(apply_simple_transfer_with_fees(
                &mut accounts,
                tx,
                gas_price_wei,
                burn_rate,
                &proposer,
                &burn_address,
            )?);
        }
        let reward = apply_block_reward_sat(
            &mut accounts,
            &proposer,
            block_reward_abs,
            supply,
            max_supply_sat,
        )?;
        supply = supply.saturating_add(reward);
        blocks_applied += 1;
    }
    let mut result = Map::new();
    result.insert(
        "accounts".to_string(),
        serde_json::from_str(&accounts_to_json(&accounts)?)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
    );
    result.insert(
        "total_burned_sat".to_string(),
        Value::Number(total_burned_sat.into()),
    );
    result.insert(
        "current_supply_sat".to_string(),
        Value::Number(supply.into()),
    );
    result.insert(
        "blocks_applied".to_string(),
        Value::Number(blocks_applied.into()),
    );
    result.insert("native_replay".to_string(), Value::Bool(true));
    serde_json::to_string(&Value::Object(result))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(amount_to_satoshi, m)?)?;
    m.add_function(wrap_pyfunction!(amount_apply_delta_satoshi, m)?)?;
    m.add_function(wrap_pyfunction!(amount_from_satoshi_float, m)?)?;
    m.add_function(wrap_pyfunction!(plan_transfer_fees, m)?)?;
    m.add_function(wrap_pyfunction!(plan_transfer_fees_satoshi, m)?)?;
    m.add_function(wrap_pyfunction!(can_afford_transfer, m)?)?;
    m.add_function(wrap_pyfunction!(state_engine_apply_transactions, m)?)?;
    m.add_function(wrap_pyfunction!(blockchain_apply_simple_block, m)?)?;
    m.add_function(wrap_pyfunction!(blockchain_apply_host_effects, m)?)?;
    m.add_function(wrap_pyfunction!(blockchain_replay_simple_blocks, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn to_satoshi_floors() {
        assert_eq!(to_satoshi_inner("1").unwrap(), 1_000_000);
        assert_eq!(to_satoshi_inner("0.0000001").unwrap(), 0);
        assert_eq!(to_satoshi_inner("1.9999999").unwrap(), 1_999_999);
    }

    #[test]
    fn apply_delta_never_negative() {
        assert_eq!(
            apply_delta_satoshi_inner(1_000_000, "-0.25").unwrap(),
            750_000
        );
        assert_eq!(apply_delta_satoshi_inner(100, "-1").unwrap(), 0);
    }

    #[test]
    fn plan_transfer_fees_splits_burn() {
        let (fee, burned, miner, total) =
            plan_transfer_fees(21_000, 0.000_000_1, 0.02, 1.0, None).unwrap();
        assert!((fee - 0.0021).abs() < 1e-12);
        assert!((burned - fee * 0.02).abs() < 1e-15);
        assert!((miner - (fee - burned)).abs() < 1e-15);
        assert!((total - (1.0 + fee)).abs() < 1e-15);
    }

    #[test]
    fn plan_transfer_fees_satoshi_decimal_path() {
        let (fee, burned, miner, total) =
            plan_transfer_fees_satoshi_inner(21_000, "0.0000001", "0.02", "1.0", None).unwrap();
        assert_eq!(fee, 2100);
        assert_eq!(burned, 42);
        assert_eq!(miner, 2058);
        assert_eq!(total, 1_000_000 + 2100);
    }

    #[test]
    fn refuse_float_amount_satoshi() {
        let tx = serde_json::json!({
            "from": "a",
            "to": "b",
            "amount_satoshi": 1.5,
            "fee": 0,
            "nonce": 0
        });
        assert!(tx_amount_sat(&tx).is_err());
    }
}
