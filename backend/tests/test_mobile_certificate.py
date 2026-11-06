"""A browser preconnect must not monopolize the public certificate download server."""
import importlib.util,socket,threading
from pathlib import Path
import httpx

spec=importlib.util.spec_from_file_location('mobile_certificate',Path(__file__).resolve().parents[2]/'scripts/mobile_certificate.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_idle_preconnect_does_not_block_certificate_and_private_paths_stay_closed(tmp_path):
    cert=tmp_path/'public-ca.cer';cert.write_bytes(b'synthetic-public-certificate')
    server=module.make_server('127.0.0.1',0,cert);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    idle=socket.create_connection(server.server_address,timeout=1)
    try:
        with httpx.Client(base_url='http://127.0.0.1:'+str(server.server_port),trust_env=False,timeout=1) as c:
            r=c.get('/public-ca.cer');assert r.status_code==200 and r.content==cert.read_bytes()
            assert 'attachment' in r.headers['content-disposition']
            h=c.head('/public-ca.cer');assert h.status_code==200 and h.content==b'' and int(h.headers['content-length'])==len(cert.read_bytes())
            for path in ['/','/server.key','/credentials.json']:assert c.get(path).status_code==404
    finally:idle.close();server.shutdown();server.server_close();thread.join(timeout=2)
