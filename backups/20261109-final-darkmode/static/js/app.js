/* Shared helpers for the switch operations console. */
(function () {
  "use strict";

  const STATUS_LABELS = {
    ok: "Healthy",
    warning: "Warning",
    critical: "Critical",
    unknown: "Unknown",
    up: "Up",
    down: "Down",
    disabled: "Disabled",
    fiber: "Fiber",
    copper: "Copper",
    other: "Other",
    minor: "Minor",
    major: "Major"
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function statusLabel(status) {
    if (status == null) return "Unknown";
    const key = String(status).toLowerCase();
    if (STATUS_LABELS[key]) return STATUS_LABELS[key];
    return key.charAt(0).toUpperCase() + key.slice(1);
  }

  function badge(status, label) {
    const safeStatus = String(status || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "");
    return '<span class="badge badge-' + safeStatus + '"><span class="badge-dot"></span>' +
      escapeHtml(label || statusLabel(status)) + "</span>";
  }

  function fmtNum(value, suffix) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) + (suffix || "");
  }

  function fmtDbm(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const number = Number(value);
    return (number >= 0 ? "+" : "") + number.toFixed(1) + " dBm";
  }

  function fmtDb(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(1) + " dB";
  }

  function fmtPct(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(1) + "%";
  }

  function fmtSpeed(mbps) {
    if (!mbps) return "—";
    const value = Number(mbps);
    if (value >= 1000) return (value / 1000).toFixed(value % 1000 === 0 ? 0 : 1) + " Gbps";
    return value.toFixed(0) + " Mbps";
  }

  function fmtRate(mbps) {
    if (mbps === null || mbps === undefined) return "—";
    const value = Number(mbps);
    if (value >= 1000) return (value / 1000).toFixed(2) + " Gbps";
    if (value >= 1) return value.toFixed(2) + " Mbps";
    if (value > 0) return (value * 1000).toFixed(0) + " kbps";
    return "0 Mbps";
  }

  function fmtTimestamp(epochSeconds) {
    if (!epochSeconds) return "—";
    const date = new Date(Number(epochSeconds) * 1000);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function statusRank(status) {
    const ranks = { ok: 0, unknown: 1, warning: 2, critical: 3 };
    const key = String(status || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(ranks, key) ? ranks[key] : 1;
  }

  function setLive(state, label) {
    const indicator = document.getElementById("live-indicator");
    const text = document.getElementById("live-label");
    if (!indicator) return;
    indicator.classList.remove("stale", "offline");
    if (state === "stale") indicator.classList.add("stale");
    if (state === "offline") indicator.classList.add("offline");
    if (text && label) text.textContent = label;
  }

  function initTheme() {
    const root = document.documentElement;
    const button = document.getElementById("theme-toggle");
    const label = document.getElementById("theme-toggle-label");
    let stored = null;
    try { stored = localStorage.getItem("snmpdash-theme"); } catch (error) { /* storage disabled */ }

    function current() {
      return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
    }

    function apply(next, persist) {
      if (next === "dark") root.setAttribute("data-theme", "dark");
      else root.removeAttribute("data-theme");
      if (button) {
        button.setAttribute("aria-pressed", next === "dark" ? "true" : "false");
        button.setAttribute("aria-label", next === "dark" ? "Switch to light mode" : "Switch to dark mode");
      }
      if (label) label.textContent = next === "dark" ? "Light" : "Dark";
      if (persist) {
        try { localStorage.setItem("snmpdash-theme", next); } catch (error) { /* storage disabled */ }
      }
    }

    apply(stored === "dark" ? "dark" : "light", false);
    if (button) {
      button.addEventListener("click", function () {
        apply(current() === "dark" ? "light" : "dark", true);
      });
    }
  }

  async function fetchJSON(url) {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      throw new Error("HTTP " + response.status + " for " + url);
    }
    return response.json();
  }

  function startPolling(callback, seconds, onError) {
    let busy = false;
    let timer = null;

    async function run() {
      if (busy) return;
      busy = true;
      try {
        const result = await callback();
        if (result && result.state) {
          setLive(result.state, result.label || "Live");
        } else {
          setLive("live", "Live");
        }
      } catch (error) {
        setLive("stale", "Stale");
        if (typeof onError === "function") onError(error);
        // eslint-disable-next-line no-console
        console.error(error);
      } finally {
        busy = false;
      }
    }

    run();
    const delay = Math.max(2, Number(seconds) || 5) * 1000;
    timer = window.setInterval(run, delay);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") run();
    });
    return {
      refresh: run,
      stop: function () {
        if (timer) window.clearInterval(timer);
        timer = null;
      }
    };
  }

  function portTileClass(port) {
    let state = port.status || "unknown";
    if (port.sfp && port.sfp.status === "critical") state = "critical";
    else if (port.sfp && port.sfp.status === "warning" && state === "up") state = "warning";
    return "port-tile " + state + (port.media === "fiber" ? " fiber" : "");
  }

  initTheme();

  window.App = {
    escapeHtml: escapeHtml,
    statusLabel: statusLabel,
    badge: badge,
    fmtNum: fmtNum,
    fmtDbm: fmtDbm,
    fmtDb: fmtDb,
    fmtPct: fmtPct,
    fmtSpeed: fmtSpeed,
    fmtRate: fmtRate,
    fmtTimestamp: fmtTimestamp,
    statusRank: statusRank,
    setLive: setLive,
    fetchJSON: fetchJSON,
    startPolling: startPolling,
    portTileClass: portTileClass
  };
})();
