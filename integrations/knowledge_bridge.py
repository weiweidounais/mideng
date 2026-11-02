"""Loopback adapter for the isolated upstream knowledge-rag runtime.

One process owns ChromaDB; the business API remains the permission boundary.
"""
import json
import os
from pathlib import Path
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'backend/.runtime/knowledge-rag'
RUNTIME.mkdir(parents=True, exist_ok=True)
configuration = RUNTIME / 'config.yaml'
if not configuration.exists():
    configuration.write_text((ROOT / 'integrations/configs/knowledge-rag.yaml').read_text())
os.environ['KNOWLEDGE_RAG_DIR'] = str(RUNTIME)
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
KEY = RUNTIME / 'bridge.key'
if not KEY.exists():
    fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(32))
TOKEN = KEY.read_text().strip()
orch = None
operation_lock = threading.RLock()


def engine():
    global orch
    if orch is None:
        from mcp_server.server import KnowledgeOrchestrator
        orch = KnowledgeOrchestrator()
    return orch


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != '/health':
            return self.reply(404, {'detail': 'Not found'})
        self.reply(200, {'status': 'ok', 'engine': 'knowledge-rag', 'initialized': orch is not None,
                         'model': 'BAAI/bge-small-zh-v1.5', 'dimension': 512, 'reranker': False})

    def do_POST(self):
        if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            return self.reply(403, {'detail': 'Forbidden'})
        with operation_lock:
            self.execute()

    def execute(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 20 * 1024 * 1024:
                return self.reply(413, {'detail': 'Request too large'})
            body = json.loads(self.rfile.read(length))
            if self.path == '/embeddings':
                texts = body.get('input')
                if not isinstance(texts, list) or not 1 <= len(texts) <= 32 or any(not isinstance(t, str) or not t.strip() or len(t) > 50000 for t in texts):
                    return self.reply(422, {'detail': 'Invalid embedding input'})
                embed = engine().embed_fn
                vectors = embed.embed_query(texts) if body.get('query') else embed.embed_documents(texts)
                return self.reply(200, {'model': embed.model_name, 'data': [{'index': i, 'embedding': vector} for i, vector in enumerate(vectors)]})
            snapshot = body.get('snapshot', '')
            if not re.fullmatch('[a-f0-9]{64}', snapshot):
                return self.reply(422, {'detail': 'Invalid snapshot'})
            if self.path == '/sync':
                documents = body['documents']
                if not documents or len(documents) > 200:
                    return self.reply(422, {'detail': 'Invalid documents'})
                results = []
                for doc in documents:
                    if not re.fullmatch('[a-f0-9]{64}', doc['key']):
                        return self.reply(422, {'detail': 'Invalid key'})
                    result = engine().add_document_from_content(doc['content'], f"{snapshot}/{doc['key']}.md", snapshot)
                    if 'error' in result:
                        return self.reply(502, {'detail': 'Local indexing failed'})
                    results.append(result)
                return self.reply(200, {'indexedDocuments': len(results)})
            if self.path == '/search':
                query = str(body.get('query', '')).strip()
                if not query or len(query) > 2000:
                    return self.reply(422, {'detail': 'Invalid query'})
                results = engine().query(query, max_results=max(1, min(20, int(body.get('topK', 5)))),
                                         category_filter=snapshot, search_method='hybrid')
                return self.reply(200, {'results': results})
            self.reply(404, {'detail': 'Not found'})
        except Exception as exc:
            print('Bridge request failed:', type(exc).__name__, flush=True)
            self.reply(502, {'detail': '本地引擎执行失败，请查看服务日志；未返回模拟结果'})


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8011), Handler).serve_forever()
