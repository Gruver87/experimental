//! ADR 0021 phase 2 — fee-sorted mempool store (hot path).
//!
//! Validation (sig / chain / TxPipeline) stays in Python. This module owns the
//! pending set + fee ordering under a Mutex. Lock order with Python: always
//! acquire Python `Mempool.lock` (RLock) first, then this Mutex — never reverse.
//!
//! Sort / min-fee / eviction use integer `fee_satoshi` (fail-closed money path).
//! ABS float `fee` is retained for wire/display dual-write only.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;
use std::sync::Mutex;

#[derive(Clone, Debug)]
struct TxEntry {
    tx_hash: String,
    from_addr: String,
    to_addr: String,
    amount: f64,
    fee: f64,
    fee_satoshi: i64,
    nonce: i64,
    signature: String,
    public_key: String,
    data: String,
    gas: i64,
    timestamp: f64,
}

struct StoreInner {
    txs: HashMap<String, TxEntry>,
    max_size: usize,
    min_fee_satoshi: i64,
}

impl StoreInner {
    fn new(max_size: usize, min_fee_satoshi: i64) -> Self {
        Self {
            txs: HashMap::new(),
            max_size: max_size.max(1),
            min_fee_satoshi: min_fee_satoshi.max(0),
        }
    }

    fn cleanup_cheapest_10pct(&mut self) {
        if self.txs.len() < (self.max_size as f64 * 0.8) as usize {
            return;
        }
        let mut ranked: Vec<(String, i64)> = self
            .txs
            .iter()
            .map(|(h, e)| (h.clone(), e.fee_satoshi))
            .collect();
        ranked.sort_by(|a, b| a.1.cmp(&b.1).then_with(|| a.0.cmp(&b.0)));
        let to_remove = (self.txs.len() as f64 * 0.1).floor() as usize;
        for (hash, _) in ranked.into_iter().take(to_remove) {
            self.txs.remove(&hash);
        }
    }

    fn insert(&mut self, entry: TxEntry) -> bool {
        if self.txs.contains_key(&entry.tx_hash) {
            return false;
        }
        if entry.fee_satoshi < self.min_fee_satoshi {
            return false;
        }
        if self.txs.len() >= self.max_size {
            self.cleanup_cheapest_10pct();
        }
        // Still full after cleanup — refuse (fail-closed capacity).
        if self.txs.len() >= self.max_size {
            return false;
        }
        self.txs.insert(entry.tx_hash.clone(), entry);
        true
    }

    fn remove(&mut self, tx_hash: &str) -> bool {
        self.txs.remove(tx_hash).is_some()
    }

    fn contains(&self, tx_hash: &str) -> bool {
        self.txs.contains_key(tx_hash)
    }

    fn get(&self, tx_hash: &str) -> Option<TxEntry> {
        self.txs.get(tx_hash).cloned()
    }

    fn size(&self) -> usize {
        self.txs.len()
    }

    fn sorted_by_fee_desc(&self) -> Vec<&TxEntry> {
        let mut items: Vec<&TxEntry> = self.txs.values().collect();
        items.sort_by(|a, b| {
            b.fee_satoshi
                .cmp(&a.fee_satoshi)
                .then_with(|| a.tx_hash.cmp(&b.tx_hash))
        });
        items
    }

    fn fee_stats(&self) -> (f64, f64) {
        if self.txs.is_empty() {
            return (0.0, 0.0);
        }
        let total: f64 = self.txs.values().map(|e| e.fee).sum();
        let avg = total / (self.txs.len() as f64);
        (total, avg)
    }
}

fn entry_to_dict(py: Python<'_>, e: &TxEntry) -> PyResult<PyObject> {
    let d = PyDict::new_bound(py);
    d.set_item("tx_hash", &e.tx_hash)?;
    d.set_item("from_addr", &e.from_addr)?;
    d.set_item("to_addr", &e.to_addr)?;
    d.set_item("amount", e.amount)?;
    d.set_item("fee", e.fee)?;
    d.set_item("fee_satoshi", e.fee_satoshi)?;
    d.set_item("nonce", e.nonce)?;
    d.set_item("signature", &e.signature)?;
    d.set_item("public_key", &e.public_key)?;
    d.set_item("data", &e.data)?;
    d.set_item("gas", e.gas)?;
    d.set_item("timestamp", e.timestamp)?;
    Ok(d.into())
}

fn dict_to_entry(dict: &Bound<'_, PyDict>) -> PyResult<TxEntry> {
    let tx_hash: String = dict
        .get_item("tx_hash")?
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("missing_field:tx_hash"))?
        .extract()?;
    if tx_hash.trim().is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err("empty_tx_hash"));
    }
    let from_addr: String = dict
        .get_item("from_addr")?
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("missing_field:from_addr"))?
        .extract()?;
    let to_addr: String = dict
        .get_item("to_addr")?
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("missing_field:to_addr"))?
        .extract()?;
    let amount: f64 = dict
        .get_item("amount")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or(0.0);
    let fee: f64 = dict
        .get_item("fee")?
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("missing_field:fee"))?
        .extract()?;
    // Prefer explicit fee_satoshi from Python (Decimal path). Fallback only if
    // missing: refuse silent float→int via IEEE — require non-negative round.
    let fee_satoshi: i64 = match dict.get_item("fee_satoshi")? {
        Some(v) => v.extract()?,
        None => {
            if !fee.is_finite() || fee < 0.0 {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "missing_field:fee_satoshi",
                ));
            }
            // Last-resort bridge for old callers; Python dual-write should always set.
            (fee * 1_000_000.0).round() as i64
        }
    };
    if fee_satoshi < 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("negative_fee_satoshi"));
    }
    let nonce: i64 = dict
        .get_item("nonce")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or(0);
    let signature: String = dict
        .get_item("signature")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or_default();
    let public_key: String = dict
        .get_item("public_key")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or_default();
    let data: String = dict
        .get_item("data")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or_default();
    let gas: i64 = dict
        .get_item("gas")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or(21_000);
    let timestamp: f64 = dict
        .get_item("timestamp")?
        .map(|v| v.extract())
        .transpose()?
        .unwrap_or(0.0);
    Ok(TxEntry {
        tx_hash,
        from_addr,
        to_addr,
        amount,
        fee,
        fee_satoshi,
        nonce,
        signature,
        public_key,
        data,
        gas,
        timestamp,
    })
}

/// Fee-sorted pending store (ADR 0021 phase 2).
#[pyclass]
pub struct MempoolStore {
    inner: Mutex<StoreInner>,
}

#[pymethods]
impl MempoolStore {
    #[new]
    #[pyo3(signature = (max_size=10000, min_fee_satoshi=100))]
    fn new(max_size: usize, min_fee_satoshi: i64) -> Self {
        Self {
            inner: Mutex::new(StoreInner::new(max_size, min_fee_satoshi)),
        }
    }

    /// Insert validated tx dict. Returns true if newly accepted.
    fn insert(&self, tx: Bound<'_, PyDict>) -> PyResult<bool> {
        let entry = dict_to_entry(&tx)?;
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        Ok(guard.insert(entry))
    }

    fn remove(&self, tx_hash: &str) -> PyResult<bool> {
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        Ok(guard.remove(tx_hash))
    }

    fn contains(&self, tx_hash: &str) -> PyResult<bool> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        Ok(guard.contains(tx_hash))
    }

    fn get(&self, py: Python<'_>, tx_hash: &str) -> PyResult<PyObject> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        match guard.get(tx_hash) {
            Some(e) => entry_to_dict(py, &e),
            None => Ok(py.None()),
        }
    }

    #[pyo3(signature = (limit=100, min_fee_satoshi=0))]
    fn get_sorted(&self, py: Python<'_>, limit: usize, min_fee_satoshi: i64) -> PyResult<PyObject> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        let list = PyList::empty_bound(py);
        let floor = min_fee_satoshi.max(0);
        for e in guard
            .sorted_by_fee_desc()
            .into_iter()
            .filter(|e| e.fee_satoshi >= floor)
            .take(limit)
        {
            list.append(entry_to_dict(py, e)?)?;
        }
        Ok(list.into())
    }

    fn hashes(&self, py: Python<'_>) -> PyResult<PyObject> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        let list = PyList::empty_bound(py);
        for h in guard.txs.keys() {
            list.append(h)?;
        }
        Ok(list.into())
    }

    fn size(&self) -> PyResult<usize> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        Ok(guard.size())
    }

    fn fee_stats(&self) -> PyResult<(f64, f64)> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("mempool_store_lock_poisoned"))?;
        Ok(guard.fee_stats())
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MempoolStore>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{StoreInner, TxEntry};

    fn entry(hash: &str, fee_satoshi: i64) -> TxEntry {
        TxEntry {
            tx_hash: hash.into(),
            from_addr: "0xa".into(),
            to_addr: "0xb".into(),
            amount: 1.0,
            fee: (fee_satoshi as f64) / 1_000_000.0,
            fee_satoshi,
            nonce: 0,
            signature: String::new(),
            public_key: String::new(),
            data: String::new(),
            gas: 21_000,
            timestamp: 1.0,
        }
    }

    #[test]
    fn insert_reject_duplicate_and_low_fee() {
        let mut s = StoreInner::new(10, 1_000);
        assert!(s.insert(entry("h1", 10_000)));
        assert!(!s.insert(entry("h1", 20_000)));
        assert!(!s.insert(entry("h2", 100)));
        assert_eq!(s.size(), 1);
    }

    #[test]
    fn sort_fee_desc() {
        let mut s = StoreInner::new(10, 0);
        assert!(s.insert(entry("low", 1_000_000)));
        assert!(s.insert(entry("high", 9_000_000)));
        assert!(s.insert(entry("mid", 5_000_000)));
        let ordered: Vec<&str> = s.sorted_by_fee_desc().iter().map(|e| e.tx_hash.as_str()).collect();
        assert_eq!(ordered, vec!["high", "mid", "low"]);
    }

    #[test]
    fn remove_and_contains() {
        let mut s = StoreInner::new(10, 0);
        assert!(s.insert(entry("x", 1_000_000)));
        assert!(s.contains("x"));
        assert!(s.remove("x"));
        assert!(!s.contains("x"));
        assert!(!s.remove("x"));
    }
}
