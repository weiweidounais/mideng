"""Question entry uses actual published text, project/space ACL, and no writes."""
from sqlalchemy import select
from test_pilot_foundation import env, add_project, grant, mutation
from test_unified_knowledge import knowledge, upload, ok
from app.knowledge_api import run_knowledge_job
from app.knowledge_models import KnowledgeDocument


def published(k, text, key='question-source'):
    app, admin, _, _, _, _, base = k
    d = ok(upload(k, key=key, raw=text.encode()))
    assert run_knowledge_job(app.state.store)
    d = ok(admin.get('/api' + base + '/documents/' + d['id']))
    return ok(mutation(admin, 'POST', base + '/documents/' + d['id'] + '/actions',
                       {'revision': d['revision'], 'action': 'publish'}))


def ask(k, query, reader=True, pid=None):
    _, admin, project, _, member, _, _ = k
    return mutation(member if reader else admin, 'POST',
                    '/projects/' + (pid or project['id']) + '/workspace/ask', {'query': query})


def test_question_returns_published_original_and_business_entries(knowledge):
    text = '# 材料到货验收\n质量人员核对材料到货数量后验收，再交商务归档。'
    document = published(knowledge, text)
    result = ok(ask(knowledge, '材料到货后怎么验收？'))
    assert result['mode'] == 'keyword' and result['model_enabled'] is False
    assert result['project_id'] == knowledge[2]['id']
    assert result['sources'] and all(s['content'] in text for s in result['sources'])
    assert result['sources'][0]['document_id'] == document['id']
    assert {e['section'] for e in result['entries']} == {'procurement', 'trace'}
    assert '未启用AI生成' in result['notice']


def test_private_and_unpublished_documents_never_enter_answer(knowledge):
    app, admin, _, _, _, library, base = knowledge
    published(knowledge, '采购共享资料')
    ok(upload(knowledge, key='queued-hidden', raw='采购待解析秘密'.encode()))
    result = ok(ask(knowledge, '采购'))
    assert all('秘密' not in source['content'] for source in result['sources'])
    ok(mutation(admin, 'PUT', base, {'name': library['name'], 'readers': [],
                                    'restricted': True, 'revision': library['revision']}))
    assert ok(ask(knowledge, '采购'))['sources'] == []
    assert ok(ask(knowledge, '采购', reader=False))['sources']


def test_withdraw_rechecks_publication_on_each_question(knowledge):
    document = published(knowledge, '采购撤回资料')
    assert ok(ask(knowledge, '采购'))['sources']
    ok(mutation(knowledge[1], 'POST', knowledge[-1] + '/documents/' + document['id'] + '/actions',
                {'revision': document['revision'], 'action': 'withdraw'}))
    assert ok(ask(knowledge, '采购'))['sources'] == []


def test_question_enforces_project_membership_and_revocation(knowledge):
    _, admin, project, person, _, _, _ = knowledge
    other = add_project(admin, 'OTHER-QUESTION')
    assert ask(knowledge, '采购', pid=other['id']).status_code == 404
    ok(grant(admin, project, person, ['采购'], revision=1, active=False))
    response = ask(knowledge, '采购')
    assert response.status_code == 404 and 'sources' not in response.json()


def test_financial_entry_depends_on_actual_project_role(knowledge):
    _, admin, project, person, _, _, _ = knowledge
    assert ok(ask(knowledge, '如何核对成本月结？'))['entries'] == []
    ok(grant(admin, project, person, ['项目经理'], revision=1))
    assert ok(ask(knowledge, '成本月结'))['entries'][0]['title'] == '已发布成本汇总'
    ok(grant(admin, project, person, ['财务'], revision=2))
    assert ok(ask(knowledge, '成本月结'))['entries'][0]['title'] == '成本与月结'


def test_no_match_is_explicit_and_questions_do_not_mutate_facts(knowledge):
    document = published(knowledge, '采购已发布资料')
    result = ok(ask(knowledge, '完全不存在的专属术语'))
    assert result['sources'] == [] and result['entries'] == []
    assert '未找到相关原文' in result['notice']
    with knowledge[0].state.store.transaction() as db:
        d = db.get(KnowledgeDocument, document['id'])
        assert d.state == 'published' and d.revision == document['revision']
        assert len(list(db.scalars(select(KnowledgeDocument)))) == 1


def test_question_validation_csrf_and_unknown_fields(knowledge):
    pid = knowledge[2]['id']
    for query in ['', '   ', '长' * 1001]:
        assert ask(knowledge, query).status_code == 422
    assert mutation(knowledge[1], 'POST', f'/projects/{pid}/workspace/ask',
                    {'query': '采购', 'model_enabled': True}).status_code == 422
    assert knowledge[4].post(f'/api/projects/{pid}/workspace/ask', json={'query': '采购'}).status_code == 403


def test_excerpt_is_bounded_and_remains_verbatim(knowledge):
    text = 'a' * 1800 + '采购需要核对原件' + 'b' * 1500
    published(knowledge, text)
    sources = ok(ask(knowledge, '采购'))['sources']
    assert sources
    assert all(len(source['content']) <= 1000 and source['content'] in text for source in sources)
    assert any(source['truncated'] for source in sources)
