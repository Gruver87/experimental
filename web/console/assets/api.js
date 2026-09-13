/* Same-origin REST + Absolute JSON-RPC client. Never sends secrets. */
(function (global) {
  "use strict";

  function stripSlash(v) {
    return String(v || "").trim().replace(/\/$/, "");
  }

  function deriveRpcUrl(httpBase, rpcPort) {
    const base = stripSlash(httpBase) || (global.location && global.location.origin) || "";
    let port = Number(rpcPort);
    if (!Number.isFinite(port) || port <= 0) port = 8545;
    try {
      const u = new URL(base);
      u.port = String(port);
      u.pathname = "/";
      u.search = "";
      u.hash = "";
      return stripSlash(u.toString());
    } catch (_) {
      return base.replace(/:\d+$/, "") + ":" + port;
    }
  }

  const AbsApi = {
    base: "",
    rpcBase: "",
    setBase(v) {
      this.base = stripSlash(v);
      try {
        sessionStorage.setItem("abs_console_base", this.base);
      } catch (_) {}
    },
    setRpcBase(v) {
      this.rpcBase = stripSlash(v);
      try {
        sessionStorage.setItem("abs_console_rpc", this.rpcBase);
      } catch (_) {}
    },
    loadBase() {
      try {
        const saved = sessionStorage.getItem("abs_console_base");
        if (saved) this.base = saved;
        const rpc = sessionStorage.getItem("abs_console_rpc");
        if (rpc) this.rpcBase = rpc;
      } catch (_) {}
      return this.base;
    },
    syncRpcFromStatus(st) {
      const httpBase = this.base || (global.location && global.location.origin) || "";
      const rpcPort = st && st.rpc_port;
      if (!this.rpcBase || this.rpcBase === deriveRpcUrl(httpBase, 8545)) {
        this.setRpcBase(deriveRpcUrl(httpBase, rpcPort));
      } else if (rpcPort) {
        // Keep manual override; still expose derived default on window for UI.
      }
      return this.rpcBase;
    },
    deriveRpcUrl,
    url(path) {
      const p = path.startsWith("/") ? path : "/" + path;
      return (this.base || "") + p;
    },
    async get(path, opts) {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), (opts && opts.timeoutMs) || 8000);
      try {
        const res = await fetch(this.url(path), {
          method: "GET",
          credentials: "same-origin",
          signal: ctrl.signal,
          headers: { Accept: "application/json, text/plain;q=0.9,*/*;q=0.8" },
        });
        const ct = res.headers.get("content-type") || "";
        if (!res.ok) {
          const err = new Error("HTTP " + res.status);
          err.status = res.status;
          throw err;
        }
        if (ct.includes("application/json")) return await res.json();
        return await res.text();
      } finally {
        clearTimeout(t);
      }
    },
    async getJson(path) {
      return this.get(path);
    },
    async getText(path) {
      return this.get(path);
    },
    async eth(method, params, opts) {
      const rpc = this.rpcBase || deriveRpcUrl(this.base, 8545);
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), (opts && opts.timeoutMs) || 12000);
      try {
        const res = await fetch(rpc, {
          method: "POST",
          signal: ctrl.signal,
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: Date.now(),
            method: method,
            params: params || [],
          }),
        });
        const body = await res.json();
        if (body && body.error) {
          const err = new Error(body.error.message || "RPC error");
          err.code = body.error.code;
          err.data = body.error.data;
          throw err;
        }
        return body ? body.result : null;
      } finally {
        clearTimeout(t);
      }
    },
  };

  AbsApi.loadBase();
  global.AbsApi = AbsApi;
})(window);
