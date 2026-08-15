//! Nested CALL / CREATE writeback planners + native apply (v1.3.59–v1.3.61).
//!
//! Plans concrete persist ops and applies them to an in-memory accounts map.
//! Python DB still commits rows — not in-process Rocks in the EVM runner.

use pyo3::prelude::*;
use serde_json::{Map, Number, Value};

fn normalize_kind(kind: &str) -> PyResult<String> {
    let kind = kind.trim().to_ascii_lowercase();
    match kind.as_str() {
        "call" | "callcode" | "delegatecall" | "staticcall" => Ok(kind),
        _ => Err(pyo3::exceptions::PyValueError::new_err(
            "kind must be call|callcode|delegatecall|staticcall",
        )),
    }
}

fn storage_object_from_json(raw: Option<&str>) -> Value {
    let Some(text) = raw else {
        return Value::Object(Map::new());
    };
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Value::Object(Map::new());
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(Value::Object(map)) => {
            let mut out = Map::new();
            for (k, v) in map {
                // Canonicalize keys as decimal strings for DB update_account_storage.
                let key = if let Ok(n) = k.parse::<i128>() {
                    n.to_string()
                } else if let Some(hex) = k.strip_prefix("0x").or_else(|| k.strip_prefix("0X")) {
                    match i128::from_str_radix(hex, 16) {
                        Ok(n) => n.to_string(),
                        Err(_) => k,
                    }
                } else {
                    k
                };
                let val = match v {
                    Value::Number(n) => Value::Number(n),
                    Value::String(s) => {
                        if let Ok(n) = s.parse::<i64>() {
                            Value::Number(n.into())
                        } else {
                            Value::String(s)
                        }
                    }
                    other => other,
                };
                out.insert(key, val);
            }
            Value::Object(out)
        }
        Ok(other) => other,
        Err(_) => Value::Object(Map::new()),
    }
}

fn logs_array_from_json(raw: Option<&str>) -> Value {
    let Some(text) = raw else {
        return Value::Array(vec![]);
    };
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Value::Array(vec![]);
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(Value::Array(arr)) => Value::Array(arr),
        _ => Value::Array(vec![]),
    }
}

/// Plan nested CALL writeback as concrete ops with resolved addresses.
#[pyfunction]
#[pyo3(name = "evm_plan_nested_call_writeback")]
#[pyo3(signature = (kind, parent_read_only, caller, target, value_wei, success, storage_json=None, logs_json=None))]
pub fn evm_plan_nested_call_writeback_py(
    kind: String,
    parent_read_only: bool,
    caller: String,
    target: String,
    value_wei: i64,
    success: bool,
    storage_json: Option<String>,
    logs_json: Option<String>,
) -> PyResult<String> {
    let kind = normalize_kind(&kind)?;
    let value_wei = value_wei.max(0);
    let caller = caller.trim().to_string();
    let target = target.trim().to_string();
    let nested_read_only = parent_read_only || kind == "staticcall";
    let mut persist_storage = false;
    let mut persist_value = false;
    let mut persist_logs = false;
    let storage_owner = if kind == "delegatecall" || kind == "callcode" {
        "caller"
    } else {
        "target"
    };
    let exec_address = storage_owner;
    let mut value_from = "";
    let mut value_to = "";
    let mut effective_value_wei: i64 = 0;
    let reject_create = nested_read_only;

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
    }

    let storage_addr = if storage_owner == "caller" {
        caller.clone()
    } else {
        target.clone()
    };
    let mut ops: Vec<Value> = Vec::new();
    if persist_storage {
        let mut op = Map::new();
        op.insert("op".into(), Value::String("set_storage".into()));
        op.insert("address".into(), Value::String(storage_addr));
        op.insert(
            "storage".into(),
            storage_object_from_json(storage_json.as_deref()),
        );
        ops.push(Value::Object(op));
    }
    if persist_value && effective_value_wei > 0 {
        let from_addr = if value_from == "caller" {
            caller.clone()
        } else {
            target.clone()
        };
        let to_addr = if value_to == "target" {
            target.clone()
        } else {
            caller.clone()
        };
        let mut op = Map::new();
        op.insert("op".into(), Value::String("transfer_value".into()));
        op.insert("from".into(), Value::String(from_addr));
        op.insert("to".into(), Value::String(to_addr));
        op.insert(
            "value_wei".into(),
            Value::Number(Number::from(effective_value_wei)),
        );
        ops.push(Value::Object(op));
    }
    if persist_logs {
        let logs = logs_array_from_json(logs_json.as_deref());
        if matches!(&logs, Value::Array(a) if !a.is_empty()) {
            let mut op = Map::new();
            op.insert("op".into(), Value::String("append_logs".into()));
            // Absolute nested logs are attributed to the caller frame address.
            op.insert("address".into(), Value::String(caller.clone()));
            op.insert("logs".into(), logs);
            ops.push(Value::Object(op));
        }
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
        Value::Number(Number::from(effective_value_wei)),
    );
    out.insert("reject_create".into(), Value::Bool(reject_create));
    out.insert("success".into(), Value::Bool(success));
    out.insert("ops".into(), Value::Array(ops));
    out.insert("native_writeback".into(), Value::Bool(true));
    out.insert("native_plan".into(), Value::Bool(true));
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Plan CREATE/CREATE2 writeback as concrete ops (v1.3.60).
/// Address is already computed by the adapter; this only plans persist ops.
#[pyfunction]
#[pyo3(name = "evm_plan_create_writeback")]
#[pyo3(signature = (deployer, contract_address, value_wei, success, code_hex=None, storage_json=None))]
pub fn evm_plan_create_writeback_py(
    deployer: String,
    contract_address: String,
    value_wei: i64,
    success: bool,
    code_hex: Option<String>,
    storage_json: Option<String>,
) -> PyResult<String> {
    let deployer = deployer.trim().to_string();
    let contract_address = contract_address.trim().to_string();
    let value_wei = value_wei.max(0);
    let mut ops: Vec<Value> = Vec::new();

    if success && !contract_address.is_empty() {
        let code = code_hex.unwrap_or_default();
        let storage = storage_object_from_json(storage_json.as_deref());
        let storage_str = match &storage {
            Value::Object(_) => serde_json::to_string(&storage).unwrap_or_else(|_| "{}".into()),
            _ => "{}".into(),
        };
        let mut save = Map::new();
        save.insert("op".into(), Value::String("save_account".into()));
        save.insert("address".into(), Value::String(contract_address.clone()));
        // Balance starts at 0; value transfer is a separate op (no double-credit).
        save.insert("balance".into(), Value::Number(Number::from(0)));
        save.insert("nonce".into(), Value::Number(Number::from(0u64)));
        save.insert("code".into(), Value::String(code));
        save.insert("storage".into(), Value::String(storage_str));
        ops.push(Value::Object(save));

        if value_wei > 0 && !deployer.is_empty() {
            let mut xfer = Map::new();
            xfer.insert("op".into(), Value::String("transfer_value".into()));
            xfer.insert("from".into(), Value::String(deployer.clone()));
            xfer.insert("to".into(), Value::String(contract_address.clone()));
            xfer.insert("value_wei".into(), Value::Number(Number::from(value_wei)));
            ops.push(Value::Object(xfer));
        }
    }

    let mut out = Map::new();
    out.insert("deployer".into(), Value::String(deployer));
    out.insert("address".into(), Value::String(contract_address));
    out.insert("value_wei".into(), Value::Number(Number::from(value_wei)));
    out.insert("success".into(), Value::Bool(success));
    out.insert("reverted".into(), Value::Bool(!success));
    out.insert("ops".into(), Value::Array(ops));
    out.insert("native_create_writeback".into(), Value::Bool(true));
    out.insert("native_plan".into(), Value::Bool(true));
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

fn ensure_account_obj<'a>(
    accounts: &'a mut Map<String, Value>,
    address: &str,
) -> &'a mut Map<String, Value> {
    if !accounts.contains_key(address) {
        let mut row = Map::new();
        row.insert("address".into(), Value::String(address.to_string()));
        row.insert("balance_satoshi".into(), Value::Number(Number::from(0i64)));
        row.insert("balance".into(), Value::Number(Number::from(0)));
        row.insert("nonce".into(), Value::Number(Number::from(0u64)));
        row.insert("code".into(), Value::String(String::new()));
        row.insert("storage".into(), Value::String("{}".into()));
        accounts.insert(address.to_string(), Value::Object(row));
    }
    accounts
        .get_mut(address)
        .and_then(|v| v.as_object_mut())
        .expect("account object")
}

fn account_satoshi(row: &Map<String, Value>) -> i64 {
    row.get("balance_satoshi")
        .and_then(|v| v.as_i64())
        .or_else(|| {
            row.get("balance").and_then(|v| match v {
                Value::Number(n) => n.as_f64().map(|f| (f * 1_000_000.0) as i64),
                Value::String(s) => crate::amount::to_satoshi_inner(s).ok(),
                _ => None,
            })
        })
        .unwrap_or(0)
        .max(0)
}

fn wei_to_satoshi(value_wei: i64) -> i64 {
    // 1 ABS = 1e18 wei = 1e6 satoshi ⇒ sat = wei / 1e12
    (value_wei.max(0) as i128 / 1_000_000_000_000i128) as i64
}

fn set_balance_sat(row: &mut Map<String, Value>, sat: i64) {
    let sat = sat.max(0);
    row.insert("balance_satoshi".into(), Value::Number(Number::from(sat)));
    let bal = (sat as f64) / 1_000_000.0;
    row.insert("balance".into(), serde_json::json!(bal));
}

/// Apply writeback ops to an in-memory accounts map (v1.3.61).
/// Python DB still commits the returned account rows.
#[pyfunction]
#[pyo3(name = "evm_apply_writeback_ops")]
pub fn evm_apply_writeback_ops_py(accounts_json: String, ops_json: String) -> PyResult<String> {
    let mut accounts: Map<String, Value> = match serde_json::from_str(&accounts_json) {
        Ok(Value::Object(map)) => map,
        Ok(_) => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "accounts_json must be an object",
            ))
        }
        Err(e) => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "accounts_json invalid: {e}"
            )))
        }
    };
    let ops: Vec<Value> = match serde_json::from_str(&ops_json) {
        Ok(Value::Array(arr)) => arr,
        Ok(_) => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "ops_json must be an array",
            ))
        }
        Err(e) => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "ops_json invalid: {e}"
            )))
        }
    };

    let mut log_batches: Vec<Value> = Vec::new();
    let mut applied = 0usize;
    let mut touched: Vec<String> = Vec::new();

    for op_val in ops {
        let Some(op) = op_val.as_object() else {
            continue;
        };
        let kind = op
            .get("op")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        match kind.as_str() {
            "set_storage" => {
                let addr = op
                    .get("address")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim()
                    .to_string();
                if addr.is_empty() {
                    continue;
                }
                let storage = op
                    .get("storage")
                    .cloned()
                    .unwrap_or(Value::Object(Map::new()));
                let storage_str = match &storage {
                    Value::Object(_) => {
                        serde_json::to_string(&storage).unwrap_or_else(|_| "{}".into())
                    }
                    Value::String(s) => s.clone(),
                    _ => "{}".into(),
                };
                let row = ensure_account_obj(&mut accounts, &addr);
                row.insert("storage".into(), Value::String(storage_str));
                if !touched.contains(&addr) {
                    touched.push(addr);
                }
                applied += 1;
            }
            "save_account" => {
                let addr = op
                    .get("address")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim()
                    .to_string();
                if addr.is_empty() {
                    continue;
                }
                let code = op
                    .get("code")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let nonce = op.get("nonce").and_then(|v| v.as_u64()).unwrap_or(0);
                let storage = match op.get("storage") {
                    Some(Value::String(s)) => s.clone(),
                    Some(Value::Object(m)) => {
                        serde_json::to_string(m).unwrap_or_else(|_| "{}".into())
                    }
                    _ => "{}".into(),
                };
                let bal_sat = op
                    .get("balance_satoshi")
                    .and_then(|v| v.as_i64())
                    .or_else(|| {
                        op.get("balance").and_then(|v| match v {
                            Value::Number(n) => n.as_f64().map(|f| (f * 1_000_000.0) as i64),
                            _ => None,
                        })
                    })
                    .unwrap_or(0)
                    .max(0);
                let row = ensure_account_obj(&mut accounts, &addr);
                row.insert("code".into(), Value::String(code));
                row.insert("nonce".into(), Value::Number(Number::from(nonce)));
                row.insert("storage".into(), Value::String(storage));
                set_balance_sat(row, bal_sat);
                if !touched.contains(&addr) {
                    touched.push(addr);
                }
                applied += 1;
            }
            "transfer_value" => {
                let from = op
                    .get("from")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim()
                    .to_string();
                let to = op
                    .get("to")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim()
                    .to_string();
                let value_wei = op
                    .get("value_wei")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0)
                    .max(0);
                if from.is_empty() || to.is_empty() || value_wei == 0 {
                    continue;
                }
                let sat = wei_to_satoshi(value_wei);
                if sat == 0 {
                    // Sub-satoshi wei dust: still count as applied no-op for honesty.
                    applied += 1;
                    continue;
                }
                {
                    let row = ensure_account_obj(&mut accounts, &from);
                    let cur = account_satoshi(row);
                    if cur < sat {
                        return Err(pyo3::exceptions::PyValueError::new_err(
                            "insufficient_writeback_value",
                        ));
                    }
                    set_balance_sat(row, cur - sat);
                }
                {
                    let row = ensure_account_obj(&mut accounts, &to);
                    let cur = account_satoshi(row);
                    set_balance_sat(row, cur.saturating_add(sat));
                }
                if !touched.contains(&from) {
                    touched.push(from);
                }
                if !touched.contains(&to) {
                    touched.push(to);
                }
                applied += 1;
            }
            "append_logs" => {
                let addr = op
                    .get("address")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let logs = op.get("logs").cloned().unwrap_or(Value::Array(vec![]));
                if matches!(&logs, Value::Array(a) if !a.is_empty()) {
                    let mut batch = Map::new();
                    batch.insert("address".into(), Value::String(addr));
                    batch.insert("logs".into(), logs);
                    log_batches.push(Value::Object(batch));
                    applied += 1;
                }
            }
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unsupported_writeback_op:{kind}"
                )));
            }
        }
    }

    let mut out_accounts = Map::new();
    for addr in &touched {
        if let Some(row) = accounts.get(addr) {
            out_accounts.insert(addr.clone(), row.clone());
        }
    }

    let mut out = Map::new();
    out.insert("accounts".into(), Value::Object(out_accounts));
    out.insert("log_batches".into(), Value::Array(log_batches));
    out.insert(
        "applied".into(),
        Value::Number(Number::from(applied as u64)),
    );
    out.insert(
        "touched".into(),
        Value::Array(touched.into_iter().map(Value::String).collect()),
    );
    out.insert("native_apply".into(), Value::Bool(true));
    serde_json::to_string(&Value::Object(out))
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(evm_plan_nested_call_writeback_py, m)?)?;
    m.add_function(wrap_pyfunction!(evm_plan_create_writeback_py, m)?)?;
    m.add_function(wrap_pyfunction!(evm_apply_writeback_ops_py, m)?)?;
    Ok(())
}
