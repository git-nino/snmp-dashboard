/* Network overview live view. */
(function () {
  "use strict";

  const A = window.App;
  const refresh = Number(window.__REFRESH__) || 5;
  let switches = Array.isArray(window.__OVERVIEW__) ? window.__OVERVIEW__ : [];

  function worstStatus(list) {
    return list.reduce(function (worst, item) {
      return A.statusRank(item.status) > A.statusRank(worst) ? item : worst;
    }, { status: "ok" }).status;
  }

  function totals(list) {
    return list.reduce(function (acc, item) {
      acc.online += item.online ? 1 : 0;
      acc.ports += item.ports.total || 0;
      acc.up += item.ports.up || 0;
      acc.down += item.ports.down || 0;
      acc.disabled += item.ports.disabled || 0;
      acc.fiber += item.ports.fiber || 0;
      acc.sfp += item.sfp_count || 0;
      acc.alerts += item.alerts || 0;
      return acc;
    }, { online: 0, ports: 0, up: 0, down: 0, disabled: 0, fiber: 0, sfp: 0, alerts: 0 });
  }

  function renderStats() {
    const container = document.getElementById("overview-stats");
    if (!container) return;
    const t = totals(switches);
    const upPercent = t.ports ? (t.up * 100 / t.ports) : 0;
    const worst = worstStatus(switches);
    const healthy = switches.filter(function (s) { return s.status === "ok"; }).length;
    const warning = switches.filter(function (s) { return s.status === "warning"; }).length;
    const critical = switches.filter(function (s) { return s.status === "critical"; }).length;

    const cards = [
      {
        label: "Switches online",
        value: t.online + '<small> / ' + switches.length + "</small>",
        sub: t.online === switches.length ? "All managed devices responding" : (switches.length - t.online) + " device(s) unreachable",
        state: t.online === switches.length ? "ok" : "critical"
      },
      {
        label: "Ports up",
        value: t.up + '<small> / ' + t.ports + "</small>",
        sub: upPercent.toFixed(1) + "% available · " + t.down + " down · " + t.disabled + " disabled",
        state: t.down ? "warning" : "ok"
      },
      {
        label: "Fiber links",
        value: String(t.fiber),
        sub: t.sfp + " SFP modules · DDM telemetry",
        state: "ok"
      },
      {
        label: "Active alerts",
        value: String(t.alerts),
        sub: t.alerts ? "Action recommended" : "No active alerts",
        state: t.alerts ? worst : "ok"
      },
      {
        label: "Fabric health",
        value: A.badge(worst),
        sub: healthy + " healthy · " + warning + " warning · " + critical + " critical",
        state: worst
      }
    ];

    container.innerHTML = cards.map(function (card) {
      const stateClass = card.state && card.state !== "ok" ? " state-" + card.state : "";
      return '<article class="stat-card' + stateClass + '">' +
        '<div class="stat-label">' + A.escapeHtml(card.label) + "</div>" +
        '<div class="stat-value">' + card.value + "</div>" +
        '<div class="stat-sub">' + card.sub + "</div>" +
        "</article>";
    }).join("");
  }

  function portBar(ports) {
    const total = ports.total || 0;
    if (!total) return '<div class="port-bar"><span class="seg-disabled" style="width:100%"></span></div>';
    const up = ports.up || 0;
    const down = ports.down || 0;
    const disabled = ports.disabled || 0;
    return '<div class="port-bar" title="' + up + " up / " + down + " down / " + disabled + ' disabled">' +
      '<span class="seg-up" style="width:' + (up * 100 / total) + '%"></span>' +
      '<span class="seg-down" style="width:' + (down * 100 / total) + '%"></span>' +
      '<span class="seg-disabled" style="width:' + (disabled * 100 / total) + '%"></span>' +
      "</div>";
  }

  function renderCards() {
    const container = document.getElementById("switch-grid");
    if (!container) return;
    if (!switches.length) {
      container.innerHTML = '<div class="panel"><div class="notice">Waiting for switch telemetry…</div></div>';
      return;
    }

    container.innerHTML = switches.map(function (item) {
      const state = item.online ? item.status : "critical";
      const alertClass = !item.online ? "" : (item.status === "warning" ? " warning" : (item.status === "critical" ? "" : " ok"));
      let alertText;
      if (!item.online) {
        alertText = "No SNMP response from " + item.host;
      } else if (item.alerts) {
        alertText = item.alerts + " active alert" + (item.alerts === 1 ? "" : "s") + " — open the dashboard for detail";
      } else {
        alertText = "All monitored values are within thresholds";
      }

      return '<article class="switch-card state-' + A.escapeHtml(state) + '">' +
        '<div class="switch-card-top">' +
          "<div>" +
            '<h2 class="switch-card-name">' + A.escapeHtml(item.name) + "</h2>" +
            '<p class="switch-card-model">' + A.escapeHtml(item.model || "Unknown model") + "</p>" +
            '<div class="switch-card-host">' + A.escapeHtml(item.host) + "</div>" +
          "</div>" +
          A.badge(item.online ? item.status : "critical", item.online ? undefined : "Offline") +
        "</div>" +
        portBar(item.ports) +
        '<div class="switch-card-metrics">' +
          '<div class="mini-metric"><span>Ports up</span><strong>' + (item.ports.up || 0) + " / " + (item.ports.total || 0) + "</strong><small>" + (item.ports.up_percent || 0) + "% available</small></div>" +
          '<div class="mini-metric"><span>Fiber</span><strong>' + (item.ports.fiber || 0) + "</strong><small>" + (item.sfp_count || 0) + " SFP modules</small></div>" +
          '<div class="mini-metric"><span>Temp</span><strong>' + (item.temperature_c == null ? "—" : item.temperature_c + " °C") + "</strong><small>Chassis sensor</small></div>" +
          '<div class="mini-metric"><span>Uptime</span><strong>' + A.escapeHtml(item.uptime_text || "—") + "</strong><small>" + (item.cpu_percent == null ? "CPU —" : "CPU " + item.cpu_percent + "%") + "</small></div>" +
        "</div>" +
        '<div class="switch-card-alert' + alertClass + '">' + A.escapeHtml(alertText) + "</div>" +
        '<div class="switch-card-actions">' +
          '<a class="btn btn-primary" href="/switch/' + encodeURIComponent(item.id) + '">Open dashboard</a>' +
          '<a class="btn btn-ghost" href="/report/' + encodeURIComponent(item.id) + '" target="_blank" rel="noopener">A4 report</a>' +
        "</div>" +
      "</article>";
    }).join("");
  }

  function renderTable() {
    const body = document.getElementById("fabric-body");
    if (!body) return;
    if (!switches.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="10">Waiting for switch telemetry…</td></tr>';
      return;
    }
    body.innerHTML = switches.map(function (item) {
      return "<tr>" +
        '<td class="strong">' + A.escapeHtml(item.name) + '<br><span class="muted mono">' + A.escapeHtml(item.host) + "</span></td>" +
        "<td>" + A.badge(item.online ? item.status : "critical", item.online ? undefined : "Offline") + "</td>" +
        "<td>" + A.escapeHtml(item.model || "—") + "</td>" +
        "<td>" + A.escapeHtml(item.uptime_text || "—") + "</td>" +
        '<td class="num">' + (item.ports.up || 0) + " / " + (item.ports.total || 0) + "</td>" +
        '<td class="num">' + (item.ports.fiber || 0) + "</td>" +
        '<td class="num">' + (item.sfp_count || 0) + "</td>" +
        '<td class="num">' + (item.temperature_c == null ? "—" : item.temperature_c + " °C") + "</td>" +
        '<td class="num">' + (item.cpu_percent == null ? "—" : item.cpu_percent + "%") + "</td>" +
        '<td class="num">' + (item.alerts || 0) + "</td>" +
      "</tr>";
    }).join("");
  }

  function render(list) {
    switches = Array.isArray(list) ? list : [];
    renderStats();
    renderCards();
    renderTable();
    const updated = document.getElementById("fabric-updated");
    if (updated && switches.length) {
      const newest = switches.reduce(function (latest, item) {
        return Math.max(latest, item.last_poll || 0);
      }, 0);
      updated.textContent = "Updated " + A.fmtTimestamp(newest);
    }
  }

  render(switches);

  A.startPolling(async function () {
    const data = await A.fetchJSON("/api/switches");
    render(data);
  }, refresh, function () {
    const updated = document.getElementById("fabric-updated");
    if (updated) updated.textContent = "Telemetry unavailable";
  });
})();
