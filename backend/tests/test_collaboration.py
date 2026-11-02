"""Pilot regression: authorization, concurrent edits, versioned handoff and export."""
from copy import deepcopy
from fastapi.testclient import TestClient
import pytest

from test_security import security_client, anonymous, login
from app.main import app
from app.db import db_session, get_entity, put_entity
from app.collaboration import KIND_REQ, KIND_IFACE, KIND_BOM, _save
from app.security import Actor


@pytest.fixture
def pilot(security_client):
    client, passwords = security_client
    headers = login(client, passwords)
    response = client.post('/api/collaboration/projects', json={
        'code': 'P-001', 'name': '合成验收项目', 'processOwner': '流程责任人', 'dataOwner': '数据责任人'}, headers=headers)
    assert response.status_code == 200, response.text
    return client, headers, response.json()['id']


def post(client, headers, path, data):
    response = client.post('/api/collaboration/' + path, json=data, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def patch(client, headers, path, row, **data):
    response = client.patch('/api/collaboration/' + path + '/' + row['id'],
        json={'expectedRevision': row['revision'], **data}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def brief(client, headers, project):
    req = post(client, headers, 'packages', {'projectId': project, 'ownerName': '客户代表',
        'summary': '要求同版本交付', 'constraints': '先确认规格'})
    req = patch(client, headers, 'packages', req, status='briefed')
    return patch(client, headers, 'packages', req, schemeNotes='设计依据已核对')


def handoff(client, headers, req):
    return post(client, headers, 'contracts', {'reqPackageId': req['id'], 'name': 'BOM交付',
        'trigger': '方案确认', 'deliverable': 'BOM及图号', 'qualityRule': '料号、规格、数量、日期完整',
        'designOwner': '设计负责人', 'purchaseOwner': '采购负责人', 'escalateTo': '项目经理'})


def test_project_grants_are_server_enforced_and_revocable(pilot):
    client, headers, project = pilot
    with TestClient(app, raise_server_exceptions=False) as other:
        other_headers = anonymous(other)
        principal = other.get('/api/collaboration/access').json()['principal']
        assert other.get('/api/collaboration/access').json()['projects'] == []
        assert other.get('/api/collaboration/board', params={'projectId': project}).status_code == 403
        data = {'projectId': project, 'ownerName': '客户', 'summary': '有效需求'}
        forged = {**other_headers, 'X-Collaboration-Role': 'market'}
        assert other.post('/api/collaboration/packages', json=data, headers=forged).status_code == 403
        member = client.put(f'/api/collaboration/projects/{project}/members', json={
            'principal': principal, 'name': '测试市场', 'roles': ['market'], 'expectedRevision': 0}, headers=headers).json()
        req = post(other, forged, 'packages', data)
        assert other.patch('/api/collaboration/packages/' + req['id'], json={
            'expectedRevision': req['revision'], 'status': 'briefed'},
            headers={**other_headers, 'X-Collaboration-Role': 'business'}).status_code == 403
        other_project = post(client, headers, 'projects', {'code': 'P-002', 'name': '隔离项目',
            'processOwner': '流程', 'dataOwner': '数据'})['id']
        assert other.get(f'/api/collaboration/projects/{other_project}/export').status_code == 403
        assert other.put(f'/api/collaboration/projects/{project}/members', json={
            'principal': principal, 'name': '自己授权', 'roles': ['business'], 'expectedRevision': 1}, headers=other_headers).status_code == 403
        response = client.put(f'/api/collaboration/projects/{project}/members', json={
            'principal': principal, 'name': '已撤销', 'roles': [], 'expectedRevision': member['revision']}, headers=headers)
        assert response.status_code == 200
        assert other.get('/api/collaboration/board', params={'projectId': project}).status_code == 403


def test_three_scenarios_happy_path_change_and_decision(pilot):
    client, headers, project = pilot
    # 1: demand → brief → scheme → design delivery → purchaser returns → accepts → order.
    req = brief(client, headers, project)
    contract = handoff(client, headers, req)
    contract = patch(client, headers, 'contracts', contract, status='delivered', note='规格齐全', evidence='TEST-BOM-v1')
    contract = patch(client, headers, 'contracts', contract, status='returned', note='请补图号')
    contract = patch(client, headers, 'contracts', contract, status='delivered', note='已补图号', evidence='TEST-BOM-v1b')
    bom = post(client, headers, 'bom', {'ifaceId': contract['id'], 'materialCode': 'TEST-M001',
        'materialName': '合成管段', 'spec': '测试规格', 'qty': '12', 'unit': '根', 'needBy': '2026-12-01'})
    blocked = client.patch('/api/collaboration/bom/' + bom['id'], json={
        'expectedRevision': bom['revision'], 'status': 'quoted', 'note': '未验收不可推进'}, headers=headers)
    assert blocked.status_code == 409
    contract = patch(client, headers, 'contracts', contract, status='closed', note='按质量规则验收合格')
    bom = patch(client, headers, 'bom', bom, status='quoted', note='人工核对报价')
    bom = patch(client, headers, 'bom', bom, status='ordered', note='人工核对原系统', sourceRef='TEST-ERP-PO-001')
    # 2: new requirement version freezes downstream actions; rebase never erases an order.
    changed = patch(client, headers, 'packages', req, status='changed', summary='需求调整为不同窗口', changeReason='客户书面变更 TEST-CH-001')
    assert changed['version'] == 2 and changed['schemeNotes'] == ''
    assert changed['snapshots'][0]['schemeNotes'] == '设计依据已核对'
    board = client.get('/api/collaboration/board', params={'projectId': project}).json()
    assert board['bom'][0]['needsReview'] and board['contracts'][0]['needsReview']
    assert client.patch('/api/collaboration/bom/' + bom['id'], json={
        'expectedRevision': bom['revision'], 'status': 'arrived', 'note': '旧版本操作'}, headers=headers).status_code == 409
    changed = patch(client, headers, 'packages', changed, status='briefed')
    changed = patch(client, headers, 'packages', changed, schemeNotes='v2重新校核')
    contract = patch(client, headers, 'contracts', contract, status='delivered', note='v2差异已核对', evidence='TEST-BOM-v2')
    bom = patch(client, headers, 'bom', bom, rebase=True, note='该物料保持不变，人工确认原订单')
    assert bom['status'] == 'ordered' and bom['sourceRef'] == 'TEST-ERP-PO-001' and bom['basisVersion'] == 2
    contract = patch(client, headers, 'contracts', contract, status='closed', note='v2验收合格')
    bom = patch(client, headers, 'bom', bom, status='arrived', note='人工核对到货凭证', sourceRef='TEST-ERP-GR-001')
    # 3: exception → human decision → recorded result, with honest measurement/export.
    decision = post(client, headers, 'decisions', {'projectId': project, 'title': '调整交期',
        'options': '原窗口 / 新窗口', 'decision': '采用新窗口', 'ownerName': '项目经理',
        'dueAt': '2020-01-01', 'evidence': 'TEST-MEETING-001'})
    board = client.get('/api/collaboration/board', params={'projectId': project}).json()
    assert any(e['type'] == '决策执行超时' for e in board['exceptions'])
    patch(client, headers, 'decisions', decision, result='已执行', evidence='TEST-ACCEPT-001')
    exported = client.get(f'/api/collaboration/projects/{project}/export').json()
    assert exported['measurements']['roi'] is None
    assert all('principal' not in e for e in exported['events'])
    assert exported['decisions'][0]['status'] == 'closed'
    assert len(exported['events']) >= 19


def test_conflicts_atomic_cas_and_audit_rollback(pilot):
    client, headers, project = pilot
    req = brief(client, headers, project)
    original = deepcopy(req)
    updated = patch(client, headers, 'packages', req, schemeNotes='先提交的版本')
    response = client.patch('/api/collaboration/packages/' + req['id'], json={
        'expectedRevision': req['revision'], 'schemeNotes': '过期修改'}, headers=headers)
    assert response.status_code == 409
    assert client.patch('/api/collaboration/packages/' + req['id'], json={'schemeNotes': '无修订号'}, headers=headers).status_code == 422
    # Two independent ORM sessions loaded the same revision: only the first SQL CAS wins.
    with db_session() as db1, db_session() as db2:
        first = get_entity(db1, KIND_REQ, req['id'])
        stale = get_entity(db2, KIND_REQ, req['id'])
        data = deepcopy(first.payload)
        _save(db1, first, {**data, 'schemeNotes': '并发胜者'}, first.revision, Actor('tester', 'admin', ''), 'design', '并发修改')
        db1.commit()
        with pytest.raises(Exception) as conflict:
            _save(db2, stale, {**data, 'schemeNotes': '不应落库'}, stale.revision, Actor('tester', 'admin', ''), 'design', '失败修改')
        assert conflict.value.status_code == 409
    board = client.get('/api/collaboration/board', params={'projectId': project}).json()
    assert board['packages'][0]['schemeNotes'] == '并发胜者'
    assert not any(e['action'] == '失败修改' for e in board['events'])
    assert original['schemeNotes'] == '设计依据已核对' and updated['revision'] > original['revision']


def test_validation_mixed_roles_and_legacy_preservation(pilot):
    client, headers, project = pilot
    req = brief(client, headers, project)
    assert client.patch('/api/collaboration/packages/' + req['id'], json={
        'expectedRevision': req['revision'], 'schemeNotes': '方案', 'summary': '偷偷改需求'}, headers=headers).status_code == 422
    assert client.patch('/api/collaboration/packages/' + req['id'], json={
        'expectedRevision': req['revision'], 'status': 'changed', 'summary': '无原因'}, headers=headers).status_code == 422
    contract = handoff(client, headers, req)
    assert client.patch('/api/collaboration/contracts/' + contract['id'], json={
        'expectedRevision': contract['revision'], 'status': 'delivered', 'note': '没有证据'}, headers=headers).status_code == 422
    bad = {'ifaceId': contract['id'], 'materialCode': 'TEST', 'materialName': '测试',
        'spec': '测试', 'qty': '-1', 'unit': '个', 'needBy': '2026-12-01'}
    assert client.post('/api/collaboration/bom', json=bad, headers=headers).status_code == 422
    bad['qty'] = 'NaN'
    assert client.post('/api/collaboration/bom', json=bad, headers=headers).status_code == 422
    with db_session() as db:
        put_entity(db, KIND_REQ, {'id': 'legacy-test', 'projectName': '旧数据项目',
            'summary': '旧内容保留', 'status': 'draft', 'version': 1}, owner='old-owner')
    first = client.get('/api/collaboration/access').json()
    second = client.get('/api/collaboration/access').json()
    assert len(first['projects']) == len(second['projects']) == 2
    legacy = next(p for p in first['projects'] if p.get('legacy'))
    board = client.get('/api/collaboration/board', params={'projectId': legacy['id']}).json()
    assert board['packages'][0]['summary'] == '旧内容保留'
    with db_session() as db:
        assert get_entity(db, KIND_REQ, 'legacy-test').owner == 'old-owner'
