/* Apply theme before paint — kept as external file for CSP (no inline script). */
(function () {
  "use strict";
  try {
    var t = localStorage.getItem("abs_console_theme");
    if (t === "light" || t === "dark") {
      document.documentElement.setAttribute("data-theme", t);
    }
  } catch (e) {}
})();
