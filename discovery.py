"""Bounded discovery of this game's HTTP receiver on local IPv4 networks."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import urllib.request

PORT = 8765
SETTINGS = Path(__file__).resolve().parent / '.local' / 'connection.json'


def normalize_host(value):
    value = value.strip()
    if not value or any(c in value for c in '/@?#'):
        raise ValueError('請輸入 IP 或主機名稱，不需要 http:// 或 port')
    if ':' not in value:
        return f'{value}:{PORT}'
    host, port = value.rsplit(':', 1)
    if not host or port != str(PORT):
        raise ValueError('遊戲使用固定連接埠 8765，只需輸入 IP')
    return value


def last_host():
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8')).get('host', '')
    except (OSError, ValueError, AttributeError):
        return ''


def remember(host):
    SETTINGS.parent.mkdir(exist_ok=True)
    SETTINGS.write_text(json.dumps({'host': host}), encoding='utf-8')


def local_networks():
    command = "Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command', command],
                                capture_output=True, text=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        rows = json.loads(result.stdout)
        if isinstance(rows, dict):
            rows = [rows]
        return [(r['IPAddress'], int(r['PrefixLength'])) for r in rows]
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        try:
            return [(a, 24) for a in socket.gethostbyname_ex(socket.gethostname())[2]]
        except OSError:
            return []


def candidates(networks):
    result = set()
    for address, prefix in networks:
        try:
            ip = ipaddress.IPv4Address(address)
            if not ip.is_private or ip.is_loopback or ip.is_link_local:
                continue
            # Never sweep large corporate ranges: cap each adapter at its local /24.
            network = ipaddress.ip_network(f'{address}/{max(24, prefix)}', strict=False)
            result.update(str(h) for h in network.hosts() if h != ip)
        except ValueError:
            continue
        if len(result) >= 1024:
            break
    return sorted(result, key=ipaddress.IPv4Address)[:1024]


def probe(host):
    try:
        endpoint = normalize_host(host)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://{endpoint}/health', timeout=.7) as response:
            body = json.loads(response.read(2048))
        if (body.get('service') != 'uno-q-reaction' or body.get('version') != 7
                or body.get('mcu_ready') is not True or not isinstance(body.get('board_id'), str)):
            return None
        return {'host': endpoint, 'board_id': body['board_id']}
    except (OSError, ValueError, AttributeError):
        return None


def discover(preferred=''):
    # A verified saved device is intentional, and avoids a scan on later launches.
    for host in dict.fromkeys(filter(None, [preferred, last_host(), '192.168.7.2'])):
        found = probe(host)
        if found:
            return [found]
    found = {}
    with ThreadPoolExecutor(max_workers=48) as pool:
        futures = [pool.submit(probe, host) for host in candidates(local_networks())]
        for future in as_completed(futures):
            item = future.result()
            if item:
                found.setdefault(item['board_id'], item)
    return sorted(found.values(), key=lambda item: item['host'])
