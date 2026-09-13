/* Canvas sparklines — no chart library. */
(function (global) {
  "use strict";

  function Sparkline(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.color = (opts && opts.color) || "#3dd6c6";
    this.fill = (opts && opts.fill) || "rgba(61,214,198,0.12)";
    this.maxPoints = (opts && opts.maxPoints) || 48;
    this.series = [];
    this._resize();
  }

  Sparkline.prototype._resize = function () {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    this.canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = rect.width;
    this.h = rect.height;
  };

  Sparkline.prototype.push = function (v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return;
    this.series.push(n);
    if (this.series.length > this.maxPoints) this.series.shift();
    this.draw();
  };

  Sparkline.prototype.draw = function () {
    this._resize();
    const ctx = this.ctx;
    const w = this.w;
    const h = this.h;
    ctx.clearRect(0, 0, w, h);
    if (this.series.length < 2) return;
    let min = Math.min.apply(null, this.series);
    let max = Math.max.apply(null, this.series);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = 8;
    const step = (w - pad * 2) / (this.series.length - 1);
    ctx.beginPath();
    this.series.forEach((v, i) => {
      const x = pad + i * step;
      const y = h - pad - ((v - min) / (max - min)) * (h - pad * 2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = this.color;
    ctx.lineWidth = 1.6;
    ctx.stroke();
    ctx.lineTo(pad + (this.series.length - 1) * step, h - pad);
    ctx.lineTo(pad, h - pad);
    ctx.closePath();
    ctx.fillStyle = this.fill;
    ctx.fill();
  };

  function parsePrometheus(text) {
    const out = [];
    const lines = String(text || "").split("\n");
    for (const line of lines) {
      if (!line || line.startsWith("#")) continue;
      const m = line.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eE]+)\s*$/);
      if (!m) continue;
      const labels = {};
      if (m[2]) {
        const body = m[2].slice(1, -1);
        body.replace(/([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"/g, (_, k, v) => {
          labels[k] = v.replace(/\\"/g, '"').replace(/\\\\/g, "\\");
          return "";
        });
      }
      out.push({ name: m[1], labels, value: Number(m[3]) });
    }
    return out;
  }

  global.AbsCharts = { Sparkline, parsePrometheus };
})(window);
