# Locked release — 2026-11-09

Version: Meraki-style switch dashboard with light/dark theme toggle.
Status: FROZEN. Application source and simulator data are read-only.

## Locked components
- /opt/snmp-dashboard/app.py
- /opt/snmp-dashboard/snmp_core.py
- /opt/snmp-dashboard/switch_model.py
- /opt/snmp-dashboard/config.json
- /opt/snmp-dashboard/templates/*.html
- /opt/snmp-dashboard/static/css/*.css
- /opt/snmp-dashboard/static/js/*.js
- /opt/snmpsim/data/switch-*.snmprec

## Final snapshot
- /opt/snmp-dashboard/backups/20261109-final-darkmode/
- Checksums: backups/20261109-final-darkmode/SHA256SUMS
- Simulator data copy: backups/20261109-final-darkmode/snmpsim-data/

## Unlock (root only)
    sudo chmod 755 /opt/snmp-dashboard /opt/snmp-dashboard/templates \
      /opt/snmp-dashboard/static /opt/snmp-dashboard/static/css \
      /opt/snmp-dashboard/static/js
    sudo chmod 644 /opt/snmp-dashboard/app.py /opt/snmp-dashboard/snmp_core.py \
      /opt/snmp-dashboard/switch_model.py /opt/snmp-dashboard/templates/*.html \
      /opt/snmp-dashboard/static/css/*.css /opt/snmp-dashboard/static/js/*.js
    sudo chmod 640 /opt/snmp-dashboard/config.json
    sudo chmod 755 /opt/snmpsim/data
    sudo chmod 644 /opt/snmpsim/data/switch-*.snmprec

After editing, restart:
    sudo systemctl restart snmp-dashboard.service
    sudo systemctl restart snmpsim
