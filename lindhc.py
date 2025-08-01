#!/usr/bin/env python3
"""
Linux Disk Health Checker
A comprehensive, modular tool for checking the health of all physical drives

Features:
- Parallel execution for better performance
- Multiple output formats (Console, JSON, Plain)
- Configurable thresholds
- Debug/Verbose modes
- Modular architecture
- Robust tool path detection for cronjobs/systemd
- Support for unmounted filesystems
"""

import os
import subprocess
import shutil
import json
import re
import sys
import argparse
import logging
import yaml
from collections import namedtuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

# Version
VERSION_MAJOR="0"
VERSION_MINOR="2"
VERSION_PATCH="0"
__version__ = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

# ANSI Color Codes for better display
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    
    @classmethod
    def disable(cls):
        """Disables all colors"""
        for attr in dir(cls):
            if not attr.startswith('_'):
                setattr(cls, attr, '')

# Unicode symbols for better visualization
class Symbols:
    OK = '✓'
    WARNING = '⚠'
    ERROR = '✗'
    INFO = 'ℹ'
    DISK = '💾'
    TEMP = '🌡️'
    CLOCK = '⏱️'
    UNMOUNTED = '⏏️'
    
    @classmethod
    def disable(cls):
        """Replaces symbols with ASCII"""
        cls.OK = '[OK]'
        cls.WARNING = '[!]'
        cls.ERROR = '[X]'
        cls.INFO = '[i]'
        cls.DISK = '[D]'
        cls.TEMP = '[T]'
        cls.CLOCK = '[>]'
        cls.UNMOUNTED = '[U]'

# Default configuration
DEFAULT_CONFIG = {
    'thresholds': {
        'smart_fail_score': 1000,
        'smart_unknown_score': 50,
        'smart_need_root_score': 10,
        'smart_no_support_score': 5,
        'reallocated_sector_multiplier': 100,
        'temp_critical': 60,
        'temp_critical_score': 200,
        'temp_warning': 50,
        'temp_warning_score': 50,
        'usage_critical': 95,
        'usage_critical_score': 300,
        'usage_warning': 90,
        'usage_warning_score': 100,
        'usage_info': 80,
        'usage_info_score': 20,
        'unmounted_partition_score': 30
    },
    'performance': {
        'max_workers': 4,
        'command_timeout': 10
    },
    'output': {
        'max_mount_points_shown': 3,
        'show_io_stats': False,
        'show_unmounted': True
    },
    'tools': {
        'search_paths': [
            '/usr/bin',
            '/bin', 
            '/usr/sbin',
            '/sbin',
            '/usr/local/bin',
            '/usr/local/sbin'
        ]
    },
    'filesystem': {
        'check_unmounted': True,
        'run_fsck': False,
        'supported_fs': ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'ntfs', 'vfat', 'exfat']
    }
}

# Extended to include partition information
class PartitionInfo:
    def __init__(self, name, fstype, mountpoint, usage, total, used, free, uuid, label, is_mounted):
        self.name = name
        self.fstype = fstype
        self.mountpoint = mountpoint
        self.usage = usage
        self.total = total
        self.used = used
        self.free = free
        self.uuid = uuid
        self.label = label
        self.is_mounted = is_mounted
        self.fs_checks = {}

DiskInfo = namedtuple('DiskInfo', [
    'name', 'model', 'size', 'smart_health', 'smart_attrs', 
    'temp', 'usage', 'mount_points', 'partitions', 'io_stats', 'score', 'issues',
    'scan_time'
])

class ToolManager:
    """Manages paths to external tools for robust execution"""
    
    def __init__(self, config=None):
        self.config = config or DEFAULT_CONFIG
        self.tool_paths = {}
        self.logger = logging.getLogger(__name__)
        
    def find_tool(self, tool_name):
        """Finds the full path to a tool"""
        if tool_name in self.tool_paths:
            return self.tool_paths[tool_name]
        
        # First try with 'which'
        try:
            result = subprocess.run(['which', tool_name], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                path = result.stdout.strip()
                if path and os.path.isfile(path) and os.access(path, os.X_OK):
                    self.tool_paths[tool_name] = path
                    self.logger.debug(f"Found {tool_name} at {path}")
                    return path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Fallback: Search in standard paths
        search_paths = self.config.get('tools', {}).get('search_paths', [])
        for search_path in search_paths:
            full_path = os.path.join(search_path, tool_name)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                self.tool_paths[tool_name] = full_path
                self.logger.debug(f"Found {tool_name} at {full_path} (fallback)")
                return full_path
        
        # Tool not found
        self.logger.warning(f"Tool {tool_name} not found in PATH or standard locations")
        return None
    
    def get_tool_path(self, tool_name):
        """Returns the full path to a tool"""
        return self.tool_paths.get(tool_name)
    
    def check_dependencies(self):
        """Checks all required tools and stores their paths"""
        missing = []
        optional = []
        
        # Required tools
        required_tools = ['lsblk']
        for tool in required_tools:
            if not self.find_tool(tool):
                missing.append(tool)
        
        # Optional tools  
        optional_tools = ['smartctl', 'blkid', 'fsck', 'file', 'dumpe2fs', 'xfs_info', 'btrfs']
        for tool in optional_tools:
            if not self.find_tool(tool):
                optional.append(tool)
        
        return missing, optional
    
    def get_environment_info(self):
        """Collects information about the execution environment"""
        return {
            'path': os.environ.get('PATH', ''),
            'user': os.environ.get('USER', 'unknown'),
            'home': os.environ.get('HOME', ''),
            'shell': os.environ.get('SHELL', ''),
            'is_systemd': os.path.exists('/run/systemd/system'),
            'is_cron': not os.isatty(sys.stdout.fileno()),
            'tool_paths': self.tool_paths.copy()
        }

class DiskHealthChecker:
    def __init__(self, config=None, args=None):
        self.config = config or DEFAULT_CONFIG
        self.args = args
        self.logger = self._setup_logging()
        self.tool_manager = ToolManager(config)
        
    def _setup_logging(self):
        """Configures the logging system"""
        level = logging.WARNING
        if self.args:
            if self.args.debug:
                level = logging.DEBUG
            elif self.args.verbose:
                level = logging.INFO
        
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        return logging.getLogger(__name__)
    
    def format_bytes(self, bytes_value):
        """Converts bytes to readable units"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} PB"
    
    def is_root(self):
        """Checks if the script is running with root privileges"""
        return os.geteuid() == 0
    
    def run_command(self, cmd, timeout=None):
        """Executes a command and returns stdout/stderr"""
        timeout = timeout or self.config['performance']['command_timeout']
        
        # Replace first element with full path if available
        if cmd and len(cmd) > 0:
            tool_name = os.path.basename(cmd[0])
            full_path = self.tool_manager.get_tool_path(tool_name)
            if full_path:
                cmd = [full_path] + cmd[1:]
        
        self.logger.debug(f"Executing: {' '.join(cmd)}")
        
        try:
            proc = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            self.logger.debug(f"Return code: {proc.returncode}")
            return proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired:
            self.logger.warning(f"Command timed out: {' '.join(cmd)}")
            return "", "Timeout", -1
        except FileNotFoundError:
            self.logger.error(f"Command not found: {cmd[0]}")
            return "", f"Command not found: {cmd[0]}", -2
        except Exception as e:
            self.logger.error(f"Command failed: {e}")
            return "", str(e), -3
    
    def check_dependencies(self):
        """Checks if all required tools are installed"""
        return self.tool_manager.check_dependencies()
    
    def list_disks(self):
        """Lists all physical drives"""
        stdout, stderr, code = self.run_command(['lsblk', '-dJ', '-o', 'NAME,MODEL,SIZE,TYPE,ROTA'])
        if code != 0:
            self.logger.error(f"lsblk failed: {stderr}")
            return []
        
        try:
            data = json.loads(stdout)
            disks = []
            for device in data.get('blockdevices', []):
                if device.get('type') == 'disk':
                    disks.append({
                        'name': device.get('name'),
                        'model': device.get('model', 'Unknown').strip() if device.get('model') else 'Unknown',
                        'size': device.get('size', 'Unknown'),
                        'rotational': device.get('rota') == '1'
                    })
            self.logger.info(f"Found {len(disks)} disk(s)")
            return disks
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse lsblk output: {e}")
            return []
    
    def get_smart_health(self, dev):
        """Gets SMART health status"""
        path = f'/dev/{dev}'
        stdout, stderr, code = self.run_command(['smartctl', '-H', path])
        
        if 'Permission denied' in stderr or 'Operation not permitted' in stderr:
            return 'NEED_ROOT', None
        
        if 'Command not found' in stderr:
            return 'NO_SMARTCTL', None
        
        if 'SMART support is: Unavailable' in stdout:
            return 'NO_SMART', None
        
        if 'SMART overall-health' in stdout:
            if 'PASSED' in stdout:
                return 'PASSED', stdout
            elif 'FAILED' in stdout:
                return 'FAILED', stdout
        
        return 'UNKNOWN', stdout
    
    def get_smart_attributes(self, dev):
        """Extracts important SMART attributes"""
        attrs = {}
        path = f'/dev/{dev}'
        stdout, stderr, code = self.run_command(['smartctl', '-A', path])
        
        if code != 0 or 'Permission denied' in stderr or 'Command not found' in stderr:
            return attrs
        
        # Important attributes to monitor
        important_attrs = {
            '5': 'Reallocated_Sectors',
            '187': 'Reported_Uncorrect',
            '188': 'Command_Timeout',
            '197': 'Current_Pending_Sector',
            '198': 'Offline_Uncorrectable',
            '199': 'UDMA_CRC_Error_Count'
        }
        
        lines = stdout.split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 10:
                attr_id = parts[0]
                if attr_id in important_attrs:
                    try:
                        raw_value = int(parts[9])
                        if raw_value > 0:
                            attrs[important_attrs[attr_id]] = raw_value
                    except (ValueError, IndexError):
                        pass
        
        return attrs
    
    def get_temperature(self, dev):
        """Gets the current temperature of the drive"""
        path = f'/dev/{dev}'
        stdout, stderr, code = self.run_command(['smartctl', '-A', path])
        
        if code != 0:
            return None
        
        # Search for temperature in various formats
        temp_patterns = [
            r'Temperature_Celsius.*\s(\d+)\s*(?:C|$)',
            r'Current Temperature:\s*(\d+)\s*Celsius',
            r'Temperature:\s*(\d+)\s*C'
        ]
        
        for pattern in temp_patterns:
            match = re.search(pattern, stdout, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        return None
    
    def get_partition_info(self, partition_name):
        """Gets detailed information about a partition"""
        info = {
            'name': partition_name,
            'fstype': None,
            'mountpoint': None,
            'uuid': None,
            'label': None,
            'is_mounted': False
        }
        
        # Get filesystem type and UUID using blkid
        if self.tool_manager.get_tool_path('blkid'):
            stdout, stderr, code = self.run_command(['blkid', f'/dev/{partition_name}'])
            if code == 0:
                # Parse UUID
                uuid_match = re.search(r'UUID="([^"]+)"', stdout)
                if uuid_match:
                    info['uuid'] = uuid_match.group(1)
                
                # Parse filesystem type
                type_match = re.search(r'TYPE="([^"]+)"', stdout)
                if type_match:
                    info['fstype'] = type_match.group(1)
                
                # Parse label
                label_match = re.search(r'LABEL="([^"]+)"', stdout)
                if label_match:
                    info['label'] = label_match.group(1)
        
        # Get mount point from lsblk
        stdout, stderr, code = self.run_command(['lsblk', '-no', 'MOUNTPOINT', f'/dev/{partition_name}'])
        if code == 0 and stdout.strip():
            info['mountpoint'] = stdout.strip()
            info['is_mounted'] = True
        
        return info
    
    def get_fsck_command(self, partition_name, fstype, force=False):
        """Returns the appropriate fsck command for a filesystem type"""
        if not fstype:
            return None
            
        device_path = f'/dev/{partition_name}'
        
        # Map filesystem types to their fsck commands
        fsck_commands = {
            'ext2': f'fsck.ext2 {"-f" if force else ""} {device_path}',
            'ext3': f'fsck.ext3 {"-f" if force else ""} {device_path}',
            'ext4': f'fsck.ext4 {"-f" if force else ""} {device_path}',
            'xfs': f'xfs_repair {"-n" if not force else ""} {device_path}',  # XFS uses -n for check-only
            'btrfs': f'btrfs check {device_path}',
            'ntfs': f'ntfsfix {device_path}',
            'vfat': f'fsck.vfat -a {device_path}',
            'exfat': f'fsck.exfat {device_path}',
            'f2fs': f'fsck.f2fs {device_path}',
            'reiserfs': f'reiserfsck --check {device_path}',
            'jfs': f'fsck.jfs -n {device_path}',
            'hfsplus': f'fsck.hfsplus -f {device_path}'
        }
        
        # Get the base fsck command
        base_command = fsck_commands.get(fstype)
        if not base_command:
            # Fallback to generic fsck
            return f'fsck -t {fstype} {device_path}'
        
        # Add sudo prefix and cleanup extra spaces
        return f'sudo {base_command}'.replace('  ', ' ').strip()
    
    def check_unmounted_filesystem(self, partition_name, fstype):
        """Performs basic checks on unmounted filesystems"""
        checks = {}
        
        if not self.config['filesystem']['check_unmounted']:
            return checks
        
        # Only check if we have the appropriate tools and filesystem is supported
        if fstype not in self.config['filesystem']['supported_fs']:
            checks['supported'] = False
            return checks
        
        checks['supported'] = True
        
        # Different checks based on filesystem type
        if fstype in ['ext2', 'ext3', 'ext4']:
            if self.tool_manager.get_tool_path('dumpe2fs'):
                stdout, stderr, code = self.run_command(
                    ['dumpe2fs', '-h', f'/dev/{partition_name}'], 
                    timeout=5
                )
                if code == 0:
                    # Check filesystem state
                    state_match = re.search(r'Filesystem state:\s*(\w+)', stdout)
                    if state_match:
                        checks['state'] = state_match.group(1)
                        checks['clean'] = state_match.group(1) == 'clean'
                    
                    # Check mount count
                    mount_count_match = re.search(r'Mount count:\s*(\d+)', stdout)
                    max_mount_match = re.search(r'Maximum mount count:\s*(-?\d+)', stdout)
                    if mount_count_match and max_mount_match:
                        mount_count = int(mount_count_match.group(1))
                        max_mount = int(max_mount_match.group(1))
                        if max_mount > 0:
                            checks['mount_count'] = mount_count
                            checks['max_mount_count'] = max_mount
                            checks['needs_check'] = mount_count >= max_mount
                    
                    # Check last check time
                    last_check_match = re.search(r'Last checked:\s*(.+)', stdout)
                    if last_check_match:
                        checks['last_checked'] = last_check_match.group(1).strip()
        
        elif fstype == 'xfs':
            # XFS doesn't need regular fsck, but we can check if it's mountable
            checks['clean'] = True  # XFS is self-healing
        
        elif fstype == 'btrfs':
            if self.tool_manager.get_tool_path('btrfs'):
                # Could add btrfs-specific checks here
                checks['clean'] = True
        
        return checks
    
    def get_disk_usage(self, dev):
        """Determines the usage of all partitions on a drive"""
        mount_info = []
        partitions = []
        max_usage = 0
        
        # Get all partitions with detailed info
        stdout, stderr, code = self.run_command(['lsblk', '-lnJ', '-o', 'NAME,MOUNTPOINT,FSTYPE,SIZE', f'/dev/{dev}'])
        if code != 0:
            return None, [], []
        
        try:
            data = json.loads(stdout)
            for device in data.get('blockdevices', []):
                part_name = device.get('name')
                if part_name and part_name != dev:  # Skip the disk itself
                    part_info = self.get_partition_info(part_name)
                    
                    # If mounted, get usage statistics
                    if part_info['is_mounted'] and part_info['mountpoint']:
                        try:
                            total, used, free = shutil.disk_usage(part_info['mountpoint'])
                            usage_pct = int(used / total * 100)
                            mount_info.append({
                                'mountpoint': part_info['mountpoint'],
                                'usage': usage_pct,
                                'total': self.format_bytes(total),
                                'used': self.format_bytes(used),
                                'free': self.format_bytes(free)
                            })
                            max_usage = max(max_usage, usage_pct)
                            
                            partition = PartitionInfo(
                                name=part_name,
                                fstype=part_info['fstype'],
                                mountpoint=part_info['mountpoint'],
                                usage=usage_pct,
                                total=self.format_bytes(total),
                                used=self.format_bytes(used),
                                free=self.format_bytes(free),
                                uuid=part_info['uuid'],
                                label=part_info['label'],
                                is_mounted=True
                            )
                            partitions.append(partition)
                        except Exception as e:
                            self.logger.debug(f"Failed to get usage for {part_info['mountpoint']}: {e}")
                    else:
                        # Unmounted partition
                        size_str = device.get('size', 'Unknown')
                        
                        # Check unmounted filesystem if enabled
                        fs_checks = {}
                        if part_info['fstype'] and self.config['filesystem']['check_unmounted']:
                            fs_checks = self.check_unmounted_filesystem(part_name, part_info['fstype'])
                        
                        partition = PartitionInfo(
                            name=part_name,
                            fstype=part_info['fstype'] or 'Unknown',
                            mountpoint=None,
                            usage=None,
                            total=size_str,
                            used=None,
                            free=None,
                            uuid=part_info['uuid'],
                            label=part_info['label'],
                            is_mounted=False
                        )
                        
                        # Store filesystem check results
                        if fs_checks:
                            partition.fs_checks = fs_checks
                            
                        partitions.append(partition)
        
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse partition info: {e}")
        
        return max_usage if mount_info else None, mount_info, partitions
    
    def get_io_stats(self, dev):
        """Gets I/O statistics from /proc/diskstats"""
        if not self.config['output']['show_io_stats']:
            return None
            
        try:
            with open('/proc/diskstats', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 14 and parts[2] == dev:
                        return {
                            'read_ios': int(parts[3]),
                            'read_sectors': int(parts[5]),
                            'write_ios': int(parts[7]),
                            'write_sectors': int(parts[9]),
                            'io_time_ms': int(parts[12])
                        }
        except Exception as e:
            self.logger.debug(f"Failed to read I/O stats: {e}")
        return None
    
    def calculate_score(self, info):
        """Calculates a health score (higher = worse)"""
        score = 0
        issues = []
        cfg = self.config['thresholds']
        
        # SMART Health Status
        if info.smart_health == 'FAILED':
            score += cfg['smart_fail_score']
            issues.append(('CRITICAL', 'SMART Health Check failed!'))
        elif info.smart_health == 'UNKNOWN':
            score += cfg['smart_unknown_score']
            issues.append(('WARNING', 'SMART status unknown'))
        elif info.smart_health == 'NEED_ROOT':
            score += cfg['smart_need_root_score']
            issues.append(('INFO', 'Root privileges required for SMART check'))
        elif info.smart_health == 'NO_SMART':
            score += cfg['smart_no_support_score']
            issues.append(('INFO', 'SMART not available'))
        elif info.smart_health == 'NO_SMARTCTL':
            score += cfg['smart_unknown_score']
            issues.append(('WARNING', 'smartctl not available'))
        
        # SMART Attributes
        if info.smart_attrs:
            critical_attrs = ['Reallocated_Sectors', 'Current_Pending_Sector', 'Offline_Uncorrectable']
            for attr in critical_attrs:
                if attr in info.smart_attrs and info.smart_attrs[attr] > 0:
                    score += cfg['reallocated_sector_multiplier'] * info.smart_attrs[attr]
                    issues.append(('WARNING', f'{attr}: {info.smart_attrs[attr]}'))
        
        # Temperature
        if info.temp:
            if info.temp > cfg['temp_critical']:
                score += cfg['temp_critical_score']
                issues.append(('CRITICAL', f'Very high temperature: {info.temp}°C'))
            elif info.temp > cfg['temp_warning']:
                score += cfg['temp_warning_score']
                issues.append(('WARNING', f'Elevated temperature: {info.temp}°C'))
        
        # Storage space
        if info.usage:
            if info.usage >= cfg['usage_critical']:
                score += cfg['usage_critical_score']
                issues.append(('CRITICAL', f'Critically low disk space: {info.usage}%'))
            elif info.usage >= cfg['usage_warning']:
                score += cfg['usage_warning_score']
                issues.append(('WARNING', f'Low disk space: {info.usage}%'))
            elif info.usage >= cfg['usage_info']:
                score += cfg['usage_info_score']
                issues.append(('INFO', f'Disk space getting low: {info.usage}%'))
        
        # Check for unmounted partitions
        unmounted_count = 0
        unclean_count = 0
        for partition in info.partitions:
            if not partition.is_mounted:
                unmounted_count += 1
                # Check if filesystem needs attention
                if partition.fs_checks:
                    checks = partition.fs_checks
                    if checks.get('state') and checks['state'] != 'clean':
                        unclean_count += 1
                        score += cfg['unmounted_partition_score'] * 2
                        issues.append(('WARNING', f'Unmounted partition {partition.name} needs fsck (state: {checks["state"]})'))
                    elif checks.get('needs_check'):
                        score += cfg['unmounted_partition_score']
                        issues.append(('INFO', f'Unmounted partition {partition.name} due for check'))
        
        if unmounted_count > 0 and unclean_count == 0:
            score += cfg['unmounted_partition_score']
            issues.append(('INFO', f'{unmounted_count} unmounted partition(s) found'))
        
        return score, issues
    
    def analyze_disk(self, disk):
        """Analyzes a single drive"""
        start_time = time.time()
        self.logger.info(f"Analyzing disk: /dev/{disk['name']}")
        
        smart_health, smart_output = self.get_smart_health(disk['name'])
        smart_attrs = self.get_smart_attributes(disk['name']) if smart_health not in ['NEED_ROOT', 'NO_SMART', 'NO_SMARTCTL'] else {}
        temp = self.get_temperature(disk['name'])
        usage, mount_points, partitions = self.get_disk_usage(disk['name'])
        io_stats = self.get_io_stats(disk['name'])
        
        info = DiskInfo(
            name=disk['name'],
            model=disk['model'],
            size=disk['size'],
            smart_health=smart_health,
            smart_attrs=smart_attrs,
            temp=temp,
            usage=usage,
            mount_points=mount_points,
            partitions=partitions,
            io_stats=io_stats,
            score=0,
            issues=[],
            scan_time=time.time() - start_time
        )
        
        score, issues = self.calculate_score(info)
        info = info._replace(score=score, issues=issues)
        
        self.logger.info(f"Disk {disk['name']} analyzed in {info.scan_time:.2f}s, score: {score}")
        return info
    
    def analyze_all_disks(self, disks):
        """Analyzes all drives in parallel"""
        disk_infos = []
        max_workers = self.config['performance']['max_workers']
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_disk = {executor.submit(self.analyze_disk, disk): disk for disk in disks}
            
            for future in as_completed(future_to_disk):
                try:
                    info = future.result()
                    disk_infos.append(info)
                    if not self.args or not self.args.quiet:
                        print(f".", end='', flush=True)
                except Exception as e:
                    disk = future_to_disk[future]
                    self.logger.error(f"Failed to analyze disk {disk['name']}: {e}")
        
        return disk_infos

class OutputFormatter:
    """Class for different output formats"""
    
    def __init__(self, checker, args):
        self.checker = checker
        self.args = args
        
    def format_console(self, disk_infos):
        """Formatted console output"""
        
        # Environment information in debug mode
        if self.args and self.args.debug:
            self._print_environment_info()
        
        # Root check
        if not self.checker.is_root() and not self.args.quiet:
            print(f"{Colors.WARNING}{Symbols.WARNING} Note: Script running without root privileges.{Colors.ENDC}")
            print(f"   Some tests (SMART, temperature, unmounted filesystems) require root access.")
            print(f"   Run with sudo for complete analysis.\n")
        
        # Sort by score
        disk_infos.sort(key=lambda x: x.score, reverse=True)
        
        print(f"\n{Colors.BOLD}{'═' * 60}{Colors.ENDC}")
        print(f"{Colors.BOLD}Results (sorted by urgency):{Colors.ENDC}")
        print(f"{Colors.BOLD}{'═' * 60}{Colors.ENDC}\n")
        
        for rank, info in enumerate(disk_infos, 1):
            self._print_disk_summary(rank, info)
        
        self._print_recommendations(disk_infos)
        self._print_summary(disk_infos)
    
    def format_json(self, disk_infos):
        """JSON output for machine processing"""
        output = {
            'version': __version__,
            'timestamp': datetime.now().isoformat(),
            'is_root': self.checker.is_root(),
            'environment': self.checker.tool_manager.get_environment_info(),
            'disks': []
        }
        
        for info in disk_infos:
            disk_data = {
                'name': info.name,
                'path': f'/dev/{info.name}',
                'model': info.model,
                'size': info.size,
                'score': info.score,
                'smart': {
                    'health': info.smart_health,
                    'attributes': info.smart_attrs
                },
                'temperature': info.temp,
                'usage': {
                    'percent': info.usage,
                    'mount_points': info.mount_points
                },
                'partitions': [
                    {
                        'name': p.name,
                        'fstype': p.fstype,
                        'mountpoint': p.mountpoint,
                        'is_mounted': p.is_mounted,
                        'usage': p.usage,
                        'uuid': p.uuid,
                        'label': p.label,
                        'total': p.total,
                        'fs_checks': p.fs_checks if p.fs_checks else {},
                        'fsck_command': self.checker.get_fsck_command(p.name, p.fstype, force=True) if p.fstype and not p.is_mounted else None
                    } for p in info.partitions
                ],
                'issues': [{'severity': sev, 'message': msg} for sev, msg in info.issues],
                'scan_time': info.scan_time
            }
            if info.io_stats:
                disk_data['io_stats'] = info.io_stats
            output['disks'].append(disk_data)
        
        print(json.dumps(output, indent=2))
    
    def format_plain(self, disk_infos):
        """Simple text output without formatting"""
        print(f"Disk Health Check Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        disk_infos.sort(key=lambda x: x.score, reverse=True)
        
        for rank, info in enumerate(disk_infos, 1):
            print(f"\n#{rank} /dev/{info.name} - {info.model} ({info.size})")
            print(f"   Score: {info.score}")
            print(f"   SMART: {info.smart_health}")
            if info.temp:
                print(f"   Temperature: {info.temp}°C")
            if info.usage is not None:
                print(f"   Usage: {info.usage}%")
            
            # Partition information
            if info.partitions:
                print("   Partitions:")
                for p in info.partitions:
                    status = "mounted" if p.is_mounted else "unmounted"
                    print(f"      - {p.name} ({p.fstype}) - {status}")
                    if p.is_mounted and p.usage:
                        print(f"        Usage: {p.usage}% at {p.mountpoint}")
                    elif not p.is_mounted and p.fs_checks:
                        checks = p.fs_checks
                        if checks.get('state'):
                            print(f"        State: {checks['state']}")
            
            if info.issues:
                print("   Issues:")
                for severity, issue in info.issues:
                    print(f"      [{severity}] {issue}")
    
    def _print_environment_info(self):
        """Shows environment information in debug mode"""
        env_info = self.checker.tool_manager.get_environment_info()
        print(f"{Colors.OKCYAN}{Colors.BOLD}DEBUG: Environment information{Colors.ENDC}")
        print(f"  USER: {env_info['user']}")
        print(f"  PATH: {env_info['path'][:100]}{'...' if len(env_info['path']) > 100 else ''}")
        print(f"  Systemd: {env_info['is_systemd']}")
        print(f"  Cron/Non-TTY: {env_info['is_cron']}")
        print(f"  Tool paths found:")
        for tool, path in env_info['tool_paths'].items():
            print(f"    {tool}: {path}")
        print()
    
    def _print_header(self):
        """Prints the header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}═══════════════════════════════════════════════════════════════")
        print(f"   Linux Disk Health Checker v{__version__}")
        print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"═══════════════════════════════════════════════════════════════{Colors.ENDC}\n")
    
    def _print_disk_summary(self, rank, info):
        """Prints a summary for a drive"""
        # Color coding based on score
        if info.score >= 500:
            color = Colors.FAIL
            status_symbol = Symbols.ERROR
        elif info.score >= 100:
            color = Colors.WARNING
            status_symbol = Symbols.WARNING
        elif info.score > 0:
            color = Colors.OKCYAN
            status_symbol = Symbols.INFO
        else:
            color = Colors.OKGREEN
            status_symbol = Symbols.OK
        
        print(f"{color}{Colors.BOLD}#{rank} - /dev/{info.name} - {info.model} ({info.size}){Colors.ENDC}")
        print(f"   Status: {color}{status_symbol} Score: {info.score}{Colors.ENDC}")
        
        # Temperature
        if info.temp:
            temp_color = Colors.FAIL if info.temp > self.checker.config['thresholds']['temp_warning'] else Colors.OKGREEN
            print(f"   {Symbols.TEMP} Temperature: {temp_color}{info.temp}°C{Colors.ENDC}")
        
        # Storage space
        if info.usage is not None:
            cfg = self.checker.config['thresholds']
            usage_color = Colors.FAIL if info.usage >= cfg['usage_warning'] else Colors.WARNING if info.usage >= cfg['usage_info'] else Colors.OKGREEN
            print(f"   {Symbols.DISK} Usage: {usage_color}{info.usage}%{Colors.ENDC}")
            
            # Mount points details
            max_shown = self.checker.config['output']['max_mount_points_shown']
            for mp in info.mount_points[:max_shown]:
                print(f"      └─ {mp['mountpoint']}: {mp['usage']}% ({mp['used']}/{mp['total']})")
        
        # Show unmounted partitions if enabled
        if self.checker.config['output']['show_unmounted']:
            unmounted = [p for p in info.partitions if not p.is_mounted]
            if unmounted:
                print(f"   {Symbols.UNMOUNTED} Unmounted partitions:")
                for part in unmounted:
                    fs_info = f"{part.fstype}" if part.fstype else "Unknown FS"
                    label_info = f" [{part.label}]" if part.label else ""
                    print(f"      └─ {part.name}: {fs_info}{label_info} ({part.total})")
                    
                    # Show filesystem check results if available
                    show_fsck_cmd = False
                    if part.fs_checks:
                        checks = part.fs_checks
                        if checks.get('state') and checks['state'] != 'clean':
                            print(f"         {Colors.WARNING}State: {checks['state']} - needs checking{Colors.ENDC}")
                            show_fsck_cmd = True
                        elif checks.get('needs_check'):
                            print(f"         {Colors.WARNING}Check recommended (mount count: {checks['mount_count']}/{checks['max_mount_count']}){Colors.ENDC}")
                            show_fsck_cmd = True
                        if checks.get('last_checked'):
                            print(f"         Last checked: {checks['last_checked']}")
                    
                    # Show fsck command if needed
                    if show_fsck_cmd and part.fstype:
                        fsck_cmd = self.checker.get_fsck_command(part.name, part.fstype, force=True)
                        if fsck_cmd:
                            print(f"         {Colors.OKGREEN}→ {fsck_cmd}{Colors.ENDC}")
        
        # I/O Stats (if enabled)
        if info.io_stats and self.checker.config['output']['show_io_stats']:
            print(f"   {Symbols.CLOCK} I/O: {info.io_stats['read_ios']:,} reads, {info.io_stats['write_ios']:,} writes")
        
        # Scan time (in debug mode)
        if self.args and self.args.debug:
            print(f"   Scan time: {info.scan_time:.2f}s")
        
        # Issues
        if info.issues:
            print(f"   {Symbols.WARNING} Found issues:")
            for severity, issue in info.issues:
                if severity == 'CRITICAL':
                    print(f"      {Colors.FAIL}• {issue}{Colors.ENDC}")
                elif severity == 'WARNING':
                    print(f"      {Colors.WARNING}• {issue}{Colors.ENDC}")
                else:
                    print(f"      {Colors.OKCYAN}• {issue}{Colors.ENDC}")
        
        print()
    
    def _print_recommendations(self, disk_infos):
        """Provides recommendations based on results"""
        print(f"{Colors.BOLD}\n{Symbols.INFO} Recommendations:{Colors.ENDC}\n")
        
        critical_disks = []
        warning_disks = []
        unmounted_issues = []
        
        for info in disk_infos:
            if info.score >= 500:
                critical_disks.append(info)
            elif info.score >= 100:
                warning_disks.append(info)
            
            # Check for unmounted filesystem issues
            for part in info.partitions:
                if not part.is_mounted and part.fs_checks:
                    checks = part.fs_checks
                    if checks.get('state') and checks['state'] != 'clean':
                        unmounted_issues.append((info, part, checks))
        
        if critical_disks:
            print(f"{Colors.FAIL}{Colors.BOLD}CRITICAL - Immediate action required:{Colors.ENDC}")
            for disk in critical_disks:
                print(f"  {Colors.FAIL}• /dev/{disk.name}:{Colors.ENDC}")
                if disk.smart_health == 'FAILED':
                    print(f"    → IMMEDIATELY create backup! Drive is about to fail!")
                if disk.usage and disk.usage >= self.checker.config['thresholds']['usage_critical']:
                    print(f"    → Urgently free up disk space or migrate data!")
                if disk.temp and disk.temp > self.checker.config['thresholds']['temp_critical']:
                    print(f"    → Check cooling! Drive is overheating!")
            print()
        
        if warning_disks:
            print(f"{Colors.WARNING}{Colors.BOLD}WARNING - Attention required:{Colors.ENDC}")
            for disk in warning_disks:
                print(f"  {Colors.WARNING}• /dev/{disk.name}:{Colors.ENDC}")
                for severity, issue in disk.issues:
                    if severity == 'WARNING':
                        print(f"    → {issue}")
            print()
        
        if unmounted_issues:
            print(f"{Colors.WARNING}{Colors.BOLD}Unmounted filesystem issues:{Colors.ENDC}")
            for disk, part, checks in unmounted_issues:
                print(f"  {Colors.WARNING}• /dev/{part.name} on disk {disk.name}:{Colors.ENDC}")
                if part.label:
                    print(f"    Label: {part.label}")
                print(f"    Filesystem: {part.fstype or 'Unknown'}")
                
                if checks.get('state') != 'clean':
                    print(f"    → Filesystem needs checking (state: {checks['state']})")
                elif checks.get('needs_check'):
                    print(f"    → Filesystem check recommended (mount count: {checks['mount_count']}/{checks['max_mount_count']})")
                
                # Get appropriate fsck command
                fsck_cmd = self.checker.get_fsck_command(part.name, part.fstype, force=True)
                if fsck_cmd:
                    print(f"    Command to check:")
                    print(f"      {Colors.OKGREEN}{fsck_cmd}{Colors.ENDC}")
                    
                    # Add filesystem-specific notes
                    if part.fstype == 'xfs':
                        print(f"      {Colors.OKCYAN}Note: For XFS, use without -n flag to repair{Colors.ENDC}")
                    elif part.fstype == 'btrfs':
                        print(f"      {Colors.OKCYAN}Note: For btrfs, add --repair only if needed{Colors.ENDC}")
                    elif part.fstype == 'ntfs':
                        print(f"      {Colors.OKCYAN}Note: For NTFS, consider using Windows chkdsk for thorough repair{Colors.ENDC}")
            print()
        
        # Tool availability
        missing_tools = []
        for tool in ['smartctl', 'blkid']:
            if not self.checker.tool_manager.get_tool_path(tool):
                missing_tools.append(tool)
        
        if missing_tools and not self.args.quiet:
            print(f"{Colors.WARNING}{Colors.BOLD}Missing optional tools:{Colors.ENDC}")
            print(f"  Install for extended functionality:")
            if 'smartctl' in missing_tools:
                print(f"    {Colors.OKGREEN}sudo apt install smartmontools{Colors.ENDC} (for SMART tests)")
            if 'blkid' in missing_tools:
                print(f"    {Colors.OKGREEN}sudo apt install util-linux{Colors.ENDC} (for filesystem detection)")
            print()
        
        # General recommendations
        if not self.checker.is_root() and not self.args.quiet:
            print(f"{Colors.OKCYAN}{Colors.BOLD}Note:{Colors.ENDC}")
            print(f"  • For complete analysis including unmounted filesystems run with sudo:")
            print(f"    {Colors.OKGREEN}sudo {' '.join(sys.argv)}{Colors.ENDC}")
            print()
        
        # Maintenance recommendations
        if not self.args.check_only:
            print(f"{Colors.OKBLUE}{Colors.BOLD}Regular maintenance:{Colors.ENDC}")
            print(f"  • Run this check monthly")
            print(f"  • Create regular backups of important data")
            print(f"  • Monitor temperature under high load")
            print(f"  • Keep at least 10-20% free disk space")
            print(f"  • Check and mount/repair unmounted filesystems if needed")
            
            # Show general fsck tips if there are unmounted partitions
            all_unmounted = []
            for info in disk_infos:
                all_unmounted.extend([p for p in info.partitions if not p.is_mounted])
            
            if all_unmounted:
                print(f"\n{Colors.OKBLUE}{Colors.BOLD}Filesystem check commands:{Colors.ENDC}")
                print(f"  Common fsck commands for different filesystems:")
                
                # Group by filesystem type
                fs_types = {}
                for part in all_unmounted:
                    if part.fstype:
                        if part.fstype not in fs_types:
                            fs_types[part.fstype] = []
                        fs_types[part.fstype].append(part)
                
                for fstype, parts in sorted(fs_types.items()):
                    example_part = parts[0]
                    fsck_cmd = self.checker.get_fsck_command(example_part.name, fstype, force=False)
                    if fsck_cmd:
                        print(f"  • {fstype}: {Colors.OKGREEN}{fsck_cmd}{Colors.ENDC}")
                        
                        # Add filesystem-specific tips
                        if fstype in ['ext2', 'ext3', 'ext4']:
                            print(f"    Use -f to force check even if filesystem seems clean")
                            print(f"    Use -y to automatically fix errors (use with caution)")
                        elif fstype == 'xfs':
                            print(f"    Use without -n to actually repair (default is check-only)")
                            print(f"    XFS is self-healing and rarely needs manual repair")
                        elif fstype == 'btrfs':
                            print(f"    Add --repair only if check reports errors")
                            print(f"    Consider 'btrfs scrub' for online checking")
                        elif fstype == 'ntfs':
                            print(f"    Limited repair capability on Linux")
                            print(f"    For thorough repair, use Windows chkdsk")
                
                print(f"\n  {Colors.WARNING}⚠ Always ensure partitions are unmounted before running fsck!{Colors.ENDC}")
                print(f"  {Colors.OKCYAN}Tip: Boot from a live USB/CD for checking root partition{Colors.ENDC}")
    
    def _print_summary(self, disk_infos):
        """Summary"""
        print(f"\n{Colors.BOLD}{'═' * 60}{Colors.ENDC}")
        critical_count = sum(1 for d in disk_infos if d.score >= 500)
        warning_count = sum(1 for d in disk_infos if 100 <= d.score < 500)
        ok_count = sum(1 for d in disk_infos if d.score < 100)
        
        # Count partitions
        total_partitions = sum(len(d.partitions) for d in disk_infos)
        unmounted_partitions = sum(len([p for p in d.partitions if not p.is_mounted]) for d in disk_infos)
        
        print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
        print(f"  {Colors.FAIL if critical_count else Colors.OKGREEN}• Critical: {critical_count}{Colors.ENDC}")
        print(f"  {Colors.WARNING if warning_count else Colors.OKGREEN}• Warning:  {warning_count}{Colors.ENDC}")
        print(f"  {Colors.OKGREEN}• OK:       {ok_count}{Colors.ENDC}")
        
        if total_partitions > 0:
            print(f"\n{Colors.BOLD}Partitions:{Colors.ENDC}")
            print(f"  • Total:     {total_partitions}")
            print(f"  • Mounted:   {total_partitions - unmounted_partitions}")
            print(f"  • Unmounted: {unmounted_partitions}")
        
        total_scan_time = sum(d.scan_time for d in disk_infos)
        print(f"\nTotal scan time: {total_scan_time:.2f}s")
        print(f"{Colors.BOLD}{'═' * 60}{Colors.ENDC}\n")

def load_config(config_file):
    """Loads configuration from YAML file"""
    if not config_file or not Path(config_file).exists():
        return DEFAULT_CONFIG
    
    try:
        with open(config_file, 'r') as f:
            user_config = yaml.safe_load(f)
        
        # Deep merge with default config
        config = DEFAULT_CONFIG.copy()
        
        def deep_merge(base, update):
            for key in update:
                if key in base and isinstance(base[key], dict) and isinstance(update[key], dict):
                    deep_merge(base[key], update[key])
                else:
                    base[key] = update[key]
        
        deep_merge(config, user_config)
        return config
    except Exception as e:
        logging.warning(f"Failed to load config file {config_file}: {e}")
        return DEFAULT_CONFIG

def create_sample_config():
    """Creates a sample configuration file"""
    sample_file = "disk_health_checker.yaml"
    with open(sample_file, 'w') as f:
        yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
    print(f"Sample configuration file created: {sample_file}")

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Linux Disk Health Checker - Comprehensive tool for checking drive health',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                     # Standard analysis with colored output
  %(prog)s --json              # JSON output for monitoring tools
  %(prog)s --check-only        # Check only, no recommendations
  %(prog)s --smart-only        # Run SMART tests only
  %(prog)s --config my.yaml    # With custom configuration
  %(prog)s --create-config     # Create sample configuration
  %(prog)s --show-unmounted    # Include unmounted partitions in output
  
For complete SMART and filesystem analysis run with sudo:
  sudo %(prog)s

For cronjobs use full path:
  /usr/local/bin/%(prog)s --json
        """
    )
    
    # Output options
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument('--json', action='store_true',
                            help='JSON output for machine processing')
    output_group.add_argument('--plain', action='store_true',
                            help='Simple text output without colors/symbols')
    
    # Analysis options
    parser.add_argument('--smart-only', action='store_true',
                       help='Run SMART tests only')
    parser.add_argument('--usage-only', action='store_true',
                       help='Check disk usage only')
    parser.add_argument('--check-only', action='store_true',
                       help='Check only, no recommendations')
    parser.add_argument('--show-unmounted', action='store_true',
                       help='Show unmounted partitions in output')
    parser.add_argument('--check-unmounted', action='store_true',
                       help='Perform filesystem checks on unmounted partitions')
    
    # Performance options
    parser.add_argument('--parallel', type=int, metavar='N',
                       help='Number of parallel workers (default: 4)')
    parser.add_argument('--timeout', type=int, metavar='SEC',
                       help='Command timeout in seconds (default: 10)')
    
    # Configuration
    parser.add_argument('--config', metavar='FILE',
                       help='Configuration file (YAML)')
    parser.add_argument('--create-config', action='store_true',
                       help='Create sample configuration file')
    
    # Debug/Logging
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    parser.add_argument('-d', '--debug', action='store_true',
                       help='Debug output with all details')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Minimal output')
    
    # Version
    parser.add_argument('--version', action='version',
                       version=f'%(prog)s {__version__}')
    
    args = parser.parse_args()
    
    # Create sample config
    if args.create_config:
        create_sample_config()
        return 0
    
    # Load configuration
    config = load_config(args.config)
    
    # Override configuration with command line arguments
    if args.parallel:
        config['performance']['max_workers'] = args.parallel
    if args.timeout:
        config['performance']['command_timeout'] = args.timeout
    if args.show_unmounted:
        config['output']['show_unmounted'] = True
    if args.check_unmounted:
        config['filesystem']['check_unmounted'] = True
    
    # Disable colors/symbols for plain/json
    if args.plain or args.json:
        Colors.disable()
        Symbols.disable()
    
    # Initialize checker
    checker = DiskHealthChecker(config, args)
    formatter = OutputFormatter(checker, args)
    
    try:
        # Check dependencies
        missing, optional = checker.check_dependencies()
        if missing:
            print(f"{Colors.FAIL}Missing required tools: {', '.join(missing)}{Colors.ENDC}")
            print("Please install the missing tools and try again.")
            return 1
        
        if optional and not args.quiet:
            print(f"{Colors.WARNING}Optional tools not found: {', '.join(optional)}{Colors.ENDC}")
            print(f"For full functionality install:")
            if 'smartctl' in optional:
                print(f"  {Colors.OKGREEN}sudo apt install smartmontools{Colors.ENDC} (Debian/Ubuntu)")
                print(f"  {Colors.OKGREEN}sudo yum install smartmontools{Colors.ENDC} (RedHat/CentOS)")
            if 'blkid' in optional:
                print(f"  {Colors.OKGREEN}sudo apt install util-linux{Colors.ENDC} (filesystem detection)")
            print()
        
        if not args.json and not args.quiet:
            formatter._print_header()
            print(f"{Colors.BOLD}Searching for drives...{Colors.ENDC}")
        
        # Find drives
        disks = checker.list_disks()
        if not disks:
            print(f"{Colors.FAIL}No physical drives found!{Colors.ENDC}")
            return 1
        
        if not args.json and not args.quiet:
            print(f"Found: {len(disks)} drive(s)")
            print(f"\n{Colors.BOLD}Analyzing drives", end='', flush=True)
        
        # Analyze
        disk_infos = checker.analyze_all_disks(disks)
        
        if not args.json and not args.quiet:
            print(f" {Colors.OKGREEN}✓{Colors.ENDC}")
        
        # Output
        if args.json:
            formatter.format_json(disk_infos)
        elif args.plain:
            formatter.format_plain(disk_infos)
        else:
            formatter.format_console(disk_infos)
        
        # Exit code based on critical drives
        critical_count = sum(1 for d in disk_infos if d.score >= 500)
        return 2 if critical_count > 0 else 0
        
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Aborted.{Colors.ENDC}")
        return 130
    except Exception as e:
        if args.debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"\n{Colors.FAIL}Error: {e}{Colors.ENDC}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
