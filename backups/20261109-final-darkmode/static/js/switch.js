/* Live switch dashboard. */
(function () {
  "use strict";

  const A = window.App;
  const switchId = window.__SWITCH_ID__;
  const refresh = Number(window.__REFRESH__) || 5;
  let data = window.__SWITCH__ || {};
  let selectedPort = null;
  let poller = null;

  const $ = function (id) { return document.getElementById(id); };

  function escape(value) { return A.escapeHtml(value); }

  function valueOrDash(value) {
    return value === null || value === undefined || value === "" ? "—" : value;
  }

  function friendlyClass(value) {
    return {
      chassis: "Chassis",
      powerSupply: "Power supply",
      fan: "Fan",
      module: "Module",
      sensor: "Sensor",
      backplane: "Backplane",
      container: "Container",
      port: "Port",
      stack: "Stack",
      cpu: "CPU"
    }[value] || A.statusLabel(value);
  }

  function fmtSensor(value, unit) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const number = Number(value);
    let decimals = 1;
    if (unit === "V" || unit === "mA" || unit === "A") decimals = 2;
    if (unit === "rpm") decimals = 0;
    return number.toFixed(decimals) + (unit ? " " + unit : "");
  }

  function banner(severity, title, bodyHtml) {
    const cls = severity === "critical" ? "" : (severity === "warning" ? " warning" : " ok");
    const icon = severity === "ok" ? "✓" : "!";
    return '<div class="alert-banner' + cls + '">' +
      '<div class="alert-banner-icon">' + icon + "</div>" +
      '<div class="alert-banner-body">' +
        '<div class="alert-banner-title">' + escape(title) + "</div>" +
        '<div class="alert-banner-text">' + bodyHtml + "</div>" +
      "</div>" +
    "</div>";
  }

  function renderHeader() {
    const sub = $("switch-sub");
    if (!sub) return;
    const hardware = data.hardware || {};
    const sys = data.sys || {};
    const pieces = [];
    pieces.push(hardware.model || "Unknown model");
    if (hardware.serial && hardware.serial !== "—") pieces.push("Serial " + hardware.serial);
    pieces.push(data.host || "");
    pieces.push("Uptime " + (sys.uptime_text || "—"));
    if (data.last_poll) pieces.push("Polled " + A.fmtTimestamp(data.last_poll));
    sub.innerHTML = A.badge(data.online ? (data.health || {}).status : "critical", data.online ? undefined : "Offline") +
      ' <span class="muted">' + pieces.filter(Boolean).map(escape).join(" · ") + "</span>";
  }

  function renderAlerts() {
    const strip = $("alert-strip");
    if (!strip) return;
    const alerts = Array.isArray(data.alerts) ? data.alerts : [];

    if (!data.online) {
      strip.innerHTML = banner("critical", "Switch unreachable",
        escape(data.last_error || "No SNMP response from " + (data.host || "device")));
      return;
    }

    if (!alerts.length) {
      strip.innerHTML = banner("ok", "All monitored values are within thresholds",
        "Hardware, ports and optical telemetry are healthy.");
      return;
    }

    const worst = alerts.reduce(function (current, alert) {
      return A.statusRank(alert.severity) > A.statusRank(current) ? alert.severity : current;
    }, "ok");
    const visible = alerts.slice(0, 4).map(function (alert) {
      return "<li>" + escape(alert.text) + "</li>";
    }).join("");
    const extra = alerts.length > 4 ? "<li>+" + (alerts.length - 4) + " more alert(s)</li>" : "";
    strip.innerHTML = banner(worst, alerts.length + " active alert" + (alerts.length === 1 ? "" : "s"),
      "<ul>" + visible + extra + "</ul>");
  }

  function renderStats() {
    const container = $("switch-stats");
    if (!container) return;
    const hardware = data.hardware || {};
    const health = data.health || {};
    const ports = data.port_summary || {};
    const cpu = health.cpu_percent;
    const memory = health.memory_percent;
    const loadState = (cpu != null && cpu >= 90) || (memory != null && memory >= 90) ? "warning" : "ok";

    const cards = [
      {
        label: "Hardware state",
        value: A.badge(health.hardware_status || "unknown"),
        sub: escape(hardware.model || "—") + " · " + (health.psu_count || 0) + " PSU · " + (health.fan_count || 0) + " fan",
        state: health.hardware_status || "unknown"
      },
      {
        label: "Ports up",
        value: (ports.up || 0) + "<small> / " + (ports.total || 0) + "</small>",
        sub: (ports.up_percent || 0) + "% available · " + (ports.down || 0) + " down · " + (ports.disabled || 0) + " disabled",
        state: "ok"
      },
      {
        label: "Optics",
        value: A.badge(health.optics_status || "unknown"),
        sub: (health.sfp_count || 0) + " SFP modules · " + (ports.fiber || 0) + " fiber links",
        state: health.optics_status || "unknown"
      },
      {
        label: "Temperature",
        value: (health.temperature_c == null ? "—" : health.temperature_c) + "<small> °C</small>",
        sub: escape(health.temperature_sensor || "—") + " · " + A.statusLabel(health.temperature_status),
        state: health.temperature_status || "unknown"
      },
      {
        label: "Load",
        value: (cpu == null ? "—" : cpu) + "<small>% CPU</small>",
        sub: "Memory " + (memory == null ? "—" : memory + "%") + " · " + (health.sensor_count || 0) + " sensors",
        state: loadState
      }
    ];

    container.innerHTML = cards.map(function (card) {
      const stateClass = card.state && card.state !== "ok" ? " state-" + card.state : "";
      return '<article class="stat-card' + stateClass + '">' +
        '<div class="stat-label">' + escape(card.label) + "</div>" +
        '<div class="stat-value">' + card.value + "</div>" +
        '<div class="stat-sub">' + card.sub + "</div>" +
      "</article>";
    }).join("");
  }

  function meter(value) {
    if (value == null || Number.isNaN(Number(value))) return "";
    const number = Math.max(0, Math.min(100, Number(value)));
    const cls = number >= 90 ? "critical" : (number >= 80 ? "warning" : "");
    return '<div class="meter"><span class="' + cls + '" style="width:' + number + '%"></span></div>';
  }

  function renderHardwareHealth() {
    const badge = $("hardware-badge");
    const container = $("hardware-health");
    if (!container) return;
    const hardware = data.hardware || {};
    const health = data.health || {};
    if (badge) badge.innerHTML = A.badge(health.hardware_status || "unknown");

    function row(label, valueHtml, statusHtml, extraHtml) {
      return '<div class="health-row">' +
        '<div class="health-label">' + escape(label) + "</div>" +
        '<div class="health-value">' + valueHtml + (extraHtml || "") + "</div>" +
        "<div>" + statusHtml + "</div>" +
      "</div>";
    }

    const rows = [];
    rows.push(row("Chassis", escape(hardware.model || "—") + '<small>Serial ' + escape(hardware.serial || "—") + "</small>",
      A.badge(health.hardware_status || "unknown")));
    rows.push(row("Power", (health.psu_count || 0) + " present", A.badge(health.psu_count ? "ok" : "unknown")));
    rows.push(row("Cooling", (health.fan_count || 0) + " fan tray" + (health.fan_count === 1 ? "" : "s"),
      A.badge(health.fan_count ? "ok" : "unknown")));
    rows.push(row("Temperature", (health.temperature_c == null ? "—" : health.temperature_c + " °C") +
      '<small>' + escape(health.temperature_sensor || "—") + "</small>", A.badge(health.temperature_status || "unknown")));
    rows.push(row("CPU", (health.cpu_percent == null ? "—" : health.cpu_percent + "%"),
      A.badge(health.cpu_percent != null && health.cpu_percent >= 90 ? "warning" : "ok"), meter(health.cpu_percent)));
    rows.push(row("Memory", (health.memory_percent == null ? "—" : health.memory_percent + "%"),
      A.badge(health.memory_percent != null && health.memory_percent >= 90 ? "warning" : "ok"), meter(health.memory_percent)));
    rows.push(row("Optics", (health.sfp_count || 0) + " SFP module" + (health.sfp_count === 1 ? "" : "s") +
      '<small>' + (data.port_summary || {}).fiber + " fiber links</small>", A.badge(health.optics_status || "unknown")));

    container.innerHTML = '<div class="health-list">' + rows.join("") + "</div>";
  }

  function renderPortGrid() {
    const grid = $("port-grid");
    if (!grid) return;
    const ports = Array.isArray(data.ports) ? data.ports : [];
    if (!ports.length) {
      grid.innerHTML = '<div class="notice">No ports reported by this device.</div>';
      return;
    }

    grid.innerHTML = ports.map(function (port) {
      const selected = selectedPort === port.index ? " selected" : "";
      const title = port.name + " · " + (port.alias || "No alias") + " · " + A.statusLabel(port.status) +
        " · " + A.statusLabel(port.media) + " · " + (port.speed_label || "—") +
        (port.sfp ? " · Rx " + A.fmtDbm(port.sfp.rx_dbm) : "");
      return '<button type="button" class="' + A.portTileClass(port) + selected + '"' +
        ' data-port-index="' + escape(port.index) + '"' +
        ' title="' + escape(title) + '" aria-label="' + escape(title) + '">' +
        '<span class="port-led"></span>' +
        '<span class="port-num">' + escape(port.index) + "</span>" +
        '<span class="port-kind">' + (port.media === "fiber" ? "SFP" : "Cu") + "</span>" +
      "</button>";
    }).join("");

    grid.querySelectorAll(".port-tile").forEach(function (button) {
      button.addEventListener("click", function () {
        selectedPort = Number(button.getAttribute("data-port-index"));
        renderPortGrid();
        renderPortDetail();
      });
    });
  }

  function renderPortDetail() {
    const detail = $("port-detail");
    if (!detail) return;
    if (selectedPort === null) {
      detail.hidden = true;
      detail.innerHTML = "";
      return;
    }
    const port = (data.ports || []).find(function (item) { return item.index === selectedPort; });
    if (!port) {
      detail.hidden = true;
      detail.innerHTML = "";
      return;
    }

    function item(label, value) {
      return "<div><span>" + escape(label) + "</span><strong>" + value + "</strong></div>";
    }

    const sfp = port.sfp;
    const items = [
      item("State", A.badge(port.status)),
      item("Media", A.badge(port.media, A.statusLabel(port.media))),
      item("Speed", escape(port.speed_label || "—")),
      item("VLAN", escape(port.vlan_id || "—") + (port.vlan_name ? " / " + escape(port.vlan_name) : "")),
      item("Rx rate", A.fmtRate(port.rx_mbps)),
      item("Tx rate", A.fmtRate(port.tx_mbps)),
      item("Utilization", A.fmtPct(port.utilization)),
      item("Errors", String(port.in_errors + port.out_errors)),
      item("Last change", escape(port.last_change || "—"))
    ];
    if (sfp) {
      items.push(item("SFP module", escape(sfp.model || sfp.name || "—")));
      items.push(item("SFP Rx", A.fmtDbm(sfp.rx_dbm)));
      items.push(item("SFP Tx", A.fmtDbm(sfp.tx_dbm)));
      items.push(item("Optical margin", A.fmtDb(sfp.margin_db)));
    }

    detail.hidden = false;
    detail.innerHTML = '<div class="port-detail-head">' +
      '<div class="port-detail-title">' + escape(port.name) + ' <span class="muted">' + escape(port.alias || "") + "</span></div>" +
      "<div>" + A.badge(port.status) + (sfp ? " " + A.badge(sfp.status, "SFP " + A.statusLabel(sfp.status)) : "") + "</div>" +
    "</div>" +
    '<div class="port-detail-grid">' + items.join("") + "</div>";
  }

  function metric(label, value, cls, sub) {
    return '<div class="sfp-metric">' +
      "<span>" + escape(label) + "</span>" +
      '<strong class="' + (cls || "") + '">' + value + "</strong>" +
      (sub ? "<small>" + sub + "</small>" : "") +
    "</div>";
  }

  function signalBar(sfp) {
    const thresholds = sfp.thresholds || {};
    const rx = thresholds.rx || {};
    if (sfp.rx_dbm == null || rx.low_alarm == null) return "";

    const lowAlarm = Number(rx.low_alarm);
    const highBase = rx.high_alarm != null ? Number(rx.high_alarm)
      : (rx.high_warn != null ? Number(rx.high_warn) : lowAlarm + 10);
    const min = lowAlarm - 2;
    const max = highBase + 2;
    const span = Math.max(max - min, 0.1);
    const lowWarn = rx.low_warn != null ? Number(rx.low_warn) : lowAlarm;
    const highWarn = rx.high_warn != null ? Number(rx.high_warn) : highBase;
    const highAlarm = rx.high_alarm != null ? Number(rx.high_alarm) : max;

    function pct(value) {
      return Math.max(0, Math.min(100, (Number(value) - min) / span * 100));
    }

    let cursor = min;
    const zones = [];
    function zone(to, cls) {
      const width = pct(to) - pct(cursor);
      if (width > 0) zones.push('<span class="signal-zone ' + cls + '" style="width:' + width + '%"></span>');
      cursor = to;
    }
    zone(lowAlarm, "alarm");
    zone(lowWarn, "warn");
    zone(highWarn, "good");
    zone(highAlarm, "warn");
    zone(max, "alarm");

    const markerClass = sfp.status === "critical" ? "critical" : (sfp.status === "warning" ? "warning" : "");
    const marker = '<span class="signal-marker ' + markerClass + '" style="left:' + pct(sfp.rx_dbm) + '%"></span>';

    function threshold(label, value) {
      return "<span>" + escape(label) + " <b>" + A.fmtDbm(value) + "</b></span>";
    }

    return '<div class="signal-block">' +
      '<div class="signal-head"><span>Rx signal vs thresholds</span><span>' + A.fmtDbm(sfp.rx_dbm) + "</span></div>" +
      '<div class="signal-track"><div class="signal-zones">' + zones.join("") + "</div>" + marker + "</div>" +
      '<div class="signal-scale"><span>' + A.fmtDbm(min) + "</span><span>" + A.fmtDbm(max) + "</span></div>" +
      '<div class="sfp-thresholds">' +
        threshold("Rx low alarm", rx.low_alarm) +
        threshold("Rx low warn", rx.low_warn) +
        threshold("Rx high warn", rx.high_warn) +
        threshold("Rx high alarm", rx.high_alarm) +
      "</div>" +
      '<div class="sfp-thresholds">' +
        threshold("Tx low alarm", (thresholds.tx || {}).low_alarm) +
        threshold("Tx high alarm", (thresholds.tx || {}).high_alarm) +
      "</div>" +
    "</div>";
  }

  function renderSfpGrid() {
    const grid = $("sfp-grid");
    const note = $("optics-note");
    if (!grid) return;
    const sfps = Array.isArray(data.sfps) ? data.sfps : [];
    if (note) {
      note.textContent = sfps.length
        ? sfps.length + " transceiver" + (sfps.length === 1 ? "" : "s") + " with DDM telemetry"
        : "No DDM-capable optics reported";
    }
    if (!sfps.length) {
      grid.innerHTML = '<div class="notice">No SFP/DDM telemetry was reported for this switch.</div>';
      return;
    }

    grid.innerHTML = sfps.map(function (sfp) {
      const rx = (sfp.thresholds || {}).rx || {};
      const rxClass = sfp.status === "critical" ? "critical" : (sfp.status === "warning" ? "warning" : "");
      const marginClass = sfp.margin_db != null && sfp.margin_db < 0 ? "critical" : "";
      const alerts = Array.isArray(sfp.alerts) ? sfp.alerts : [];
      const alertHtml = alerts.length
        ? '<div class="sfp-alert ' + (sfp.status === "warning" ? "warning" : "") + '">' + escape(alerts[0].text) + "</div>"
        : "";

      return '<article class="sfp-card state-' + escape(sfp.status) + '">' +
        '<div class="sfp-head">' +
          "<div>" +
            '<h3 class="sfp-title">' + escape(sfp.port_name) +
              (sfp.alias ? ' <span class="muted">/ ' + escape(sfp.alias) + "</span>" : "") + "</h3>" +
            '<p class="sfp-sub">' + escape(sfp.model || sfp.name) + " · " + escape(sfp.module) +
              " · " + escape(sfp.fiber) + " · " + escape(sfp.reach) + "</p>" +
          "</div>" +
          A.badge(sfp.status) +
        "</div>" +
        '<div class="sfp-metrics">' +
          metric("Rx power", A.fmtDbm(sfp.rx_dbm), rxClass, "low alarm " + A.fmtDbm(rx.low_alarm)) +
          metric("Tx power", A.fmtDbm(sfp.tx_dbm), "", "launch power") +
          metric("Link loss", A.fmtDb(sfp.loss_db), "", "Tx − Rx") +
          metric("Margin", A.fmtDb(sfp.margin_db), marginClass, "to low alarm") +
        "</div>" +
        signalBar(sfp) +
        '<div class="sfp-thresholds">' +
          "<span>Temp <b>" + (sfp.temperature_c == null ? "—" : Number(sfp.temperature_c).toFixed(1) + " °C") + "</b></span>" +
          "<span>Voltage <b>" + (sfp.voltage_v == null ? "—" : Number(sfp.voltage_v).toFixed(2) + " V") + "</b></span>" +
          "<span>Bias <b>" + (sfp.bias_ma == null ? "—" : Number(sfp.bias_ma).toFixed(1) + " mA") + "</b></span>" +
          "<span>Budget <b>" + A.fmtDb(sfp.budget_db) + "</b></span>" +
        "</div>" +
        alertHtml +
      "</article>";
    }).join("");
  }

  function filteredPorts() {
    const search = ($("port-search") && $("port-search").value || "").toLowerCase().trim();
    const status = ($("port-status-filter") && $("port-status-filter").value) || "all";
    const media = ($("port-media-filter") && $("port-media-filter").value) || "all";
    return (data.ports || []).filter(function (port) {
      if (status !== "all" && port.status !== status) return false;
      if (media !== "all" && port.media !== media) return false;
      if (!search) return true;
      return [port.name, port.alias, port.vlan_id, port.vlan_name, port.media, port.status]
        .join(" ").toLowerCase().indexOf(search) !== -1;
    });
  }

  function renderPortTable() {
    const body = $("port-body");
    if (!body) return;
    const all = data.ports || [];
    const ports = filteredPorts();

    if (!ports.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="12">No ports match the current filter.</td></tr>';
    } else {
      body.innerHTML = ports.map(function (port) {
        const errors = (port.in_errors || 0) + (port.out_errors || 0);
        const sfpState = port.sfp && port.sfp.status !== "ok"
          ? " " + A.badge(port.sfp.status, "SFP")
          : "";
        return '<tr data-port-index="' + escape(port.index) + '">' +
          '<td class="strong">' + escape(port.name) + "</td>" +
          "<td>" + escape(port.alias || "—") + "</td>" +
          "<td>" + A.badge(port.status) + sfpState + "</td>" +
          "<td>" + A.badge(port.media, A.statusLabel(port.media)) + "</td>" +
          "<td>" + escape(port.speed_label || "—") + "</td>" +
          "<td>" + escape(port.vlan_id || "—") + (port.vlan_name ? ' <span class="muted">/ ' + escape(port.vlan_name) + "</span>" : "") + "</td>" +
          '<td class="num">' + A.fmtRate(port.rx_mbps) + "</td>" +
          '<td class="num">' + A.fmtRate(port.tx_mbps) + "</td>" +
          '<td class="num">' + A.fmtPct(port.utilization) + "</td>" +
          '<td class="num">' + errors + "</td>" +
          '<td class="num">' + (port.sfp ? A.fmtDbm(port.sfp.rx_dbm) : "—") + "</td>" +
          "<td>" + escape(port.last_change || "—") + "</td>" +
        "</tr>";
      }).join("");
    }

    body.querySelectorAll("tr[data-port-index]").forEach(function (row) {
      row.addEventListener("click", function () {
        selectedPort = Number(row.getAttribute("data-port-index"));
        renderPortGrid();
        renderPortDetail();
        const grid = $("port-grid");
        if (grid) grid.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });

    const foot = $("port-foot");
    if (foot) {
      const up = ports.filter(function (p) { return p.status === "up"; }).length;
      const down = ports.filter(function (p) { return p.status === "down"; }).length;
      const disabled = ports.filter(function (p) { return p.status === "disabled"; }).length;
      foot.innerHTML = "Showing <strong>" + ports.length + "</strong> of <strong>" + all.length +
        "</strong> ports · <strong>" + up + "</strong> up · <strong>" + down + "</strong> down · <strong>" +
        disabled + "</strong> disabled";
    }
  }

  function renderComponents() {
    const body = $("component-body");
    if (!body) return;
    const components = (data.hardware || {}).components || [];
    if (!components.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="5">No physical components reported.</td></tr>';
      return;
    }
    body.innerHTML = components.map(function (component) {
      return "<tr>" +
        '<td class="strong">' + escape(component.name) + "</td>" +
        "<td>" + escape(friendlyClass(component.class)) + "</td>" +
        "<td>" + escape(component.model || "—") + "</td>" +
        '<td class="mono">' + escape(component.serial || "—") + "</td>" +
        "<td>" + A.badge(component.status) + "</td>" +
      "</tr>";
    }).join("");
  }

  function renderSensors() {
    const body = $("sensor-body");
    if (!body) return;
    const sensors = (data.hardware || {}).sensors || [];
    if (!sensors.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="7">No environment sensors reported.</td></tr>';
      return;
    }
    body.innerHTML = sensors.map(function (sensor) {
      const thresholds = sensor.thresholds || {};
      return "<tr>" +
        '<td class="strong">' + escape(sensor.name) + "</td>" +
        "<td>" + fmtSensor(sensor.value, sensor.unit) + "</td>" +
        '<td class="num">' + fmtSensor(thresholds.low_alarm, sensor.unit) + "</td>" +
        '<td class="num">' + fmtSensor(thresholds.low_warn, sensor.unit) + "</td>" +
        '<td class="num">' + fmtSensor(thresholds.high_warn, sensor.unit) + "</td>" +
        '<td class="num">' + fmtSensor(thresholds.high_alarm, sensor.unit) + "</td>" +
        "<td>" + A.badge(sensor.status) + "</td>" +
      "</tr>";
    }).join("");
  }

  function renderNeighbors() {
    const body = $("neighbor-body");
    if (!body) return;
    const neighbors = data.neighbors || [];
    if (!neighbors.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="4">No LLDP neighbors reported.</td></tr>';
      return;
    }
    body.innerHTML = neighbors.map(function (neighbor) {
      return "<tr>" +
        '<td class="strong">' + escape(neighbor.local_port) + "</td>" +
        "<td>" + escape(neighbor.remote_name || "—") + "</td>" +
        "<td>" + escape(neighbor.remote_port || "—") + "</td>" +
        "<td>" + escape(neighbor.remote_descr || neighbor.remote_port_desc || "—") + "</td>" +
      "</tr>";
    }).join("");
  }

  function renderAll() {
    renderHeader();
    renderAlerts();
    renderStats();
    renderHardwareHealth();
    renderPortGrid();
    renderPortDetail();
    renderSfpGrid();
    renderPortTable();
    renderComponents();
    renderSensors();
    renderNeighbors();
  }

  renderAll();
  if (data.online === false) A.setLive("offline", "Offline");

  ["port-search", "port-status-filter", "port-media-filter"].forEach(function (id) {
    const element = $(id);
    if (element) {
      element.addEventListener("input", renderPortTable);
      element.addEventListener("change", renderPortTable);
    }
  });

  poller = A.startPolling(async function () {
    data = await A.fetchJSON("/api/switch/" + encodeURIComponent(switchId));
    renderAll();
    return data.online === false
      ? { state: "offline", label: "Offline" }
      : { state: "live", label: "Live" };
  }, refresh, function () {
    const sub = $("switch-sub");
    if (sub) sub.innerHTML = A.badge("critical", "Telemetry stale") +
      ' <span class="muted">Last successful update ' + A.fmtTimestamp(data.last_poll) + "</span>";
  });

  const refreshButton = $("refresh-now");
  if (refreshButton && poller) {
    refreshButton.addEventListener("click", function () {
      refreshButton.disabled = true;
      const original = refreshButton.textContent;
      refreshButton.textContent = "Refreshing…";
      Promise.resolve(poller.refresh()).finally(function () {
        refreshButton.disabled = false;
        refreshButton.textContent = original;
      });
    });
  }
})();
