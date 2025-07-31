# Linux Disk Health Checker

A comprehensive, modular tool for checking the health of all physical drives on Linux systems.

## Features

* 🔍 **Automatic detection** of all physical drives
* 🚀 **Parallel execution** for better performance
* 📊 **Multiple output formats** (console, JSON, plain text)
* 🎨 **Color-coded output** with Unicode symbols for better readability
* ⚙️ **Configurable thresholds** via YAML files
* 🔐 **Works with and without root privileges**
* 📈 **Intelligent scoring system** for prioritization
* 🛠️ **Modular architecture** for easy extension

## Installation

### Requirements

* Python 3.6 or higher
* `lsblk` (usually preinstalled)
* `smartmontools` (optional but recommended)

### Install dependencies

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install python3 python3-yaml smartmontools

# RedHat/CentOS/Fedora
sudo yum install python3 python3-pyyaml smartmontools

# Arch Linux
sudo pacman -S python python-yaml smartmontools
```

### Install the script

```bash
# Download
wget https://raw.githubusercontent.com/dbt1/lindhc/refs/heads/master/lindhc.py

# Make executable
chmod +x lindhc.py

# Optional: move to PATH
sudo mv lindhc.py /usr/local/bin/lindhc.py
```

## Usage

### Basic usage

```bash
# Standard analysis (without root)
./lindhc.py

# Full analysis (with root)
sudo ./lindhc.py
```

### Output formats

```bash
# JSON for monitoring tools
./lindhc.py --json

# Simple text without formatting
./lindhc.py --plain

# Quiet mode (minimal output)
./lindhc.py -q
```

### Selective tests

```bash
# SMART tests only
./lindhc.py --smart-only

# Disk usage only
./lindhc.py --usage-only

# Tests only, no recommendations
./lindhc.py --check-only
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
sudo ./lindhc.py -d --json
```

## Configuration

### Create example configuration

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
performance:
  max_workers: 4
  command_timeout: 10
output:
  max_mount_points_shown: 3
  show_io_stats: false
```

### Use with custom configuration

```bash
./lindhc.py --config my_config.yaml
```

## Scoring system

The tool uses an intelligent scoring system (higher = more critical):

| Issue                        | Score       |
| ---------------------------- | ----------- |
| SMART failed                 | 1000        |
| Critical disk usage (>95%)   | 300         |
| High temperature (>60°C)     | 200         |
| Reallocated sectors          | 100 × count |
| Low disk space (>90%)        | 100         |
| Elevated temperature (>50°C) | 50          |
| SMART status unknown         | 50          |

## Integration with monitoring systems

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

### Cron job for regular checks

```bash
# Daily check at 2 AM
0 2 * * * /usr/local/bin/lindhc.py --json > /var/log/disk-health/$(date +\%Y-\%m-\%d).json
```

## Example outputs

### Standard output

```
═══════════════════════════════════════════════════════════════
   Linux Disk Health Checker v0.1.0
   2024-01-15 14:23:45
═══════════════════════════════════════════════════════════════

#1 - /dev/sda - Samsung SSD 870 (500.1 GB)
   Status: ⚠ Score: 120
   🌡️ Temperature: 45°C
   💾 Usage: 92%
      └─ /: 92% (460.5 GB/500.1 GB)
   ⚠ Issues found:
      • Low disk space: 92%
```

### JSON output

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

## Exit codes

* `0` - All drives are healthy
* `1` - Script execution error
* `2` - Critical drives detected (Score ≥ 500)

## Troubleshooting

### "smartctl not found"

```bash
# Install smartmontools
sudo apt install smartmontools  # Debian/Ubuntu
sudo yum install smartmontools  # RedHat/CentOS
```

### "Permission denied" error

```bash
# Run with root privileges
sudo ./lindhc.py
```

### No colors in output

```bash
# Check if terminal supports colors
echo $TERM

# Force colors
TERM=xterm-256color ./lindhc.py
```

## Development

### Structure

```
lindhc.py
├── DiskHealthChecker    # Main class for analysis
├── OutputFormatter      # Output formatting
├── Colors/Symbols       # Visual elements
└── Config Management    # YAML configuration
```

### Adding custom checks

```python
def get_custom_metric(self, dev):
    """Implement custom metric"""
    # Your logic here
    return metric_value

# Integrate in calculate_score()
if info.custom_metric > threshold:
    score += 50
    issues.append(('WARNING', 'Custom metric exceeded'))
```

## License

MIT License - see LICENSE file

## Contributions

Pull requests are welcome! For major changes, please open an issue first.

## Author

Created with ❤️ for the Linux community
