"""Prepare-only by default. Use start only AFTER explicit LAN/certificate approval."""
from pathlib import Path
import argparse,os,sys,json,subprocess,time,socket,signal,ipaddress,hashlib
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'backend/.runtime/mobile-qa';STATE=DATA/'preview-processes.json'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['plan','start','stop']);p.add_argument('--host');p.add_argument('--approved-lan-and-certificate',action='store_true');args=p.parse_args()
if args.action=='plan':
 print('仅预案：指定可信Wi-Fi IPv4:18412 HTTPS（合成管段库）；18413 HTTP仅提供公开CA证书。证书两天过期；不自动安装信任；关闭用stop；正常18410不变。');sys.exit()
if args.action=='stop':
 if not STATE.exists():print('没有本脚本登记的入口');sys.exit()
 state=json.loads(STATE.read_text())
 for item in state['processes']:
  try:cmd=subprocess.check_output(['ps','-p',str(item['pid']),'-o','command='],text=True)
  except subprocess.CalledProcessError:continue
  if item['identity'] not in cmd:raise SystemExit('进程身份已变化，未终止其他进程')
  os.kill(item['pid'],signal.SIGTERM)
 STATE.rename(DATA/('preview-stopped-'+str(int(time.time()))+'.json'));print('已停止登记入口；手机信任证书须由本人移除。');sys.exit()
if not args.approved_lan_and_certificate:raise SystemExit('尚未提供具体LAN/证书授权，不启动')
if not args.host:raise SystemExit('须指定本次获准的Wi-Fi IPv4')
sys.path.insert(0,str(ROOT/'backend'));from app.mobile_boundary import mobile_host
host=mobile_host(DATA,args.host)
if STATE.exists():raise SystemExit('已有登记入口；先核对状态，勿重复启动')
for port in [18412,18413]:
 with socket.socket() as s:s.bind((host,port))
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from datetime import datetime,timezone,timedelta
TLS=DATA/'tls';TLS.mkdir(mode=0o700,exist_ok=True);now=datetime.now(timezone.utc)
# A narrow, short-lived CA. No Keychain/system trust or external certificate service.
ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048);leaf_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Mideng Mobile QA temporary CA')]);leaf_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,host)])
ca=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True).add_extension(x509.NameConstraints([x509.IPAddress(ipaddress.ip_network(host+'/32')),x509.IPAddress(ipaddress.ip_network('127.0.0.1/32'))],None),critical=True).sign(ca_key,hashes.SHA256())
leaf=x509.CertificateBuilder().subject_name(leaf_name).issuer_name(name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host)),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(ca_key,hashes.SHA256())
for filename,raw in [('ca.pem',ca.public_bytes(serialization.Encoding.PEM)),('public-ca.cer',ca.public_bytes(serialization.Encoding.DER)),('server.pem',leaf.public_bytes(serialization.Encoding.PEM)),('server.key',leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:
 file=TLS/filename;file.write_bytes(raw);file.chmod(0o600)
# CA signing key is not persisted, only the leaf private key is retained locally.
env=os.environ.copy();env['PILOT_DATA_DIR']=str(DATA);env['PILOT_MOBILE_QA_HOST']=host
processes=[]
try:
 with (DATA/'preview.log').open('ab') as log:
  child=subprocess.Popen([str(ROOT/'backend/.venv/bin/python'),'-m','uvicorn','app.pilot:app','--host',host,'--port','18412','--ssl-keyfile',str(TLS/'server.key'),'--ssl-certfile',str(TLS/'server.pem'),'--no-access-log'],cwd=ROOT/'backend',env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True);processes.append({'pid':child.pid,'identity':'app.pilot:app --host '+host+' --port 18412'})
  boot=subprocess.Popen([str(ROOT/'backend/.venv/bin/python'),str(ROOT/'scripts/mobile_certificate.py'),'--host',host],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True);processes.append({'pid':boot.pid,'identity':'mobile_certificate.py --host '+host})
 import httpx,ssl
 context=ssl.create_default_context(cafile=str(TLS/'ca.pem'))
 for attempt in range(60):
  try:
   r=httpx.get('https://'+host+':18412/api/health',verify=context,trust_env=False,timeout=1);r.raise_for_status();break
  except httpx.HTTPError:
   if child.poll() is not None:raise RuntimeError('HTTPS进程退出，请查本地日志')
   time.sleep(.1)
 else:raise RuntimeError('HTTPS入口未就绪')
 STATE.write_text(json.dumps({'host':host,'processes':processes}));STATE.chmod(0o600)
 print({'https':'https://'+host+':18412/','public_certificate':'http://'+host+':18413/public-ca.cer','certificate_sha256':hashlib.sha256(ca.public_bytes(serialization.Encoding.DER)).hexdigest(),'expires':ca.not_valid_after_utc.isoformat()})
except BaseException:
 for item in processes:
  try:os.kill(item['pid'],signal.SIGTERM)
  except ProcessLookupError:pass
 raise
