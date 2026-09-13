/* Wallet hub: EIP-1193 chain switch + sendTx + watchlist. No private-key POST. */
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

  function toHexChainId(n) {
    return "0x" + Number(n).toString(16);
  }

  /** ABS amount (up to 18 fractional digits) → wei hex for eth_sendTransaction. */
  function absToWeiHex(absAmount) {
    const raw = String(absAmount ?? "").trim();
    if (!raw || !/^\d+(\.\d+)?$/.test(raw)) {
      throw new Error("Amount must be a non-negative decimal");
    }
    const parts = raw.split(".");
    const whole = parts[0] || "0";
    const frac = ((parts[1] || "") + "000000000000000000").slice(0, 18);
    const wei = BigInt(whole) * 10n ** 18n + BigInt(frac);
    return "0x" + wei.toString(16);
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

    async ensureAbsoluteChain(opts) {
      if (!this.provider) throw new Error("Connect a wallet first");
      const chainId = Number(opts.chainId);
      if (!Number.isFinite(chainId) || chainId <= 0) {
        throw new Error("Invalid Absolute chain_id");
      }
      const hexId = toHexChainId(chainId);
      const current = String(await this.chainId()).toLowerCase();
      if (current === hexId.toLowerCase()) return { switched: false, chainId: hexId };

      try {
        await this.provider.request({
          method: "wallet_switchEthereumChain",
          params: [{ chainId: hexId }],
        });
        return { switched: true, chainId: hexId };
      } catch (e) {
        // 4902 = unknown chain → add
        if (e && (e.code === 4902 || e.code === -32603 || /Unrecognized chain/i.test(String(e.message)))) {
          const rpcUrl = opts.rpcUrl;
          if (!rpcUrl) throw new Error("rpcUrl required to add Absolute chain");
          await this.provider.request({
            method: "wallet_addEthereumChain",
            params: [
              {
                chainId: hexId,
                chainName: opts.chainName || ("Absolute " + chainId),
                nativeCurrency: {
                  name: opts.symbol || "ABS",
                  symbol: opts.symbol || "ABS",
                  decimals: 18,
                },
                rpcUrls: [rpcUrl],
                blockExplorerUrls: opts.explorerUrl ? [opts.explorerUrl] : [],
              },
            ],
          });
          return { switched: true, added: true, chainId: hexId };
        }
        throw e;
      }
    },

    async personalSign(message) {
      if (!this.accounts[0]) throw new Error("Connect a wallet first");
      return this.provider.request({
        method: "personal_sign",
        params: [message, this.accounts[0]],
      });
    },

    /**
     * Browser-wallet signed send. Refuses prod auto-sign paths by never
     * posting keys; MetaMask signs locally.
     */
    async sendTransaction(tx) {
      if (!this.accounts[0]) throw new Error("Connect a wallet first");
      const to = String(tx.to || "").trim();
      if (!/^0x[0-9a-fA-F]{40}$/.test(to)) throw new Error("Invalid to address");
      const valueHex =
        tx.valueHex ||
        (tx.amountAbs != null ? absToWeiHex(tx.amountAbs) : "0x0");
      const params = {
        from: this.accounts[0],
        to: to,
        value: valueHex,
      };
      if (tx.data) params.data = tx.data;
      if (tx.gas) params.gas = tx.gas;
      return this.provider.request({
        method: "eth_sendTransaction",
        params: [params],
      });
    },

    absToWeiHex: absToWeiHex,
    toHexChainId: toHexChainId,

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
