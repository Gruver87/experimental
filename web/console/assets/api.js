/* Same-origin API client — never sends secrets; JSON only. */
(function (global) {
  "use strict";

  const AbsApi = {
    base: "",
    setBase(v) {
      const raw = String(v || "").trim().replace(/\/$/, "");
      this.base = raw;
      try {
        sessionStorage.setItem("abs_console_base", raw);
      } catch (_) {}
    },
    loadBase() {
      try {
        const saved = sessionStorage.getItem("abs_console_base");
        if (saved) this.base = saved;
      } catch (_) {}
      return this.base;
    },
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
  };

  AbsApi.loadBase();
  global.AbsApi = AbsApi;
})(window);
