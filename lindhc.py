#!/usr/bin/env python3
"""
Linux Disk Health Checker
Ein umfassendes, modulares Tool zur Überprüfung der Gesundheit aller physischen Laufwerke

Features:
- Parallele Ausführung für bessere Performance
- Multiple Ausgabeformate (Konsole, JSON, Plain)
- Konfigurierbare Schwellenwerte
- Debug/Verbose Modi
- Modulare Architektur
- Robuste Tool-Pfad-Erkennung für Cronjobs/Systemd
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
VERSION_MINOR="1"
VERSION_PATCH="6"
__version__ = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

# ANSI Color Codes für bessere Darstellung
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
        """Deaktiviert alle Farben"""
        for attr in dir(cls):
            if not attr.startswith('_'):
                setattr(cls, attr, '')

# Unicode Symbole für bessere Visualisierung
class Symbols:
    OK = '✓'
    WARNING = '⚠'
    ERROR = '✗'
    INFO = 'ℹ'
    DISK = '💾'
    TEMP = '🌡️'
    CLOCK = '⏱️'
    
    @classmethod
    def disable(cls):
        """Ersetzt Symbole durch ASCII"""
        cls.OK = '[OK]'
        cls.WARNING = '[!]'
        cls.ERROR = '[X]'
        cls.INFO = '[i]'
        cls.DISK = '[D]'
        cls.TEMP = '[T]'
        cls.CLOCK = '[>]'

# Default Konfiguration
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
        'usage_info_score': 20
    },
    'performance': {
        'max_workers': 4,
        'command_timeout': 10
    },
    'output': {
        'max_mount_points_shown': 3,
        'show_io_stats': False
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
    }
}

DiskInfo = namedtuple('DiskInfo', [
    'name', 'model', 'size', 'smart_health', 'smart_attrs', 
    'temp', 'usage', 'mount_points', 'io_stats', 'score', 'issues',
    'scan_time'
])

class ToolManager:
    """Verwaltet Pfade zu externen Tools für robuste Ausführung"""
    
    def __init__(self, config=None):
        self.config = config or DEFAULT_CONFIG
        self.tool_paths = {}
        self.logger = logging.getLogger(__name__)
        
    def find_tool(self, tool_name):
        """Findet den vollständigen Pfad zu einem Tool"""
        if tool_name in self.tool_paths:
            return self.tool_paths[tool_name]
        
        # Zuerst mit 'which' versuchen
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
        
        # Fallback: In Standard-Pfaden suchen
        search_paths = self.config.get('tools', {}).get('search_paths', [])
        for search_path in search_paths:
            full_path = os.path.join(search_path, tool_name)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                self.tool_paths[tool_name] = full_path
                self.logger.debug(f"Found {tool_name} at {full_path} (fallback)")
                return full_path
        
        # Tool nicht gefunden
        self.logger.warning(f"Tool {tool_name} not found in PATH or standard locations")
        return None
    
    def get_tool_path(self, tool_name):
        """Gibt den vollständigen Pfad zu einem Tool zurück"""
        return self.tool_paths.get(tool_name)
    
    def check_dependencies(self):
        """Prüft alle benötigten Tools und speichert ihre Pfade"""
        missing = []
        optional = []
        
        # Erforderliche Tools
        required_tools = ['lsblk']
        for tool in required_tools:
            if not self.find_tool(tool):
                missing.append(tool)
        
        # Optionale Tools  
        optional_tools = ['smartctl']
        for tool in optional_tools:
            if not self.find_tool(tool):
                optional.append(tool)
        
        return missing, optional
    
    def get_environment_info(self):
        """Sammelt Informationen über die Ausführungsumgebung"""
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
        """Konfiguriert das Logging-System"""
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
        """Konvertiert Bytes in lesbare Einheiten"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} PB"
    
    def is_root(self):
        """Prüft ob das Script mit Root-Rechten läuft"""
        return os.geteuid() == 0
    
    def run_command(self, cmd, timeout=None):
        """Führt einen Befehl aus und gibt stdout/stderr zurück"""
        timeout = timeout or self.config['performance']['command_timeout']
        
        # Erstes Element durch vollständigen Pfad ersetzen, falls verfügbar
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
        """Prüft ob alle benötigten Tools installiert sind"""
        return self.tool_manager.check_dependencies()
    
    def list_disks(self):
        """Listet alle physischen Laufwerke auf"""
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
        """Holt SMART Health Status"""
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
        """Extrahiert wichtige SMART Attribute"""
        attrs = {}
        path = f'/dev/{dev}'
        stdout, stderr, code = self.run_command(['smartctl', '-A', path])
        
        if code != 0 or 'Permission denied' in stderr or 'Command not found' in stderr:
            return attrs
        
        # Wichtige Attribute zum Überwachen
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
        """Holt die aktuelle Temperatur des Laufwerks"""
        path = f'/dev/{dev}'
        stdout, stderr, code = self.run_command(['smartctl', '-A', path])
        
        if code != 0:
            return None
        
        # Suche nach Temperatur in verschiedenen Formaten
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
    
    def get_disk_usage(self, dev):
        """Ermittelt die Belegung aller Partitionen eines Laufwerks"""
        mount_info = []
        max_usage = 0
        
        stdout, stderr, code = self.run_command(['lsblk', '-lno', 'NAME,MOUNTPOINT,FSTYPE', f'/dev/{dev}'])
        if code != 0:
            return None, []
        
        for line in stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split(None, 2)
            if len(parts) >= 2 and parts[1]:  # Hat Mountpoint
                mountpoint = parts[1]
                try:
                    total, used, free = shutil.disk_usage(mountpoint)
                    usage_pct = int(used / total * 100)
                    mount_info.append({
                        'mountpoint': mountpoint,
                        'usage': usage_pct,
                        'total': self.format_bytes(total),
                        'used': self.format_bytes(used),
                        'free': self.format_bytes(free)
                    })
                    max_usage = max(max_usage, usage_pct)
                except Exception as e:
                    self.logger.debug(f"Failed to get usage for {mountpoint}: {e}")
        
        return max_usage if mount_info else None, mount_info
    
    def get_io_stats(self, dev):
        """Holt I/O Statistiken aus /proc/diskstats"""
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
        """Berechnet einen Gesundheitsscore (höher = schlechter)"""
        score = 0
        issues = []
        cfg = self.config['thresholds']
        
        # SMART Health Status
        if info.smart_health == 'FAILED':
            score += cfg['smart_fail_score']
            issues.append(('CRITICAL', 'SMART Health Check fehlgeschlagen!'))
        elif info.smart_health == 'UNKNOWN':
            score += cfg['smart_unknown_score']
            issues.append(('WARNING', 'SMART Status unbekannt'))
        elif info.smart_health == 'NEED_ROOT':
            score += cfg['smart_need_root_score']
            issues.append(('INFO', 'Root-Rechte für SMART-Check benötigt'))
        elif info.smart_health == 'NO_SMART':
            score += cfg['smart_no_support_score']
            issues.append(('INFO', 'SMART nicht verfügbar'))
        elif info.smart_health == 'NO_SMARTCTL':
            score += cfg['smart_unknown_score']
            issues.append(('WARNING', 'smartctl nicht verfügbar'))
        
        # SMART Attribute
        if info.smart_attrs:
            critical_attrs = ['Reallocated_Sectors', 'Current_Pending_Sector', 'Offline_Uncorrectable']
            for attr in critical_attrs:
                if attr in info.smart_attrs and info.smart_attrs[attr] > 0:
                    score += cfg['reallocated_sector_multiplier'] * info.smart_attrs[attr]
                    issues.append(('WARNING', f'{attr}: {info.smart_attrs[attr]}'))
        
        # Temperatur
        if info.temp:
            if info.temp > cfg['temp_critical']:
                score += cfg['temp_critical_score']
                issues.append(('CRITICAL', f'Sehr hohe Temperatur: {info.temp}°C'))
            elif info.temp > cfg['temp_warning']:
                score += cfg['temp_warning_score']
                issues.append(('WARNING', f'Erhöhte Temperatur: {info.temp}°C'))
        
        # Speicherplatz
        if info.usage:
            if info.usage >= cfg['usage_critical']:
                score += cfg['usage_critical_score']
                issues.append(('CRITICAL', f'Kritisch wenig Speicherplatz: {info.usage}%'))
            elif info.usage >= cfg['usage_warning']:
                score += cfg['usage_warning_score']
                issues.append(('WARNING', f'Wenig Speicherplatz: {info.usage}%'))
            elif info.usage >= cfg['usage_info']:
                score += cfg['usage_info_score']
                issues.append(('INFO', f'Speicherplatz wird knapp: {info.usage}%'))
        
        return score, issues
    
    def analyze_disk(self, disk):
        """Analysiert ein einzelnes Laufwerk"""
        start_time = time.time()
        self.logger.info(f"Analyzing disk: /dev/{disk['name']}")
        
        smart_health, smart_output = self.get_smart_health(disk['name'])
        smart_attrs = self.get_smart_attributes(disk['name']) if smart_health not in ['NEED_ROOT', 'NO_SMART', 'NO_SMARTCTL'] else {}
        temp = self.get_temperature(disk['name'])
        usage, mount_points = self.get_disk_usage(disk['name'])
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
        """Analysiert alle Laufwerke parallel"""
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
    """Klasse für verschiedene Ausgabeformate"""
    
    def __init__(self, checker, args):
        self.checker = checker
        self.args = args
        
    def format_console(self, disk_infos):
        """Formatierte Konsolenausgabe"""
        
        # Umgebungsinformationen im Debug-Modus
        if self.args and self.args.debug:
            self._print_environment_info()
        
        # Root-Check
        if not self.checker.is_root() and not self.args.quiet:
            print(f"{Colors.WARNING}{Symbols.WARNING} Hinweis: Script läuft ohne Root-Rechte.{Colors.ENDC}")
            print(f"   Einige Tests (SMART, Temperatur) benötigen Root-Zugriff.")
            print(f"   Für vollständige Analyse mit sudo ausführen.\n")
        
        # Sortiere nach Score
        disk_infos.sort(key=lambda x: x.score, reverse=True)
        
        print(f"\n{Colors.BOLD}{'═' * 60}{Colors.ENDC}")
        print(f"{Colors.BOLD}Ergebnisse (sortiert nach Dringlichkeit):{Colors.ENDC}")
        print(f"{Colors.BOLD}{'═' * 60}{Colors.ENDC}\n")
        
        for rank, info in enumerate(disk_infos, 1):
            self._print_disk_summary(rank, info)
        
        self._print_recommendations(disk_infos)
        self._print_summary(disk_infos)
    
    def format_json(self, disk_infos):
        """JSON-Ausgabe für maschinelle Verarbeitung"""
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
                'issues': [{'severity': sev, 'message': msg} for sev, msg in info.issues],
                'scan_time': info.scan_time
            }
            if info.io_stats:
                disk_data['io_stats'] = info.io_stats
            output['disks'].append(disk_data)
        
        print(json.dumps(output, indent=2))
    
    def format_plain(self, disk_infos):
        """Einfache Textausgabe ohne Formatierung"""
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
            if info.issues:
                print("   Issues:")
                for severity, issue in info.issues:
                    print(f"      [{severity}] {issue}")
    
    def _print_environment_info(self):
        """Zeigt Umgebungsinformationen im Debug-Modus"""
        env_info = self.checker.tool_manager.get_environment_info()
        print(f"{Colors.OKCYAN}{Colors.BOLD}DEBUG: Umgebungsinformationen{Colors.ENDC}")
        print(f"  USER: {env_info['user']}")
        print(f"  PATH: {env_info['path'][:100]}{'...' if len(env_info['path']) > 100 else ''}")
        print(f"  Systemd: {env_info['is_systemd']}")
        print(f"  Cron/Non-TTY: {env_info['is_cron']}")
        print(f"  Tool-Pfade gefunden:")
        for tool, path in env_info['tool_paths'].items():
            print(f"    {tool}: {path}")
        print()
    
    def _print_header(self):
        """Druckt den Header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}═══════════════════════════════════════════════════════════════")
        print(f"   Linux Disk Health Checker v{__version__}")
        print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"═══════════════════════════════════════════════════════════════{Colors.ENDC}\n")
    
    def _print_disk_summary(self, rank, info):
        """Druckt eine Zusammenfassung für ein Laufwerk"""
        # Farbcodierung basierend auf Score
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
        
        # Temperatur
        if info.temp:
            temp_color = Colors.FAIL if info.temp > self.checker.config['thresholds']['temp_warning'] else Colors.OKGREEN
            print(f"   {Symbols.TEMP} Temperatur: {temp_color}{info.temp}°C{Colors.ENDC}")
        
        # Speicherplatz
        if info.usage is not None:
            cfg = self.checker.config['thresholds']
            usage_color = Colors.FAIL if info.usage >= cfg['usage_warning'] else Colors.WARNING if info.usage >= cfg['usage_info'] else Colors.OKGREEN
            print(f"   {Symbols.DISK} Belegung: {usage_color}{info.usage}%{Colors.ENDC}")
            
            # Mount Points Details
            max_shown = self.checker.config['output']['max_mount_points_shown']
            for mp in info.mount_points[:max_shown]:
                print(f"      └─ {mp['mountpoint']}: {mp['usage']}% ({mp['used']}/{mp['total']})")
        
        # I/O Stats (wenn aktiviert)
        if info.io_stats and self.checker.config['output']['show_io_stats']:
            print(f"   {Symbols.CLOCK} I/O: {info.io_stats['read_ios']:,} reads, {info.io_stats['write_ios']:,} writes")
        
        # Scan-Zeit (im Debug-Modus)
        if self.args and self.args.debug:
            print(f"   Scan time: {info.scan_time:.2f}s")
        
        # Probleme
        if info.issues:
            print(f"   {Symbols.WARNING} Gefundene Probleme:")
            for severity, issue in info.issues:
                if severity == 'CRITICAL':
                    print(f"      {Colors.FAIL}• {issue}{Colors.ENDC}")
                elif severity == 'WARNING':
                    print(f"      {Colors.WARNING}• {issue}{Colors.ENDC}")
                else:
                    print(f"      {Colors.OKCYAN}• {issue}{Colors.ENDC}")
        
        print()
    
    def _print_recommendations(self, disk_infos):
        """Gibt Empfehlungen basierend auf den Ergebnissen aus"""
        print(f"{Colors.BOLD}\n{Symbols.INFO} Empfehlungen:{Colors.ENDC}\n")
        
        critical_disks = []
        warning_disks = []
        
        for info in disk_infos:
            if info.score >= 500:
                critical_disks.append(info)
            elif info.score >= 100:
                warning_disks.append(info)
        
        if critical_disks:
            print(f"{Colors.FAIL}{Colors.BOLD}KRITISCH - Sofortiges Handeln erforderlich:{Colors.ENDC}")
            for disk in critical_disks:
                print(f"  {Colors.FAIL}• /dev/{disk.name}:{Colors.ENDC}")
                if disk.smart_health == 'FAILED':
                    print(f"    → SOFORT Backup erstellen! Laufwerk steht vor dem Ausfall!")
                if disk.usage and disk.usage >= self.checker.config['thresholds']['usage_critical']:
                    print(f"    → Dringend Speicherplatz freigeben oder Daten auslagern!")
                if disk.temp and disk.temp > self.checker.config['thresholds']['temp_critical']:
                    print(f"    → Kühlung überprüfen! Laufwerk überhitzt!")
            print()
        
        if warning_disks:
            print(f"{Colors.WARNING}{Colors.BOLD}WARNUNG - Aufmerksamkeit erforderlich:{Colors.ENDC}")
            for disk in warning_disks:
                print(f"  {Colors.WARNING}• /dev/{disk.name}:{Colors.ENDC}")
                for severity, issue in disk.issues:
                    if severity == 'WARNING':
                        print(f"    → {issue}")
            print()
        
        # Tool-Verfügbarkeit
        missing_tools = []
        for tool in ['smartctl']:
            if not self.checker.tool_manager.get_tool_path(tool):
                missing_tools.append(tool)
        
        if missing_tools and not self.args.quiet:
            print(f"{Colors.WARNING}{Colors.BOLD}Fehlende optionale Tools:{Colors.ENDC}")
            print(f"  Für erweiterte Funktionen installieren:")
            if 'smartctl' in missing_tools:
                print(f"    {Colors.OKGREEN}sudo apt install smartmontools{Colors.ENDC} (für SMART-Tests)")
            print()
        
        # Allgemeine Empfehlungen
        if not self.checker.is_root() and not self.args.quiet:
            print(f"{Colors.OKCYAN}{Colors.BOLD}Hinweis:{Colors.ENDC}")
            print(f"  • Für vollständige SMART-Tests das Script mit sudo ausführen:")
            print(f"    {Colors.OKGREEN}sudo {' '.join(sys.argv)}{Colors.ENDC}")
            print()
        
        # Wartungsempfehlungen
        if not self.args.check_only:
            print(f"{Colors.OKBLUE}{Colors.BOLD}Regelmäßige Wartung:{Colors.ENDC}")
            print(f"  • Führen Sie diesen Check monatlich durch")
            print(f"  • Erstellen Sie regelmäßige Backups wichtiger Daten")
            print(f"  • Überwachen Sie die Temperatur bei hoher Auslastung")
            print(f"  • Halten Sie mindestens 10-20% freien Speicherplatz")
    
    def _print_summary(self, disk_infos):
        """Zusammenfassung"""
        print(f"\n{Colors.BOLD}{'═' * 60}{Colors.ENDC}")
        critical_count = sum(1 for d in disk_infos if d.score >= 500)
        warning_count = sum(1 for d in disk_infos if 100 <= d.score < 500)
        ok_count = sum(1 for d in disk_infos if d.score < 100)
        
        print(f"{Colors.BOLD}Zusammenfassung:{Colors.ENDC}")
        print(f"  {Colors.FAIL if critical_count else Colors.OKGREEN}• Kritisch: {critical_count}{Colors.ENDC}")
        print(f"  {Colors.WARNING if warning_count else Colors.OKGREEN}• Warnung:  {warning_count}{Colors.ENDC}")
        print(f"  {Colors.OKGREEN}• OK:       {ok_count}{Colors.ENDC}")
        
        total_scan_time = sum(d.scan_time for d in disk_infos)
        print(f"\nGesamte Scan-Zeit: {total_scan_time:.2f}s")
        print(f"{Colors.BOLD}{'═' * 60}{Colors.ENDC}\n")

def load_config(config_file):
    """Lädt Konfiguration aus YAML-Datei"""
    if not config_file or not Path(config_file).exists():
        return DEFAULT_CONFIG
    
    try:
        with open(config_file, 'r') as f:
            user_config = yaml.safe_load(f)
        
        # Merge mit Default-Config
        config = DEFAULT_CONFIG.copy()
        for key in user_config:
            if key in config and isinstance(config[key], dict):
                config[key].update(user_config[key])
            else:
                config[key] = user_config[key]
        
        return config
    except Exception as e:
        logging.warning(f"Failed to load config file {config_file}: {e}")
        return DEFAULT_CONFIG

def create_sample_config():
    """Erstellt eine Beispiel-Konfigurationsdatei"""
    sample_file = "disk_health_checker.yaml"
    with open(sample_file, 'w') as f:
        yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
    print(f"Sample configuration file created: {sample_file}")

def main():
    """Hauptfunktion"""
    parser = argparse.ArgumentParser(
        description='Linux Disk Health Checker - Umfassendes Tool zur Überprüfung der Laufwerksgesundheit',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s                     # Standard-Analyse mit farbiger Ausgabe
  %(prog)s --json              # JSON-Ausgabe für Monitoring-Tools
  %(prog)s --check-only        # Nur prüfen, keine Empfehlungen
  %(prog)s --smart-only        # Nur SMART-Tests ausführen
  %(prog)s --config my.yaml    # Mit eigener Konfiguration
  %(prog)s --create-config     # Beispiel-Konfiguration erstellen
  
Für vollständige SMART-Analysen mit sudo ausführen:
  sudo %(prog)s

Für Cronjobs vollständigen Pfad verwenden:
  /usr/local/bin/%(prog)s --json
        """
    )
    
    # Ausgabeoptionen
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument('--json', action='store_true',
                            help='JSON-Ausgabe für maschinelle Verarbeitung')
    output_group.add_argument('--plain', action='store_true',
                            help='Einfache Textausgabe ohne Farben/Symbole')
    
    # Analyse-Optionen
    parser.add_argument('--smart-only', action='store_true',
                       help='Nur SMART-Tests durchführen')
    parser.add_argument('--usage-only', action='store_true',
                       help='Nur Speicherbelegung prüfen')
    parser.add_argument('--check-only', action='store_true',
                       help='Nur Prüfung, keine Empfehlungen ausgeben')
    
    # Performance-Optionen
    parser.add_argument('--parallel', type=int, metavar='N',
                       help='Anzahl paralleler Worker (Standard: 4)')
    parser.add_argument('--timeout', type=int, metavar='SEC',
                       help='Timeout für Befehle in Sekunden (Standard: 10)')
    
    # Konfiguration
    parser.add_argument('--config', metavar='FILE',
                       help='Konfigurationsdatei (YAML)')
    parser.add_argument('--create-config', action='store_true',
                       help='Beispiel-Konfigurationsdatei erstellen')
    
    # Debug/Logging
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Ausführliche Ausgabe')
    parser.add_argument('-d', '--debug', action='store_true',
                       help='Debug-Ausgabe mit allen Details')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Minimale Ausgabe')
    
    # Version
    parser.add_argument('--version', action='version',
                       version=f'%(prog)s {__version__}')
    
    args = parser.parse_args()
    
    # Beispiel-Config erstellen
    if args.create_config:
        create_sample_config()
        return 0
    
    # Konfiguration laden
    config = load_config(args.config)
    
    # Performance-Parameter überschreiben
    if args.parallel:
        config['performance']['max_workers'] = args.parallel
    if args.timeout:
        config['performance']['command_timeout'] = args.timeout
    
    # Farben/Symbole deaktivieren für plain/json
    if args.plain or args.json:
        Colors.disable()
        Symbols.disable()
    
    # Checker initialisieren
    checker = DiskHealthChecker(config, args)
    formatter = OutputFormatter(checker, args)
    
    try:
        # Dependencies prüfen
        missing, optional = checker.check_dependencies()
        if missing:
            print(f"{Colors.FAIL}Fehlende erforderliche Tools: {', '.join(missing)}{Colors.ENDC}")
            print("Bitte installieren Sie die fehlenden Tools und versuchen Sie es erneut.")
            return 1
        
        if optional and not args.quiet:
            print(f"{Colors.WARNING}Optionale Tools nicht gefunden: {', '.join(optional)}{Colors.ENDC}")
            print(f"Für vollständige Funktionalität installieren:")
            if 'smartctl' in optional:
                print(f"  {Colors.OKGREEN}sudo apt install smartmontools{Colors.ENDC} (Debian/Ubuntu)")
                print(f"  {Colors.OKGREEN}sudo yum install smartmontools{Colors.ENDC} (RedHat/CentOS)")
            print()
        
        if not args.json and not args.quiet:
            formatter._print_header()
            print(f"{Colors.BOLD}Suche Laufwerke...{Colors.ENDC}")
        
        # Laufwerke finden
        disks = checker.list_disks()
        if not disks:
            print(f"{Colors.FAIL}Keine physischen Laufwerke gefunden!{Colors.ENDC}")
            return 1
        
        if not args.json and not args.quiet:
            print(f"Gefunden: {len(disks)} Laufwerk(e)")
            print(f"\n{Colors.BOLD}Analysiere Laufwerke", end='', flush=True)
        
        # Analysieren
        disk_infos = checker.analyze_all_disks(disks)
        
        if not args.json and not args.quiet:
            print(f" {Colors.OKGREEN}✓{Colors.ENDC}")
        
        # Ausgabe
        if args.json:
            formatter.format_json(disk_infos)
        elif args.plain:
            formatter.format_plain(disk_infos)
        else:
            formatter.format_console(disk_infos)
        
        # Exit-Code basierend auf kritischen Laufwerken
        critical_count = sum(1 for d in disk_infos if d.score >= 500)
        return 2 if critical_count > 0 else 0
        
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Abgebrochen.{Colors.ENDC}")
        return 130
    except Exception as e:
        if args.debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"\n{Colors.FAIL}Fehler: {e}{Colors.ENDC}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
