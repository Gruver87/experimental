//! RocksDB engine for Absolute chain storage (LSM, concurrent reads).
//!
//! Optional column-family split (`column_families=true`):
//! - `blocks` — key prefixes 0x01..=0x08 (blocks, txs, receipts, indexes)
//! - `state`  — key prefix 0x10 (accounts)
//! - `index`  — validators / meta / audits / nft / evm logs / …
//!
//! Reads fall back to `default` so existing single-CF databases keep working
//! after enabling the flag (new writes go to the target CF).

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use rocksdb::{
    BlockBasedOptions, Cache, ColumnFamily, ColumnFamilyDescriptor, Direction, IteratorMode,
    Options, WriteBatch, WriteOptions, DB,
};
use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

const CF_DEFAULT: &str = "default";
const CF_BLOCKS: &str = "blocks";
const CF_STATE: &str = "state";
const CF_INDEX: &str = "index";
const CF_NAMES: &[&str] = &[CF_DEFAULT, CF_BLOCKS, CF_STATE, CF_INDEX];

fn cf_name_for_key(key: &[u8]) -> &'static str {
    match key.first() {
        Some(1..=8) => CF_BLOCKS,
        Some(0x10) => CF_STATE,
        _ => CF_INDEX,
    }
}

enum BatchOp {
    Put { key: Vec<u8>, value: Vec<u8> },
    Delete { key: Vec<u8> },
}

#[pyclass]
pub struct RocksWriteBatch {
    ops: Vec<BatchOp>,
}

#[pymethods]
impl RocksWriteBatch {
    #[new]
    fn new() -> Self {
        Self { ops: Vec::new() }
    }

    fn put(&mut self, key: &[u8], value: &[u8]) {
        self.ops.push(BatchOp::Put {
            key: key.to_vec(),
            value: value.to_vec(),
        });
    }

    fn delete(&mut self, key: &[u8]) {
        self.ops.push(BatchOp::Delete { key: key.to_vec() });
    }

    fn clear(&mut self) {
        self.ops.clear();
    }

    fn len(&self) -> usize {
        self.ops.len()
    }
}

#[pyclass]
pub struct RocksEngine {
    db: Arc<DB>,
    sync_writes: bool,
    block_cache_mb: u32,
    write_buffer_mb: u32,
    column_families: bool,
    _block_cache: Option<Arc<Cache>>,
}

const STORAGE_PROPERTY_KEYS: &[&str] = &[
    "rocksdb.estimate-num-keys",
    "rocksdb.cur-size-all-mem-tables",
    "rocksdb.estimate-table-readers-mem",
    "rocksdb.total-sst-files-size",
    "rocksdb.live-sst-files-size",
    "rocksdb.num-immutable-mem-table",
    "rocksdb.num-running-compactions",
    "rocksdb.num-running-flushes",
];

fn apply_common_opts(
    opts: &mut Options,
    create_if_missing: bool,
    block_cache_mb: u32,
    write_buffer_mb: u32,
) -> Option<Arc<Cache>> {
    opts.create_if_missing(create_if_missing);
    opts.set_max_open_files(512);
    opts.set_bytes_per_sync(1_048_576);
    opts.set_wal_bytes_per_sync(1_048_576);

    let mut block_cache = None;
    if block_cache_mb > 0 {
        let cache = Cache::new_lru_cache((block_cache_mb as usize) * 1024 * 1024);
        let mut block_opts = BlockBasedOptions::default();
        block_opts.set_block_cache(&cache);
        opts.set_block_based_table_factory(&block_opts);
        block_cache = Some(Arc::new(cache));
    }
    if write_buffer_mb > 0 {
        opts.set_write_buffer_size((write_buffer_mb as usize) * 1024 * 1024);
    }
    block_cache
}

#[pymethods]
impl RocksEngine {
    #[new]
    #[pyo3(signature = (
        path,
        *,
        create_if_missing=true,
        sync_writes=false,
        block_cache_mb=0,
        write_buffer_mb=0,
        read_only=false,
        column_families=false
    ))]
    fn new(
        path: &str,
        create_if_missing: bool,
        sync_writes: bool,
        block_cache_mb: u32,
        write_buffer_mb: u32,
        read_only: bool,
        column_families: bool,
    ) -> PyResult<Self> {
        let mut opts = Options::default();
        let block_cache = apply_common_opts(
            &mut opts,
            create_if_missing,
            block_cache_mb,
            write_buffer_mb,
        );

        let db = if column_families {
            opts.create_missing_column_families(true);
            let cf_opts = Options::default();
            let cfs: Vec<ColumnFamilyDescriptor> = CF_NAMES
                .iter()
                .map(|name| ColumnFamilyDescriptor::new(*name, cf_opts.clone()))
                .collect();
            if read_only {
                opts.create_if_missing(false);
                opts.create_missing_column_families(false);
                DB::open_cf_for_read_only(&opts, path, CF_NAMES, false)
            } else {
                DB::open_cf_descriptors(&opts, path, cfs)
            }
        } else {
            opts.create_missing_column_families(false);
            if read_only {
                opts.create_if_missing(false);
                DB::open_for_read_only(&opts, path, false)
            } else {
                DB::open(&opts, path)
            }
        }
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;

        Ok(Self {
            db: Arc::new(db),
            sync_writes,
            block_cache_mb,
            write_buffer_mb,
            column_families,
            _block_cache: block_cache,
        })
    }

    fn get_bytes(&self, key: &[u8]) -> PyResult<Option<Vec<u8>>> {
        if !self.column_families {
            return self.db.get(key).map_err(map_db_err);
        }
        let cf = self.cf_handle(cf_name_for_key(key))?;
        if let Some(value) = self.db.get_cf(cf, key).map_err(map_db_err)? {
            return Ok(Some(value));
        }
        let default_cf = self.cf_handle(CF_DEFAULT)?;
        self.db.get_cf(default_cf, key).map_err(map_db_err)
    }

    fn get<'py>(&self, py: Python<'py>, key: &[u8]) -> PyResult<Option<Py<PyBytes>>> {
        match self.get_bytes(key)? {
            Some(value) => Ok(Some(PyBytes::new_bound(py, &value).unbind())),
            None => Ok(None),
        }
    }

    /// Decode account JSON blob for `address` into a structured view (v1.3.58).
    fn get_account_view(&self, py: Python<'_>, address: String) -> PyResult<PyObject> {
        let addr = address.trim().to_ascii_lowercase();
        let mut key = Vec::with_capacity(1 + addr.len());
        key.push(0x10);
        key.extend_from_slice(addr.as_bytes());
        match self.get_bytes(&key)? {
            Some(blob) => crate::account_view::decode_account_view_bytes(py, &blob, &addr),
            None => crate::account_view::decode_account_view_bytes(py, &[], &addr),
        }
    }

    /// Batch-load account JSON rows for writeback preload (v1.3.64).
    /// `addresses_json`: `["0xaddr", ...]` → `{ "0xaddr": { ...row... }, ... }`
    /// Missing / corrupt blobs become empty default rows (address filled).
    fn get_account_rows(&self, addresses_json: &str) -> PyResult<String> {
        use serde_json::{Map, Value};
        let parsed: Value = serde_json::from_str(addresses_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("addresses_json invalid: {e}"))
        })?;
        let arr = parsed.as_array().ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err("addresses_json must be an array")
        })?;
        let mut out = Map::new();
        for item in arr {
            let addr_raw = match item.as_str() {
                Some(s) => s,
                None => continue,
            };
            let addr = addr_raw.trim().to_ascii_lowercase();
            if addr.is_empty() || out.contains_key(&addr) {
                continue;
            }
            let mut key = Vec::with_capacity(1 + addr.len());
            key.push(0x10);
            key.extend_from_slice(addr.as_bytes());
            let row = match self.get_bytes(&key)? {
                Some(blob) => match crate::account_row::account_blob_to_value(&blob) {
                    Ok(Value::Object(mut map)) => {
                        map.insert("address".into(), Value::String(addr.clone()));
                        Value::Object(map)
                    }
                    _ => {
                        return Err(pyo3::exceptions::PyValueError::new_err(format!(
                            "corrupt_account_blob:{addr}"
                        )));
                    }
                },
                None => empty_account_row_value(&addr),
            };
            out.insert(addr, row);
        }
        Ok(Value::Object(out).to_string())
    }

    /// Batch-put account JSON rows (caller must hold store write lock) — v1.3.62.
    /// `accounts_json`: `{ "0xaddr": { ...account fields... }, ... }`
    fn commit_account_rows(&self, accounts_json: &str) -> PyResult<usize> {
        let (accounts, logs) = self.commit_writeback_bundle(accounts_json, "[]")?;
        let _ = logs;
        Ok(accounts)
    }

    /// Single WriteBatch for account rows + dual-indexed EVM log rows (v1.3.63).
    /// `logs_json`: `[{block_height, tx_hash, log_index, contract_address, topics, data, timestamp}, ...]`
    /// Returns `(accounts_written, logs_written)`.
    fn commit_writeback_bundle(
        &self,
        accounts_json: &str,
        logs_json: &str,
    ) -> PyResult<(usize, usize)> {
        use serde_json::Value;

        let parsed: Value = serde_json::from_str(accounts_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("accounts_json invalid: {e}"))
        })?;
        let obj = parsed.as_object().ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err("accounts_json must be an object")
        })?;
        let logs_parsed: Value = serde_json::from_str(logs_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("logs_json invalid: {e}"))
        })?;
        let logs_arr = logs_parsed
            .as_array()
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("logs_json must be an array"))?;

        let mut batch = RocksWriteBatch { ops: Vec::new() };
        let mut account_count = 0usize;
        for (addr_raw, row) in obj {
            let addr = addr_raw.trim().to_ascii_lowercase();
            if addr.is_empty() {
                continue;
            }
            let mut key = Vec::with_capacity(1 + addr.len());
            key.push(0x10);
            key.extend_from_slice(addr.as_bytes());
            let mut row_obj = match row {
                Value::Object(map) => map.clone(),
                _ => continue,
            };
            row_obj.insert("address".into(), Value::String(addr.clone()));
            // v1.3.147: pack typed ABAR value (reads still accept legacy JSON).
            let blob = crate::account_row::pack_account_row_value(&Value::Object(row_obj))
                .map_err(|e| {
                    pyo3::exceptions::PyValueError::new_err(format!("account encode failed: {e}"))
                })?;
            batch.put(&key, &blob);
            account_count += 1;
        }

        let mut log_count = 0usize;
        for entry in logs_arr {
            let row_obj = match entry {
                Value::Object(map) => map.clone(),
                _ => continue,
            };
            let block_height = row_obj
                .get("block_height")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let tx_hash = row_obj
                .get("tx_hash")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let log_index = row_obj
                .get("log_index")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let blob = serde_json::to_vec(&Value::Object(row_obj)).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("log encode failed: {e}"))
            })?;
            let key_h = key_evm_log_bytes(block_height, &tx_hash, log_index)?;
            let key_tx = key_evm_log_tx_bytes(&tx_hash, log_index)?;
            batch.put(&key_h, &blob);
            batch.put(&key_tx, &blob);
            log_count += 1;
        }

        if account_count > 0 || log_count > 0 {
            self.write_batch(&mut batch)?;
        }
        Ok((account_count, log_count))
    }

    fn put(&self, key: &[u8], value: &[u8]) -> PyResult<()> {
        let mut write_opts = WriteOptions::default();
        write_opts.set_sync(self.sync_writes);
        if !self.column_families {
            return self.db.put_opt(key, value, &write_opts).map_err(map_db_err);
        }
        let cf = self.cf_handle(cf_name_for_key(key))?;
        self.db
            .put_cf_opt(cf, key, value, &write_opts)
            .map_err(map_db_err)
    }

    fn delete(&self, key: &[u8]) -> PyResult<()> {
        let mut write_opts = WriteOptions::default();
        write_opts.set_sync(self.sync_writes);
        if !self.column_families {
            return self.db.delete_opt(key, &write_opts).map_err(map_db_err);
        }
        let cf = self.cf_handle(cf_name_for_key(key))?;
        self.db
            .delete_cf_opt(cf, key, &write_opts)
            .map_err(map_db_err)?;
        // Also clear legacy default copy if present.
        let default_cf = self.cf_handle(CF_DEFAULT)?;
        let _ = self.db.delete_cf_opt(default_cf, key, &write_opts);
        Ok(())
    }

    fn write_batch(&self, batch: &mut RocksWriteBatch) -> PyResult<()> {
        let mut write_opts = WriteOptions::default();
        write_opts.set_sync(self.sync_writes);
        let ops = std::mem::take(&mut batch.ops);
        let mut wb = WriteBatch::default();
        if !self.column_families {
            for op in ops {
                match op {
                    BatchOp::Put { key, value } => wb.put(key, value),
                    BatchOp::Delete { key } => wb.delete(key),
                }
            }
        } else {
            for op in ops {
                match op {
                    BatchOp::Put { key, value } => {
                        let cf = self.cf_handle(cf_name_for_key(&key))?;
                        wb.put_cf(cf, key, value);
                    }
                    BatchOp::Delete { key } => {
                        let cf = self.cf_handle(cf_name_for_key(&key))?;
                        wb.delete_cf(cf, &key);
                        let default_cf = self.cf_handle(CF_DEFAULT)?;
                        wb.delete_cf(default_cf, key);
                    }
                }
            }
        }
        self.db.write_opt(wb, &write_opts).map_err(map_db_err)
    }

    #[pyo3(signature = (prefix, limit=10_000))]
    fn prefix_scan<'py>(
        &self,
        py: Python<'py>,
        prefix: &[u8],
        limit: usize,
    ) -> PyResult<Vec<(Py<PyBytes>, Py<PyBytes>)>> {
        if !self.column_families {
            return self.prefix_scan_single(py, None, prefix, limit);
        }
        let mut merged: BTreeMap<Vec<u8>, Vec<u8>> = BTreeMap::new();
        let cf = cf_name_for_key(prefix);
        self.collect_prefix_into(&mut merged, cf, prefix, limit)?;
        if cf != CF_DEFAULT {
            self.collect_prefix_into(&mut merged, CF_DEFAULT, prefix, limit)?;
        }
        let mut out = Vec::with_capacity(merged.len().min(limit));
        for (key, value) in merged.into_iter().take(limit) {
            out.push((
                PyBytes::new_bound(py, &key).unbind(),
                PyBytes::new_bound(py, &value).unbind(),
            ));
        }
        Ok(out)
    }

    /// Last key/value under prefix (reverse seek) — v1.3.66 tip lookup.
    fn prefix_last<'py>(
        &self,
        py: Python<'py>,
        prefix: &[u8],
    ) -> PyResult<Option<(Py<PyBytes>, Py<PyBytes>)>> {
        let row = self.prefix_last_bytes(prefix)?;
        Ok(row.map(|(k, v)| {
            (
                PyBytes::new_bound(py, &k).unbind(),
                PyBytes::new_bound(py, &v).unbind(),
            )
        }))
    }

    fn checkpoint(&self, dest: &str) -> PyResult<()> {
        let checkpoint =
            rocksdb::checkpoint::Checkpoint::new(self.db.as_ref()).map_err(map_db_err)?;
        checkpoint.create_checkpoint(dest).map_err(map_db_err)
    }

    fn path(&self) -> PyResult<String> {
        Ok(self.db.path().to_str().unwrap_or("").to_string())
    }

    fn tuning_config(&self) -> PyResult<HashMap<String, u32>> {
        let mut out = HashMap::new();
        out.insert("block_cache_mb".to_string(), self.block_cache_mb);
        out.insert("write_buffer_mb".to_string(), self.write_buffer_mb);
        out.insert(
            "sync_writes".to_string(),
            if self.sync_writes { 1 } else { 0 },
        );
        out.insert(
            "column_families".to_string(),
            if self.column_families { 1 } else { 0 },
        );
        Ok(out)
    }

    fn column_family_names(&self) -> PyResult<Vec<String>> {
        if !self.column_families {
            return Ok(vec![CF_DEFAULT.to_string()]);
        }
        Ok(CF_NAMES.iter().map(|s| (*s).to_string()).collect())
    }

    fn storage_properties<'py>(&self, py: Python<'py>) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new_bound(py);
        for key in STORAGE_PROPERTY_KEYS {
            if let Ok(Some(value)) = self.db.property_value(*key) {
                dict.set_item(*key, value)?;
            }
        }
        if self.column_families {
            let mut keys: u64 = 0;
            for name in CF_NAMES {
                let Ok(cf) = self.cf_handle(name) else {
                    continue;
                };
                if let Ok(Some(value)) = self.db.property_value_cf(cf, "rocksdb.estimate-num-keys")
                {
                    if let Ok(n) = value.trim().parse::<u64>() {
                        keys = keys.saturating_add(n);
                    }
                }
            }
            dict.set_item("rocksdb.estimate-num-keys-all-cf", keys.to_string())?;
        }
        Ok(dict.unbind())
    }

    #[pyo3(signature = (prefix, limit=100_000))]
    fn state_root_from_account_prefix(&self, prefix: &[u8], limit: usize) -> PyResult<String> {
        if limit > crate::MAX_STATE_ROOT_BLOBS {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "prefix_scan_limit_too_large: {} > {}",
                limit,
                crate::MAX_STATE_ROOT_BLOBS
            )));
        }
        let rows = if !self.column_families {
            self.prefix_scan_bytes(None, prefix, limit)?
        } else {
            let mut merged: BTreeMap<Vec<u8>, Vec<u8>> = BTreeMap::new();
            self.collect_prefix_into(&mut merged, CF_STATE, prefix, limit)?;
            self.collect_prefix_into(&mut merged, CF_DEFAULT, prefix, limit)?;
            merged.into_iter().take(limit).collect()
        };
        let mut values = Vec::with_capacity(rows.len());
        for (_key, value) in rows {
            if value.len() > crate::MAX_ACCOUNT_BLOB_BYTES {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "account_blob_too_large: {} > {} bytes",
                    value.len(),
                    crate::MAX_ACCOUNT_BLOB_BYTES
                )));
            }
            values.push(value);
        }
        crate::state_trie::compute_state_root_from_account_blobs(values)
    }
}

impl RocksEngine {
    fn cf_handle(&self, name: &str) -> PyResult<&ColumnFamily> {
        self.db.cf_handle(name).ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "rocksdb_missing_column_family:{name}"
            ))
        })
    }

    fn collect_prefix_into(
        &self,
        out: &mut BTreeMap<Vec<u8>, Vec<u8>>,
        cf_name: &str,
        prefix: &[u8],
        limit: usize,
    ) -> PyResult<()> {
        if out.len() >= limit {
            return Ok(());
        }
        let cf = self.cf_handle(cf_name)?;
        let iter = self
            .db
            .iterator_cf(cf, IteratorMode::From(prefix, Direction::Forward));
        for item in iter {
            if out.len() >= limit {
                break;
            }
            let (key, value) = item.map_err(map_db_err)?;
            if !key.starts_with(prefix) {
                break;
            }
            out.entry(key.to_vec()).or_insert_with(|| value.to_vec());
        }
        Ok(())
    }

    fn prefix_scan_bytes(
        &self,
        cf_name: Option<&str>,
        prefix: &[u8],
        limit: usize,
    ) -> PyResult<Vec<(Vec<u8>, Vec<u8>)>> {
        let mut out = Vec::new();
        let iter = if let Some(name) = cf_name {
            let cf = self.cf_handle(name)?;
            self.db
                .iterator_cf(cf, IteratorMode::From(prefix, Direction::Forward))
        } else {
            self.db
                .iterator(IteratorMode::From(prefix, Direction::Forward))
        };
        for item in iter.take(limit) {
            let (key, value) = item.map_err(map_db_err)?;
            if !key.starts_with(prefix) {
                break;
            }
            out.push((key.to_vec(), value.to_vec()));
        }
        Ok(out)
    }

    fn prefix_last_in_cf(
        &self,
        cf_name: &str,
        prefix: &[u8],
        seek: &[u8],
    ) -> PyResult<Option<(Vec<u8>, Vec<u8>)>> {
        let cf = self.cf_handle(cf_name)?;
        let mut iter = self
            .db
            .iterator_cf(cf, IteratorMode::From(seek, Direction::Reverse));
        if let Some(item) = iter.next() {
            let (key, value) = item.map_err(map_db_err)?;
            if key.starts_with(prefix) {
                return Ok(Some((key.to_vec(), value.to_vec())));
            }
        }
        Ok(None)
    }

    fn prefix_last_bytes(&self, prefix: &[u8]) -> PyResult<Option<(Vec<u8>, Vec<u8>)>> {
        let mut seek = prefix.to_vec();
        seek.extend(std::iter::repeat_n(0xffu8, 32));
        if !self.column_families {
            let mut iter = self
                .db
                .iterator(IteratorMode::From(&seek, Direction::Reverse));
            if let Some(item) = iter.next() {
                let (key, value) = item.map_err(map_db_err)?;
                if key.starts_with(prefix) {
                    return Ok(Some((key.to_vec(), value.to_vec())));
                }
            }
            return Ok(None);
        }
        // Dual-CF prefix_last: pick the lexicographically last key across
        // target CF and legacy default (primary-first would hide a later default key).
        let mut best: Option<(Vec<u8>, Vec<u8>)> = None;
        for cf_name in [cf_name_for_key(prefix), CF_DEFAULT] {
            if let Some((key, value)) = self.prefix_last_in_cf(cf_name, prefix, &seek)? {
                match &best {
                    Some((best_key, _)) if key.as_slice() <= best_key.as_slice() => {}
                    _ => best = Some((key, value)),
                }
            }
        }
        Ok(best)
    }

    fn prefix_scan_single<'py>(
        &self,
        py: Python<'py>,
        cf_name: Option<&str>,
        prefix: &[u8],
        limit: usize,
    ) -> PyResult<Vec<(Py<PyBytes>, Py<PyBytes>)>> {
        let rows = self.prefix_scan_bytes(cf_name, prefix, limit)?;
        let mut out = Vec::with_capacity(rows.len());
        for (key, value) in rows {
            out.push((
                PyBytes::new_bound(py, &key).unbind(),
                PyBytes::new_bound(py, &value).unbind(),
            ));
        }
        Ok(out)
    }
}

fn empty_account_row_value(addr: &str) -> serde_json::Value {
    serde_json::json!({
        "address": addr,
        "balance": 0.0,
        "balance_satoshi": 0,
        "nonce": 0,
        "code": "",
        "storage": "{}"
    })
}

fn tx_hash_body_bytes(tx_hash: &str) -> PyResult<Vec<u8>> {
    let mut h = tx_hash.trim().to_ascii_lowercase();
    if let Some(rest) = h.strip_prefix("0x") {
        h = rest.to_string();
    }
    if h.len() > 64 {
        h = h[h.len() - 64..].to_string();
    }
    while h.len() < 64 {
        h.insert(0, '0');
    }
    hex::decode(&h)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid tx hash hex: {e}")))
}

fn key_evm_log_bytes(block_height: u64, tx_hash: &str, log_index: u64) -> PyResult<Vec<u8>> {
    let body = tx_hash_body_bytes(tx_hash)?;
    let mut out = Vec::with_capacity(1 + 8 + body.len() + 4);
    out.push(0x52);
    out.extend_from_slice(&block_height.to_be_bytes());
    out.extend_from_slice(&body);
    out.extend_from_slice(&(log_index as u32).to_be_bytes());
    Ok(out)
}

fn key_evm_log_tx_bytes(tx_hash: &str, log_index: u64) -> PyResult<Vec<u8>> {
    let body = tx_hash_body_bytes(tx_hash)?;
    let mut out = Vec::with_capacity(1 + body.len() + 4);
    out.push(0x53);
    out.extend_from_slice(&body);
    out.extend_from_slice(&(log_index as u32).to_be_bytes());
    Ok(out)
}

fn map_db_err(err: rocksdb::Error) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyOSError, _>(err.to_string())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RocksEngine>()?;
    m.add_class::<RocksWriteBatch>()?;
    Ok(())
}
