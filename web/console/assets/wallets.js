/* Wallet hub: EIP-1193 + watchlist. Never posts private keys. */
(function (global) {
  "use strict";

  const STORE_KEY = "abs_console_watchlist_v1";

  function loadWatch() {
    try {
      const raw = sessionStorage.getItem(STORE_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [];
    } catch (_) {
      return [];
    }
  }

  function saveWatch(list) {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(list.slice(0, 32)));
    } catch (_) {}
  }

  const AbsWallets = {
    provider: null,
    accounts: [],
    watchlist: loadWatch(),

    hasInjected() {
      return !!(global.ethereum && typeof global.ethereum.request === "function");
    },

    async connectInjected() {
      if (!this.hasInjected()) {
        throw new Error("No EIP-1193 provider (MetaMask / Rabby / Frame)");
      }
      this.provider = global.ethereum;
      const accounts = await this.provider.request({ method: "eth_requestAccounts" });
      this.accounts = Array.isArray(accounts) ? accounts : [];
      if (this.accounts[0]) this.addWatch(this.accounts[0], "injected");
      return this.accounts;
    },

    async chainId() {
      if (!this.provider) return null;
      return this.provider.request({ method: "eth_chainId" });
    },

    async personalSign(message) {
      if (!this.accounts[0]) throw new Error("Connect a wallet first");
      return this.provider.request({
        method: "personal_sign",
        params: [message, this.accounts[0]],
      });
    },

    addWatch(addr, tag) {
      const a = String(addr || "").trim();
      if (!/^0x[0-9a-fA-F]{40}$/.test(a)) throw new Error("Need 0x + 40 hex address");
      const entry = a + (tag ? " #" + tag : "");
      const bare = this.watchlist.map((x) => x.split(" #")[0].toLowerCase());
      if (!bare.includes(a.toLowerCase())) {
        this.watchlist.unshift(tag ? entry : a);
        saveWatch(this.watchlist);
      }
      return this.watchlist;
    },

    removeWatch(addr) {
      const target = String(addr || "").split(" #")[0].toLowerCase();
      this.watchlist = this.watchlist.filter(
        (x) => x.split(" #")[0].toLowerCase() !== target
      );
      saveWatch(this.watchlist);
      return this.watchlist;
    },

    clearSessionSecrets() {
      // Intentional: we never persist private keys. Clear JWT leftovers if any.
      try {
        sessionStorage.removeItem("abs_jwt");
        localStorage.removeItem("abs_jwt");
        localStorage.removeItem("abs_rpc_key");
      } catch (_) {}
    },
  };

  AbsWallets.clearSessionSecrets();
  global.AbsWallets = AbsWallets;
})(window);
