"""PM-owned procurement items are independent of the designer's technical scheme."""
from datetime import datetime,timezone
import pytest
from test_handoff import chain,req,post as handoff_post,SCHEME
from test_procurement import flow,base,ok,act,get,upload,archive_data
from test_pilot_foundation import mutation

ITEMS=[{'material':'项目经理确认管材','spec':'DN25','quantity':'2.75','unit':'米','need_by':'2026-12-01'},{'material':'项目经理确认接头','spec':'DN25螺纹','quantity':'5','unit':'个','need_by':'2026-12-02'}]


def payload(flow,lines=ITEMS):
    (_,_,_,_,people),s=flow
    return {'version_id':s['versions'][0]['id'],'title':'PM独立采购需求','note':'项目经理按现场核定种类与数量','purchase_id':people['purchase']['id'],'quality_id':people['quality']['id'],'commerce_id':people['biz']['id'],'lines':lines}


def test_design_can_publish_technical_scheme_without_any_procurement_lines(flow):
    chain,_=flow;_,_,p,cs,people=chain;d=req(chain)
    body={k:v for k,v in SCHEME.items() if k!='bom'}
    s=ok(handoff_post(cs['design'],p,'/documents',{'kind':'scheme','parent_id':d['id'],'source_version_id':d['versions'][0]['id'],'body':body}))
    assert s['draft']['bom']==[]
    s=ok(handoff_post(cs['design'],p,'/documents/'+s['id']+'/publish',{'revision':s['revision'],'recipient_ids':[people['pm']['id']],'diff_summary':'仅落地方案，由PM编制采购清单'}))
    assert s['versions'][0]['body']['bom']==[]
    request=payload(flow)|{'version_id':s['versions'][0]['id']}
    ok(mutation(cs['pm'],'POST',base(p)+'/orders',request))
    assert get(flow)['lines'][0]['material']=='项目经理确认管材'
    assert handoff_post(cs['design'],p,'/contracts',{'version_id':s['versions'][0]['id'],'recipient_id':people['purchase']['id'],'deliverable':'不得用空旧料表发交接','quality_rule':'合成'}).status_code==422


def test_pm_two_item_quantities_drive_procurement_arrival_quality_and_archive(flow):
    (_,_,p,cs,_),s=flow;original=s['versions'][0]['body']['bom']
    ok(mutation(cs['pm'],'POST',base(p)+'/orders',payload(flow)));o=get(flow)
    assert o['lines']==ITEMS and o['lines_origin']=='project_manager'
    ok(act(flow,o,'accept_purchase','purchase'));o=get(flow)
    ok(act(flow,o,'submit_result','purchase',result={'supplier':'合成供应商','lines':[{'line_no':i+1,'quantity':l['quantity'],'eta':l['need_by']} for i,l in enumerate(ITEMS)]}));o=get(flow)
    ok(act(flow,o,'approve_purchase','pm'));o=get(flow)
    for i,l in enumerate(ITEMS):
        ok(act(flow,o,'arrival','purchase',arrival={'line_no':i+1,'quantity':l['quantity'],'occurred_at':datetime.now(timezone.utc).isoformat()}));o=get(flow)
        assert o['state']==('quality_wait' if i==0 else 'quality_check')
    proof=ok(upload(flow,o,'quality'));ok(act(flow,o,'pass_quality','quality',file_ids=[proof['id']]));o=get(flow)
    contract=ok(upload(flow,o,'biz','archive',b'pm items synthetic contract','contract.md'))
    ok(act(flow,o,'archive','biz',archive=archive_data(contract['id'])));o=get(flow)
    assert o['state']=='archived' and o['lines']==ITEMS
    detail=ok(cs['pm'].get('/api/projects/'+p['id']+'/workspace/purchase-orders/'+o['id']))
    assert [l['required_quantity'] for l in detail['comparison']]==['2.75','5']
    legacy=ok(cs['design'].get('/api/projects/'+p['id']+'/handoff/documents/'+s['id']))
    assert legacy['versions'][0]['body']['bom']==original


def test_missing_or_empty_pm_items_cannot_fall_back_to_design_bom(flow):
    (_,_,p,cs,_),_=flow
    for request in [{k:v for k,v in payload(flow).items() if k!='lines'},payload(flow,[])]:
        assert mutation(cs['pm'],'POST',base(p)+'/orders',request).status_code==422
    assert cs['pm'].get('/api'+base(p)+'/board').json()['orders']==[]


@pytest.mark.parametrize('bad', [{'quantity':'0'},{'quantity':'1.1234567'},{'need_by':'2026-02-30'},{'material':''},{'unit':''}])
def test_invalid_pm_item_rejects_entire_request(flow,bad):
    (_,_,p,cs,_),_=flow
    assert mutation(cs['pm'],'POST',base(p)+'/orders',payload(flow,[ITEMS[0]|bad])).status_code==422
    assert cs['pm'].get('/api'+base(p)+'/board').json()['orders']==[]


def test_design_and_purchase_cannot_submit_pm_request_or_rewrite_frozen_items(flow):
    (_,_,p,cs,_),_=flow
    for who in ['design','purchase']:
        assert mutation(cs[who],'POST',base(p)+'/orders',payload(flow)).status_code==403
    ok(mutation(cs['pm'],'POST',base(p)+'/orders',payload(flow)));o=get(flow)
    assert mutation(cs['purchase'],'POST',base(p)+'/orders/'+o['id']+'/actions',{'revision':o['revision'],'action':'accept_purchase','lines':[ITEMS[0]|{'quantity':'99'}]}).status_code==422
    assert get(flow)['lines']==ITEMS


def test_pm_csv_precheck_does_not_submit_or_replace_procurement(flow):
    (_,_,p,cs,_),_=flow;c=cs['pm']
    content='物料,规格,数量,单位,需用日期\nPM管材,DN25,2.75,米,2026-12-01\n'.encode()
    r=c.post('/api/projects/'+p['id']+'/handoff/bom-preview',files={'file':('pm-items.csv',content,'text/csv')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf']})
    assert r.status_code==200,r.text
    assert not r.json()['errors'] and r.json()['rows'][0]['quantity']=='2.75'
    assert cs['pm'].get('/api'+base(p)+'/board').json()['orders']==[]
