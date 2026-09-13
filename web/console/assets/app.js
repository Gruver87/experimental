/* Absolute Ops Console — read-heavy, fail-closed honesty UI. */
(function () {
  "use strict";

  const META = {
    overview: ["Overview", "Live node strip · honesty badges · height sparkline"],
    mesh: ["Mesh & Sync", "under_mesh · topology · security · wire probe"],
    metrics: ["Live Metrics", "All scrapeable abs_* series from GET /metrics"],
    mempool: ["Mempool", "Store backend honesty · pending · fee surface"],
    chain: ["Chain", "Recent blocks · tip · state consistency"],
    wallets: ["Wallets", "EIP-1193 · Absolute chain switch · eth_sendTransaction"],
    council: ["Council", "ADR 0022 watch — staging 778889 only (never prod mint)"],
    markets: ["Markets", "Exchange clocks · FX · crypto · macro — not L1 oracle"],
    security: ["Security", "CSP · CORS posture · what this console will not do"],
  };

  const state = {
    view: "overview",
    poll: true,
    timer: null,
    status: null,
    metrics: [],
    heightSpark: null,
    peersSpark: null,
    mempoolSpark: null,
    metricHistory: new Map(),
  };

  function el(id) {
    return document.getElementById(id);
  }

  function toast(msg) {
    const t = el("toast");
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 2600);
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function badgeForSync(sync) {
    const s = String(sync || "");
    if (s === "aligned") return '<span class="badge ok">aligned</span>';
    if (s === "under_mesh" || s === "under_mesh_lagging")
      return '<span class="badge warn">' + esc(s) + "</span>";
    if (s === "solo") return '<span class="badge">solo</span>';
    if (s.includes("stale") || s === "catching_up" || s === "inconsistent")
      return '<span class="badge warn">' + esc(s || "—") + "</span>";
    return '<span class="badge signal">' + esc(s || "—") + "</span>";
  }

  function clsForSync(sync) {
    const s = String(sync || "");
    if (s === "aligned") return "ok";
    if (s === "under_mesh" || s === "under_mesh_lagging" || s === "inconsistent")
      return "warn";
    if (s === "solo") return "";
    return "";
  }

  function setView(name) {
    state.view = name;
    document.querySelectorAll(".nav-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === name);
    });
    document.querySelectorAll(".view").forEach((v) => {
      v.classList.toggle("active", v.id === "view-" + name);
    });
    const m = META[name] || ["", ""];
    el("view-title").textContent = m[0];
    el("view-lede").textContent = m[1];
    try {
      if (location.hash.replace(/^#/, "") !== name) {
        history.replaceState(null, "", "#" + name);
      }
    } catch (_) {}
    renderView();
  }

  function renderStrip(st) {
    const sync = st.p2p_sync_status || "—";
    const mp = st.mempool_store || {};
    const demoted = !!mp.store_demoted;
    const ready = st.status || "—";
    const items = [
      ["Status", ready, ready === "degraded" ? "warn" : "ok"],
      ["Height", st.height ?? "—", ""],
      ["Chain", st.chain_id ?? "—", ""],
      ["Peers", st.peers_connected ?? st.peers ?? "—", ""],
      ["Sync", sync, clsForSync(sync)],
      ["Mempool", st.mempool_size ?? "—", ""],
      [
        "Store",
        demoted ? "demoted" : mp.store_backend || "—",
        demoted ? "bad" : "ok",
      ],
      ["Mode", st.deployment_mode || "—", ""],
    ];
    el("status-strip").innerHTML = items
      .map(
        ([k, v, c]) =>
          `<div class="stat"><div class="k">${esc(k)}</div><div class="v ${c}">${esc(
            v
          )}</div></div>`
      )
      .join("");
  }

  function renderOverview() {
    const st = state.status || {};
    const mp = st.mempool_store || {};
    const root = el("view-overview");
    root.innerHTML = `
      <div class="grid grid-2">
        <div class="card">
          <h2>Tip velocity</h2>
          <div class="chart-wrap"><canvas id="chart-height"></canvas></div>
          <div class="honesty">
            ${badgeForSync(st.p2p_sync_status)}
            <span class="badge ${st.state_consistent ? "ok" : "warn"}">state_consistent=${esc(
              String(!!st.state_consistent)
            )}</span>
            <span class="badge ${st.wire_probe_ok ? "ok" : "warn"}">wire_probe=${esc(
              st.wire_probe_probed ? (st.wire_probe_ok ? "ok" : "fail") : "never"
            )}</span>
            <span class="badge">gap=${esc(st.peer_sync_gap ?? 0)}</span>
            <span class="badge">mesh_min=${esc(st.mesh_min_peers ?? "—")}</span>
          </div>
        </div>
        <div class="card">
          <h2>Honesty snapshot</h2>
          <table>
            <tbody>
              <tr><th>Node</th><td>${esc(st.node_id || "—")}</td></tr>
              <tr><th>Head</th><td class="mono">${esc((st.head_hash || "").slice(0, 18) || "—")}</td></tr>
              <tr><th>P2P sync</th><td>${badgeForSync(st.p2p_sync_status)}</td></tr>
              <tr><th>Mempool store</th><td class="mono">${esc(
                JSON.stringify(mp || {})
              )}</td></tr>
              <tr><th>Bridge</th><td>${
                st.bridge_enabled
                  ? '<span class="badge warn">ON</span>'
                  : '<span class="badge ok">OFF</span>'
              } <span class="muted mono">${esc(
                st.bridge_disabled_reason || st.bridge_mode || ""
              )}</span></td></tr>
              <tr><th>Probe ms</th><td class="mono">${esc(
                st.status_handler_ms ?? "—"
              )}</td></tr>
            </tbody>
          </table>
          <p class="muted" style="margin-top:12px;font-size:12px">
            Read-only ops surface. Mutations stay in
            <a href="/explorer">legacy explorer</a> (dev) or signed RPC.
          </p>
        </div>
      </div>
      <div class="grid grid-3" style="margin-top:14px">
        <div class="card">
          <h2>Peers spark</h2>
          <div class="chart-wrap"><canvas id="chart-peers"></canvas></div>
        </div>
        <div class="card">
          <h2>Mempool spark</h2>
          <div class="chart-wrap"><canvas id="chart-mempool"></canvas></div>
        </div>
        <div class="card">
          <h2>Quick links</h2>
          <div class="row" style="margin-top:8px">
            <a class="btn ghost" href="/metrics" target="_blank" rel="noopener">/metrics</a>
            <a class="btn ghost" href="/health/ready" target="_blank" rel="noopener">/health/ready</a>
            <a class="btn ghost" href="/status?probe=1" target="_blank" rel="noopener">/status?probe=1</a>
            <a class="btn ghost" href="/openapi.json" target="_blank" rel="noopener">openapi</a>
          </div>
        </div>
      </div>`;
    const h = el("chart-height");
    const p = el("chart-peers");
    const m = el("chart-mempool");
    if (h) {
      state.heightSpark = new AbsCharts.Sparkline(h, {
        color: "#c4783a",
        fill: "rgba(196,120,58,0.14)",
      });
      (state._heightHist || []).forEach((v) => state.heightSpark.push(v));
    }
    if (p) {
      state.peersSpark = new AbsCharts.Sparkline(p, { color: "#3dd6c6" });
      (state._peersHist || []).forEach((v) => state.peersSpark.push(v));
    }
    if (m) {
      state.mempoolSpark = new AbsCharts.Sparkline(m, {
        color: "#6ecf8e",
        fill: "rgba(110,207,142,0.12)",
      });
      (state._mpHist || []).forEach((v) => state.mempoolSpark.push(v));
    }
  }

  async function renderMesh() {
    const root = el("view-mesh");
    root.innerHTML = `<div class="card"><h2>Loading mesh…</h2></div>`;
    let topo = null;
    let sec = null;
    let sync = null;
    try {
      topo = await AbsApi.getJson("/p2p/topology");
    } catch (_) {}
    try {
      sec = await AbsApi.getJson("/p2p/security");
    } catch (_) {}
    try {
      sync = await AbsApi.getJson("/sync/status");
    } catch (_) {}
    const st = state.status || {};
    const under =
      st.p2p_sync_status === "under_mesh" ||
      st.p2p_sync_status === "under_mesh_lagging";
    root.innerHTML = `
      <div class="grid grid-2">
        <div class="card">
          <h2>Sync honesty</h2>
          ${
            under
              ? `<div class="warn-box">Node is under_mesh — peer count below mesh_min_peers_before_mine. Forging may be gated.</div>`
              : `<div class="ok-box">Not under_mesh (or non-prod single-peer labels).</div>`
          }
          <table>
            <tr><th>p2p_sync_status</th><td>${badgeForSync(st.p2p_sync_status)}</td></tr>
            <tr><th>peers</th><td class="mono">${esc(
              st.peers_connected ?? st.peers ?? "—"
            )} / min ${esc(st.mesh_min_peers ?? "—")}</td></tr>
            <tr><th>peer_sync_gap</th><td class="mono">${esc(
              st.peer_sync_gap ?? 0
            )}</td></tr>
            <tr><th>state_consistent</th><td>${
              st.state_consistent
                ? '<span class="badge ok">true</span>'
                : '<span class="badge warn">false</span>'
            }</td></tr>
            <tr><th>wire probe</th><td class="mono">${esc(
              JSON.stringify({
                probed: st.wire_probe_probed,
                ok: st.wire_probe_ok,
              })
            )}</td></tr>
          </table>
          <h3>sync/status</h3>
          <pre class="mono muted" style="white-space:pre-wrap;max-height:180px;overflow:auto">${esc(
            JSON.stringify(sync || { error: "unavailable" }, null, 2)
          )}</pre>
        </div>
        <div class="card">
          <h2>P2P security</h2>
          <pre class="mono muted" style="white-space:pre-wrap;max-height:360px;overflow:auto">${esc(
            JSON.stringify(
              sec
                ? {
                    active_bans: sec.active_bans,
                    rate_limit_drops: sec.rate_limit_drops,
                    handshake_rejects: sec.handshake_rejects,
                    shape_rejects_total: sec.shape_rejects_total,
                    eclipse_at_risk: sec.eclipse_at_risk,
                    native_p2p_tls: sec.native_p2p_tls,
                    native_p2p_transport: sec.native_p2p_transport,
                  }
                : { error: "unavailable" },
              null,
              2
            )
          )}</pre>
          <h3>Topology</h3>
          <pre class="mono muted" style="white-space:pre-wrap;max-height:200px;overflow:auto">${esc(
            JSON.stringify(topo || { error: "unavailable" }, null, 2)
          )}</pre>
        </div>
      </div>`;
  }

  function metricKey(m) {
    const labs = Object.keys(m.labels || {})
      .sort()
      .map((k) => k + "=" + m.labels[k])
      .join(",");
    return m.name + "{" + labs + "}";
  }

  function renderMetrics() {
    const root = el("view-metrics");
    const rows = state.metrics || [];
    const focus = [
      "abs_p2p_under_mesh",
      "abs_p2p_sync_status",
      "abs_state_consistent",
      "abs_sync_wire_probe_ok",
      "abs_peers_connected",
      "abs_mempool_size",
      "abs_chain_height",
      "abs_rocksdb_native_pack_fallbacks",
      "abs_p2p_shape_rejects_total",
      "abs_native_crypto_self_test",
    ];
    const focusRows = focus
      .map((name) => rows.filter((r) => r.name === name))
      .flat();
    const maxAbs = Math.max(
      1,
      ...rows.map((r) => Math.abs(Number(r.value) || 0))
    );
    root.innerHTML = `
      <div class="card" style="margin-bottom:14px">
        <h2>Priority gauges</h2>
        <div class="metric-grid">
          ${
            focusRows.length
              ? focusRows
                  .map((r) => {
                    const pct = Math.min(
                      100,
                      (Math.abs(Number(r.value) || 0) / maxAbs) * 100
                    );
                    return `<div class="metric-tile"><div class="name">${esc(
                      metricKey(r)
                    )}</div><div class="val">${esc(
                      r.value
                    )}</div><div class="bar"><i style="width:${pct}%"></i></div></div>`;
                  })
                  .join("")
              : '<p class="muted">No /metrics yet — check scrape or metrics_enabled.</p>'
          }
        </div>
      </div>
      <div class="card">
        <h2>Full scrape (${rows.length} series)</h2>
        <div class="form-row"><input id="metric-filter" placeholder="filter abs_…" /></div>
        <div class="metric-grid" id="metric-all"></div>
      </div>`;
    const all = el("metric-all");
    const paint = (q) => {
      const qq = String(q || "")
        .trim()
        .toLowerCase();
      const list = rows.filter((r) => !qq || metricKey(r).toLowerCase().includes(qq));
      all.innerHTML = list
        .slice(0, 240)
        .map((r) => {
          const pct = Math.min(100, (Math.abs(Number(r.value) || 0) / maxAbs) * 100);
          return `<div class="metric-tile"><div class="name">${esc(
            metricKey(r)
          )}</div><div class="val">${esc(r.value)}</div><div class="bar"><i style="width:${pct}%"></i></div></div>`;
        })
        .join("");
    };
    paint("");
    el("metric-filter").addEventListener("input", (e) => paint(e.target.value));
  }

  async function renderMempool() {
    const root = el("view-mempool");
    let mp = null;
    try {
      mp = await AbsApi.getJson("/mempool");
    } catch (_) {}
    const store = (state.status && state.status.mempool_store) || {};
    root.innerHTML = `
      <div class="grid grid-2">
        <div class="card">
          <h2>Store honesty</h2>
          ${
            store.store_demoted
              ? `<div class="warn-box">Mempool store demoted — native path fell back. Prod+require_native should surface degraded.</div>`
              : `<div class="ok-box">Store not demoted (or field absent on older nodes).</div>`
          }
          <pre class="mono muted">${esc(JSON.stringify(store, null, 2))}</pre>
        </div>
        <div class="card">
          <h2>/mempool</h2>
          <pre class="mono muted" style="white-space:pre-wrap;max-height:420px;overflow:auto">${esc(
            JSON.stringify(mp || { error: "unavailable" }, null, 2)
          )}</pre>
        </div>
      </div>`;
  }

  async function renderChain() {
    const root = el("view-chain");
    let blocks = null;
    try {
      blocks = await AbsApi.getJson("/blocks?limit=12");
    } catch (_) {
      try {
        blocks = await AbsApi.getJson("/blocks");
      } catch (__) {}
    }
    const list = Array.isArray(blocks)
      ? blocks
      : blocks && Array.isArray(blocks.blocks)
        ? blocks.blocks
        : [];
    root.innerHTML = `
      <div class="card">
        <h2>Recent blocks</h2>
        <table>
          <thead><tr><th>#</th><th>Hash</th><th>Txs</th><th>Time</th></tr></thead>
          <tbody>
            ${
              list.length
                ? list
                    .slice(0, 16)
                    .map((b) => {
                      const h = b.height ?? b.number ?? "—";
                      const hash = (b.hash || b.block_hash || "").toString();
                      const txs = Array.isArray(b.transactions)
                        ? b.transactions.length
                        : b.tx_count ?? "—";
                      const ts = b.timestamp || b.time || "";
                      return `<tr><td>${esc(h)}</td><td class="mono">${esc(
                        hash.slice(0, 18)
                      )}</td><td>${esc(txs)}</td><td class="mono">${esc(
                        ts
                      )}</td></tr>`;
                    })
                    .join("")
                : `<tr><td colspan="4" class="muted">No blocks payload</td></tr>`
            }
          </tbody>
        </table>
      </div>`;
  }

  async function renderWallets() {
    const root = el("view-wallets");
    const st = state.status || {};
    let nodeW = null;
    try {
      nodeW = await AbsApi.getJson("/wallet/status");
    } catch (_) {}
    const injected = AbsWallets.hasInjected();
    if (nodeW) {
      ["address", "signing_address", "founder_address", "miner_address"].forEach(
        (k) => {
          const a = nodeW[k];
          if (a && /^0x[0-9a-fA-F]{40}$/.test(a)) {
            try {
              AbsWallets.addWatch(a, k);
            } catch (_) {}
          }
        }
      );
    }
    const balances = [];
    for (const entry of AbsWallets.watchlist.slice(0, 12)) {
      const addr = entry.split(" #")[0];
      let bal = null;
      try {
        bal = await AbsApi.getJson("/address/" + encodeURIComponent(addr));
      } catch (_) {
        try {
          bal = await AbsApi.getJson(
            "/wallet/balance?address=" + encodeURIComponent(addr)
          );
        } catch (__) {}
      }
      balances.push({ entry, addr, bal });
    }
    const chainId = st.chain_id || "—";
    const symbol = st.coin_symbol || "ABS";
    root.innerHTML = `
      <div class="warn-box">
        Keys never POST to the node. MetaMask signs locally after
        <code>wallet_switchEthereumChain</code> / <code>wallet_addEthereumChain</code>
        to Absolute chain_id <strong>${esc(chainId)}</strong> with JSON-RPC
        <code>${esc(AbsApi.rpcBase || "—")}</code>.
      </div>
      <div class="grid grid-2">
        <div class="card">
          <h2>Connect &amp; Absolute chain</h2>
          <p class="muted" style="margin-bottom:10px">${
            injected
              ? "Injected provider detected."
              : "No browser wallet — watch-only still works."
          }</p>
          <div class="row">
            <button type="button" class="btn" id="btn-connect">Connect</button>
            <button type="button" class="btn ghost" id="btn-switch-chain">Switch to Absolute</button>
            <button type="button" class="btn ghost" id="btn-sign-ping">Sign ping</button>
          </div>
          <div id="wallet-connect-out" class="mono" style="margin-top:12px"></div>
          <h3>Send (eth_sendTransaction)</h3>
          <div class="form-row"><label>To</label><input id="tx-to" placeholder="0x…" spellcheck="false" /></div>
          <div class="form-row"><label>Amount (${esc(symbol)})</label><input id="tx-amt" value="0.001" /></div>
          <button type="button" class="btn" id="btn-send-tx">Send via wallet</button>
          <div id="tx-send-out" class="mono" style="margin-top:10px"></div>
          <h3>Node operational (read-only)</h3>
          <pre class="mono muted">${esc(
            JSON.stringify(nodeW || { error: "unavailable" }, null, 2)
          )}</pre>
        </div>
        <div class="card">
          <h2>Watchlist</h2>
          <div class="form-row"><label>Address</label><input id="watch-addr" placeholder="0x…" spellcheck="false" /></div>
          <div class="row">
            <button type="button" class="btn ghost" id="btn-watch-add">Add watch</button>
            <button type="button" class="btn ghost" id="btn-watch-refresh">Refresh balances</button>
          </div>
          <div class="grid" style="margin-top:12px;gap:8px" id="watch-cards">
            ${balances
              .map((b) => {
                const bal =
                  b.bal && (b.bal.balance ?? b.bal.balance_formatted ?? b.bal.abs);
                return `<div class="wallet-card"><div class="muted" style="font-size:11px">${esc(
                  b.entry.includes("#") ? b.entry.split("#")[1] : "watch"
                )}</div><div class="addr mono">${esc(
                  b.addr
                )}</div><div style="margin-top:8px;font-size:18px;color:var(--copper)">${esc(
                  bal ?? "—"
                )} ${esc(symbol)}</div>
                <button type="button" class="btn ghost" data-rm="${esc(
                  b.addr
                )}" style="margin-top:8px">Remove</button></div>`;
              })
              .join("") || '<p class="muted">Empty watchlist</p>'}
          </div>
        </div>
      </div>`;

    async function ensureChain() {
      const cid = Number(st.chain_id);
      if (!cid) throw new Error("Node chain_id unknown — refresh status");
      return AbsWallets.ensureAbsoluteChain({
        chainId: cid,
        rpcUrl: AbsApi.rpcBase,
        chainName: "Absolute " + cid,
        symbol: symbol,
        explorerUrl: AbsApi.base || window.location.origin,
      });
    }

    el("btn-connect").onclick = async () => {
      try {
        const accs = await AbsWallets.connectInjected();
        const cid = await AbsWallets.chainId();
        el("wallet-connect-out").textContent = JSON.stringify(
          { accounts: accs, walletChainId: cid, nodeChainId: st.chain_id },
          null,
          2
        );
        toast("Wallet connected");
      } catch (e) {
        toast(String(e.message || e));
      }
    };
    el("btn-switch-chain").onclick = async () => {
      try {
        if (!AbsWallets.accounts[0]) await AbsWallets.connectInjected();
        const r = await ensureChain();
        el("wallet-connect-out").textContent = JSON.stringify(r, null, 2);
        toast("On Absolute chain");
      } catch (e) {
        toast(String(e.message || e));
      }
    };
    el("btn-sign-ping").onclick = async () => {
      try {
        const msg = "Absolute Ops Console ping " + new Date().toISOString();
        const sig = await AbsWallets.personalSign(msg);
        el("wallet-connect-out").textContent = JSON.stringify(
          { message: msg, signature: sig },
          null,
          2
        );
        toast("Signed locally");
      } catch (e) {
        toast(String(e.message || e));
      }
    };
    el("btn-send-tx").onclick = async () => {
      try {
        if (!AbsWallets.accounts[0]) await AbsWallets.connectInjected();
        await ensureChain();
        const hash = await AbsWallets.sendTransaction({
          to: el("tx-to").value.trim(),
          amountAbs: el("tx-amt").value.trim(),
        });
        el("tx-send-out").textContent = JSON.stringify({ txHash: hash }, null, 2);
        toast("Broadcast via wallet");
      } catch (e) {
        toast(String(e.message || e));
      }
    };
    el("btn-watch-add").onclick = () => {
      try {
        AbsWallets.addWatch(el("watch-addr").value.trim(), "watch");
        toast("Watch added");
        renderWallets();
      } catch (e) {
        toast(String(e.message || e));
      }
    };
    el("btn-watch-refresh").onclick = () => renderWallets();
    root.querySelectorAll("[data-rm]").forEach((btn) => {
      btn.onclick = () => {
        AbsWallets.removeWatch(btn.getAttribute("data-rm"));
        renderWallets();
      };
    });
  }

  async function renderCouncil() {
    const root = el("view-council");
    root.innerHTML = `<div class="card"><h2>Loading council…</h2></div>`;
    let stats = null;
    let manifest = null;
    try {
      stats = await AbsApi.getJson("/council/stats");
    } catch (_) {}
    try {
      manifest = await AbsApi.getJson("/council/manifest?summary=1");
    } catch (_) {}
    const st = state.status || {};
    const nodeCid = Number(st.chain_id || 0);
    const staging = Number((manifest && manifest.chain_id_staging) || 778889);
    const onProd = nodeCid === 778888;
    const onStaging = nodeCid === staging;
    // Founder seat watch from manifest summary if full tokens not loaded
    if (manifest && manifest.ok && Array.isArray(manifest.tokens)) {
      const founder = manifest.tokens.find((t) => Number(t.token_id) === 87);
      if (founder && founder.owner) {
        try {
          AbsWallets.addWatch(founder.owner, "council-founder");
        } catch (_) {}
      }
    }
    root.innerHTML = `
      <div class="${onProd ? "warn-box" : "ok-box"}">
        ${
          onProd
            ? "Node is prod chain_id 778888 — council genesis mint is forbidden here. Watch-only."
            : onStaging
              ? "Node looks like Profile C staging (" +
                staging +
                ") — council lab surface OK."
              : "Node chain_id=" +
                esc(nodeCid || "—") +
                "; council staging target is " +
                staging +
                ". Mint stays off prod."
        }
      </div>
      <div class="grid grid-2">
        <div class="card">
          <h2>Manifest summary</h2>
          <table>
            <tr><th>ok</th><td>${esc(String(!!(manifest && manifest.ok)))}</td></tr>
            <tr><th>collection</th><td class="mono">${esc(
              (manifest && manifest.collection_id) || "—"
            )}</td></tr>
            <tr><th>supply_cap</th><td class="mono">${esc(
              (manifest && manifest.supply_cap) || 87
            )}</td></tr>
            <tr><th>token_count</th><td class="mono">${esc(
              (manifest && manifest.token_count) || "—"
            )}</td></tr>
            <tr><th>chain_id_staging</th><td class="mono">${esc(staging)}</td></tr>
            <tr><th>sha256</th><td class="mono">${esc(
              ((manifest && manifest.manifest_tokens_sha256) || "").slice(0, 24) || "—"
            )}</td></tr>
          </table>
          <div class="row" style="margin-top:12px">
            <button type="button" class="btn ghost" id="btn-council-refresh">Refresh</button>
            <a class="btn ghost" href="/council/manifest?summary=1" target="_blank" rel="noopener">Raw summary</a>
          </div>
        </div>
        <div class="card">
          <h2>On-node council_stats</h2>
          <pre class="mono muted" style="white-space:pre-wrap;max-height:360px;overflow:auto">${esc(
            JSON.stringify(stats || { error: "unavailable" }, null, 2)
          )}</pre>
          <p class="muted" style="margin-top:10px;font-size:12px">
            Not an L1 security guarantor. Operator lab:
            <code>.\\scripts\\verify_council_lab.ps1</code>
          </p>
        </div>
      </div>`;
    el("btn-council-refresh").onclick = () => renderCouncil();
  }

  function fmtPx(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (Math.abs(n) >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
    return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }

  function fmtCh(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return { text: "—", cls: "" };
    const sign = n > 0 ? "+" : "";
    return {
      text: sign + n.toFixed(2) + "%",
      cls: n > 0 ? "up" : n < 0 ? "dn" : "",
    };
  }

  function localParts(tz) {
    try {
      const fmt = new Intl.DateTimeFormat("en-GB", {
        timeZone: tz,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
      const parts = fmt.formatToParts(new Date());
      const get = (t) => (parts.find((p) => p.type === t) || {}).value;
      return {
        weekday: get("weekday"),
        time: get("hour") + ":" + get("minute") + ":" + get("second"),
        hour: Number(get("hour")),
        minute: Number(get("minute")),
      };
    } catch (_) {
      return { weekday: "—", time: "—", hour: 0, minute: 0 };
    }
  }

  function sessionOpen(ex, parts) {
    if (ex.always_open) return true;
    const wd = String(parts.weekday || "");
    if (wd === "Sat" || wd === "Sun") return false;
    const [oh, om] = String(ex.open || "00:00")
      .split(":")
      .map(Number);
    const [ch, cm] = String(ex.close || "23:59")
      .split(":")
      .map(Number);
    const now = parts.hour * 60 + parts.minute;
    const o = oh * 60 + (om || 0);
    const c = ch * 60 + (cm || 0);
    if (ex.id === "cme") {
      // Globex wraps overnight — treat as open unless in daily maintenance window roughly 16:00-17:00 CT weekdays
      return !(now >= 16 * 60 && now < 17 * 60);
    }
    if (c > o) return now >= o && now < c;
    return now >= o || now < c;
  }

  async function renderMarkets() {
    const root = el("view-markets");
    root.innerHTML = `<div class="card"><h2>Loading markets…</h2></div>`;
    let snap = null;
    try {
      snap = await AbsApi.getJson("/market/snapshot");
    } catch (e) {
      root.innerHTML = `<div class="warn-box">Market snapshot unavailable: ${esc(
        e.message || e
      )}</div>`;
      return;
    }
    const exchanges = (snap && snap.exchanges) || [];
    const crypto = ((snap && snap.crypto) || {}).items || [];
    const fx = ((snap && snap.fx) || {}).items || [];
    const tickers = ((snap && snap.tickers) || {}).items || [];
    const commodities = tickers.filter((t) => t.kind === "commodity" || t.kind === "index");
    const equities = tickers.filter((t) => t.kind === "equity");

    root.innerHTML = `
      <div class="warn-box">
        Orientation only — <strong>not</strong> Absolute consensus / not on-chain oracle.
        Feeds: ${(snap.upstreams || []).map(esc).join(", ") || "—"}.
        Cache ${(snap.cache || "?")} · TTL ${esc(snap.ttl_sec || "—")}s · ${esc(
          snap.generated_at || ""
        )}
      </div>
      <div class="card" style="margin-bottom:14px">
        <h2>Leading exchange clocks</h2>
        <div class="clock-grid" id="market-clocks"></div>
      </div>
      <div class="grid grid-2" style="margin-bottom:14px">
        <div class="card">
          <h2>FX converter (ECB / Frankfurter)</h2>
          <div class="row">
            <div class="form-row" style="flex:1"><label>Amount</label><input id="fx-amt" value="100" /></div>
            <div class="form-row" style="width:100px"><label>From</label><input id="fx-from" value="USD" /></div>
            <div class="form-row" style="width:100px"><label>To</label><input id="fx-to" value="EUR" /></div>
          </div>
          <button type="button" class="btn" id="btn-fx">Convert</button>
          <div id="fx-out" class="mono" style="margin-top:10px"></div>
          <h3>USD crosses</h3>
          <div class="ticker-grid">
            ${fx
              .slice(0, 16)
              .map(
                (r) =>
                  `<div class="ticker"><div class="sym">${esc(
                    r.pair
                  )}</div><div class="px">${esc(fmtPx(r.rate))}</div></div>`
              )
              .join("") || '<p class="muted">FX unavailable</p>'}
          </div>
        </div>
        <div class="card">
          <h2>Exchanges board</h2>
          <table class="ex-table">
            <thead><tr><th>Venue</th><th>Local</th><th>Session</th><th>Kind</th></tr></thead>
            <tbody id="ex-body"></tbody>
          </table>
        </div>
      </div>
      <div class="card" style="margin-bottom:14px">
        <h2>Crypto (CoinGecko)</h2>
        <div class="ticker-grid">
          ${crypto
            .map((c) => {
              const ch = fmtCh(c.change_24h_pct);
              return `<div class="ticker"><div class="sym">${esc(
                c.id
              )}</div><div class="px">$${esc(fmtPx(c.price_usd))}</div><div class="ch ${
                ch.cls
              }">${esc(ch.text)}</div></div>`;
            })
            .join("") || '<p class="muted">Crypto unavailable</p>'}
        </div>
      </div>
      <div class="grid grid-2">
        <div class="card">
          <h2>Commodities &amp; indices</h2>
          <div class="ticker-grid">
            ${commodities
              .map((t) => {
                const ch = fmtCh(t.change_pct);
                return `<div class="ticker"><div class="sym">${esc(t.name)} · ${esc(
                  t.symbol
                )}</div><div class="px">${esc(fmtPx(t.price))} ${esc(
                  t.currency || ""
                )}</div><div class="ch ${ch.cls}">${esc(ch.text)}</div></div>`;
              })
              .join("") || '<p class="muted">Unavailable</p>'}
          </div>
        </div>
        <div class="card">
          <h2>Mega-cap equities</h2>
          <div class="ticker-grid">
            ${equities
              .map((t) => {
                const ch = fmtCh(t.change_pct);
                return `<div class="ticker"><div class="sym">${esc(t.name)} · ${esc(
                  t.symbol
                )}</div><div class="px">${esc(fmtPx(t.price))} ${esc(
                  t.currency || ""
                )}</div><div class="ch ${ch.cls}">${esc(ch.text)}</div></div>`;
              })
              .join("") || '<p class="muted">Unavailable</p>'}
          </div>
        </div>
      </div>
      <div class="row" style="margin-top:12px">
        <button type="button" class="btn ghost" id="btn-market-refresh">Refresh snapshot</button>
      </div>`;

    function paintClocks() {
      const clockRoot = el("market-clocks");
      const exBody = el("ex-body");
      if (!clockRoot || !exBody) return;
      clockRoot.innerHTML = exchanges
        .map((ex) => {
          const p = localParts(ex.tz);
          const open = sessionOpen(ex, p);
          return `<div class="clock-card"><div class="city">${esc(ex.city)} · ${esc(
            ex.name
          )}</div><div class="time">${esc(p.time)}</div><div class="meta">${esc(
            p.weekday
          )} · ${open ? "SESSION OPEN" : "closed / off"} · ${esc(ex.tz)}</div></div>`;
        })
        .join("");
      exBody.innerHTML = exchanges
        .map((ex) => {
          const p = localParts(ex.tz);
          const open = sessionOpen(ex, p);
          return `<tr><td>${esc(ex.name)}</td><td class="mono">${esc(
            p.time
          )}</td><td class="${open ? "open-yes" : "open-no"}">${
            open ? "open" : "closed"
          }</td><td>${esc(ex.kind)}</td></tr>`;
        })
        .join("");
    }
    paintClocks();
    if (state._marketClockTimer) clearInterval(state._marketClockTimer);
    state._marketClockTimer = setInterval(paintClocks, 1000);

    el("btn-fx").onclick = async () => {
      try {
        const amount = el("fx-amt").value.trim();
        const frm = el("fx-from").value.trim();
        const to = el("fx-to").value.trim();
        const q =
          "/market/fx?amount=" +
          encodeURIComponent(amount) +
          "&from=" +
          encodeURIComponent(frm) +
          "&to=" +
          encodeURIComponent(to);
        const r = await AbsApi.getJson(q);
        el("fx-out").textContent = JSON.stringify(r, null, 2);
      } catch (e) {
        toast(String(e.message || e));
      }
    };
    el("btn-market-refresh").onclick = () => renderMarkets();
  }

  function renderSecurity() {
    el("view-security").innerHTML = `
      <div class="grid grid-2">
        <div class="card">
          <h2>Browser hardening</h2>
          <ul class="muted" style="padding-left:18px;line-height:1.8">
            <li>UI served with Content-Security-Policy (no CDN scripts)</li>
            <li>X-Frame-Options: DENY · nosniff · referrer no-referrer</li>
            <li>Static paths confined to web/console and web/explorer</li>
            <li>Path traversal refused by realpath allowlist</li>
            <li>CORS remain allow-list only (never *)</li>
            <li>Theme preference in localStorage only (no secrets)</li>
          </ul>
        </div>
        <div class="card">
          <h2>Explicit non-goals</h2>
          <ul class="muted" style="padding-left:18px;line-height:1.8">
            <li>No private key paste → POST /tx/sign</li>
            <li>No JWT / API keys stored by default</li>
            <li>No admin mutations / council mint from this console</li>
            <li>eth_sendTransaction only via injected wallet on Absolute chain_id</li>
            <li>Not a mainnet readiness claim · not soak evidence</li>
          </ul>
        </div>
      </div>`;
  }

  function renderView() {
    switch (state.view) {
      case "overview":
        renderOverview();
        break;
      case "mesh":
        renderMesh();
        break;
      case "metrics":
        renderMetrics();
        break;
      case "mempool":
        renderMempool();
        break;
      case "chain":
        renderChain();
        break;
      case "wallets":
        renderWallets();
        break;
      case "council":
        renderCouncil();
        break;
      case "markets":
        renderMarkets();
        break;
      case "security":
        renderSecurity();
        break;
      default:
        break;
    }
  }

  async function refreshAll() {
    const pill = el("live-pill");
    try {
      let st = null;
      try {
        st = await AbsApi.getJson("/status?probe=1");
      } catch (_) {
        st = await AbsApi.getJson("/status");
      }
      state.status = st || {};
      AbsApi.syncRpcFromStatus(state.status);
      const ethRpc = el("eth-rpc");
      if (ethRpc && AbsApi.rpcBase && (!ethRpc.value || ethRpc.dataset.auto === "1")) {
        ethRpc.value = AbsApi.rpcBase;
        ethRpc.dataset.auto = "1";
      }
      renderStrip(state.status);

      state._heightHist = state._heightHist || [];
      state._peersHist = state._peersHist || [];
      state._mpHist = state._mpHist || [];
      state._heightHist.push(Number(st.height) || 0);
      state._peersHist.push(Number(st.peers_connected ?? st.peers) || 0);
      state._mpHist.push(Number(st.mempool_size) || 0);
      if (state._heightHist.length > 48) state._heightHist.shift();
      if (state._peersHist.length > 48) state._peersHist.shift();
      if (state._mpHist.length > 48) state._mpHist.shift();
      if (state.heightSpark) state.heightSpark.push(Number(st.height) || 0);
      if (state.peersSpark)
        state.peersSpark.push(Number(st.peers_connected ?? st.peers) || 0);
      if (state.mempoolSpark)
        state.mempoolSpark.push(Number(st.mempool_size) || 0);

      try {
        const text = await AbsApi.getText("/metrics");
        state.metrics = AbsCharts.parsePrometheus(text);
      } catch (_) {
        state.metrics = state.metrics || [];
      }

      pill.classList.remove("off");
      pill.innerHTML = '<span class="pulse"></span> live';
      renderView();
    } catch (e) {
      pill.classList.add("off");
      pill.innerHTML = '<span class="pulse"></span> offline';
      toast("Refresh failed: " + (e.message || e));
    }
  }

  function schedule() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    if (state.poll) state.timer = setInterval(refreshAll, 5000);
  }

  function boot() {
    const baseInput = el("rpc-base");
    const ethInput = el("eth-rpc");
    baseInput.value = AbsApi.base || window.location.origin;
    AbsApi.setBase(baseInput.value);
    if (!AbsApi.rpcBase) {
      AbsApi.setRpcBase(AbsApi.deriveRpcUrl(baseInput.value, 8545));
    }
    ethInput.value = AbsApi.rpcBase;
    ethInput.dataset.auto = AbsApi.rpcBase ? "1" : "0";

    baseInput.addEventListener("change", () => {
      AbsApi.setBase(baseInput.value);
      AbsApi.setRpcBase(AbsApi.deriveRpcUrl(baseInput.value, (state.status || {}).rpc_port || 8545));
      ethInput.value = AbsApi.rpcBase;
      ethInput.dataset.auto = "1";
      toast("REST + JSON-RPC bases updated");
      refreshAll();
    });
    ethInput.addEventListener("change", () => {
      AbsApi.setRpcBase(ethInput.value);
      ethInput.dataset.auto = "0";
      toast("JSON-RPC override saved");
    });

    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => setView(btn.dataset.view));
    });
    el("btn-refresh").onclick = () => refreshAll();
    el("btn-poll").onclick = () => {
      state.poll = !state.poll;
      el("btn-poll").dataset.on = state.poll ? "1" : "0";
      el("btn-poll").textContent = state.poll ? "Auto 5s" : "Paused";
      schedule();
    };
    el("btn-theme").onclick = () => {
      const cur = document.documentElement.getAttribute("data-theme") || "dark";
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem("abs_console_theme", next);
      } catch (_) {}
      toast("Theme: " + next);
    };

    window.addEventListener("hashchange", () => {
      const h = (location.hash || "").replace(/^#/, "");
      if (META[h] && h !== state.view) setView(h);
    });

    const initial = (location.hash || "").replace(/^#/, "");
    setView(META[initial] ? initial : "overview");
    refreshAll();
    schedule();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
