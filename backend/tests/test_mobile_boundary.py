import pytest
from app.mobile_boundary import mobile_host
from test_pilot_foundation import env,PASS
from fastapi.testclient import TestClient

def test_mobile_scope_rejects_normal_data_and_public_hosts(tmp_path):
 assert mobile_host(tmp_path,None) is None
 for host in ['0.0.0.0','8.8.8.8','127.0.0.1','::1','192.168.1.64']:
  with pytest.raises(ValueError):mobile_host(tmp_path,host)

def test_https_session_cookie_is_secure(env):
 app,_=env
 with TestClient(app,base_url='https://127.0.0.1') as c:
  r=c.post('/api/auth/login',json={'username':'admin','password':PASS});assert r.status_code==200
  assert 'Secure' in r.headers['set-cookie'] and 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
