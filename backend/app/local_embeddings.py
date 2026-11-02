"""Fixed-address adapter for the installed, authenticated local ONNX engine."""
import math
from pathlib import Path
import subprocess
import time

import httpx
from fastapi import HTTPException
from langchain_core.embeddings import Embeddings
from .config import config

PROVIDER = '本地 knowledge-rag'
MODEL = 'BAAI/bge-small-zh-v1.5'
BASE = 'http://127.0.0.1:8011'
_process = None


def start_installed_engine():
    global _process
    root = Path(__file__).resolve().parents[2]
    runtime = root / 'integrations/knowledge-rag-venv/bin/python'
    if config.task_mode != 'local' or not runtime.exists(): return
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            if client.get(BASE + '/health').json().get('engine') == 'knowledge-rag': return
    except (httpx.HTTPError, ValueError): pass
    log = config.data_dir / 'knowledge-rag/bridge.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as output:
        _process = subprocess.Popen([str(runtime), str(root / 'integrations/knowledge_bridge.py')], cwd=root, stdout=output, stderr=output)
    for _ in range(30):
        if _process.poll() is not None: break
        try:
            with httpx.Client(timeout=1, trust_env=False) as client:
                if client.get(BASE + '/health').is_success: return
        except httpx.HTTPError: pass
        time.sleep(.1)


def stop_owned_engine():
    global _process
    if _process and _process.poll() is None:
        _process.terminate()
        try: _process.wait(timeout=5)
        except subprocess.TimeoutExpired: _process.kill(); _process.wait()
    _process = None


class LocalEmbeddings(Embeddings):
    last_usage = None

    def _embed(self, texts, query=False):
        if not texts: return []
        key = config.data_dir / 'knowledge-rag/bridge.key'
        if not key.exists(): raise HTTPException(503, '本地向量引擎未安装或启动，请运行 scripts/start-rag-engine.sh')
        vectors = []
        try:
            with httpx.Client(timeout=120, trust_env=False, follow_redirects=False) as client:
                for offset in range(0, len(texts), 32):
                    batch = texts[offset:offset+32]
                    response = client.post(BASE + '/embeddings', headers={'Authorization': 'Bearer ' + key.read_text().strip()}, json={'input': batch, 'query': query})
                    response.raise_for_status()
                    data = response.json()
                    if data.get('model') != MODEL: raise ValueError()
                    rows = sorted(data['data'], key=lambda row: row['index'])
                    if [row['index'] for row in rows] != list(range(len(batch))): raise ValueError()
                    for row in rows:
                        v = row['embedding']
                        if len(v) != 512 or any(type(x) not in (int, float) or not math.isfinite(x) for x in v) or not any(v): raise ValueError()
                        vectors.append(v)
            return vectors
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise HTTPException(503, '本地向量引擎调用失败，请检查 8011 服务；未返回模拟向量') from None

    def embed_documents(self, texts): return self._embed(texts)
    def embed_query(self, text): return self._embed([text], query=True)[0]
