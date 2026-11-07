"""Evaluation facts, release gate, actual node failures and authorization."""
from sqlalchemy import select
from test_pilot_foundation import env, grant, mutation
from test_unified_knowledge import knowledge, graph, ok
from app.knowledge_models import RuleRun, RuleApplication


def create(k, definition=None):
    a = ok(mutation(k[1], 'POST', k[-1] + '/applications', {'definition': definition or graph()}))
    return a, k[-1] + '/applications/' + a['id']


def body(revision=1, expected='核对'):
    return {'revision': revision, 'cases': [{'input': '材料', 'expectContains': expected}]}


def test_evaluation_persists_expected_actual_and_node_trace_without_publishing(knowledge):
    a, path = create(knowledge)
    report = ok(mutation(knowledge[1], 'POST', path + '/evaluate', body(expected='错误预期')))
    assert report['purpose'] == 'evaluation' and report['passed'] == 0 and report['total'] == 1
    assert report['application_revision'] == 1 and report['application_id'] == a['id']
    assert len(report['definition_sha256']) == 64 and report['model_enabled'] is False
    row = report['cases'][0]
    assert row['output_preview'] == '核对：材料' and not row['passed']
    assert [s['node_id'] for s in row['steps']] == ['start', 'text', 'out']
    assert ok(knowledge[1].get('/api' + knowledge[-1] + '/runs')) == [report]
    with knowledge[0].state.store.transaction() as db:
        assert db.get(RuleApplication, a['id']).published is None


def test_evaluation_idempotency_and_lost_response_recovery(knowledge):
    _, path = create(knowledge)
    first = ok(mutation(knowledge[1], 'POST', path + '/evaluate', body(), key='evaluation-recovery'))
    assert ok(mutation(knowledge[1], 'POST', path + '/evaluate', body(), key='evaluation-recovery')) == first
    assert ok(knowledge[1].get('/api/requests/evaluation-recovery'))['result'] == first
    assert mutation(knowledge[1], 'POST', path + '/evaluate', body(expected='other'), key='evaluation-recovery').status_code == 409
    with knowledge[0].state.store.transaction() as db:
        assert len(list(db.scalars(select(RuleRun)))) == 1


def test_empty_or_oversized_expectations_and_invalid_inputs_are_blocked(knowledge):
    _, path = create(knowledge)
    invalid = [[], [{'input': '', 'expectContains': 'x'}], [{'input': '材料'}],
               [{'input': '材料', 'expectContains': '   '}], [{'input': 'a'*2001, 'expectContains': 'a'}],
               [{'input': '材料', 'expectContains': 'x'*501}], [{'input': '材料', 'expectContains': 'x'}]*21]
    for cases in invalid:
        for action in ['evaluate', 'publish']:
            assert mutation(knowledge[1], 'POST', path + '/' + action, {'revision': 1, 'cases': cases}).status_code == 422


def test_saved_evaluation_does_not_authorize_new_draft_or_replace_published(knowledge):
    a, path = create(knowledge)
    ok(mutation(knowledge[1], 'POST', path + '/publish', body()))
    report = ok(mutation(knowledge[1], 'POST', path + '/evaluate', body()))
    ok(mutation(knowledge[1], 'PUT', path, {'definition': graph('新版：{{input}}'), 'revision': 1}))
    assert mutation(knowledge[1], 'POST', path + '/publish', body()).status_code == 409
    failed = mutation(knowledge[1], 'POST', path + '/publish', body(2))
    assert failed.status_code == 422 and failed.json()['error']['code'] == 'EVALUATION_FAILED'
    assert failed.json()['error']['field_errors'][0]['field'] == 'cases.0'
    assert ok(mutation(knowledge[4], 'POST', path + '/run', {'input': '材料'}))['output'] == '核对：材料'
    history = ok(knowledge[1].get('/api' + knowledge[-1] + '/runs'))
    assert next(x for x in history if x['id'] == report['id']) == report


def test_runtime_failure_reports_failed_node_and_unexecuted_downstream(knowledge):
    _, path = create(knowledge, graph('{{input}}'*60))
    report = ok(mutation(knowledge[1], 'POST', path + '/evaluate', {'revision': 1, 'cases': [{'input': '长'*2000, 'expectContains': '不会出现'}]}))
    row = report['cases'][0]
    assert not row['passed'] and row['actual_status'] == 'failed'
    assert row['steps'][1]['node_id'] == 'text' and row['steps'][1]['status'] == 'failed'
    assert '过长' in row['steps'][1]['error'] and row['steps'][2]['status'] == 'skipped'


def test_evaluation_private_history_and_recovered_result_recheck_acl(knowledge):
    _, admin, project, person, reader, library, base = knowledge
    _, path = create(knowledge)
    assert mutation(reader, 'POST', path + '/evaluate', body()).status_code == 403
    report = ok(mutation(admin, 'POST', path + '/evaluate', body(), key='private-report'))
    assert ok(reader.get('/api' + base + '/runs')) == []
    assert reader.get('/api/requests/private-report').status_code == 404
    ok(grant(admin, project, {'id': library['owner_id']}, ['管理员'], revision=1, active=False))
    assert admin.get('/api' + base + '/runs').status_code == 404
    assert admin.get('/api/requests/private-report').status_code == 404


def test_report_and_application_restore_in_full_maintenance_bundle(knowledge, tmp_path):
    import sqlite3
    from pathlib import Path
    from app.data_bundle import backup, restore
    app, _, _, _, _, _, _ = knowledge
    _, path = create(knowledge)
    report = ok(mutation(knowledge[1], 'POST', path + '/evaluate', body()))
    source = Path(app.state.store.engine.url.database).parent
    archive = tmp_path / 'evaluation-backup.zip'
    restored = tmp_path / 'evaluation-restored'
    backup(source, archive); restore(archive, restored)
    with sqlite3.connect(restored / 'pilot.db') as db:
        import json
        result = json.loads(db.execute('select result from knowledge_runs where id=?', (report['id'],)).fetchone()[0])
        assert result == report
