use primitive_types::U256;
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyList};
use std::collections::HashMap;

use crate::{
    evm_calldataload_inner, evm_is_jumpdest_inner, evm_keccak256_memory_inner,
    evm_memory_read_word_inner, evm_memory_slice_inner, evm_read_push_inner, evm_u256_addmod_inner,
    evm_u256_exp_inner, evm_u256_mulmod_inner, evm_u256_sar_inner, evm_u256_sdiv_inner,
    evm_u256_signextend_inner, evm_u256_slt_inner, evm_u256_smod_inner, keccak256_digest_bytes,
    u256_from_be32, u256_to_be32,
};

const U256_MASK: U256 = U256::MAX;
const MAX_PURE_STEPS: usize = 8192;
const MAX_FULL_STEPS: usize = 10_000_000;

pub fn evm_opcode_is_bridge(op: u8) -> bool {
    matches!(op, 0x31 | 0x3B | 0x3C | 0x3F | 0x40)
}

pub fn evm_opcode_is_host(op: u8) -> bool {
    matches!(op, 0xF0 | 0xF1 | 0xF2 | 0xF4 | 0xF5 | 0xFA | 0xFF) || (0xA0..=0xA4).contains(&op)
}

/// True when bytecode has no recursive host ops (CALL/CREATE/LOG/SELFDESTRUCT).
/// Bridge ops (BALANCE/EXTCODE*/BLOCKHASH) are allowed — same gate as Python.
pub fn bytecode_is_nested_native_eligible(bytecode: &[u8]) -> bool {
    let mut pc = 0usize;
    while pc < bytecode.len() {
        let op = bytecode[pc];
        if evm_opcode_is_host(op) {
            return false;
        }
        if (0x60..=0x7F).contains(&op) {
            pc = pc.saturating_add(1 + (op as usize - 0x5F));
        } else {
            pc += 1;
        }
    }
    true
}

/// v1.3.75: allow CALL*/LOG inside an in-Rust frame; reject CREATE/SELFDESTRUCT.
pub fn bytecode_is_inline_call_frame_eligible(bytecode: &[u8]) -> bool {
    let mut pc = 0usize;
    while pc < bytecode.len() {
        let op = bytecode[pc];
        if matches!(op, 0xF0 | 0xF5 | 0xFF) {
            return false;
        }
        if (0x60..=0x7F).contains(&op) {
            pc = pc.saturating_add(1 + (op as usize - 0x5F));
        } else {
            pc += 1;
        }
    }
    true
}

const MAX_INLINE_CALL_DEPTH: usize = 4; // v1.3.75 multi-depth value=0 CALL frames

fn get_inline_depth(host_context: Option<&Bound<'_, PyDict>>) -> usize {
    let Some(ctx) = host_context else {
        return 0;
    };
    match ctx.get_item("_abs_inline_depth") {
        Ok(Some(v)) => v.extract::<usize>().unwrap_or(0),
        _ => 0,
    }
}

fn set_inline_depth(host_context: Option<&Bound<'_, PyDict>>, depth: usize) -> PyResult<()> {
    let Some(ctx) = host_context else {
        return Ok(());
    };
    ctx.set_item("_abs_inline_depth", depth)?;
    Ok(())
}

fn dict_flag(ctx: &Bound<'_, PyDict>, key: &str) -> bool {
    match ctx.get_item(key) {
        Ok(Some(v)) => v.is_truthy().unwrap_or(false),
        _ => false,
    }
}

/// Sticky STATICCALL / eth_call read-only: parent `_abs_read_only` or nested inline flag.
fn get_inline_read_only(host_context: Option<&Bound<'_, PyDict>>) -> bool {
    let Some(ctx) = host_context else {
        return false;
    };
    dict_flag(ctx, "_abs_inline_read_only") || dict_flag(ctx, "_abs_read_only")
}

fn set_inline_read_only(host_context: Option<&Bound<'_, PyDict>>, read_only: bool) -> PyResult<()> {
    let Some(ctx) = host_context else {
        return Ok(());
    };
    ctx.set_item("_abs_inline_read_only", read_only)?;
    Ok(())
}

fn refuse_static_write(read_only: bool, reverted: &mut bool, running: &mut bool) -> bool {
    if !read_only {
        return false;
    }
    *reverted = true;
    *running = false;
    true
}

fn opcode_stops_segment(
    op: u8,
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
) -> bool {
    // v1.3.57: LOG0–LOG4 always handled in Rust (no Python apply_host_op).
    if (0xA0..=0xA4).contains(&op) {
        return false;
    }
    if evm_opcode_is_host(op) {
        return !host_opcode_available(op, host_context, host_bridge);
    }
    if evm_opcode_is_bridge(op) {
        return !bridge_opcode_available(host_context, host_bridge);
    }
    false
}

fn bridge_state_has_codes(host_context: Option<&Bound<'_, PyDict>>) -> bool {
    let Some(state) = bridge_state_dict(host_context) else {
        return false;
    };
    matches!(state.get_item("codes"), Ok(Some(_)))
}

fn host_opcode_available(
    op: u8,
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
) -> bool {
    if bridge_supports_runtime(host_bridge) {
        return true;
    }
    match op {
        0xF1 | 0xF2 | 0xF4 | 0xFA => hook_contract_call(host_context).is_some(),
        0xF0 | 0xF5 => {
            hook_contract_create(host_context).is_some() || bridge_state_has_codes(host_context)
        }
        0xFF => hook_selfdestruct(host_context).is_some(),
        _ => false,
    }
}

fn bridge_supports_inline(host_context: Option<&Bound<'_, PyDict>>) -> bool {
    let Some(ctx) = host_context else {
        return false;
    };
    if let Ok(Some(state)) = ctx.get_item("bridge_state") {
        if state.downcast::<PyDict>().is_ok() {
            return true;
        }
    }
    if let Ok(Some(hooks)) = ctx.get_item("bridge_hooks") {
        if let Ok(dict) = hooks.downcast::<PyDict>() {
            return dict.len() > 0;
        }
    }
    false
}

fn bridge_opcode_available(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
) -> bool {
    host_bridge.is_some() || bridge_supports_inline(host_context)
}

fn bridge_supports_runtime(host_bridge: Option<&Bound<'_, PyAny>>) -> bool {
    host_bridge
        .map(|bridge| bridge.hasattr("apply_host_op").unwrap_or(false))
        .unwrap_or(false)
}

fn apply_runtime_host_op(
    py: Python<'_>,
    bridge: &Bound<'_, PyAny>,
    op: u8,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    gas_limit: u64,
    gas_used: &mut u64,
    storage: Option<&Bound<'_, PyDict>>,
    return_data: &mut Vec<u8>,
    running: &mut bool,
    reverted: &mut bool,
) -> PyResult<()> {
    let stack_list = stack_to_pylist(py, stack)?;
    let memory_ba = PyByteArray::new_bound(py, memory);
    let storage_obj: PyObject = match storage {
        Some(dict) => dict.clone().unbind().into(),
        None => PyDict::new_bound(py).into(),
    };
    let out = bridge.call_method1(
        "apply_host_op",
        (
            op,
            stack_list,
            memory_ba,
            gas_limit,
            *gas_used,
            storage_obj,
            return_data.as_slice(),
        ),
    )?;
    let out_dict = out.downcast::<PyDict>()?;
    *gas_used = out_dict.get_item("gas_used")?.unwrap().extract()?;
    *memory = out_dict.get_item("memory")?.unwrap().extract::<Vec<u8>>()?;
    let stack_any = out_dict.get_item("stack")?.unwrap();
    let stack_list = stack_any.downcast::<PyList>()?;
    *stack = stack_from_py(stack_list)?;
    *return_data = out_dict
        .get_item("return_data")?
        .unwrap()
        .extract::<Vec<u8>>()?;
    *running = out_dict.get_item("running")?.unwrap().extract()?;
    *reverted = out_dict.get_item("reverted")?.unwrap().extract()?;
    Ok(())
}

struct EvmStaticContext {
    address: U256,
    caller: U256,
    origin: U256,
    value: U256,
    timestamp: U256,
    block_number: U256,
    chain_id: U256,
    base_fee: U256,
    gas_price: U256,
    difficulty: U256,
    coinbase: U256,
    blob_base_fee: U256,
    blob_hashes: Vec<U256>,
}

fn parse_static_context(host_context: Option<&Bound<'_, PyDict>>) -> PyResult<EvmStaticContext> {
    let Some(ctx) = host_context else {
        return Ok(EvmStaticContext {
            address: U256::zero(),
            caller: U256::zero(),
            origin: U256::zero(),
            value: U256::zero(),
            timestamp: U256::zero(),
            block_number: U256::zero(),
            chain_id: U256::zero(),
            base_fee: U256::zero(),
            gas_price: U256::zero(),
            difficulty: U256::zero(),
            coinbase: U256::zero(),
            blob_base_fee: U256::zero(),
            blob_hashes: Vec::new(),
        });
    };
    Ok(EvmStaticContext {
        address: dict_get_u256(ctx, "address")?,
        caller: dict_get_u256(ctx, "caller")?,
        origin: dict_get_u256(ctx, "origin")?,
        value: dict_get_u256(ctx, "value")?,
        timestamp: dict_get_u256(ctx, "timestamp")?,
        block_number: dict_get_u256(ctx, "block_number")?,
        chain_id: dict_get_u256(ctx, "chain_id")?,
        base_fee: dict_get_u256(ctx, "base_fee")?,
        gas_price: dict_get_u256(ctx, "gas_price")?,
        difficulty: dict_get_u256(ctx, "difficulty")?,
        coinbase: dict_get_u256(ctx, "coinbase")?,
        blob_base_fee: dict_get_u256(ctx, "blob_base_fee")?,
        blob_hashes: dict_get_u256_list(ctx, "blob_hashes")?,
    })
}

fn dict_get_u256_list(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<U256>> {
    match dict.get_item(key)? {
        Some(value) => {
            let items: Vec<Bound<'_, PyAny>> = value.extract()?;
            items.into_iter().map(py_to_u256).collect()
        }
        None => Ok(Vec::new()),
    }
}

fn py_to_u256(obj: Bound<'_, PyAny>) -> PyResult<U256> {
    let bytes_obj = obj.call_method1("to_bytes", (32, "big"))?;
    let bytes: Vec<u8> = bytes_obj.extract()?;
    let mut buf = [0u8; 32];
    let start = 32usize.saturating_sub(bytes.len());
    buf[start..].copy_from_slice(&bytes);
    Ok(U256::from_big_endian(&buf))
}

fn dict_get_u256(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<U256> {
    match dict.get_item(key)? {
        Some(value) => py_to_u256(value),
        None => Ok(U256::zero()),
    }
}

fn u256_to_py_int(py: Python<'_>, value: U256) -> PyResult<PyObject> {
    let builtins = py.import_bound("builtins")?;
    let int_cls = builtins.getattr("int")?;
    let bytes = u256_to_be32(value);
    Ok(int_cls
        .call_method1("from_bytes", (bytes.as_slice(), "big"))?
        .into())
}

fn storage_load(arena: &HashMap<U256, U256>, key: U256) -> U256 {
    arena.get(&key).copied().unwrap_or_else(U256::zero)
}

fn storage_store(arena: &mut HashMap<U256, U256>, key: U256, value: U256) {
    if value.is_zero() {
        arena.remove(&key);
    } else {
        arena.insert(key, value);
    }
}

fn snapshot_storage_dict(
    storage: Option<&Bound<'_, PyDict>>,
) -> PyResult<Option<HashMap<U256, U256>>> {
    let Some(dict) = storage else {
        return Ok(None);
    };
    let mut map = HashMap::new();
    for (key, value) in dict.iter() {
        let k = py_to_u256(key)?;
        let v = py_to_u256(value)?;
        if !v.is_zero() {
            map.insert(k, v);
        }
    }
    Ok(Some(map))
}

fn restore_storage_dict(
    storage: Option<&Bound<'_, PyDict>>,
    snap: &HashMap<U256, U256>,
) -> PyResult<()> {
    let Some(dict) = storage else {
        return Ok(());
    };
    dict.clear();
    let py = dict.py();
    for (key, value) in snap {
        if value.is_zero() {
            continue;
        }
        dict.set_item(u256_to_py_int(py, *key)?, u256_to_py_int(py, *value)?)?;
    }
    Ok(())
}

fn abort_restore_host_storage(
    storage: Option<&Bound<'_, PyDict>>,
    snap: &Option<HashMap<U256, U256>>,
    arena: &mut HashMap<U256, U256>,
    transient: &mut HashMap<U256, U256>,
) -> PyResult<()> {
    if let Some(map) = snap {
        *arena = map.clone();
        restore_storage_dict(storage, map)?;
    }
    transient.clear();
    Ok(())
}

fn word_to_address(word: U256) -> String {
    let mask = (U256::one() << 160) - U256::one();
    format!("0x{:040x}", word & mask)
}

fn py_to_u256_or_int(obj: Bound<'_, PyAny>) -> PyResult<U256> {
    if let Ok(v) = obj.extract::<u64>() {
        return Ok(U256::from(v));
    }
    py_to_u256(obj)
}

fn bridge_balance(bridge: &Bound<'_, PyAny>, who: U256) -> PyResult<U256> {
    let addr = word_to_address(who);
    let result = bridge.call_method1("balance", (addr,))?;
    py_to_u256_or_int(result)
}

fn bridge_code_size(bridge: &Bound<'_, PyAny>, who: U256) -> PyResult<U256> {
    let addr = word_to_address(who);
    let result = bridge.call_method1("code_size", (addr,))?;
    py_to_u256_or_int(result)
}

fn bridge_code_copy(
    bridge: &Bound<'_, PyAny>,
    who: U256,
    code_offset: usize,
    size: usize,
) -> PyResult<Vec<u8>> {
    let addr = word_to_address(who);
    let result = bridge.call_method1("code_copy", (addr, code_offset, size))?;
    result.extract::<Vec<u8>>()
}

fn bridge_block_hash(bridge: &Bound<'_, PyAny>, block_num: U256) -> PyResult<U256> {
    let result = bridge.call_method1("block_hash", (block_num.as_u64(),))?;
    py_to_u256_or_int(result)
}

fn bridge_state_dict<'py>(host_context: Option<&Bound<'py, PyDict>>) -> Option<Bound<'py, PyDict>> {
    let ctx = host_context?;
    let state = ctx.get_item("bridge_state").ok()??;
    state.downcast::<PyDict>().ok().cloned()
}

fn bridge_hooks_dict<'py>(host_context: Option<&Bound<'py, PyDict>>) -> Option<Bound<'py, PyDict>> {
    let ctx = host_context?;
    let hooks = ctx.get_item("bridge_hooks").ok()??;
    hooks.downcast::<PyDict>().ok().cloned()
}

fn inline_balance(host_context: Option<&Bound<'_, PyDict>>, who: U256) -> Option<PyResult<U256>> {
    let state = bridge_state_dict(host_context)?;
    let balances = state.get_item("balances").ok()??;
    let dict = balances.downcast::<PyDict>().ok()?;
    let addr = word_to_address(who);
    let value = dict.get_item(addr.as_str()).ok()??;
    Some(py_to_u256_or_int(value))
}

fn inline_code_bytes(
    host_context: Option<&Bound<'_, PyDict>>,
    who: U256,
) -> Option<PyResult<Vec<u8>>> {
    let state = bridge_state_dict(host_context)?;
    let codes = state.get_item("codes").ok()??;
    let dict = codes.downcast::<PyDict>().ok()?;
    let addr = word_to_address(who);
    let value = dict.get_item(addr.as_str()).ok()??;
    Some(value.extract::<Vec<u8>>())
}

fn inline_block_hash(
    host_context: Option<&Bound<'_, PyDict>>,
    block_num: U256,
) -> Option<PyResult<U256>> {
    let state = bridge_state_dict(host_context)?;
    let hashes = state.get_item("block_hashes").ok()??;
    let dict = hashes.downcast::<PyDict>().ok()?;
    let block_key = block_num.as_u64();
    let value = dict
        .get_item(block_key)
        .ok()
        .flatten()
        .or_else(|| dict.get_item(block_key.to_string()).ok().flatten())?;
    Some(py_to_u256_or_int(value))
}

fn hook_balance(host_context: Option<&Bound<'_, PyDict>>, who: U256) -> Option<PyResult<U256>> {
    let hooks = bridge_hooks_dict(host_context)?;
    let func = hooks.get_item("balance").ok()??;
    let addr = word_to_address(who);
    Some(
        func.call1((addr,))
            .and_then(|value| py_to_u256_or_int(value)),
    )
}

fn hook_code_size(host_context: Option<&Bound<'_, PyDict>>, who: U256) -> Option<PyResult<U256>> {
    let hooks = bridge_hooks_dict(host_context)?;
    let func = hooks.get_item("code_size").ok()??;
    let addr = word_to_address(who);
    Some(
        func.call1((addr,))
            .and_then(|value| py_to_u256_or_int(value)),
    )
}

fn hook_code_copy(
    host_context: Option<&Bound<'_, PyDict>>,
    who: U256,
    code_offset: usize,
    size: usize,
) -> Option<PyResult<Vec<u8>>> {
    let hooks = bridge_hooks_dict(host_context)?;
    let func = hooks.get_item("code_copy").ok()??;
    let addr = word_to_address(who);
    Some(
        func.call1((addr, code_offset, size))
            .and_then(|value| value.extract::<Vec<u8>>()),
    )
}

fn hook_block_hash(
    host_context: Option<&Bound<'_, PyDict>>,
    block_num: U256,
) -> Option<PyResult<U256>> {
    let hooks = bridge_hooks_dict(host_context)?;
    let func = hooks.get_item("block_hash").ok()??;
    Some(
        func.call1((block_num.as_u64(),))
            .and_then(|value| py_to_u256_or_int(value)),
    )
}

fn hook_emit_log<'py>(host_context: Option<&Bound<'py, PyDict>>) -> Option<Bound<'py, PyAny>> {
    let hooks = bridge_hooks_dict(host_context)?;
    match hooks.get_item("emit_log") {
        Ok(Some(value)) => Some(value),
        _ => None,
    }
}

fn hook_contract_call<'py>(host_context: Option<&Bound<'py, PyDict>>) -> Option<Bound<'py, PyAny>> {
    let hooks = bridge_hooks_dict(host_context)?;
    match hooks.get_item("contract_call") {
        Ok(Some(value)) => Some(value),
        _ => None,
    }
}

fn hook_contract_create<'py>(
    host_context: Option<&Bound<'py, PyDict>>,
) -> Option<Bound<'py, PyAny>> {
    let hooks = bridge_hooks_dict(host_context)?;
    match hooks.get_item("contract_create") {
        Ok(Some(value)) => Some(value),
        _ => None,
    }
}

fn hook_selfdestruct<'py>(host_context: Option<&Bound<'py, PyDict>>) -> Option<Bound<'py, PyAny>> {
    let hooks = bridge_hooks_dict(host_context)?;
    match hooks.get_item("selfdestruct") {
        Ok(Some(value)) => Some(value),
        _ => None,
    }
}

fn log_opcode_gas(n_topics: usize, data_size: usize) -> u64 {
    375 + (n_topics as u64 * 375) + data_size as u64
}

type HostLogEntry = (Vec<String>, Vec<u8>);

fn py_u256_int(py: Python<'_>, word: U256) -> PyResult<Bound<'_, PyAny>> {
    let builtins = py.import_bound("builtins")?;
    let int_cls = builtins.getattr("int")?;
    int_cls.call_method1("from_bytes", (u256_to_be32(word).as_slice(), "big"))
}

fn execute_log_native(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    op: u8,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    gas_used: &mut u64,
    gas_limit: u64,
    host_logs: &mut Vec<HostLogEntry>,
) -> PyResult<()> {
    let n_topics = (op - 0xA0) as usize;
    let mut topics = Vec::with_capacity(n_topics);
    for _ in 0..n_topics {
        topics.push(stack_pop(stack)?);
    }
    topics.reverse();
    let size = stack_pop(stack)?.as_usize();
    let offset = stack_pop(stack)?.as_usize();
    let cost = log_opcode_gas(n_topics, size);
    if let Err(reason) = consume_gas(gas_used, gas_limit, cost) {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(reason));
    }
    mem_extend(memory, offset, size);
    let data = evm_memory_slice_inner(memory, offset, size);
    let topic_hex: Vec<String> = topics.iter().map(|t| format!("0x{:x}", t)).collect();
    host_logs.push((topic_hex, data.clone()));

    if let Some(emit_log) = hook_emit_log(host_context) {
        let topics_list = PyList::empty_bound(py);
        for topic in topics {
            topics_list.append(py_u256_int(py, topic)?)?;
        }
        emit_log.call1((n_topics, topics_list, data))?;
    }
    Ok(())
}

fn plan_nested_call_gas(remaining: u64, requested: u64, value_wei: i64, kind: &str) -> u64 {
    let base_cap = if requested == 0 {
        remaining.saturating_mul(63) / 64
    } else {
        (remaining.saturating_mul(63) / 64).min(requested)
    };
    let stipend_applied = value_wei > 0 && (kind == "call" || kind == "callcode");
    if stipend_applied {
        remaining.min(base_cap.saturating_add(2300))
    } else {
        base_cap
    }
}

struct DecodedCall {
    kind: &'static str,
    gas: U256,
    to_word: U256,
    value: U256,
    args_offset: usize,
    args_size: usize,
    ret_offset: usize,
    ret_size: usize,
    delegate: bool,
    static_call: bool,
    callcode: bool,
}

fn decode_call_from_stack(op: u8, stack: &mut Vec<U256>) -> PyResult<DecodedCall> {
    let (kind, consume, has_value, delegate, static_call, callcode) = match op {
        0xF1 => ("call", 7usize, true, false, false, false),
        0xF2 => ("callcode", 7, true, false, false, true),
        0xF4 => ("delegatecall", 6, false, true, false, false),
        0xFA => ("staticcall", 6, false, false, true, false),
        _ => {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "unsupported_call_opcode",
            ))
        }
    };
    if stack.len() < consume {
        return Err(pyo3::exceptions::PyRuntimeError::new_err("stack_underflow"));
    }
    let gas = stack_pop(stack)?;
    let to_word = stack_pop(stack)?;
    let value = if has_value {
        stack_pop(stack)?
    } else {
        U256::zero()
    };
    let args_offset = stack_pop(stack)?.as_usize();
    let args_size = stack_pop(stack)?.as_usize();
    let ret_offset = stack_pop(stack)?.as_usize();
    let ret_size = stack_pop(stack)?.as_usize();
    Ok(DecodedCall {
        kind,
        gas,
        to_word,
        value,
        args_offset,
        args_size,
        ret_offset,
        ret_size,
        delegate,
        static_call,
        callcode,
    })
}

fn write_return_to_memory(memory: &mut Vec<u8>, ret_offset: usize, ret_size: usize, data: &[u8]) {
    if ret_size == 0 {
        return;
    }
    mem_extend(memory, ret_offset, ret_size);
    let copy_n = ret_size.min(data.len());
    memory[ret_offset..ret_offset + copy_n].copy_from_slice(&data[..copy_n]);
    if copy_n < ret_size {
        for b in &mut memory[ret_offset + copy_n..ret_offset + ret_size] {
            *b = 0;
        }
    }
}

fn merge_storage_dict(
    storage: Option<&Bound<'_, PyDict>>,
    py_storage: Bound<'_, PyAny>,
) -> PyResult<()> {
    let Some(dst) = storage else {
        return Ok(());
    };
    let src = match py_storage.downcast::<PyDict>() {
        Ok(d) => d,
        Err(_) => return Ok(()),
    };
    dst.clear();
    for (k, v) in src.iter() {
        dst.set_item(k, v)?;
    }
    Ok(())
}

fn addr_string_to_u256(addr: &str) -> U256 {
    let raw = addr
        .trim()
        .trim_start_matches("0x")
        .trim_start_matches("0X");
    if raw.is_empty() {
        return U256::zero();
    }
    U256::from_str_radix(raw, 16).unwrap_or(U256::zero())
}

fn execute_call_native(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    op: u8,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    gas_limit: u64,
    gas_used: &mut u64,
    storage: Option<&Bound<'_, PyDict>>,
    arena: &mut HashMap<U256, U256>,
    return_data: &mut Vec<u8>,
) -> PyResult<()> {
    let frame = decode_call_from_stack(op, stack)?;
    if get_inline_read_only(host_context) && !frame.value.is_zero() {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            "static_write_protection",
        ));
    }
    let prev_ro = get_inline_read_only(host_context);
    set_inline_read_only(host_context, prev_ro || frame.static_call)?;
    let result = execute_call_native_inner(
        py,
        host_context,
        host_bridge,
        &frame,
        stack,
        memory,
        gas_limit,
        gas_used,
        storage,
        arena,
        return_data,
    );
    set_inline_read_only(host_context, prev_ro)?;
    result
}

fn execute_call_native_inner(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    frame: &DecodedCall,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    gas_limit: u64,
    gas_used: &mut u64,
    storage: Option<&Bound<'_, PyDict>>,
    arena: &mut HashMap<U256, U256>,
    return_data: &mut Vec<u8>,
) -> PyResult<()> {
    // v1.3.70: flush Rust arena → Python before nested CALL so DELEGATECALL
    // children (and hooks) see parent SSTOREs from this frame.
    restore_storage_dict(storage, arena)?;
    mem_extend(memory, frame.args_offset, frame.args_size);
    let call_data = evm_memory_slice_inner(memory, frame.args_offset, frame.args_size);
    let remaining = gas_limit.saturating_sub(*gas_used);
    let requested = if frame.gas > U256::from(u64::MAX) {
        u64::MAX
    } else {
        frame.gas.low_u64()
    };
    let value_i64 = if frame.value > U256::from(i64::MAX as u64) {
        i64::MAX
    } else {
        frame.value.low_u64() as i64
    };
    let call_gas = plan_nested_call_gas(remaining, requested, value_i64, frame.kind);

    // v1.3.71/79: in-Rust leaf frame for eligible DELEGATECALL/CALLCODE
    // (CALLCODE value via balances in v1.3.79). Falls through when ineligible.
    if try_inline_leaf_delegate_call(
        py,
        host_context,
        host_bridge,
        frame,
        &call_data,
        call_gas,
        gas_limit,
        gas_used,
        storage,
        arena,
        stack,
        memory,
        return_data,
    )? {
        return Ok(());
    }

    // v1.3.74–76 Priority 38: CALL/STATICCALL in-Rust (value transfer via balances in v1.3.76).
    if try_inline_leaf_value0_call(
        py,
        host_context,
        host_bridge,
        frame,
        &call_data,
        call_gas,
        gas_limit,
        gas_used,
        stack,
        memory,
        return_data,
    )? {
        return Ok(());
    }

    let sticky_static = get_inline_read_only(host_context);
    let call_fn = hook_contract_call(host_context).ok_or_else(|| {
        pyo3::exceptions::PyRuntimeError::new_err("contract_call_hook_unavailable")
    })?;
    let call_data_py = PyBytes::new_bound(py, &call_data);
    let to_addr = word_to_address(frame.to_word);
    let value_obj = py_u256_int(py, frame.value)?;
    let out = if frame.callcode {
        call_fn.call1((
            to_addr,
            call_data_py,
            value_obj,
            call_gas,
            frame.delegate,
            sticky_static,
            true,
        ))?
    } else {
        call_fn.call1((
            to_addr,
            call_data_py,
            value_obj,
            call_gas,
            frame.delegate,
            sticky_static,
        ))?
    };
    let out_dict = out.downcast::<PyDict>()?;
    let sub_gas = out_dict
        .get_item("gas_used")?
        .map(|v| v.extract::<u64>().unwrap_or(0))
        .unwrap_or(0)
        .min(call_gas);
    if let Err(reason) = consume_gas(gas_used, gas_limit, sub_gas) {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(reason));
    }
    let rd = out_dict
        .get_item("return_data")?
        .map(|v| v.extract::<Vec<u8>>().unwrap_or_default())
        .unwrap_or_default();
    *return_data = rd.clone();
    if (frame.delegate || frame.callcode) && !get_inline_read_only(host_context) {
        if let Ok(Some(st)) = out_dict.get_item("storage") {
            merge_storage_dict(storage, st)?;
        }
        // v1.3.70: re-sync arena after DELEGATECALL/CALLCODE storage merge so
        // subsequent SLOAD/SSTORE in this frame see child writes (not stale arena).
        *arena = snapshot_storage_dict(storage)?.unwrap_or_default();
    }
    write_return_to_memory(memory, frame.ret_offset, frame.ret_size, &rd);
    let success = out_dict
        .get_item("success")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false);
    let reverted = out_dict
        .get_item("reverted")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false);
    stack_push(
        stack,
        if success && !reverted {
            U256::one()
        } else {
            U256::zero()
        },
    );
    Ok(())
}

/// v1.3.71 Priority 37: push/pop eligible DELEGATECALL/CALLCODE leaf inside parent
/// Rust frame (no Python `_contract_call_hook` re-entry).
/// v1.3.79: CALLCODE with value>0 via fail-closed `bridge_state.balances`
/// (value credited to current account — net no-op when balances present).
/// Returns Ok(true) when handled; Ok(false) to fall through to Python hook.
fn try_inline_leaf_delegate_call(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    frame: &DecodedCall,
    call_data: &[u8],
    call_gas: u64,
    gas_limit: u64,
    gas_used: &mut u64,
    storage: Option<&Bound<'_, PyDict>>,
    arena: &mut HashMap<U256, U256>,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    return_data: &mut Vec<u8>,
) -> PyResult<bool> {
    // Only DELEGATECALL / CALLCODE share parent storage (DELEGATECALL never transfers).
    if !(frame.delegate || frame.callcode) {
        return Ok(false);
    }
    if frame.delegate && !frame.value.is_zero() {
        // DELEGATECALL ignores value on the wire in practice; refuse unexpected value.
        return Ok(false);
    }
    let code = match resolve_full_code(host_context, host_bridge, frame.to_word) {
        Ok(c) if !c.is_empty() => c,
        _ => return Ok(false),
    };
    if !bytecode_is_nested_native_eligible(&code) {
        return Ok(false);
    }

    // v1.3.79: CALLCODE value → current account (fail-closed balance check).
    let mut balance_snap: Option<HashMap<String, U256>> = None;
    if frame.callcode && !frame.value.is_zero() {
        let static_ctx = parse_static_context(host_context)?;
        match try_inline_value_transfer(
            host_context,
            static_ctx.address,
            static_ctx.address,
            frame.value,
        )? {
            InlineValueTransfer::Unavailable => return Ok(false),
            InlineValueTransfer::Insufficient => {
                *return_data = Vec::new();
                write_return_to_memory(memory, frame.ret_offset, frame.ret_size, &[]);
                stack_push(stack, U256::zero());
                return Ok(true);
            }
            InlineValueTransfer::Transferred { snap } => {
                balance_snap = Some(snap);
            }
        }
    }

    // Pre-leaf snap: if child stops host/handoff, restore and fall through.
    let pre_snap = snapshot_storage_dict(storage)?.unwrap_or_default();
    let jumpdest = crate::evm_build_jumpdest_table_inner(&code);
    let stack_py = PyList::empty_bound(py);
    let memory_py = PyByteArray::new_bound(py, &[]);
    // Leaf: no host_bridge — recursive host ops are rejected by eligibility.
    // Pass host_context so bridge ops (BALANCE/…) can still resolve via bridge_state.
    let child = run_pure_segment_inner(
        py,
        &code,
        0,
        call_gas,
        0,
        &stack_py,
        &memory_py,
        &jumpdest,
        call_data,
        &[],
        host_context,
        storage,
        None,
        MAX_FULL_STEPS,
        true,
    );
    let child = match child {
        Ok(c) => c,
        Err(e) => {
            if let Some(ref snap) = balance_snap {
                restore_inline_balances(host_context, snap)?;
            }
            return Err(e);
        }
    };
    let child_dict = child.downcast_bound::<PyDict>(py)?;
    let reason = child_dict
        .get_item("stop_reason")?
        .map(|v| v.extract::<String>().unwrap_or_default())
        .unwrap_or_default();
    if !matches!(reason.as_str(), "halt" | "return" | "revert" | "out_of_gas") {
        restore_storage_dict(storage, &pre_snap)?;
        *arena = pre_snap;
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
        return Ok(false);
    }
    let sub_gas = charge_nested_call_gas(
        reason.as_str(),
        child_dict
            .get_item("gas_used")?
            .map(|v| v.extract::<u64>().unwrap_or(0))
            .unwrap_or(0),
        call_gas,
    );
    if let Err(reason) = consume_gas(gas_used, gas_limit, sub_gas) {
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
        return Err(pyo3::exceptions::PyRuntimeError::new_err(reason));
    }
    let mut rd = child_dict
        .get_item("return_data")?
        .map(|v| v.extract::<Vec<u8>>().unwrap_or_default())
        .unwrap_or_default();
    if reason == "out_of_gas" {
        rd.clear();
    }
    *return_data = rd.clone();
    // Shared parent storage already mutated in place; re-sync arena (v1.3.70+71).
    *arena = snapshot_storage_dict(storage)?.unwrap_or_default();
    write_return_to_memory(memory, frame.ret_offset, frame.ret_size, &rd);
    let reverted = child_dict
        .get_item("reverted")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false)
        || reason == "out_of_gas";
    let success = !reverted && matches!(reason.as_str(), "halt" | "return");
    if !success {
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
    }
    stack_push(stack, if success { U256::one() } else { U256::zero() });
    // Mark for observability (tests assert via storage side-effects / hook counter).
    let _ = child_dict.set_item("native_inline_leaf_frame", true);
    if balance_snap.is_some() {
        let _ = child_dict.set_item("native_inline_callcode_value", true);
    }
    Ok(true)
}

fn inline_storage_dict<'py>(
    host_context: Option<&Bound<'py, PyDict>>,
    who: U256,
) -> Option<Bound<'py, PyDict>> {
    let state = bridge_state_dict(host_context)?;
    let storages = state.get_item("storages").ok()??;
    let dict = storages.downcast::<PyDict>().ok()?;
    let addr = word_to_address(who);
    let value = dict.get_item(addr.as_str()).ok()??;
    value.downcast::<PyDict>().ok().cloned()
}

fn store_inline_storage(
    host_context: Option<&Bound<'_, PyDict>>,
    who: U256,
    child_storage: &Bound<'_, PyDict>,
) -> PyResult<()> {
    let Some(ctx) = host_context else {
        return Ok(());
    };
    let Ok(Some(state_any)) = ctx.get_item("bridge_state") else {
        return Ok(());
    };
    let Ok(state) = state_any.downcast::<PyDict>() else {
        return Ok(());
    };
    let storages = match state.get_item("storages")? {
        Some(s) => match s.downcast::<PyDict>() {
            Ok(d) => d.clone(),
            Err(_) => {
                let d = PyDict::new_bound(ctx.py());
                state.set_item("storages", &d)?;
                d
            }
        },
        None => {
            let d = PyDict::new_bound(ctx.py());
            state.set_item("storages", &d)?;
            d
        }
    };
    let addr = word_to_address(who);
    // Persist a copy so later CALLs see mutations.
    let snap = child_storage.copy()?;
    storages.set_item(addr.as_str(), snap)?;
    Ok(())
}

/// Snapshot `bridge_state.balances` for fail-closed value transfer (v1.3.76).
fn snapshot_inline_balances(
    host_context: Option<&Bound<'_, PyDict>>,
) -> PyResult<Option<HashMap<String, U256>>> {
    let Some(state) = bridge_state_dict(host_context) else {
        return Ok(None);
    };
    let Ok(Some(balances_any)) = state.get_item("balances") else {
        return Ok(None);
    };
    let Ok(balances) = balances_any.downcast::<PyDict>() else {
        return Ok(None);
    };
    let mut map = HashMap::new();
    for (k, v) in balances.iter() {
        let key = k.extract::<String>().unwrap_or_default();
        if key.is_empty() {
            continue;
        }
        map.insert(key, py_to_u256_or_int(v)?);
    }
    Ok(Some(map))
}

fn restore_inline_balances(
    host_context: Option<&Bound<'_, PyDict>>,
    snap: &HashMap<String, U256>,
) -> PyResult<()> {
    let Some(state) = bridge_state_dict(host_context) else {
        return Ok(());
    };
    let py = state.py();
    let balances = match state.get_item("balances")? {
        Some(b) => match b.downcast::<PyDict>() {
            Ok(d) => d.clone(),
            Err(_) => {
                let d = PyDict::new_bound(py);
                state.set_item("balances", &d)?;
                d
            }
        },
        None => {
            let d = PyDict::new_bound(py);
            state.set_item("balances", &d)?;
            d
        }
    };
    balances.clear();
    for (k, v) in snap {
        balances.set_item(k.as_str(), u256_to_py_int(py, *v)?)?;
    }
    Ok(())
}

enum InlineValueTransfer {
    /// Balances map missing — fall through to Python for real DB debit.
    Unavailable,
    /// Fail-closed: insufficient balance (CALL fails without executing child).
    Insufficient,
    /// Transferred; caller must restore `snap` on child revert.
    Transferred { snap: HashMap<String, U256> },
}

/// Fail-closed wei transfer in `bridge_state.balances` (v1.3.76).
/// Same-address transfer (CALLCODE) requires balance >= value but is a no-op net (v1.3.79).
fn try_inline_value_transfer(
    host_context: Option<&Bound<'_, PyDict>>,
    from: U256,
    to: U256,
    value: U256,
) -> PyResult<InlineValueTransfer> {
    if value.is_zero() {
        return Ok(InlineValueTransfer::Transferred {
            snap: HashMap::new(),
        });
    }
    let Some(snap) = snapshot_inline_balances(host_context)? else {
        return Ok(InlineValueTransfer::Unavailable);
    };
    let Some(state) = bridge_state_dict(host_context) else {
        return Ok(InlineValueTransfer::Unavailable);
    };
    let Ok(Some(balances_any)) = state.get_item("balances") else {
        return Ok(InlineValueTransfer::Unavailable);
    };
    let Ok(balances) = balances_any.downcast::<PyDict>() else {
        return Ok(InlineValueTransfer::Unavailable);
    };
    let py = balances.py();
    let from_s = word_to_address(from);
    let to_s = word_to_address(to);
    let from_bal = match balances.get_item(from_s.as_str())? {
        Some(v) => py_to_u256_or_int(v)?,
        None => U256::zero(),
    };
    if from_bal < value {
        return Ok(InlineValueTransfer::Insufficient);
    }
    // CALLCODE credits the current account: debit+credit cancel; still fail-closed.
    if from_s == to_s {
        return Ok(InlineValueTransfer::Transferred { snap });
    }
    let to_bal = match balances.get_item(to_s.as_str())? {
        Some(v) => py_to_u256_or_int(v)?,
        None => U256::zero(),
    };
    let new_from = from_bal - value;
    let new_to = to_bal + value;
    balances.set_item(from_s.as_str(), u256_to_py_int(py, new_from)?)?;
    balances.set_item(to_s.as_str(), u256_to_py_int(py, new_to)?)?;
    Ok(InlineValueTransfer::Transferred { snap })
}

/// v1.3.83: enqueue `transfer_value` for adapter satoshi writeback journal.
/// Same-addr / zero / >i64 wei → no op (fail-closed: no silent wrong satoshi).
fn push_pending_writeback_transfer(
    host_context: Option<&Bound<'_, PyDict>>,
    from: U256,
    to: U256,
    value: U256,
) -> PyResult<()> {
    if value.is_zero() {
        return Ok(());
    }
    let from_s = word_to_address(from);
    let to_s = word_to_address(to);
    if from_s == to_s {
        return Ok(());
    }
    if value.bits() > 63 {
        return Ok(());
    }
    let wei = value.as_u64() as i64;
    let Some(state) = bridge_state_dict(host_context) else {
        return Ok(());
    };
    let py = state.py();
    let pending = pending_writeback_list(py, &state)?;
    let op = PyDict::new_bound(py);
    op.set_item("op", "transfer_value")?;
    op.set_item("from", from_s.as_str())?;
    op.set_item("to", to_s.as_str())?;
    op.set_item("value_wei", wei)?;
    op.set_item("native_inline_writeback", true)?;
    pending.append(op)?;
    state.set_item("native_inline_writeback_value", true)?;
    state.set_item("native_inline_writeback_ops", pending.len())?;
    Ok(())
}

/// Ensure `bridge_state.pending_writeback_ops` is a mutable list (v1.3.83+).
fn pending_writeback_list<'py>(
    py: Python<'py>,
    state: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    match state.get_item("pending_writeback_ops")? {
        Some(existing) => match existing.downcast::<PyList>() {
            Ok(list) => Ok(list.clone()),
            Err(_) => {
                let list = PyList::empty_bound(py);
                state.set_item("pending_writeback_ops", &list)?;
                Ok(list)
            }
        },
        None => {
            let list = PyList::empty_bound(py);
            state.set_item("pending_writeback_ops", &list)?;
            Ok(list)
        }
    }
}

/// v1.3.84: enqueue `save_account` for inline CREATE/CREATE2 (balance 0; value is separate).
fn push_pending_writeback_save_account(
    host_context: Option<&Bound<'_, PyDict>>,
    address: &str,
    runtime: &[u8],
) -> PyResult<()> {
    if address.is_empty() {
        return Ok(());
    }
    let Some(state) = bridge_state_dict(host_context) else {
        return Ok(());
    };
    let py = state.py();
    let pending = pending_writeback_list(py, &state)?;
    let code_hex = hex::encode(runtime);
    let op = PyDict::new_bound(py);
    op.set_item("op", "save_account")?;
    op.set_item("address", address)?;
    op.set_item("balance", 0)?;
    op.set_item("nonce", 0u64)?;
    op.set_item("code", code_hex.as_str())?;
    op.set_item("storage", "{}")?;
    op.set_item("native_inline_writeback", true)?;
    pending.append(op)?;
    state.set_item("native_inline_writeback_create", true)?;
    state.set_item("native_inline_writeback_ops", pending.len())?;
    Ok(())
}

/// v1.3.74–76 Priority 38: CALL/STATICCALL in-Rust frame with callee storage.
/// v1.3.76: value>0 CALL via fail-closed `bridge_state.balances` (no silent debit).
fn try_inline_leaf_value0_call(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    frame: &DecodedCall,
    call_data: &[u8],
    call_gas: u64,
    gas_limit: u64,
    gas_used: &mut u64,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    return_data: &mut Vec<u8>,
) -> PyResult<bool> {
    // CALL / STATICCALL only; DELEGATECALL/CALLCODE use the other inline path.
    if frame.delegate || frame.callcode {
        return Ok(false);
    }
    if frame.static_call && !frame.value.is_zero() {
        return Ok(false);
    }
    let depth = get_inline_depth(host_context);
    if depth >= MAX_INLINE_CALL_DEPTH {
        return Ok(false);
    }
    let code = match resolve_full_code(host_context, host_bridge, frame.to_word) {
        Ok(c) if !c.is_empty() => c,
        _ => return Ok(false),
    };
    let leaf_ok = bytecode_is_nested_native_eligible(&code);
    let frame_ok = bytecode_is_inline_call_frame_eligible(&code);
    if !leaf_ok && !frame_ok {
        return Ok(false);
    }

    // v1.3.76: value transfer before child execution (EVM order).
    let mut balance_snap: Option<HashMap<String, U256>> = None;
    if !frame.value.is_zero() {
        let static_ctx = parse_static_context(host_context)?;
        match try_inline_value_transfer(
            host_context,
            static_ctx.address,
            frame.to_word,
            frame.value,
        )? {
            InlineValueTransfer::Unavailable => return Ok(false),
            InlineValueTransfer::Insufficient => {
                // CALL fails closed without executing child (no silent clamp).
                *return_data = Vec::new();
                write_return_to_memory(memory, frame.ret_offset, frame.ret_size, &[]);
                stack_push(stack, U256::zero());
                return Ok(true);
            }
            InlineValueTransfer::Transferred { snap } => {
                balance_snap = Some(snap);
            }
        }
    }

    // Callee storage: prefer bridge_state.storages[addr], else empty (ephemeral).
    let child_storage = if let Some(existing) = inline_storage_dict(host_context, frame.to_word) {
        existing
    } else {
        PyDict::new_bound(py)
    };
    let child_storage_ref = Some(&child_storage);
    let jumpdest = crate::evm_build_jumpdest_table_inner(&code);
    let stack_py = PyList::empty_bound(py);
    let memory_py = PyByteArray::new_bound(py, &[]);
    let prev_depth = depth;
    set_inline_depth(host_context, depth + 1)?;
    let child = run_pure_segment_inner(
        py,
        &code,
        0,
        call_gas,
        0,
        &stack_py,
        &memory_py,
        &jumpdest,
        call_data,
        &[],
        host_context,
        child_storage_ref,
        None,
        MAX_FULL_STEPS,
        true,
    );
    let _ = set_inline_depth(host_context, prev_depth);
    let child = match child {
        Ok(c) => c,
        Err(e) => {
            if let Some(ref snap) = balance_snap {
                restore_inline_balances(host_context, snap)?;
            }
            return Err(e);
        }
    };
    let child_dict = child.downcast_bound::<PyDict>(py)?;
    let reason = child_dict
        .get_item("stop_reason")?
        .map(|v| v.extract::<String>().unwrap_or_default())
        .unwrap_or_default();
    if !matches!(reason.as_str(), "halt" | "return" | "revert" | "out_of_gas") {
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
        return Ok(false);
    }
    let sub_gas = charge_nested_call_gas(
        reason.as_str(),
        child_dict
            .get_item("gas_used")?
            .map(|v| v.extract::<u64>().unwrap_or(0))
            .unwrap_or(0),
        call_gas,
    );
    if let Err(reason) = consume_gas(gas_used, gas_limit, sub_gas) {
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
        return Err(pyo3::exceptions::PyRuntimeError::new_err(reason));
    }
    let mut rd = child_dict
        .get_item("return_data")?
        .map(|v| v.extract::<Vec<u8>>().unwrap_or_default())
        .unwrap_or_default();
    if reason == "out_of_gas" {
        rd.clear();
    }
    *return_data = rd.clone();
    let reverted = child_dict
        .get_item("reverted")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false)
        || reason == "out_of_gas";
    let success = !reverted && matches!(reason.as_str(), "halt" | "return");
    if success && !frame.static_call {
        store_inline_storage(host_context, frame.to_word, &child_storage)?;
        // v1.3.83: plan satoshi journal op only after child success (matches balance keep).
        if !frame.value.is_zero() {
            let static_ctx = parse_static_context(host_context)?;
            push_pending_writeback_transfer(
                host_context,
                static_ctx.address,
                frame.to_word,
                frame.value,
            )?;
        }
    } else if let Some(ref snap) = balance_snap {
        // Revert value transfer with the child.
        restore_inline_balances(host_context, snap)?;
    }
    write_return_to_memory(memory, frame.ret_offset, frame.ret_size, &rd);
    stack_push(stack, if success { U256::one() } else { U256::zero() });
    let _ = child_dict.set_item("native_inline_value0_call", true);
    if balance_snap.is_some() {
        let _ = child_dict.set_item("native_inline_value_call", true);
    }
    if !leaf_ok {
        let _ = child_dict.set_item("native_inline_call_frame", true);
        let _ = child_dict.set_item("native_inline_depth", depth + 1);
    }
    Ok(true)
}

fn execute_create_native(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    op: u8,
    stack: &mut Vec<U256>,
    memory: &mut Vec<u8>,
    gas_limit: u64,
    gas_used: &mut u64,
) -> PyResult<()> {
    let salt = if op == 0xF5 {
        Some(stack_pop(stack)?)
    } else {
        None
    };
    let size = stack_pop(stack)?.as_usize();
    let offset = stack_pop(stack)?.as_usize();
    let value = stack_pop(stack)?;
    mem_extend(memory, offset, size);
    let init_code = evm_memory_slice_inner(memory, offset, size);

    // v1.3.80/81: empty/STOP init CREATE/CREATE2 owned in Rust when bridge_state.codes present.
    if try_inline_simple_create(
        py,
        host_context,
        op,
        salt,
        &init_code,
        value,
        stack,
        gas_limit,
        gas_used,
    )? {
        return Ok(());
    }

    let create_fn = hook_contract_create(host_context).ok_or_else(|| {
        pyo3::exceptions::PyRuntimeError::new_err("contract_create_hook_unavailable")
    })?;
    let init_py = PyBytes::new_bound(py, &init_code);
    let value_obj = py_u256_int(py, value)?;
    let out = if let Some(salt_word) = salt {
        let salt_obj = py_u256_int(py, salt_word)?;
        create_fn.call1((init_py, value_obj, salt_obj))?
    } else {
        create_fn.call1((init_py, value_obj))?
    };
    let out_dict = out.downcast::<PyDict>()?;
    let sub_gas = out_dict
        .get_item("gas_used")?
        .map(|v| v.extract::<u64>().unwrap_or(0))
        .unwrap_or(0);
    if let Err(reason) = consume_gas(gas_used, gas_limit, sub_gas) {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(reason));
    }
    let success = out_dict
        .get_item("success")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false);
    let reverted = out_dict
        .get_item("reverted")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false);
    if !success || reverted {
        stack_push(stack, U256::zero());
        return Ok(());
    }
    let addr = out_dict
        .get_item("address")?
        .map(|v| v.extract::<String>().unwrap_or_default())
        .unwrap_or_default();
    stack_push(stack, addr_string_to_u256(&addr));
    Ok(())
}

/// Empty/STOP or leaf-eligible init (no CALL/CREATE/LOG/SELFDESTRUCT) — v1.3.80/82.
fn init_is_inline_create_eligible(init: &[u8]) -> bool {
    init.is_empty() || init == [0x00] || bytecode_is_nested_native_eligible(init)
}

const MAX_INLINE_CREATE_CODE_BYTES: usize = 24_576; // EIP-170

/// Prefer EIP-1014 CREATE2 unless bridge_state/host explicitly disables it.
fn create2_eip1014_enabled(host_context: Option<&Bound<'_, PyDict>>) -> bool {
    if let Some(state) = bridge_state_dict(host_context) {
        if let Ok(Some(v)) = state.get_item("create2_eip1014") {
            return v.is_truthy().unwrap_or(true);
        }
    }
    if let Some(ctx) = host_context {
        if let Ok(Some(v)) = ctx.get_item("evm_create2_eip1014") {
            return v.is_truthy().unwrap_or(true);
        }
    }
    true
}

fn resolve_inline_create_address(
    host_context: Option<&Bound<'_, PyDict>>,
    deployer: &str,
    block_n: u64,
    init_code: &[u8],
    salt: Option<U256>,
) -> PyResult<Option<String>> {
    match salt {
        None => Ok(Some(crate::evm_deploy_address_create_inner(
            deployer,
            block_n,
            init_code.len(),
        ))),
        Some(salt_word) => {
            if create2_eip1014_enabled(host_context) {
                let deployer20 = match crate::parse_address_20(deployer) {
                    Ok(a) => a,
                    Err(_) => return Ok(None),
                };
                let salt32 = crate::u256_to_be32(salt_word);
                let init_hash = crate::keccak256_digest_bytes(init_code);
                let addr20 =
                    crate::evm_create2_address_eip1014_inner(&deployer20, &salt32, &init_hash);
                Ok(Some(format!("0x{}", hex::encode(addr20))))
            } else {
                // Match Python: salt_text = str(int(salt))
                let salt_text = salt_word.to_string();
                Ok(Some(crate::evm_deploy_address_create2_legacy_inner(
                    deployer, &salt_text, init_code,
                )))
            }
        }
    }
}

fn code_entry_occupied(existing: &Bound<'_, PyAny>) -> bool {
    if let Ok(b) = existing.extract::<Vec<u8>>() {
        !b.is_empty()
    } else if let Ok(s) = existing.extract::<String>() {
        !s.is_empty()
    } else {
        true
    }
}

/// Run eligible init bytecode; Ok(Some((runtime, gas_used, success))).
/// Ok(None) = fall through to Python; success=false = fail-closed CREATE.
fn run_inline_create_init(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    init_code: &[u8],
    call_gas: u64,
) -> PyResult<Option<(Vec<u8>, u64, bool)>> {
    if init_code.is_empty() || init_code == [0x00] {
        return Ok(Some((Vec::new(), 0, true)));
    }
    if !bytecode_is_nested_native_eligible(init_code) {
        return Ok(None);
    }
    let init_storage = PyDict::new_bound(py);
    let jumpdest = crate::evm_build_jumpdest_table_inner(init_code);
    let stack_py = PyList::empty_bound(py);
    let memory_py = PyByteArray::new_bound(py, &[]);
    let child = run_pure_segment_inner(
        py,
        init_code,
        0,
        call_gas,
        0,
        &stack_py,
        &memory_py,
        &jumpdest,
        &[],
        &[],
        host_context,
        Some(&init_storage),
        None,
        MAX_PURE_STEPS.max(65_536),
        true,
    )?;
    let child_dict = child.downcast_bound::<PyDict>(py)?;
    let reason = child_dict
        .get_item("stop_reason")?
        .map(|v| v.extract::<String>().unwrap_or_default())
        .unwrap_or_default();
    if !matches!(reason.as_str(), "halt" | "return" | "revert" | "out_of_gas") {
        return Ok(None);
    }
    let sub_gas = charge_nested_call_gas(
        reason.as_str(),
        child_dict
            .get_item("gas_used")?
            .map(|v| v.extract::<u64>().unwrap_or(0))
            .unwrap_or(0),
        call_gas,
    );
    let reverted = child_dict
        .get_item("reverted")?
        .map(|v| v.is_truthy().unwrap_or(false))
        .unwrap_or(false)
        || reason == "out_of_gas"
        || reason == "revert";
    if reverted {
        return Ok(Some((Vec::new(), sub_gas, false)));
    }
    let runtime = child_dict
        .get_item("return_data")?
        .map(|v| v.extract::<Vec<u8>>().unwrap_or_default())
        .unwrap_or_default();
    if runtime.len() > MAX_INLINE_CREATE_CODE_BYTES {
        return Ok(Some((Vec::new(), sub_gas, false)));
    }
    Ok(Some((runtime, sub_gas, true)))
}

/// v1.3.80–84 Priority 38: CREATE/CREATE2 via bridge_state.
/// Empty/STOP or leaf-eligible init (RETURN runtime) owned in Rust.
/// CREATE2 defaults to EIP-1014 (`create2_eip1014=false` → legacy Absolute seed).
fn try_inline_simple_create(
    py: Python<'_>,
    host_context: Option<&Bound<'_, PyDict>>,
    op: u8,
    salt: Option<U256>,
    init_code: &[u8],
    value: U256,
    stack: &mut Vec<U256>,
    gas_limit: u64,
    gas_used: &mut u64,
) -> PyResult<bool> {
    if !matches!(op, 0xF0 | 0xF5) {
        return Ok(false);
    }
    if op == 0xF0 && salt.is_some() {
        return Ok(false);
    }
    if op == 0xF5 && salt.is_none() {
        return Ok(false);
    }
    if !init_is_inline_create_eligible(init_code) {
        return Ok(false);
    }
    let Some(state) = bridge_state_dict(host_context) else {
        return Ok(false);
    };
    let Ok(Some(codes_any)) = state.get_item("codes") else {
        return Ok(false);
    };
    let Ok(codes) = codes_any.downcast::<PyDict>() else {
        return Ok(false);
    };

    let static_ctx = parse_static_context(host_context)?;
    let deployer = word_to_address(static_ctx.address);
    let block_n = if static_ctx.block_number > U256::from(u64::MAX) {
        u64::MAX
    } else {
        static_ctx.block_number.low_u64()
    };
    let Some(addr) =
        resolve_inline_create_address(host_context, &deployer, block_n, init_code, salt)?
    else {
        return Ok(false);
    };
    let addr_word = addr_string_to_u256(&addr);

    // Collision: non-empty existing code → failed CREATE (push 0).
    if let Some(existing) = codes.get_item(addr.as_str())? {
        if code_entry_occupied(&existing) {
            stack_push(stack, U256::zero());
            return Ok(true);
        }
    }

    let mut balance_snap: Option<HashMap<String, U256>> = None;
    if !value.is_zero() {
        match try_inline_value_transfer(host_context, static_ctx.address, addr_word, value)? {
            InlineValueTransfer::Unavailable => return Ok(false),
            InlineValueTransfer::Insufficient => {
                stack_push(stack, U256::zero());
                return Ok(true);
            }
            InlineValueTransfer::Transferred { snap } => {
                balance_snap = Some(snap);
            }
        }
    }

    let remaining = gas_limit.saturating_sub(*gas_used);
    let call_gas = remaining.saturating_sub(remaining / 64);
    let init_result = match run_inline_create_init(py, host_context, init_code, call_gas)? {
        Some(v) => v,
        None => {
            if let Some(ref snap) = balance_snap {
                restore_inline_balances(host_context, snap)?;
            }
            return Ok(false);
        }
    };
    let (runtime, init_gas, success) = init_result;
    if let Err(_reason) = consume_gas(gas_used, gas_limit, init_gas) {
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
        stack_push(stack, U256::zero());
        return Ok(true);
    }
    if !success {
        if let Some(ref snap) = balance_snap {
            restore_inline_balances(host_context, snap)?;
        }
        stack_push(stack, U256::zero());
        return Ok(true);
    }

    // Persist runtime code + empty storage under bridge_state.
    if runtime.is_empty() {
        codes.set_item(addr.as_str(), "")?;
    } else {
        codes.set_item(addr.as_str(), PyBytes::new_bound(py, &runtime))?;
    }
    if let Ok(Some(storages_any)) = state.get_item("storages") {
        if let Ok(storages) = storages_any.downcast::<PyDict>() {
            storages.set_item(addr.as_str(), PyDict::new_bound(py))?;
        }
    } else {
        let storages = PyDict::new_bound(py);
        storages.set_item(addr.as_str(), PyDict::new_bound(py))?;
        state.set_item("storages", storages)?;
    }

    let _ = balance_snap; // success keeps transfer
                          // v1.3.84: plan save_account then optional transfer_value (same order as evm_plan_create_writeback).
    push_pending_writeback_save_account(host_context, addr.as_str(), &runtime)?;
    // v1.3.83: enqueue transfer_value for adapter satoshi journal.
    if !value.is_zero() {
        push_pending_writeback_transfer(host_context, static_ctx.address, addr_word, value)?;
    }
    stack_push(stack, addr_word);
    state.set_item("native_inline_simple_create", true)?;
    state.set_item("native_inline_create_address", addr.as_str())?;
    if !runtime.is_empty() {
        // v1.3.82: eligible init returned runtime bytecode
        state.set_item("native_inline_create_runtime", true)?;
        state.set_item("native_inline_create_runtime_len", runtime.len())?;
    }
    if op == 0xF5 {
        // v1.3.81
        state.set_item("native_inline_create2", true)?;
        state.set_item(
            "native_inline_create2_eip1014",
            create2_eip1014_enabled(host_context),
        )?;
    }
    Ok(true)
}

fn execute_selfdestruct_native(
    host_context: Option<&Bound<'_, PyDict>>,
    stack: &mut Vec<U256>,
    running: &mut bool,
) -> PyResult<()> {
    let beneficiary = stack_pop(stack)?;
    if let Some(func) = hook_selfdestruct(host_context) {
        let addr = word_to_address(beneficiary);
        func.call1((addr,))?;
    }
    *running = false;
    Ok(())
}

fn resolve_balance(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    who: U256,
) -> PyResult<U256> {
    if let Some(result) = inline_balance(host_context, who) {
        return result;
    }
    if let Some(result) = hook_balance(host_context, who) {
        return result;
    }
    if let Some(bridge) = host_bridge {
        return bridge_balance(bridge, who);
    }
    Err(pyo3::exceptions::PyRuntimeError::new_err(
        "bridge_unavailable",
    ))
}

fn resolve_code_size(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    who: U256,
) -> PyResult<U256> {
    if let Some(result) = inline_code_bytes(host_context, who) {
        return result.map(|code| U256::from(code.len()));
    }
    if let Some(result) = hook_code_size(host_context, who) {
        return result;
    }
    if let Some(bridge) = host_bridge {
        return bridge_code_size(bridge, who);
    }
    Err(pyo3::exceptions::PyRuntimeError::new_err(
        "bridge_unavailable",
    ))
}

fn resolve_code_copy(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    who: U256,
    code_offset: usize,
    size: usize,
) -> PyResult<Vec<u8>> {
    if let Some(result) = inline_code_bytes(host_context, who) {
        return result.map(|code| {
            let mut out = vec![0u8; size];
            let available = code.len().saturating_sub(code_offset);
            let copy_len = size.min(available);
            if copy_len > 0 {
                out[..copy_len].copy_from_slice(&code[code_offset..code_offset + copy_len]);
            }
            out
        });
    }
    if let Some(result) = hook_code_copy(host_context, who, code_offset, size) {
        return result;
    }
    if let Some(bridge) = host_bridge {
        return bridge_code_copy(bridge, who, code_offset, size);
    }
    Err(pyo3::exceptions::PyRuntimeError::new_err(
        "bridge_unavailable",
    ))
}

fn resolve_block_hash(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    block_num: U256,
) -> PyResult<U256> {
    if let Some(result) = inline_block_hash(host_context, block_num) {
        return result;
    }
    if let Some(result) = hook_block_hash(host_context, block_num) {
        return result;
    }
    if let Some(bridge) = host_bridge {
        return bridge_block_hash(bridge, block_num);
    }
    Err(pyo3::exceptions::PyRuntimeError::new_err(
        "bridge_unavailable",
    ))
}

fn resolve_full_code(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    who: U256,
) -> PyResult<Vec<u8>> {
    if let Some(result) = inline_code_bytes(host_context, who) {
        return result;
    }
    let size = resolve_code_size(host_context, host_bridge, who)?.as_usize();
    if size == 0 {
        return Ok(Vec::new());
    }
    resolve_code_copy(host_context, host_bridge, who, 0, size)
}

fn resolve_code_hash(
    host_context: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    who: U256,
) -> PyResult<U256> {
    let code = resolve_full_code(host_context, host_bridge, who)?;
    if code.is_empty() {
        return Ok(U256::zero());
    }
    Ok(u256_from_be32(keccak256_digest_bytes(&code)))
}

fn evm_u256_div_inner(a: U256, b: U256) -> U256 {
    if b.is_zero() {
        U256::zero()
    } else {
        a / b
    }
}

fn evm_u256_mod_inner(a: U256, b: U256) -> U256 {
    if b.is_zero() {
        U256::zero()
    } else {
        a % b
    }
}

fn evm_u256_bool_word(truthy: bool) -> U256 {
    if truthy {
        U256::one()
    } else {
        U256::zero()
    }
}

fn evm_u256_eq_inner(a: U256, b: U256) -> U256 {
    evm_u256_bool_word(a == b)
}

fn evm_u256_lt_inner(a: U256, b: U256) -> U256 {
    evm_u256_bool_word(a < b)
}

fn evm_u256_gt_inner(a: U256, b: U256) -> U256 {
    evm_u256_bool_word(a > b)
}

fn evm_u256_iszero_inner(v: U256) -> U256 {
    evm_u256_bool_word(v.is_zero())
}

fn evm_u256_byte_inner(index: u32, value: U256) -> U256 {
    if index >= 32 {
        return U256::zero();
    }
    let shift = 8 * (31 - index);
    let byte = if shift >= 256 {
        0
    } else {
        ((value >> shift).low_u32() & 0xff) as u64
    };
    U256::from(byte)
}

fn evm_memory_active_bytes(len: usize) -> usize {
    if len == 0 {
        0
    } else {
        len.div_ceil(32) * 32
    }
}

fn gas_cost(op: u8) -> u64 {
    match op {
        0x00 => 0,
        0x01 | 0x03 => 3,
        0x02 => 5,
        0x04..=0x07 => 5,
        0x08 => 8,
        0x09 => 8,
        0x0A => 10,
        0x0B => 5,
        0x10 | 0x11 | 0x12 | 0x14 | 0x15 | 0x16 | 0x17 | 0x18 | 0x19 | 0x1A | 0x1B | 0x1C
        | 0x1D => 3,
        0x20 => 30,
        0x35 | 0x37 | 0x39 | 0x3E => 3,
        0x36 | 0x3D => 2,
        0x38 => 2,
        0x50 => 2,
        0x51..=0x53 => 3,
        0x56 => 8,
        0x57 => 10,
        0x5A | 0x5F | 0x58 | 0x59 => 2,
        0x5B => 1,
        0x47 => 5,
        0x48 => 2,
        0x3A | 0x41 | 0x44 => 2,
        0x3F => 700,
        0x30 | 0x32 | 0x33 | 0x34 | 0x42 | 0x43 | 0x45 | 0x46 => 2,
        0x31 => 400,
        0x3B | 0x3C => 700,
        0x40 => 20,
        0x54 => 200,
        0x55 => 5000,
        0x5C | 0x5D => 100,
        0x5E => 3,
        0x49 | 0x4A => 2,
        0xF0 | 0xF5 => 32000,
        0xF1 | 0xF2 | 0xF4 | 0xFA => 700,
        0xFF => 5000,
        0xF3 | 0xFD => 0,
        0xFE => 0,
        _ if (0x60..=0x7F).contains(&op) => 3,
        _ if (0x80..=0x8F).contains(&op) => 3,
        _ if (0x90..=0x9F).contains(&op) => 3,
        _ => 3,
    }
}

fn consume_gas(gas_used: &mut u64, gas_limit: u64, cost: u64) -> Result<(), &'static str> {
    if *gas_used + cost > gas_limit {
        Err("out_of_gas")
    } else {
        *gas_used += cost;
        Ok(())
    }
}

/// Yellow Paper: exceptional halt of a nested call consumes all forwarded gas.
/// REVERT refunds unused gas; OOG does not.
fn charge_nested_call_gas(reason: &str, child_gas_used: u64, call_gas: u64) -> u64 {
    if reason == "out_of_gas" {
        call_gas
    } else {
        child_gas_used.min(call_gas)
    }
}

fn mem_extend(memory: &mut Vec<u8>, offset: usize, size: usize) {
    let need = offset.saturating_add(size);
    if need > memory.len() {
        memory.resize(need, 0);
    }
}

fn stack_pop(stack: &mut Vec<U256>) -> PyResult<U256> {
    stack
        .pop()
        .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("stack_underflow"))
}

fn stack_push(stack: &mut Vec<U256>, value: U256) {
    stack.push(value & U256_MASK);
}

fn stack_dup(stack: &mut Vec<U256>, depth: usize) -> PyResult<()> {
    if depth == 0 || depth > stack.len() {
        return Err(pyo3::exceptions::PyRuntimeError::new_err("stack_underflow"));
    }
    stack_push(stack, stack[stack.len() - depth]);
    Ok(())
}

fn stack_swap(stack: &mut [U256], depth: usize) -> PyResult<()> {
    if depth == 0 || depth >= stack.len() {
        return Err(pyo3::exceptions::PyRuntimeError::new_err("stack_underflow"));
    }
    let top = stack.len() - 1;
    let other = stack.len() - 1 - depth;
    stack.swap(top, other);
    Ok(())
}

fn stack_from_py(list: &Bound<'_, PyList>) -> PyResult<Vec<U256>> {
    let mut stack = Vec::with_capacity(list.len());
    for i in 0..list.len() {
        let item = list.get_item(i)?;
        let bytes_obj = item.call_method1("to_bytes", (32, "big"))?;
        let bytes: Vec<u8> = bytes_obj.extract()?;
        let mut buf = [0u8; 32];
        let start = 32usize.saturating_sub(bytes.len());
        buf[start..].copy_from_slice(&bytes);
        stack.push(U256::from_big_endian(&buf));
    }
    Ok(stack)
}

fn stack_to_pylist<'py>(py: Python<'py>, stack: &[U256]) -> PyResult<Bound<'py, PyList>> {
    let builtins = py.import_bound("builtins")?;
    let int_cls = builtins.getattr("int")?;
    let out = PyList::empty_bound(py);
    for value in stack {
        let bytes = u256_to_be32(*value);
        let obj = int_cls.call_method1("from_bytes", (bytes.as_slice(), "big"))?;
        out.append(obj)?;
    }
    Ok(out)
}

fn write_word(memory: &mut Vec<u8>, offset: usize, value: U256) {
    mem_extend(memory, offset, 32);
    memory[offset..offset + 32].copy_from_slice(&u256_to_be32(value));
}

fn memory_copy(memory: &mut Vec<u8>, dest: usize, src: &[u8], src_offset: usize, size: usize) {
    mem_extend(memory, dest, size);
    for i in 0..size {
        let byte = src.get(src_offset + i).copied().unwrap_or(0);
        memory[dest + i] = byte;
    }
}

fn memory_copy_within(memory: &mut Vec<u8>, dest: usize, src: usize, size: usize) {
    if size == 0 {
        return;
    }
    mem_extend(memory, dest.max(src), size);
    if dest == src {
        return;
    }
    let chunk = memory[src..src + size].to_vec();
    memory[dest..dest + size].copy_from_slice(&chunk);
}

fn result_dict(
    py: Python<'_>,
    pc: usize,
    gas_used: u64,
    running: bool,
    reverted: bool,
    return_data: Vec<u8>,
    stop_reason: &str,
    host_opcode: Option<u8>,
    error: Option<String>,
    steps: usize,
    stack: Bound<'_, PyList>,
    memory: Bound<'_, PyByteArray>,
    host_logs: &[HostLogEntry],
) -> PyResult<PyObject> {
    let dict = PyDict::new_bound(py);
    dict.set_item("pc", pc)?;
    dict.set_item("gas_used", gas_used)?;
    dict.set_item("running", running)?;
    dict.set_item("reverted", reverted)?;
    dict.set_item("return_data", return_data)?;
    dict.set_item("stop_reason", stop_reason)?;
    dict.set_item("host_opcode", host_opcode)?;
    dict.set_item("error", error)?;
    dict.set_item("steps", steps)?;
    dict.set_item("stack", stack)?;
    dict.set_item("memory", memory)?;
    let logs = PyList::empty_bound(py);
    for (topics, data) in host_logs {
        let entry = PyDict::new_bound(py);
        entry.set_item("topics", topics.clone())?;
        entry.set_item("data", hex::encode(data))?;
        logs.append(entry)?;
    }
    dict.set_item("logs", logs)?;
    Ok(dict.into())
}

fn run_pure_segment_inner(
    py: Python<'_>,
    bytecode: &[u8],
    pc: usize,
    gas_limit: u64,
    gas_used: u64,
    stack_py: &Bound<'_, PyList>,
    memory_py: &Bound<'_, PyByteArray>,
    jumpdest_table: &[u8],
    calldata: &[u8],
    return_data_in: &[u8],
    host_context: Option<&Bound<'_, PyDict>>,
    storage: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
    max_steps: usize,
    host_frame_snapshot: bool,
) -> PyResult<PyObject> {
    if pc >= bytecode.len() {
        let stack = stack_to_pylist(py, &stack_from_py(stack_py)?)?;
        return result_dict(
            py,
            pc,
            gas_used,
            false,
            false,
            Vec::new(),
            "halt",
            None,
            None,
            0,
            stack,
            memory_py.clone(),
            &[],
        );
    }

    let mut stack = stack_from_py(stack_py)?;
    let mut memory = unsafe { memory_py.as_bytes() }.to_vec();
    let mut pc = pc;
    let mut gas_used = gas_used;
    let mut running = true;
    let mut reverted = false;
    let mut return_data = return_data_in.to_vec();
    let mut steps = 0usize;
    let mut handoff = false;
    let mut host_logs: Vec<HostLogEntry> = Vec::new();
    let static_ctx = parse_static_context(host_context)?;
    let read_only = get_inline_read_only(host_context);
    let mut transient: HashMap<U256, U256> = HashMap::new();
    // v1.3.67: Rust-owned storage arena for SLOAD/SSTORE (Priority 34)
    let mut arena: HashMap<U256, U256> = snapshot_storage_dict(storage)?.unwrap_or_default();
    let storage_snap = if host_frame_snapshot {
        Some(arena.clone())
    } else {
        None
    };
    while pc < bytecode.len() && running && steps < max_steps {
        let op = bytecode[pc];
        if opcode_stops_segment(op, host_context, host_bridge) {
            break;
        }

        if (op == 0x54 || op == 0x55) && storage.is_none() {
            handoff = true;
            break;
        }

        let cost = if (0xA0..=0xA4).contains(&op) {
            0
        } else {
            gas_cost(op)
        };
        if cost > 0 {
            if let Err(reason) = consume_gas(&mut gas_used, gas_limit, cost) {
                running = false;
                if host_frame_snapshot {
                    abort_restore_host_storage(storage, &storage_snap, &mut arena, &mut transient)?;
                } else {
                    restore_storage_dict(storage, &arena)?;
                }
                let stack = stack_to_pylist(py, &stack)?;
                let memory_out = PyByteArray::new_bound(py, &memory);
                return result_dict(
                    py,
                    pc,
                    gas_used,
                    running,
                    true,
                    Vec::new(),
                    reason,
                    None,
                    Some(reason.to_string()),
                    steps,
                    stack,
                    memory_out,
                    &host_logs,
                );
            }
        }

        steps += 1;

        let step_result: PyResult<Option<bool>> = (|| -> PyResult<Option<bool>> {
            match op {
                0x00 => {
                    running = false;
                    Ok(Some(false))
                }
                0x01 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, (a.overflowing_add(b).0) & U256_MASK);
                    Ok(Some(false))
                }
                0x02 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, (a.overflowing_mul(b).0) & U256_MASK);
                    Ok(Some(false))
                }
                0x03 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, (a.overflowing_sub(b).0) & U256_MASK);
                    Ok(Some(false))
                }
                0x04 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_div_inner(a, b));
                    Ok(Some(false))
                }
                0x05 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_sdiv_inner(a, b));
                    Ok(Some(false))
                }
                0x06 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_mod_inner(a, b));
                    Ok(Some(false))
                }
                0x07 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_smod_inner(a, b));
                    Ok(Some(false))
                }
                0x08 => {
                    let modulo = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    let a = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_addmod_inner(a, b, modulo));
                    Ok(Some(false))
                }
                0x09 => {
                    let modulo = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    let a = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_mulmod_inner(a, b, modulo));
                    Ok(Some(false))
                }
                0x0A => {
                    let exp = stack_pop(&mut stack)?;
                    let base = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_exp_inner(base, exp));
                    Ok(Some(false))
                }
                0x0B => {
                    let k = stack_pop(&mut stack)?;
                    let x = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_signextend_inner(k.as_u32(), x));
                    Ok(Some(false))
                }
                0x10 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, a & b);
                    Ok(Some(false))
                }
                0x11 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, a | b);
                    Ok(Some(false))
                }
                0x12 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, a ^ b);
                    Ok(Some(false))
                }
                0x13 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_slt_inner(b, a));
                    Ok(Some(false))
                }
                0x14 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_eq_inner(a, b));
                    Ok(Some(false))
                }
                0x15 => {
                    let v = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_iszero_inner(v));
                    Ok(Some(false))
                }
                0x16 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_lt_inner(a, b));
                    Ok(Some(false))
                }
                0x17 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_gt_inner(a, b));
                    Ok(Some(false))
                }
                0x18 => {
                    let a = stack_pop(&mut stack)?;
                    let b = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_slt_inner(a, b));
                    Ok(Some(false))
                }
                0x19 => {
                    let v = stack_pop(&mut stack)?;
                    stack_push(&mut stack, !v);
                    Ok(Some(false))
                }
                0x1A => {
                    let i = stack_pop(&mut stack)?;
                    let x = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_byte_inner(i.as_u32(), x));
                    Ok(Some(false))
                }
                0x1B => {
                    let shift = stack_pop(&mut stack)?;
                    let v = stack_pop(&mut stack)?;
                    stack_push(&mut stack, v << shift.as_u32());
                    Ok(Some(false))
                }
                0x1C => {
                    let shift = stack_pop(&mut stack)?;
                    let v = stack_pop(&mut stack)?;
                    stack_push(&mut stack, v >> shift.as_u32());
                    Ok(Some(false))
                }
                0x1D => {
                    let shift = stack_pop(&mut stack)?;
                    let v = stack_pop(&mut stack)?;
                    stack_push(&mut stack, evm_u256_sar_inner(v, shift.as_u32()));
                    Ok(Some(false))
                }
                0x20 => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    mem_extend(&mut memory, offset, size);
                    let digest = evm_keccak256_memory_inner(&memory, offset, size);
                    stack_push(&mut stack, u256_from_be32(digest));
                    Ok(Some(false))
                }
                0x35 => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let word = evm_calldataload_inner(calldata, offset);
                    stack_push(&mut stack, u256_from_be32(word));
                    Ok(Some(false))
                }
                0x36 => {
                    stack_push(&mut stack, U256::from(calldata.len()));
                    Ok(Some(false))
                }
                0x37 => {
                    let dest = stack_pop(&mut stack)?.as_usize();
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    memory_copy(&mut memory, dest, calldata, offset, size);
                    Ok(Some(false))
                }
                0x38 => {
                    stack_push(&mut stack, U256::from(bytecode.len()));
                    Ok(Some(false))
                }
                0x39 => {
                    let dest = stack_pop(&mut stack)?.as_usize();
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    memory_copy(&mut memory, dest, bytecode, offset, size);
                    Ok(Some(false))
                }
                0x3D => {
                    stack_push(&mut stack, U256::from(return_data.len()));
                    Ok(Some(false))
                }
                0x3E => {
                    let dest = stack_pop(&mut stack)?.as_usize();
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    // Live buffer: CALL/CREATE update `return_data`. The inbound
                    // snapshot `return_data_in` is only the value at segment start.
                    memory_copy(&mut memory, dest, &return_data, offset, size);
                    Ok(Some(false))
                }
                0x30 => {
                    stack_push(&mut stack, static_ctx.address);
                    Ok(Some(false))
                }
                0x32 => {
                    stack_push(&mut stack, static_ctx.origin);
                    Ok(Some(false))
                }
                0x33 => {
                    stack_push(&mut stack, static_ctx.caller);
                    Ok(Some(false))
                }
                0x34 => {
                    stack_push(&mut stack, static_ctx.value);
                    Ok(Some(false))
                }
                0x42 => {
                    stack_push(&mut stack, static_ctx.timestamp);
                    Ok(Some(false))
                }
                0x43 => {
                    stack_push(&mut stack, static_ctx.block_number);
                    Ok(Some(false))
                }
                0x45 => {
                    stack_push(&mut stack, U256::from(gas_limit));
                    Ok(Some(false))
                }
                0x46 => {
                    stack_push(&mut stack, static_ctx.chain_id);
                    Ok(Some(false))
                }
                0x47 => {
                    stack_push(
                        &mut stack,
                        resolve_balance(host_context, host_bridge, static_ctx.address)?,
                    );
                    Ok(Some(false))
                }
                0x48 => {
                    stack_push(&mut stack, static_ctx.base_fee);
                    Ok(Some(false))
                }
                0x49 => {
                    let index = stack_pop(&mut stack)?.as_usize();
                    let val = static_ctx
                        .blob_hashes
                        .get(index)
                        .copied()
                        .unwrap_or(U256::zero());
                    stack_push(&mut stack, val);
                    Ok(Some(false))
                }
                0x4A => {
                    stack_push(&mut stack, static_ctx.blob_base_fee);
                    Ok(Some(false))
                }
                0x3A => {
                    stack_push(&mut stack, static_ctx.gas_price);
                    Ok(Some(false))
                }
                0x41 => {
                    stack_push(&mut stack, static_ctx.coinbase);
                    Ok(Some(false))
                }
                0x44 => {
                    stack_push(&mut stack, static_ctx.difficulty);
                    Ok(Some(false))
                }
                0x31 => {
                    let who = stack_pop(&mut stack)?;
                    stack_push(&mut stack, resolve_balance(host_context, host_bridge, who)?);
                    Ok(Some(false))
                }
                0x3B => {
                    let who = stack_pop(&mut stack)?;
                    stack_push(
                        &mut stack,
                        resolve_code_size(host_context, host_bridge, who)?,
                    );
                    Ok(Some(false))
                }
                0x3F => {
                    let who = stack_pop(&mut stack)?;
                    stack_push(
                        &mut stack,
                        resolve_code_hash(host_context, host_bridge, who)?,
                    );
                    Ok(Some(false))
                }
                0x3C => {
                    let code_offset = stack_pop(&mut stack)?.as_usize();
                    let mem_offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    let who = stack_pop(&mut stack)?;
                    let chunk =
                        resolve_code_copy(host_context, host_bridge, who, code_offset, size)?;
                    memory_copy(&mut memory, mem_offset, &chunk, 0, size);
                    Ok(Some(false))
                }
                0x40 => {
                    let block_num = stack_pop(&mut stack)?;
                    stack_push(
                        &mut stack,
                        resolve_block_hash(host_context, host_bridge, block_num)?,
                    );
                    Ok(Some(false))
                }
                0x50 => {
                    stack_pop(&mut stack)?;
                    Ok(Some(false))
                }
                0x51 => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    mem_extend(&mut memory, offset, 32);
                    let word = evm_memory_read_word_inner(&memory, offset);
                    stack_push(&mut stack, u256_from_be32(word));
                    Ok(Some(false))
                }
                0x52 => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let value = stack_pop(&mut stack)?;
                    write_word(&mut memory, offset, value);
                    Ok(Some(false))
                }
                0x53 => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let value = stack_pop(&mut stack)?;
                    mem_extend(&mut memory, offset, 1);
                    memory[offset] = (value.as_u32() & 0xff) as u8;
                    Ok(Some(false))
                }
                0x54 => {
                    let key = stack_pop(&mut stack)?;
                    stack_push(&mut stack, storage_load(&arena, key));
                    Ok(Some(false))
                }
                0x55 => {
                    if refuse_static_write(read_only, &mut reverted, &mut running) {
                        return Ok(Some(false));
                    }
                    let key = stack_pop(&mut stack)?;
                    let value = stack_pop(&mut stack)?;
                    storage_store(&mut arena, key, value);
                    Ok(Some(false))
                }
                0x56 => {
                    let dest = stack_pop(&mut stack)?.as_usize();
                    if !evm_is_jumpdest_inner(jumpdest_table, dest, bytecode.len()) {
                        Err(pyo3::exceptions::PyRuntimeError::new_err("invalid_jump"))
                    } else {
                        pc = dest;
                        Ok(Some(true))
                    }
                }
                0x57 => {
                    let dest = stack_pop(&mut stack)?.as_usize();
                    let cond = stack_pop(&mut stack)?;
                    if !cond.is_zero() {
                        if !evm_is_jumpdest_inner(jumpdest_table, dest, bytecode.len()) {
                            Err(pyo3::exceptions::PyRuntimeError::new_err("invalid_jump"))
                        } else {
                            pc = dest;
                            Ok(Some(true))
                        }
                    } else {
                        Ok(Some(false))
                    }
                }
                0x5A => {
                    stack_push(&mut stack, U256::from(gas_limit.saturating_sub(gas_used)));
                    Ok(Some(false))
                }
                0x5B => Ok(Some(false)),
                0x5C => {
                    let key = stack_pop(&mut stack)?;
                    let value = transient.get(&key).copied().unwrap_or(U256::zero());
                    stack_push(&mut stack, value);
                    Ok(Some(false))
                }
                0x5D => {
                    if refuse_static_write(read_only, &mut reverted, &mut running) {
                        return Ok(Some(false));
                    }
                    let key = stack_pop(&mut stack)?;
                    let value = stack_pop(&mut stack)?;
                    if value.is_zero() {
                        transient.remove(&key);
                    } else {
                        transient.insert(key, value);
                    }
                    Ok(Some(false))
                }
                0x5E => {
                    let length = stack_pop(&mut stack)?.as_usize();
                    let src = stack_pop(&mut stack)?.as_usize();
                    let dest = stack_pop(&mut stack)?.as_usize();
                    let words = length.div_ceil(32) as u64;
                    if consume_gas(&mut gas_used, gas_limit, 3 * words).is_err() {
                        running = false;
                    } else {
                        memory_copy_within(&mut memory, dest, src, length);
                    }
                    Ok(Some(false))
                }
                0x58 => {
                    stack_push(&mut stack, U256::from(pc));
                    Ok(Some(false))
                }
                0x59 => {
                    stack_push(
                        &mut stack,
                        U256::from(evm_memory_active_bytes(memory.len())),
                    );
                    Ok(Some(false))
                }
                0x5F => {
                    stack_push(&mut stack, U256::zero());
                    Ok(Some(false))
                }
                0xF3 => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    return_data = evm_memory_slice_inner(&memory, offset, size);
                    running = false;
                    Ok(Some(false))
                }
                0xFD => {
                    let offset = stack_pop(&mut stack)?.as_usize();
                    let size = stack_pop(&mut stack)?.as_usize();
                    return_data = evm_memory_slice_inner(&memory, offset, size);
                    reverted = true;
                    running = false;
                    Ok(Some(false))
                }
                0xFE => Err(pyo3::exceptions::PyRuntimeError::new_err("invalid_opcode")),
                op if (0x60..=0x7F).contains(&op) => {
                    let n = (op - 0x5F) as usize;
                    let word = evm_read_push_inner(bytecode, pc, n);
                    stack_push(&mut stack, u256_from_be32(word));
                    pc += n;
                    Ok(Some(false))
                }
                op if (0x80..=0x8F).contains(&op) => {
                    stack_dup(&mut stack, (op - 0x7F) as usize)?;
                    Ok(Some(false))
                }
                op if (0x90..=0x9F).contains(&op) => {
                    stack_swap(&mut stack, (op - 0x8F) as usize)?;
                    Ok(Some(false))
                }
                op if (0xA0..=0xA4).contains(&op) => {
                    if refuse_static_write(read_only, &mut reverted, &mut running) {
                        return Ok(Some(false));
                    }
                    // v1.3.57: LOG body fully in Rust (optional emit_log side-effect only).
                    execute_log_native(
                        py,
                        host_context,
                        op,
                        &mut stack,
                        &mut memory,
                        &mut gas_used,
                        gas_limit,
                        &mut host_logs,
                    )?;
                    Ok(Some(false))
                }
                op if matches!(op, 0xF1 | 0xF2 | 0xF4 | 0xFA)
                    && hook_contract_call(host_context).is_some() =>
                {
                    execute_call_native(
                        py,
                        host_context,
                        host_bridge,
                        op,
                        &mut stack,
                        &mut memory,
                        gas_limit,
                        &mut gas_used,
                        storage,
                        &mut arena,
                        &mut return_data,
                    )?;
                    Ok(Some(false))
                }
                op if matches!(op, 0xF0 | 0xF5)
                    && (hook_contract_create(host_context).is_some()
                        || bridge_state_has_codes(host_context)) =>
                {
                    if refuse_static_write(read_only, &mut reverted, &mut running) {
                        return Ok(Some(false));
                    }
                    execute_create_native(
                        py,
                        host_context,
                        op,
                        &mut stack,
                        &mut memory,
                        gas_limit,
                        &mut gas_used,
                    )?;
                    Ok(Some(false))
                }
                0xFF if hook_selfdestruct(host_context).is_some() => {
                    if refuse_static_write(read_only, &mut reverted, &mut running) {
                        return Ok(Some(false));
                    }
                    execute_selfdestruct_native(host_context, &mut stack, &mut running)?;
                    Ok(Some(false))
                }
                op if evm_opcode_is_host(op) => {
                    let bridge = host_bridge.ok_or_else(|| {
                        pyo3::exceptions::PyRuntimeError::new_err("host_bridge_unavailable")
                    })?;
                    apply_runtime_host_op(
                        py,
                        bridge,
                        op,
                        &mut stack,
                        &mut memory,
                        gas_limit,
                        &mut gas_used,
                        storage,
                        &mut return_data,
                        &mut running,
                        &mut reverted,
                    )?;
                    Ok(Some(false))
                }
                _ => Ok(None),
            }
        })();

        match step_result {
            Ok(None) => {
                handoff = true;
                break;
            }
            Ok(Some(true)) => continue,
            Ok(Some(false)) => {}
            Err(err) => {
                let error_msg = err.to_string();
                running = false;
                if error_msg.contains("static_write_protection") {
                    reverted = true;
                }
                if host_frame_snapshot {
                    abort_restore_host_storage(storage, &storage_snap, &mut arena, &mut transient)?;
                } else {
                    restore_storage_dict(storage, &arena)?;
                }
                let stop = if error_msg.contains("out_of_gas") {
                    "out_of_gas"
                } else if error_msg.contains("static_write_protection") {
                    "revert"
                } else {
                    "error"
                };
                let stack = stack_to_pylist(py, &stack)?;
                let memory_out = PyByteArray::new_bound(py, &memory);
                return result_dict(
                    py,
                    pc,
                    gas_used,
                    running,
                    reverted,
                    return_data,
                    stop,
                    None,
                    Some(error_msg),
                    steps,
                    stack,
                    memory_out,
                    &host_logs,
                );
            }
        }

        pc += 1;
    }

    let stop_reason = if handoff || (steps >= max_steps && running) {
        "handoff"
    } else if pc < bytecode.len() && opcode_stops_segment(bytecode[pc], host_context, host_bridge) {
        "host"
    } else if !running {
        if reverted {
            "revert"
        } else if !return_data.is_empty() {
            "return"
        } else {
            "halt"
        }
    } else {
        "halt"
    };

    if host_frame_snapshot && reverted {
        abort_restore_host_storage(storage, &storage_snap, &mut arena, &mut transient)?;
    } else {
        // Flush Rust storage arena back to Python dict (v1.3.67).
        restore_storage_dict(storage, &arena)?;
    }

    let host_opcode = if stop_reason == "host" {
        Some(bytecode[pc])
    } else {
        None
    };

    let stack = stack_to_pylist(py, &stack)?;
    let memory_out = PyByteArray::new_bound(py, &memory);
    result_dict(
        py,
        pc,
        gas_used,
        running,
        reverted,
        return_data,
        stop_reason,
        host_opcode,
        None,
        steps,
        stack,
        memory_out,
        &host_logs,
    )
}

#[pyfunction]
#[pyo3(name = "evm_opcode_is_bridge")]
pub fn evm_opcode_is_bridge_py(op: u8) -> PyResult<bool> {
    Ok(evm_opcode_is_bridge(op))
}

#[pyfunction]
#[pyo3(name = "evm_opcode_is_host")]
pub fn evm_opcode_is_host_py(op: u8) -> PyResult<bool> {
    Ok(evm_opcode_is_host(op))
}

#[pyfunction]
#[pyo3(name = "evm_bytecode_is_nested_native_eligible")]
pub fn evm_bytecode_is_nested_native_eligible_py(bytecode: Vec<u8>) -> PyResult<bool> {
    Ok(bytecode_is_nested_native_eligible(&bytecode))
}

#[pyfunction]
#[pyo3(name = "evm_bytecode_is_inline_call_frame_eligible")]
pub fn evm_bytecode_is_inline_call_frame_eligible_py(bytecode: Vec<u8>) -> PyResult<bool> {
    Ok(bytecode_is_inline_call_frame_eligible(&bytecode))
}

#[pyfunction]
#[pyo3(name = "evm_run_pure_until_host")]
#[pyo3(signature = (bytecode, pc, gas_limit, gas_used, stack, memory, jumpdest_table, calldata, return_data, host_context=None, storage=None, host_bridge=None))]
pub fn evm_run_pure_until_host_py(
    py: Python<'_>,
    bytecode: Vec<u8>,
    pc: usize,
    gas_limit: u64,
    gas_used: u64,
    stack: &Bound<'_, PyList>,
    memory: &Bound<'_, PyByteArray>,
    jumpdest_table: Vec<u8>,
    calldata: Vec<u8>,
    return_data: Vec<u8>,
    host_context: Option<&Bound<'_, PyDict>>,
    storage: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
) -> PyResult<PyObject> {
    run_pure_segment_inner(
        py,
        &bytecode,
        pc,
        gas_limit,
        gas_used,
        stack,
        memory,
        &jumpdest_table,
        &calldata,
        &return_data,
        host_context,
        storage,
        host_bridge,
        MAX_PURE_STEPS,
        false,
    )
}

#[pyfunction]
#[pyo3(name = "evm_run_until_halt")]
#[pyo3(signature = (bytecode, pc, gas_limit, gas_used, stack, memory, jumpdest_table, calldata, return_data, host_context=None, storage=None, host_bridge=None))]
pub fn evm_run_until_halt_py(
    py: Python<'_>,
    bytecode: Vec<u8>,
    pc: usize,
    gas_limit: u64,
    gas_used: u64,
    stack: &Bound<'_, PyList>,
    memory: &Bound<'_, PyByteArray>,
    jumpdest_table: Vec<u8>,
    calldata: Vec<u8>,
    return_data: Vec<u8>,
    host_context: Option<&Bound<'_, PyDict>>,
    storage: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
) -> PyResult<PyObject> {
    run_pure_segment_inner(
        py,
        &bytecode,
        pc,
        gas_limit,
        gas_used,
        stack,
        memory,
        &jumpdest_table,
        &calldata,
        &return_data,
        host_context,
        storage,
        host_bridge,
        MAX_FULL_STEPS,
        true,
    )
}

/// Nested CALL child frame: pure opcodes only (no host_bridge).
/// Reuses the full-step runner; stops with `host`/`handoff` if child needs Python.
#[pyfunction]
#[pyo3(name = "evm_run_nested_pure_frame")]
#[pyo3(signature = (bytecode, gas_limit, calldata, host_context=None, storage=None))]
pub fn evm_run_nested_pure_frame_py(
    py: Python<'_>,
    bytecode: Vec<u8>,
    gas_limit: u64,
    calldata: Vec<u8>,
    host_context: Option<&Bound<'_, PyDict>>,
    storage: Option<&Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let jumpdest = crate::evm_build_jumpdest_table_inner(&bytecode);
    let stack = PyList::empty_bound(py);
    let memory = PyByteArray::new_bound(py, &[]);
    run_pure_segment_inner(
        py,
        &bytecode,
        0,
        gas_limit,
        0,
        &stack,
        &memory,
        &jumpdest,
        &calldata,
        &[],
        host_context,
        storage,
        None,
        MAX_FULL_STEPS,
        true,
    )
}

/// Nested CALL child with runtime host_bridge and/or thin host hooks
/// (CALL/CREATE/LOG bodies in Rust; state via Python callbacks).
/// Same dispatch loop as `evm_run_until_halt`, started at pc=0 for a fresh child frame.
#[pyfunction]
#[pyo3(name = "evm_run_nested_host_frame")]
#[pyo3(signature = (bytecode, gas_limit, calldata, host_context=None, storage=None, host_bridge=None))]
pub fn evm_run_nested_host_frame_py(
    py: Python<'_>,
    bytecode: Vec<u8>,
    gas_limit: u64,
    calldata: Vec<u8>,
    host_context: Option<&Bound<'_, PyDict>>,
    storage: Option<&Bound<'_, PyDict>>,
    host_bridge: Option<&Bound<'_, PyAny>>,
) -> PyResult<PyObject> {
    let jumpdest = crate::evm_build_jumpdest_table_inner(&bytecode);
    let stack = PyList::empty_bound(py);
    let memory = PyByteArray::new_bound(py, &[]);
    run_pure_segment_inner(
        py,
        &bytecode,
        0,
        gas_limit,
        0,
        &stack,
        &memory,
        &jumpdest,
        &calldata,
        &[],
        host_context,
        storage,
        host_bridge,
        MAX_FULL_STEPS,
        true,
    )
}

#[pyfunction]
#[pyo3(name = "evm_host_snapshot_storage")]
pub fn evm_host_snapshot_storage_py(storage: &Bound<'_, PyDict>) -> PyResult<PyObject> {
    let snap = snapshot_storage_dict(Some(storage))?.unwrap_or_default();
    let out = PyDict::new_bound(storage.py());
    let py = storage.py();
    for (key, value) in snap {
        out.set_item(u256_to_py_int(py, key)?, u256_to_py_int(py, value)?)?;
    }
    Ok(out.into())
}

#[pyfunction]
#[pyo3(name = "evm_host_restore_storage")]
pub fn evm_host_restore_storage_py(
    storage: &Bound<'_, PyDict>,
    snapshot: &Bound<'_, PyDict>,
) -> PyResult<()> {
    let snap = snapshot_storage_dict(Some(snapshot))?.unwrap_or_default();
    restore_storage_dict(Some(storage), &snap)
}
