"""Project-installed skill capabilities, adapted to the business data model."""
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Literal
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
import httpx
from pydantic import BaseModel, Field

from .config import config
from .db import db_session, get_entity, list_entities, put_entity
from .security import Actor, require_manager
from .rag import RetrievalBody, retrieve_sync

router = APIRouter(prefix='/rag-workbench', dependencies=[Depends(require_manager)])
PROJECT = Path(__file__).resolve().parents[2]


def corpus(kb_id):
    with db_session() as db:
        kb = dict(get_entity(db, 'kb', kb_id).payload)
        docs = [dict(r.payload) for r in list_entities(db, 'doc', parent_id=kb_id)]
    return kb, docs


def published(docs):
    return sorted([d for d in docs if d.get('status') == 'ready' and d.get('chunks')], key=lambda d: d['id'])


def local_documents(docs, include_drafts=False):
    result = published(docs)
    if include_drafts:
        result += [{**d, '_localDraft': True, 'originalPath': (d.get('pendingOriginal') or d).get('originalPath'),
                    'chunks': d.get('draftChunks') or d.get('chunks')}
                   for d in docs if d.get('status') == 'review' and (d.get('draftChunks') or d.get('chunks'))]
    return sorted(result, key=lambda d: d['id'])


def markdown(doc):
    original_url = f"/api/documents/{doc['id']}/original" + ('' if doc.get('_localDraft') else f"?version={doc.get('version', 1)}")
    meta = {'title': doc['name'], 'doc_id': doc['id'], 'version': doc.get('version', 1),
            'source': original_url, 'draft': bool(doc.get('_localDraft')),
            'warnings': doc.get('warnings', []), 'converted_by': 'zhixu-parsed-snapshot'}
    # JSON is valid YAML; scalar escaping also prevents frontmatter injection.
    return '---\n' + '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in meta.items()) + '\n---\n\n' + '\n\n'.join(
        f"## {c.get('title', '正文')}\n\n> 来源位置：{c.get('location', '')}\n\n{c['content']}" for c in doc['chunks'])


def snapshot(docs):
    return hashlib.sha256(json.dumps([(d['id'], markdown(d)) for d in docs], ensure_ascii=False).encode()).hexdigest()


async def bridge(path, body=None):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600 if body is not None else 3, connect=3), trust_env=False) as client:
            if body is None:
                response = await client.get('http://127.0.0.1:8011/health')
            else:
                key = (config.data_dir / 'knowledge-rag/bridge.key').read_text().strip()
                response = await client.post('http://127.0.0.1:8011' + path, json=body, headers={'Authorization': 'Bearer ' + key})
        if response.status_code != 200:
            raise HTTPException(502, '本地引擎执行失败，请检查本地引擎日志')
        return response.json()
    except (OSError, httpx.HTTPError):
        raise HTTPException(503, '本地引擎尚未启动或请求超时，请运行 scripts/start-rag-engine.sh') from None


@router.get('/capabilities')
async def capabilities():
    manifest = json.loads((PROJECT / 'integrations/sources.lock.json').read_text())
    try:
        health = await bridge('/health')
    except HTTPException as exc:
        health = {'status': 'unavailable', 'detail': exc.detail}
    return {'sources': manifest, 'engine': health,
            'notice': '技能已安装在项目 .agents/skills；产品功能由适配接口执行，技能文本不会作为任意代码运行。'}


@router.get('/knowledge-bases/{kb_id}/audit')
def audit(kb_id: str):
    kb, docs = corpus(kb_id)
    issues = []
    hashes = {}
    for doc in docs:
        if doc.get('status') != 'ready':
            issues.append({'docId': doc['id'], 'name': doc['name'], 'problem': '尚未发布，当前状态：' + str(doc.get('status', '未知'))})
        chunks = doc.get('chunks') or doc.get('draftChunks') or []
        if not chunks:
            issues.append({'docId': doc['id'], 'name': doc['name'], 'problem': '没有可用知识片段'})
        for chunk in chunks:
            if not str(chunk.get('content', '')).strip():
                issues.append({'docId': doc['id'], 'name': doc['name'], 'problem': '存在空片段'})
            if not chunk.get('location'):
                issues.append({'docId': doc['id'], 'name': doc['name'], 'problem': '片段缺少来源位置'})
        for warning in doc.get('warnings', []):
            issues.append({'docId': doc['id'], 'name': doc['name'], 'problem': warning})
        digest = doc.get('sha256')
        if digest and digest in hashes:
            issues.append({'docId': doc['id'], 'name': doc['name'], 'problem': '原件内容与另一份文档重复'})
        hashes[digest] = doc['id']
    return {'kbId': kb_id, 'documentCount': len(docs), 'publishedCount': len(published(docs)),
            'chunkCount': sum(len(d.get('chunks', [])) for d in published(docs)), 'issues': issues,
            'embeddingConfigId': kb.get('embeddingConfigId') or kb.get('embedding'),
            'checks': ['空内容', '来源位置', '原件去重', '解析警告', '发布状态']}


@router.get('/knowledge-bases/{kb_id}/vault.zip')
def export_vault(kb_id: str):
    kb, docs = corpus(kb_id)
    docs = published(docs)
    if not docs:
        raise HTTPException(409, '没有已发布的文档可导出')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        index = [f"# {kb['name']}\n", '从已发布片段生成；原件链接需在中台登录后访问。\n']
        for doc in docs:
            name = hashlib.sha256(doc['id'].encode()).hexdigest() + '.md'
            archive.writestr('documents/' + name, markdown(doc))
            index.append(f"- [{doc['name']}](documents/{name})")
        archive.writestr('index.md', '\n'.join(index))
        archive.writestr('manifest.json', json.dumps({'kbId': kb_id, 'snapshot': snapshot(docs), 'documents': len(docs)}, indent=2))
    return Response(out.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="knowledge-vault.zip"'})


@router.post('/knowledge-bases/{kb_id}/local-index')
async def local_index(kb_id: str, include_drafts: bool = False):
    _, docs = corpus(kb_id)
    docs = local_documents(docs, include_drafts)
    if not docs or len(docs) > 200:
        raise HTTPException(409, '本地引擎同步需要 1–200 份已发布文档')
    fingerprint = snapshot(docs)
    result = await bridge('/sync', {'snapshot': fingerprint, 'documents': [
        {'key': hashlib.sha256(d['id'].encode()).hexdigest(), 'content': markdown(d)} for d in docs]})
    # Publish the pointer only when the complete snapshot was indexed.
    with db_session() as db:
        put_entity(db, 'local-index', {'id': kb_id + (':drafts' if include_drafts else ''), 'snapshot': fingerprint,
                                    'updatedAt': datetime.now(timezone.utc).isoformat()})
    return {**result, 'snapshot': fingerprint}


class LocalSearchBody(RetrievalBody):
    includeDrafts: bool = False


@router.post('/knowledge-bases/{kb_id}/local-search')
async def local_search(kb_id: str, body: LocalSearchBody):
    _, docs = corpus(kb_id)
    docs = local_documents(docs, body.includeDrafts)
    fingerprint = snapshot(docs)
    with db_session() as db:
        pointer = get_entity(db, 'local-index', kb_id + (':drafts' if body.includeDrafts else ''), False)
        if not pointer or pointer.payload['snapshot'] != fingerprint:
            raise HTTPException(409, '知识库已更新或尚未同步，请先同步本地索引')
    result = await bridge('/search', {'snapshot': fingerprint, 'query': body.query, 'topK': body.topK})
    allowed = {hashlib.sha256(d['id'].encode()).hexdigest(): d for d in docs}
    # Re-check SQL after the long-running request: disabled/deleted material must not leak.
    _, current = corpus(kb_id)
    if snapshot(local_documents(current, body.includeDrafts)) != fingerprint:
        raise HTTPException(409, '检索期间知识库已更新，请重新同步索引')
    rows = []
    for hit in result.get('results', []):
        doc = allowed.get(Path(hit.get('source', '')).stem)
        if doc:
            rows.append({'docId': doc['id'], 'name': doc['name'], 'version': doc.get('version', 1),
                         'content': hit.get('content', ''), 'score': hit.get('score'),
                         'draft': bool(doc.get('_localDraft')),
                         'originalUrl': f"/api/documents/{doc['id']}/original" + ('' if doc.get('_localDraft') else f"?version={doc.get('version', 1)}")})
    return {'results': rows, 'engine': 'lyonzin/knowledge-rag', 'snapshot': fingerprint, 'includesDrafts': body.includeDrafts}


class EvalCase(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    expectedDocIds: list[str] = Field(min_length=1, max_length=50)
    answer: str = Field(default='', max_length=10000)


class EvalBody(BaseModel):
    cases: list[EvalCase] = Field(min_length=1, max_length=100)
    topK: int = Field(default=5, ge=1, le=20)
    mode: Literal['keyword', 'hybrid', 'semantic'] = 'keyword'
    rerank: bool = False
    engine: Literal['platform', 'local'] = 'platform'
    includeDrafts: bool = False


def metrics(sources, expected, k):
    expected = set(expected)
    seen = set()
    ranks = []
    for rank, source in enumerate(sources[:k], 1):
        doc_id = source['docId']
        if doc_id in expected and doc_id not in seen:
            ranks.append(rank)
        seen.add(doc_id)
    dcg = sum(1 / math.log2(r + 1) for r in ranks)
    ideal = sum(1 / math.log2(r + 1) for r in range(1, min(k, len(expected)) + 1))
    return {'hit': int(bool(ranks)), 'recall': len(ranks) / len(expected),
            'mrr': 1 / ranks[0] if ranks else 0, 'ndcg': dcg / ideal if ideal else 0}


@router.post('/knowledge-bases/{kb_id}/evaluations')
async def evaluate(kb_id: str, body: EvalBody, actor: Actor = Depends(require_manager)):
    _, docs = corpus(kb_id)
    docs = local_documents(docs, body.includeDrafts) if body.engine == 'local' else published(docs)
    allowed = {d['id'] for d in docs}
    if any(not set(c.expectedDocIds) <= allowed for c in body.cases):
        raise HTTPException(422, '参考文档必须是当前知识库中已发布的文档')
    fingerprint = snapshot(docs)
    if body.engine == 'local':
        with db_session() as db:
            pointer = get_entity(db, 'local-index', kb_id + (':drafts' if body.includeDrafts else ''), False)
            if not pointer or pointer.payload['snapshot'] != fingerprint:
                raise HTTPException(409, '请先在本地检索引擎中同步相同范围的资料')
    rows = []
    for case in body.cases:
        try:
            if body.engine == 'local':
                local = await local_search(kb_id, LocalSearchBody(query=case.query, topK=body.topK, includeDrafts=body.includeDrafts))
                result = {'sources': local['results'], 'steps': [{'name': '本地中文检索', 'model': 'BAAI/bge-small-zh-v1.5', 'meter': 'local'}], 'degraded': False}
            else:
                result = await asyncio.to_thread(retrieve_sync, [kb_id], case.query,
                    RetrievalBody(query=case.query, topK=body.topK, mode=body.mode, rerank=body.rerank, minScore=0))
            rows.append({**case.model_dump(), 'status': 'success', **metrics(result['sources'], case.expectedDocIds, body.topK),
                         'retrievedDocIds': [s['docId'] for s in result['sources']], 'steps': result['steps'], 'degraded': result['degraded']})
        except HTTPException as exc:
            rows.append({**case.model_dump(), 'status': 'failed', 'error': str(exc.detail)})
        except Exception:
            rows.append({**case.model_dump(), 'status': 'failed', 'error': '检索执行失败'})
    _, after = corpus(kb_id)
    stable = snapshot(local_documents(after, body.includeDrafts) if body.engine == 'local' else published(after)) == fingerprint
    good = [r for r in rows if r['status'] == 'success']
    report = {'id': 'eval-' + uuid.uuid4().hex, 'kbId': kb_id, 'createdAt': datetime.now(timezone.utc).isoformat(),
              'status': 'success' if len(good) == len(rows) and stable else 'incomplete',
              'snapshot': fingerprint, 'corpusStable': stable, 'options': body.model_dump(exclude={'cases'}),
              'total': len(rows), 'completed': len(good), 'rows': rows,
              'summary': {m: sum(r[m] for r in good) / len(good) if good and stable else None for m in ('hit', 'recall', 'mrr', 'ndcg')},
              'metricScope': 'Top K 个返回片段；相关性按参考文档判断，同文档重复片段不重复计分；聚合仅含成功执行项。',
              'judge': '未执行 LLM/RAGAS 答案评审，不能据此判断忠实度或答案正确性。'}
    with db_session() as db:
        put_entity(db, 'rag-evaluation', report, owner=actor.owner, parent_id=kb_id)
    return report


@router.get('/knowledge-bases/{kb_id}/evaluations')
def reports(kb_id: str):
    corpus(kb_id)
    with db_session() as db:
        return [r.payload for r in list_entities(db, 'rag-evaluation', parent_id=kb_id)][:50]


@router.get('/knowledge-bases/{kb_id}/evaluations/{report_id}/nvidia.zip')
def nvidia_bundle(kb_id: str, report_id: str):
    _, docs = corpus(kb_id)
    with db_session() as db:
        row = get_entity(db, 'rag-evaluation', report_id)
        if row.parent_id != kb_id:
            raise HTTPException(404, '评测记录不存在')
        report = dict(row.payload)
    options = report.get('options', {})
    docs = local_documents(docs, options.get('includeDrafts', False)) if options.get('engine') == 'local' else published(docs)
    if snapshot(docs) != report['snapshot']:
        raise HTTPException(409, '语料已变化，请重新评测后导出')
    if any(not r.get('answer', '').strip() for r in report['rows']):
        raise HTTPException(422, 'NVIDIA 评测需要每条用例填写人工核实的参考答案 answer，请补齐后重新评测')
    out = io.BytesIO()
    names = {}
    size = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for doc in docs:
            original = Path(doc.get('originalPath', '')).resolve()
            root = (config.data_dir / 'originals').resolve()
            if root not in original.parents or not original.is_file():
                raise HTTPException(409, '原件不可用；为避免丢失图片或表格，未用文字快照代替原件')
            size += original.stat().st_size
            if size > 100 * 1024 * 1024:
                raise HTTPException(413, '导出原件超过 100MB，请拆分知识库')
            name = hashlib.sha256(doc['id'].encode()).hexdigest() + original.suffix
            names[doc['id']] = name
            archive.write(original, 'corpus/' + name)
        train = [{'id': i, 'question': r['query'], 'answer': r['answer'], 'is_impossible': False,
                  'contexts': [{'filename': names[d]} for d in dict.fromkeys(r['expectedDocIds'])]}
                 for i, r in enumerate(report['rows'])]
        archive.writestr('train.json', json.dumps(train, ensure_ascii=False, indent=2))
        archive.writestr('README.md', '# NVIDIA RAG 评测数据包\n\n包含原件 corpus/ 和人工参考答案 train.json。\n'
                         '需要另行部署 NVIDIA RAG Blueprint、安装其 scripts/eval 依赖并配置 NVIDIA_API_KEY；本导出不代表已运行 RAGAS。\n'
                         '按原件类型配置 --file-type；混合格式需按上游 ingest 支持情况分组。\n')
    return Response(out.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="nvidia-rag-dataset.zip"'})
