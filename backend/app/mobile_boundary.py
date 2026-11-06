"""Opt-in host scope for the isolated, trace-only mobile rehearsal."""
import ipaddress
from pathlib import Path

def mobile_host(data:Path,value:str|None):
 if not value:return None
 ip=ipaddress.IPv4Address(value)
 if not any(ip in ipaddress.IPv4Network(n) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']):raise ValueError('手机入口须为指定可信局域网IPv4')
 expected=Path(__file__).resolve().parents[1]/'.runtime/mobile-qa'
 if data.resolve()!=expected.resolve() or not (data/'synthetic-only.marker').is_file():raise ValueError('手机入口仅限独立合成验收目录')
 return str(ip)
