# Linux Disk Health Checker

Ein umfassendes, modulares Tool zur Überprüfung der Gesundheit aller physischen Laufwerke auf Linux-Systemen.

## Features

- 🔍 **Automatische Erkennung** aller physischen Laufwerke
- 🚀 **Parallele Ausführung** für bessere Performance
- 📊 **Multiple Ausgabeformate** (Konsole, JSON, Plain Text)
- 🎨 **Farbcodierte Ausgabe** mit Unicode-Symbolen für bessere Lesbarkeit
- ⚙️ **Konfigurierbare Schwellenwerte** über YAML-Dateien
- 🔐 **Funktioniert mit und ohne Root-Rechte**
- 📈 **Intelligentes Scoring-System** zur Priorisierung
- 🛠️ **Modulare Architektur** für einfache Erweiterung

## Installation

### Voraussetzungen

- Python 3.6 oder höher
- `lsblk` (normalerweise vorinstalliert)
- `smartmontools` (optional, aber empfohlen)

### Dependencies installieren

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install python3 python3-yaml smartmontools

# RedHat/CentOS/Fedora
sudo yum install python3 python3-pyyaml smartmontools

# Arch Linux
sudo pacman -S python python-yaml smartmontools
```

### Script installieren

```bash
# Download
wget https://raw.githubusercontent.com/dbt1/lindhc/refs/heads/master/lindhc.py

# Ausführbar machen
chmod +x lindhc.py

# Optional: In PATH verschieben
sudo mv lindhc.py /usr/local/bin/lindhc.py
```

## Verwendung

### Basis-Verwendung

```bash
# Standard-Analyse (ohne Root)
./lindhc.py

# Vollständige Analyse (mit Root)
sudo ./lindhc.py
```

### Ausgabeformate

```bash
# JSON für Monitoring-Tools
./lindhc.py --json

# Einfacher Text ohne Formatierung
./lindhc.py --plain

# Quiet Mode (minimale Ausgabe)
./lindhc.py -q
```

### Selektive Tests

```bash
# Nur SMART-Tests
./lindhc.py --smart-only

# Nur Speicherbelegung
./lindhc.py --usage-only

# Nur Tests, keine Empfehlungen
./lindhc.py --check-only
```

### Performance-Optionen

```bash
# Mehr parallele Worker (Standard: 4)
./lindhc.py --parallel 8

# Längerer Timeout (Standard: 10s)
./lindhc.py --timeout 30
```

### Debug und Logging

```bash
# Verbose Output
./lindhc.py -v

# Debug Mode (sehr detailliert)
./lindhc.py -d

# Kombiniert mit anderen Optionen
sudo ./lindhc.py -d --json
```

## Konfiguration

### Beispiel-Konfiguration erstellen

```bash
./lindhc.py --create-config
```

Dies erstellt `disk_health_checker.yaml`:

```yaml
thresholds:
  smart_fail_score: 1000
  smart_unknown_score: 50
  smart_need_root_score: 10
  smart_no_support_score: 5
  reallocated_sector_multiplier: 100
  temp_critical: 60
  temp_critical_score: 200
  temp_warning: 50
  temp_warning_score: 50
  usage_critical: 95
  usage_critical_score: 300
  usage_warning: 90
  usage_warning_score: 100
  usage_info: 80
  usage_info_score: 20
performance:
  max_workers: 4
  command_timeout: 10
output:
  max_mount_points_shown: 3
  show_io_stats: false
```

### Mit eigener Konfiguration verwenden

```bash
./lindhc.py --config my_config.yaml
```

## Scoring-System

Das Tool verwendet ein intelligentes Scoring-System (höher = problematischer):

| Problem | Score |
|---------|-------|
| SMART Failed | 1000 |
| Kritischer Speicher (>95%) | 300 |
| Hohe Temperatur (>60°C) | 200 |
| Defekte Sektoren | 100 × Anzahl |
| Wenig Speicher (>90%) | 100 |
| Erhöhte Temperatur (>50°C) | 50 |
| SMART Status unbekannt | 50 |

## Integration in Monitoring-Systeme

### Zabbix

```bash
# UserParameter in zabbix_agentd.conf
UserParameter=disk.health[*],/usr/local/bin/lindhc.py --json | jq -r '.disks[] | select(.name=="$1") | .score'
UserParameter=disk.health.discovery,/usr/local/bin/lindhc.py --json | jq -r '.disks | map({"{#DISKNAME}": .name}) | {data: .}'
```

### Nagios/Icinga

```bash
#!/bin/bash
# check_disk_health.sh
OUTPUT=$(/usr/local/bin/lindhc.py --json)
CRITICAL=$(echo "$OUTPUT" | jq '[.disks[] | select(.score >= 500)] | length')
WARNING=$(echo "$OUTPUT" | jq '[.disks[] | select(.score >= 100 and .score < 500)] | length')

if [ "$CRITICAL" -gt 0 ]; then
    echo "CRITICAL - $CRITICAL disk(s) in critical state"
    exit 2
elif [ "$WARNING" -gt 0 ]; then
    echo "WARNING - $WARNING disk(s) need attention"
    exit 1
else
    echo "OK - All disks healthy"
    exit 0
fi
```

### Cron-Job für regelmäßige Checks

```bash
# Täglicher Check um 2 Uhr nachts
0 2 * * * /usr/local/bin/lindhc.py --json > /var/log/disk-health/$(date +\%Y-\%m-\%d).json
```

## Beispiel-Ausgaben

### Standard-Ausgabe
```
═══════════════════════════════════════════════════════════════
   Linux Disk Health Checker v0.1.0
   2024-01-15 14:23:45
═══════════════════════════════════════════════════════════════

#1 - /dev/sda - Samsung SSD 870 (500.1 GB)
   Status: ⚠ Score: 120
   🌡️ Temperatur: 45°C
   💾 Belegung: 92%
      └─ /: 92% (460.5 GB/500.1 GB)
   ⚠ Gefundene Probleme:
      • Wenig Speicherplatz: 92%
```

### JSON-Ausgabe
```json
{
  "version": "2.0.0",
  "timestamp": "2024-01-15T14:23:45.123456",
  "is_root": true,
  "disks": [
    {
      "name": "sda",
      "path": "/dev/sda",
      "model": "Samsung SSD 870",
      "size": "500.1 GB",
      "score": 120,
      "smart": {
        "health": "PASSED",
        "attributes": {}
      },
      "temperature": 45,
      "usage": {
        "percent": 92,
        "mount_points": [...]
      }
    }
  ]
}
```

## Exit-Codes

- `0` - Alle Laufwerke sind gesund
- `1` - Fehler beim Ausführen des Scripts
- `2` - Kritische Laufwerke gefunden (Score ≥ 500)

## Troubleshooting

### "smartctl nicht gefunden"
```bash
# Installation von smartmontools
sudo apt install smartmontools  # Debian/Ubuntu
sudo yum install smartmontools  # RedHat/CentOS
```

### "Permission denied" Fehler
```bash
# Mit Root-Rechten ausführen
sudo ./lindhc.py
```

### Keine Farben in der Ausgabe
```bash
# Prüfen ob Terminal Farben unterstützt
echo $TERM

# Farben erzwingen
TERM=xterm-256color ./lindhc.py
```

## Entwicklung

### Struktur
```
lindhc.py
├── DiskHealthChecker    # Hauptklasse für Analyse
├── OutputFormatter      # Formatierung der Ausgabe
├── Colors/Symbols       # Visuelle Elemente
└── Config Management    # YAML-Konfiguration
```

### Eigene Checks hinzufügen

```python
def get_custom_metric(self, dev):
    """Eigene Metrik implementieren"""
    # Ihre Logik hier
    return metric_value

# In calculate_score() einbinden
if info.custom_metric > threshold:
    score += 50
    issues.append(('WARNING', 'Custom metric exceeded'))
```

## Lizenz

MIT License - siehe LICENSE Datei

## Beiträge

Pull Requests sind willkommen! Für größere Änderungen bitte erst ein Issue erstellen.

## Autor

Erstellt mit ❤️ für die Linux-Community