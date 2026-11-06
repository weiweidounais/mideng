from test_trace import trace,prepare,fabricate,base,post,ok,get,record,upload,board
from test_procurement import flow
from test_handoff import chain

from test_pilot_foundation import grant

def read(t,path,who='pm',**params):return t['env'][3][who].get('/api'+base(t)+'/workspace'+path,params=params)
def test_bounded_index_and_light_detail_preserve_legacy(trace):
 prepare(trace)
 for i in range(23):ok(post(trace,'factory','/spools',{'code':f'PAGE-{i}','order_id':trace['order']['id'],'template_id':trace['template']['id']}))
 one=ok(read(trace,''));two=ok(read(trace,'',page=2));assert one['total']==24 and len(one['items'])==20 and len(two['items'])==4
 assert not set(x['id'] for x in one['items'])&set(x['id'] for x in two['items'])
 assert 'records' not in one['items'][0]
 detail=ok(read(trace,'/spools/'+trace['spool']['id']));assert detail['records']==detail['events']==detail['files']==detail['welds']==[] and detail['record_total']==0 and detail['source_version_id']==trace['scheme']['versions'][0]['id']
 assert len(board(trace)['spools'])==24
 assert ok(read(trace,'',query='PAGE-2'))['total']==4
 assert read(trace,'',page_size=51).status_code==422

def test_history_revision_tokens_and_original_upload_change(trace):
 prepare(trace);sid=trace['spool']['id'];f=upload(trace)
 previous=None
 for i in range(23):
  saved=ok(record(trace,'material',{'batch':f'B-{i}'},file_ids=[f],**({'corrects_id':previous,'correction_reason':'追加合成更正'} if previous else {})));previous=previous or get(trace)['records'][0]['id']
 rev=get(trace)['revision'];path='/spools/'+sid+'/history';one=ok(read(trace,path,kind='records',revision=rev));two=ok(read(trace,path,kind='records',revision=rev,page=2,dataset_token=one['dataset_token']))
 assert one['total']==23 and len(one['items'])==20 and len(two['items'])==3 and one['items'][0]['attachments'][0]['id']==f
 assert read(trace,path,kind='records',revision=rev,page=2).status_code==422
 files=ok(read(trace,path,kind='files',revision=rev));upload(trace)
 assert read(trace,path,kind='files',revision=rev,page=2,dataset_token=files['dataset_token']).status_code==409
 ok(record(trace,'material',{'batch':'new'},file_ids=[f],corrects_id=previous,correction_reason='追加合成更正'));assert read(trace,path,kind='records',revision=rev,dataset_token=one['dataset_token']).status_code==409

def test_mobile_history_privacy_and_revocation(trace):
 fabricate(trace);sid=trace['spool']['id'];rev=get(trace)['revision'];path='/spools/'+sid+'/history';args={'kind':'records','revision':rev}
 assert 'QUAL-1' not in read(trace,path,'biz',**args).text and 'QUAL-1' in read(trace,path,'quality',**args).text
 assert read(trace,'/spools/'+sid,'outsider').status_code==404
 _,admin,p,_,people=trace['env'];ok(grant(admin,p,people['factory'],['工厂'],revision=1,active=False));assert read(trace,path,'factory',**args).status_code==404

def test_choices_metrics_and_preview_contract(trace):
 prepare(trace);sid=trace['spool']['id'];assert ok(read(trace,'/choices','factory',kind='orders'))['items'][0]['id']==trace['order']['id'];assert ok(read(trace,'/choices',kind='sources'))['items'][0]['id']==trace['scheme']['versions'][0]['id']
 assert ok(read(trace,'/choices',kind='templates',order_id=trace['order']['id']))['items'][0]['id']==trace['template']['id']
 assert read(trace,'/choices',kind='parents').status_code==422
 metrics=ok(read(trace,'/metrics'));assert metrics['completed_rate'] is None and metrics['in_progress_total']==1 and metrics['checked_at']
 from PIL import Image
 import io,uuid
 raw=io.BytesIO();Image.new('RGB',(8,8),'blue').save(raw,format='PNG');c=trace['env'][3]['factory'];r=c.post('/api'+base(trace)+'/spools/'+sid+'/files',files={'file':('phone.png',raw.getvalue(),'image/png')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex});fid=ok(r)['id'];url='/api'+base(trace)+'/files/'+fid
 assert c.get(url).headers['content-disposition'].startswith('attachment') and c.get(url+'?preview=true').headers['content-disposition'].startswith('inline')
 assert trace['env'][3]['outsider'].get(url+'?preview=true').status_code==404
