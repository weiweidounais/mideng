import io,hashlib,uuid
import pytest
from PIL import Image
from fastapi import HTTPException
from app.image_validation import validate_camera_image
from test_trace import trace,flow,chain,prepare,base
from test_procurement import ok

def camera(fmt='JPEG',mpo=False):
    b=io.BytesIO();image=Image.new('RGB',(80,50),'blue')
    image.save(b,format='MPO' if mpo else fmt,**({'save_all':True,'append_images':[Image.new('RGB',(40,25),'red')]} if mpo else {}))
    return b.getvalue()

def test_valid_multi_picture_jpeg_no_longer_rejected_or_modified():
    raw=camera(mpo=True)
    with Image.open(io.BytesIO(raw)) as image:assert image.format=='MPO' and image.n_frames==2
    validate_camera_image(raw,'.jpg');validate_camera_image(raw,'.jpeg',max_pixels=20_000_000,full_decode=True)

@pytest.mark.parametrize('raw,extension,code',[(camera('PNG'),'.jpg','IMAGE_FORMAT_MISMATCH'),(b'not an image','.jpg','IMAGE_CORRUPT'),(camera()[:150],'.jpg','IMAGE_CORRUPT'),(b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1','.jpg','IMAGE_ENCODING_UNSUPPORTED')])
def test_camera_errors_identify_format_or_damage(raw,extension,code):
    with pytest.raises(HTTPException) as e:validate_camera_image(raw,extension)
    assert e.value.status_code==422 and e.value.detail['code']==code

def test_pixel_limit_and_truncated_auxiliary_jpeg_still_rejected():
    with pytest.raises(HTTPException) as e:validate_camera_image(camera(),'.jpg',max_pixels=100)
    assert e.value.detail['code']=='IMAGE_PIXELS'
    with pytest.raises(HTTPException):validate_camera_image(camera(mpo=True)[:-80],'.jpg')

def test_both_photo_routes_preserve_mpo_originals_and_retry_once(trace):
    prepare(trace);raw=camera(mpo=True);cs=trace['env'][3]
    for who,path in [('factory','/spools/'+trace['spool']['id']+'/files'),('quality','/template-photos')]:
        c=cs[who];headers={'X-CSRF-Token':c.get('/api/session').json()['csrf'],'X-Idempotency-Key':uuid.uuid4().hex};url='/api'+base(trace)+path
        first=ok(c.post(url,files={'file':('android-photo.jpg',raw,'image/jpeg')},headers=headers));second=ok(c.post(url,files={'file':('android-photo.jpg',raw,'image/jpeg')},headers=headers));assert first['id']==second['id'] and first['sha256']==hashlib.sha256(raw).hexdigest()
        geturl='/api'+base(trace)+('/files/' if who=='factory' else '/template-photos/')+first['id'];assert c.get(geturl).content==raw

def test_existing_animated_webp_photo_keeps_first_frame_validation_contract():
    b=io.BytesIO();frames=[Image.new('RGB',(8,8),(i*7%255,20,40)) for i in range(33)]
    frames[0].save(b,format='WEBP',save_all=True,append_images=frames[1:],duration=100,loop=0)
    validate_camera_image(b.getvalue(),'.webp',max_pixels=20_000_000,full_decode=True)

def test_procurement_camera_uses_the_same_content_validation_and_preserves_original(flow):
    from test_procurement import create,upload,base as purchase_base
    order=ok(create(flow));raw=camera(mpo=True);photo=ok(upload(flow,order,'quality',content=raw,name='camera.jpg'))
    (_,_,project,clients,_),_=flow
    assert clients['quality'].get('/api'+purchase_base(project)+'/files/'+photo['id']).content==raw
    rejected=upload(flow,order,'quality',content=camera('PNG'),name='mismatch.jpg')
    assert rejected.status_code==422 and rejected.json()['error']['code']=='IMAGE_FORMAT_MISMATCH'
