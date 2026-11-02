"""Copy a sanitized local DB snapshot without starting or writing to the backend."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'backend' / '.runtime'
TARGET = ROOT / 'frontend' / 'src' / 'prototype'
HIDDEN = {'originalPath', 'path', 'filePath', 'storagePath', 'encrypted', 'secret',
          'apiKey', 'api_key', 'accessId', 'accessSecret', 'password', 'oldPassword',
          'owner', 'sha256', 'draftSourceSha256', 'pendingOriginal', 'pendingIndex',
          'publishedIndexVersion', 'publishedCollection', 'vectorCollection',
          'versionHistory', 'originalUrl', 'assetUrl'}


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in HIDDEN and not k.startswith('_')}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def fingerprint():
    db_path = DATA / 'knowledge.db'
    if not db_path.exists():
        raise SystemExit('没有现有本地数据库；请先确认数据位置，不创建或覆盖数据库。')
    # URI mode=ro includes committed WAL contents; never use the application's
    # startup/state endpoints, which may migrate or prune records.
    with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT kind,id,payload FROM entities ORDER BY kind,id').fetchall()
        credentials = db.execute('SELECT id,encrypted FROM credentials ORDER BY id').fetchall()
    digest = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    originals = {}
    for path in sorted((DATA / 'originals').rglob('*')):
        if path.is_file():
            checksum = hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    checksum.update(block)
            originals[str(path.relative_to(DATA / 'originals'))] = checksum.hexdigest()
    return rows, {'entitiesSha256': digest(rows), 'credentialsSha256': digest(credentials), 'originals': originals}


def capture():
    rows, manifest = fingerprint()
    kinds = {}
    for kind, _, payload in rows:
        kinds.setdefault(kind, []).append(json.loads(payload))
    settings = next((r for r in kinds.get('setting', []) if r.get('id') == 'system'), {})
    snapshot = {'kbs': clean(kinds.get('kb', [])), 'docs': clean(kinds.get('doc', [])),
                'tasks': clean(kinds.get('task', [])), 'models': clean(kinds.get('model', [])),
                'connections': clean(kinds.get('connection', [])), 'settings': clean(settings),
                'applications': clean(kinds.get('application', [])),
                'sessions': [], 'logs': [], 'applicationRuns': [],
                'snapshotInfo': {'capturedOn': '2026-10-28', 'mode': 'local-prototype-copy'}}
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / 'baseline.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    (TARGET / 'preservation.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'knowledgeBases': len(snapshot['kbs']), 'documents': len(snapshot['docs']),
                      'applications': len(snapshot['applications']), 'mode': 'read-only snapshot'}, ensure_ascii=False))


if __name__ == '__main__':
    import sys
    if '--verify' in sys.argv:
        _, current = fingerprint()
        expected = json.loads((TARGET / 'preservation.json').read_text())
        if current != expected:
            raise SystemExit('资料指纹发生变化，请检查；脚本没有写入后台。')
        print('已核对：真实业务记录、加密凭证和原件内容均未改变。')
    else:
        if (TARGET / 'baseline.json').exists():
            raise SystemExit('原型快照已存在，不自动覆盖。需要重新取样时请先保存当前原型并明确替换快照。')
        capture()
