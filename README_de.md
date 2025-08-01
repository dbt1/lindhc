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
- ⏏️ **Unterstützung für nicht-gemountete Partitionen** mit Filesystem-Checks
- 🔧 **Automatische fsck-Befehlsgenerierung** für verschiedene Dateisystemtypen

## Installation

### Voraussetzungen

- Python 3.6 oder höher
- `lsblk` (normalerweise vorinstalliert)
- `smartmontools` (optional, aber empfohlen)
- `blkid` (optional, für erweiterte Partitionserkennung)
- `e2fsprogs` (optional, für ext2/3/4 Filesystem-Checks)

### Dependencies installieren

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install python3 python3-yaml smartmontools util-linux e2fsprogs

# RedHat/CentOS/Fedora
sudo yum install python3 python3-pyyaml smartmontools util-linux e2fsprogs

# Arch Linux
sudo pacman -S python python-yaml smartmontools util-linux e2fsprogs
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

# Mit Anzeige von nicht-gemounteten Partitionen
sudo ./lindhc.py --show-unmounted

# Mit Filesystem-Checks für nicht-gemountete Partitionen
sudo ./lindhc.py --check-unmounted
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

# Fokus auf nicht-gemountete Partitionen
./lindhc.py --show-unmounted --check-unmounted
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
sudo ./lindhc.py -d --json --show-unmounted
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
  unmounted_partition_score: 30
performance:
  max_workers: 4
  command_timeout: 10
output:
  max_mount_points_shown: 3
  show_io_stats: false
  show_unmounted: true
filesystem:
  check_unmounted: true
  run_fsck: false
  supported_fs: ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'ntfs', 'vfat', 'exfat']
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
| Nicht-sauberes Filesystem | 60 |
| Erhöhte Temperatur (>50°C) | 50 |
| SMART Status unbekannt | 50 |
| Nicht-gemountete Partition | 30 |

## Neue Features: Nicht-gemountete Partitionen

### Erkennung und Anzeige

Das Tool erkennt automatisch alle nicht-gemounteten Partitionen und zeigt:
- Partitionsname und Dateisystemtyp
- UUID und Label (falls vorhanden)
- Größe der Partition
- Filesystem-Status (bei unterstützten Dateisystemen)

### Automatische fsck-Befehle

Für jede nicht-gemountete Partition wird der passende fsck-Befehl generiert:

```bash
# Beispiel-Ausgabe
⏏️ Unmounted partitions:
   └─ sda5: ext4 (232.9G)
      ⚠ Check recommended (mount count: 35/30)
      Last checked: Mon Mar 15 15:08:59 2021
      → sudo fsck.ext4 -f /dev/sda5
```

### Unterstützte Dateisysteme

- **ext2/3/4**: Vollständige Checks mit mount count, last check time
- **XFS**: Basis-Support (XFS ist selbstheilend)
- **Btrfs**: Basis-Support
- **NTFS**: Eingeschränkter Support (empfiehlt Windows chkdsk)
- **FAT/exFAT**: Basis-Support
- **F2FS, ReiserFS, JFS, HFS+**: Basis-Support

### Filesystem-spezifische Empfehlungen

Das Tool gibt automatisch passende Empfehlungen:
- **ext4**: `-f` für Force-Check, `-y` für Auto-Fix
- **XFS**: Hinweis auf selbstheilende Eigenschaften
- **NTFS**: Empfehlung für Windows chkdsk
- **Btrfs**: `--repair` nur bei Bedarf

## Integration in Monitoring-Systeme

### Zabbix

```bash
# UserParameter in zabbix_agentd.conf
UserParameter=disk.health[*],/usr/local/bin/lindhc.py --json | jq -r '.disks[] | select(.name=="$1") | .score'
UserParameter=disk.health.discovery,/usr/local/bin/lindhc.py --json | jq -r '.disks | map({"{#DISKNAME}": .name}) | {data: .}'
UserParameter=disk.unmounted.count,/usr/local/bin/lindhc.py --json | jq -r '[.disks[].partitions[] | select(.is_mounted==false)] | length'
```

### Nagios/Icinga

```bash
#!/bin/bash
# check_disk_health.sh
OUTPUT=$(/usr/local/bin/lindhc.py --json --show-unmounted)
CRITICAL=$(echo "$OUTPUT" | jq '[.disks[] | select(.score >= 500)] | length')
WARNING=$(echo "$OUTPUT" | jq '[.disks[] | select(.score >= 100 and .score < 500)] | length')
UNMOUNTED=$(echo "$OUTPUT" | jq '[.disks[].partitions[] | select(.is_mounted==false)] | length')

if [ "$CRITICAL" -gt 0 ]; then
    echo "CRITICAL - $CRITICAL disk(s) in critical state, $UNMOUNTED unmounted partition(s)"
    exit 2
elif [ "$WARNING" -gt 0 ]; then
    echo "WARNING - $WARNING disk(s) need attention, $UNMOUNTED unmounted partition(s)"
    exit 1
else
    echo "OK - All disks healthy, $UNMOUNTED unmounted partition(s)"
    exit 0
fi
```

### Cron-Job für regelmäßige Checks

```bash
# Täglicher Check um 2 Uhr nachts mit Filesystem-Checks
0 2 * * * /usr/local/bin/lindhc.py --json --check-unmounted > /var/log/disk-health/$(date +\%Y-\%m-\%d).json

# Wöchentlicher Report für unmountete Partitionen
0 8 * * 1 /usr/local/bin/lindhc.py --show-unmounted | mail -s "Weekly Disk Report" admin@example.com
```

## Beispiel-Ausgaben

### Standard-Ausgabe mit nicht-gemounteten Partitionen
```
#1 - /dev/sda - Samsung SSD 870 (500.1 GB)
   Status: ⚠ Score: 150
   🌡️ Temperatur: 45°C
   💾 Belegung: 92%
      └─ /: 92% (460.5 GB/500.1 GB)
   ⏏️ Unmounted partitions:
      └─ sda2: ext4 [Backup] (100.0 GB)
         ⚠ State: not clean - needs checking
         Last checked: Mon Jul 15 10:23:45 2024
         → sudo fsck.ext4 -f /dev/sda2
   ⚠ Gefundene Probleme:
      • Wenig Speicherplatz: 92%
      • Unmounted partition sda2 needs fsck (state: not clean)
```

### JSON-Ausgabe mit Partitionsdetails
```json
{
  "version": "0.2.2",
  "timestamp": "2024-01-15T14:23:45.123456",
  "is_root": true,
  "disks": [
    {
      "name": "sda",
      "path": "/dev/sda",
      "model": "Samsung SSD 870",
      "size": "500.1 GB",
      "score": 150,
      "partitions": [
        {
          "name": "sda1",
          "fstype": "ext4",
          "mountpoint": "/",
          "is_mounted": true,
          "usage": 92,
          "uuid": "123e4567-e89b-12d3-a456-426614174000",
          "label": null
        },
        {
          "name": "sda2",
          "fstype": "ext4",
          "mountpoint": null,
          "is_mounted": false,
          "uuid": "987f6543-e21b-98d7-a654-321098765432",
          "label": "Backup",
          "fs_checks": {
            "state": "not clean",
            "clean": false,
            "mount_count": 35,
            "max_mount_count": 30,
            "needs_check": true,
            "last_checked": "Mon Jul 15 10:23:45 2024"
          },
          "fsck_command": "sudo fsck.ext4 -f /dev/sda2"
        }
      ]
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

### "blkid nicht gefunden"
```bash
# Installation von util-linux
sudo apt install util-linux  # Debian/Ubuntu
sudo yum install util-linux  # RedHat/CentOS
```

### "Permission denied" Fehler
```bash
# Mit Root-Rechten ausführen für vollständige Analyse
sudo ./lindhc.py
```

### Keine Farben in der Ausgabe
```bash
# Prüfen ob Terminal Farben unterstützt
echo $TERM

# Farben erzwingen
TERM=xterm-256color ./lindhc.py
```

### Nicht-gemountete Partitionen werden nicht angezeigt
```bash
# Explizit aktivieren
./lindhc.py --show-unmounted

# Oder in der Konfiguration setzen
output:
  show_unmounted: true
```

## Entwicklung

### Struktur
```
lindhc.py
├── DiskHealthChecker    # Hauptklasse für Analyse
├── OutputFormatter      # Formatierung der Ausgabe
├── ToolManager          # Tool-Pfad-Verwaltung
├── PartitionInfo        # Partitionsinformationen
├── Colors/Symbols       # Visuelle Elemente
└── Config Management    # YAML-Konfiguration
```

### Eigene Filesystem-Checks hinzufügen

```python
def check_custom_filesystem(self, partition_name, fstype):
    """Eigenen Filesystem-Check implementieren"""
    checks = {}
    # Ihre Logik hier
    checks['custom_metric'] = value
    return checks

# In check_unmounted_filesystem() einbinden
elif fstype == 'customfs':
    checks = self.check_custom_filesystem(partition_name, fstype)
```

## Lizenz

MIT License - siehe LICENSE Datei

## Beiträge

Pull Requests sind willkommen! Für größere Änderungen bitte erst ein Issue erstellen.

## Autor

Erstellt mit ❤️ für die Linux-Community