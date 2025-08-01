# Linux Disk Health Checker

A comprehensive, modular tool for checking the health of all physical drives on Linux systems.

## Features

- 🔍 **Automatic detection** of all physical drives
- 🚀 **Parallel execution** for better performance
- 📊 **Multiple output formats** (console, JSON, plain text)
- 🎨 **Color-coded output** with Unicode symbols for better readability
- ⚙️ **Configurable thresholds** via YAML files
- 🔐 **Works with and without root privileges**
- 📈 **Smart scoring system** for prioritization
- 🛠️ **Modular architecture** for easy extension
- ⏏️ **Support for unmounted partitions** with filesystem checks
- 🔧 **Automatic fsck command generation** for various filesystem types

## Installation

### Requirements

- Python 3.6 or higher
- `lsblk` (usually preinstalled)
- `smartmontools` (optional but recommended)
- `blkid` (optional, for advanced partition detection)
- `e2fsprogs` (optional, for ext2/3/4 filesystem checks)

### Install dependencies

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install python3 python3-yaml smartmontools util-linux e2fsprogs

# RedHat/CentOS/Fedora
sudo yum install python3 python3-pyyaml smartmontools util-linux e2fsprogs

# Arch Linux
sudo pacman -S python python-yaml smartmontools util-linux e2fsprogs
```

### Install script

```bash
# Download
wget https://raw.githubusercontent.com/dbt1/lindhc/refs/heads/master/lindhc.py

# Make executable
chmod +x lindhc.py

# Optional: Move to PATH
sudo mv lindhc.py /usr/local/bin/lindhc.py
```

## Usage

### Basic usage

```bash
# Standard analysis (no root)
./lindhc.py

# Full analysis (with root)
sudo ./lindhc.py

# Show unmounted partitions
sudo ./lindhc.py --show-unmounted

# Check unmounted partitions' filesystems
sudo ./lindhc.py --check-unmounted
```

### Output formats

```bash
# JSON for monitoring tools
./lindhc.py --json

# Plain text without formatting
./lindhc.py --plain

# Quiet mode (minimal output)
./lindhc.py -q
```

### Selective tests

```bash
# SMART tests only
./lindhc.py --smart-only

# Usage stats only
./lindhc.py --usage-only

# Checks only, no suggestions
./lindhc.py --check-only

# Focus on unmounted partitions
./lindhc.py --show-unmounted --check-unmounted
```

### Performance options

```bash
# More parallel workers (default: 4)
./lindhc.py --parallel 8

# Longer timeout (default: 10s)
./lindhc.py --timeout 30
```

### Debug and logging

```bash
# Verbose output
./lindhc.py -v

# Debug mode (very detailed)
./lindhc.py -d

# Combine with other options
sudo ./lindhc.py -d --json --show-unmounted
```

## Configuration

### Create sample config

```bash
./lindhc.py --create-config
```

This creates `disk_health_checker.yaml`:

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

### Use custom config

```bash
./lindhc.py --config my_config.yaml
```

## Scoring System

The tool uses a smart scoring system (higher = more problematic):

| Problem                     | Score       |
| --------------------------- | ----------- |
| SMART failed                | 1000        |
| Critical usage (>95%)       | 300         |
| High temperature (>60°C)    | 200         |
| Reallocated sectors         | 100 × count |
| Low space (>90%)            | 100         |
| Dirty filesystem            | 60          |
| Warning temperature (>50°C) | 50          |
| SMART status unknown        | 50          |
| Unmounted partition         | 30          |

## New Feature: Unmounted Partitions

### Detection and display

The tool automatically detects all unmounted partitions and shows:

- Partition name and filesystem type
- UUID and label (if present)
- Partition size
- Filesystem status (for supported types)

### Auto fsck commands

For each unmounted partition, a matching fsck command is generated:

```bash
# Sample output
⏏️ Unmounted partitions:
   └─ sda5: ext4 (232.9G)
      ⚠ Check recommended (mount count: 35/30)
      Last checked: Mon Mar 15 15:08:59 2021
      → sudo fsck.ext4 -f /dev/sda5
```

### Supported filesystems

- **ext2/3/4**: Full checks with mount count, last check time
- **XFS**: Basic support (self-healing)
- **Btrfs**: Basic support
- **NTFS**: Limited support (Windows chkdsk recommended)
- **FAT/exFAT**: Basic support
- **F2FS, ReiserFS, JFS, HFS+**: Basic support

### Filesystem-specific recommendations

The tool gives tailored recommendations:

- **ext4**: Use `-f` for force-check, `-y` for auto-fix
- **XFS**: Mentions self-healing
- **NTFS**: Suggests Windows chkdsk
- **Btrfs**: Use `--repair` only if necessary

## Integration with Monitoring Tools

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

### Cron job for regular checks

```bash
# Daily check at 2 AM with filesystem checks
0 2 * * * /usr/local/bin/lindhc.py --json --check-unmounted > /var/log/disk-health/$(date +\%Y-\%m-\%d).json

# Weekly report for unmounted partitions
0 8 * * 1 /usr/local/bin/lindhc.py --show-unmounted | mail -s "Weekly Disk Report" admin@example.com
```

## Example Outputs

### Standard output with unmounted partitions

```
#1 - /dev/sda - Samsung SSD 870 (500.1 GB)
   Status: ⚠ Score: 150
   🌡️ Temperature: 45°C
   💾 Usage: 92%
      └─ /: 92% (460.5 GB/500.1 GB)
   ⏏️ Unmounted partitions:
      └─ sda2: ext4 [Backup] (100.0 GB)
         ⚠ State: not clean - needs checking
         Last checked: Mon Jul 15 10:23:45 2024
         → sudo fsck.ext4 -f /dev/sda2
   ⚠ Issues found:
      • Low disk space: 92%
      • Unmounted partition sda2 needs fsck (state: not clean)
```

### JSON output with partition details

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

## Exit Codes

- `0` - All disks are healthy
- `1` - Script execution error
- `2` - Critical disks found (score ≥ 500)

## Troubleshooting

### "smartctl not found"

```bash
# Install smartmontools
sudo apt install smartmontools  # Debian/Ubuntu
sudo yum install smartmontools  # RedHat/CentOS
```

### "blkid not found"

```bash
# Install util-linux
sudo apt install util-linux  # Debian/Ubuntu
sudo yum install util-linux  # RedHat/CentOS
```

### "Permission denied" errors

```bash
# Run as root for full analysis
sudo ./lindhc.py
```

### No colors in output

```bash
# Check if terminal supports colors
echo $TERM

# Force colors
TERM=xterm-256color ./lindhc.py
```

### Unmounted partitions not shown

```bash
# Enable explicitly
./lindhc.py --show-unmounted

# Or set in config
output:
  show_unmounted: true
```

## Development

### Structure

```
lindhc.py
├── DiskHealthChecker    # Main analysis class
├── OutputFormatter      # Output formatting
├── ToolManager          # Tool path management
├── PartitionInfo        # Partition details
├── Colors/Symbols       # Visual elements
└── Config Management    # YAML config handling
```

### Add custom filesystem checks

```python
def check_custom_filesystem(self, partition_name, fstype):
    """Implement your own filesystem check"""
    checks = {}
    # Your logic here
    checks['custom_metric'] = value
    return checks

# Integrate into check_unmounted_filesystem()
elif fstype == 'customfs':
    checks = self.check_custom_filesystem(partition_name, fstype)
```

## License

MIT License - see LICENSE file

## Contributions

Pull requests are welcome! For major changes, please open an issue first.

## Author

Made with ❤️ for the Linux community

