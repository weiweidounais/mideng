"""Validate camera originals without renaming, recompressing or dropping auxiliary JPEG images."""
import io,warnings
from struct import error as struct_error
from PIL import Image,UnidentifiedImageError
from .pilot_service import fail

EXPECTED={'.jpg':{'JPEG','MPO'},'.jpeg':{'JPEG','MPO'},'.png':{'PNG'},'.webp':{'WEBP'}}

def validate_camera_image(data:bytes,extension:str,*,max_pixels:int|None=None,full_decode:bool=False):
    detected=None
    # ISO BMFF containers may be returned under a generic .jpg filename by a camera picker.
    if len(data)>=12 and data[4:8]==b'ftyp':
        brands=data[8:min(len(data),64)]
        detected='AVIF' if b'avif' in brands else 'HEIF/HEIC' if any(b in brands for b in [b'heic',b'heix',b'hevc',b'hevx',b'mif1',b'msf1']) else 'ISO-BMFF'
        fail(422,'IMAGE_ENCODING_UNSUPPORTED',f'照片实际编码为{detected}，当前未支持；请在相机关闭高效图片格式后重拍，或另存为JPG/PNG副本再上传。',detected_format=detected)
    problem=None
    try:
        with warnings.catch_warnings():
            if max_pixels is not None:warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                detected=image.format or '未知'
                if detected not in EXPECTED.get(extension,set()):
                    problem=('IMAGE_FORMAT_MISMATCH',f'照片实际格式为{detected}，与文件后缀{extension}不符或当前未支持；请另存为JPG/PNG副本后选择。')
                elif max_pixels is not None and image.width*image.height>max_pixels:
                    problem=('IMAGE_PIXELS',f'照片分辨率{image.width}×{image.height}超过本入口{max_pixels//1_000_000}百万像素上限，请另存较小副本。')
                else:image.verify()
            if not problem and (full_decode or detected=='MPO'):
                with Image.open(io.BytesIO(data)) as image:
                    frames=getattr(image,'n_frames',1) if detected=='MPO' else 1
                    if frames>32:problem=('IMAGE_FRAME_LIMIT','多图照片包含过多子图，请另存普通JPG副本后上传。')
                    else:
                        total=0
                        for frame in range(frames):
                            image.seek(frame);pixels=image.width*image.height;total+=pixels
                            if max_pixels is not None and pixels>max_pixels:
                                problem=('IMAGE_PIXELS','照片子图分辨率超过本入口2000万像素上限，请另存较小副本。');break
                            if detected=='MPO' and total>178_956_970:
                                problem=('IMAGE_FRAME_LIMIT','多图照片子图累计像素过大，请另存普通JPG副本后上传。');break
                            image.load()
    except (Image.DecompressionBombError,Image.DecompressionBombWarning):
        problem=('IMAGE_PIXELS','照片分辨率过大，请另存较小的JPG/PNG副本后上传。')
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,IndexError,TypeError,KeyError,OverflowError,EOFError,struct_error):
        problem=('IMAGE_CORRUPT','照片内容无法完整解码，可能损坏或相机未提供完整文件；请重新拍摄或从相册选择原件。')
    if problem:fail(422,problem[0],problem[1],detected_format=detected)
