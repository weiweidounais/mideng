import io,uuid,hashlib
from pathlib import Path
import pytest
from PIL import Image
from sqlalchemy import select,func,text
from sqlalchemy.exc import DatabaseError
from app.trace_models import TemplatePhoto,TraceTemplate
from test_trace import trace,flow,chain,prepare,board,post,base
from test_procurement import ok
from test_pilot_foundation import mutation,add_project,grant

def image_bytes(fmt='PNG'):
 stream=io.BytesIO();Image.new('RGB',(80,50),(30,120,105)).save(stream,format=fmt);return stream.getvalue()
def upload(t,who='quality',name='示意照片.png',data=None,key=None):
 c=t['env'][3][who];return c.post('/api'+base(t)+'/template-photos',files={'file':(name,image_bytes() if data is None else data,'image/png')},headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':key or uuid.uuid4().hex})
def create(t,ids):return post(t,'quality','/templates',{'name':'照片合成模板','scope':'QA','welding':False,'pressure':False,'basis':'质量明确确认并关联照片','photo_ids':ids})
def test_photos_save_with_template_and_only_visible_when_linked(trace):
 photo=ok(upload(trace));pid=trace['env'][2]['id'];factory=trace['env'][3]['factory'];url='/api'+base(trace)+'/template-photos/'+photo['id']
 assert factory.get(url).status_code==404
 template=ok(create(trace,[photo['id']]));t=next(t for t in board(trace)['templates'] if t['id']==template['id']);assert t['photos'][0]['sha256']==hashlib.sha256(image_bytes()).hexdigest()
 response=factory.get(url);assert response.status_code==200 and response.content==image_bytes() and response.headers['content-type'].startswith('image/png')
 assert trace['env'][3]['outsider'].get(url).status_code==404
 with pytest.raises(DatabaseError):
  with trace['env'][0].state.store.transaction(write=True) as db:db.execute(text('DELETE FROM trace_template_photo_links'))

def test_supplement_is_append_only_owner_scoped_and_idempotent(trace):
 prepare(trace);tid=trace['template']['id'];before=next(t for t in board(trace)['templates'] if t['id']==tid);p=ok(upload(trace));path='/templates/'+tid+'/photos';body={'photo_ids':[p['id']]};r=post(trace,'quality',path,body,'supplement-same-key');ok(r);assert post(trace,'quality',path,body,'supplement-same-key').json()==r.json()
 after=next(t for t in board(trace)['templates'] if t['id']==tid);assert len(after['photos'])==1 and all(after[k]==before[k] for k in ['name','scope','basis','welding','pressure','approved_by'])
 assert post(trace,'factory',path,body).status_code==403
 app,admin,project,cs,people=trace['env'];ok(grant(admin,project,people['design'],['质量'],revision=1));assert post(trace,'design',path,body).status_code==403

def test_upload_rejects_nonimages_path_traversal_and_wrong_roles(trace):
 assert upload(trace,'factory').status_code==403
 assert upload(trace,'outsider').status_code==404
 for name,data in [('fake.jpg',b'not image'),('../unsafe.png',image_bytes()),('wrong.jpg',image_bytes()),('code.svg',b'<svg/>'),('empty.png',b'')]:assert upload(trace,name=name,data=data).status_code==422
 assert upload(trace,name='real.jpg',data=image_bytes('JPEG')).status_code==200
 assert upload(trace,name='real.webp',data=image_bytes('WEBP')).status_code==200

def test_cross_project_stale_original_and_photo_count_fail_atomically(trace):
 p=ok(upload(trace));app,admin,project,cs,people=trace['env'];other=add_project(admin,'PHOTO-OTHER');ok(grant(admin,other,people['quality'],['质量']))
 body={'name':'跨项目','scope':'X','welding':False,'pressure':False,'basis':'X','photo_ids':[p['id']]};assert mutation(cs['quality'],'POST','/projects/'+other['id']+'/trace/templates',body).status_code==404
 assert create(trace,[p['id']]*2).status_code==422
 with app.state.store.transaction() as db:Path(db.get(TemplatePhoto,p['id']).path).write_bytes(b'tamper')
 assert create(trace,[p['id']]).status_code==409
 with app.state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(TraceTemplate))==0
 assert create(trace,[str(x) for x in range(11)]).status_code==422

def test_upload_retry_keeps_single_original_and_private_result_checks_project(trace):
 p=ok(upload(trace,key='photo-upload-once'));assert ok(upload(trace,key='photo-upload-once'))==p
 with trace['env'][0].state.store.transaction() as db:assert db.scalar(select(func.count()).select_from(TemplatePhoto))==1
 app,admin,project,cs,people=trace['env'];ok(grant(admin,project,people['quality'],['质量'],revision=1,active=False));assert cs['quality'].get('/api/requests/photo-upload-once').status_code==404
