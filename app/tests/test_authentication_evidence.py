import base64
import io
import pytest
from PIL import Image
from ygc import authentication_evidence as auth

@pytest.mark.parametrize('text,status,expected',[
    ('1SSB25003873','readable','mismatched'),('ISSB25003873','uncertain','unconfirmed'),
    (None,'not_visible','unconfirmed'),('issb 25003873','readable','matched'),
    ('ISSB/25003873','readable','mismatched'),
])
def test_only_unambiguous_complete_reading_is_matched(text,status,expected):
    assert auth.check_reading({'status':status,'text':text,'note':''},'ISSB25003873')['match_status']==expected


def test_image_conversion_strips_exif_and_has_bounded_resolution():
    image=Image.new('RGB',(3200,100))
    exif=Image.Exif();exif[270]='private comment'
    stream=io.BytesIO();image.save(stream,format='JPEG',exif=exif)
    result=auth.prepare_image(stream.getvalue())
    assert result['sent_dimensions'][0]==3000
    with Image.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as decoded:
        assert not decoded.getexif()




@pytest.mark.parametrize('content', [b'', b'invalid image', b'x' * (12 * 1024 * 1024 + 1)])
def test_invalid_images_are_rejected(content):
    with pytest.raises(ValueError):
        auth.prepare_image(content)


def test_animated_images_are_rejected():
    stream=io.BytesIO()
    Image.new('RGB',(20,20),'red').save(stream,format='GIF',save_all=True,
        append_images=[Image.new('RGB',(20,20),'blue')])
    with pytest.raises(ValueError,match='still image'):
        auth.prepare_image(stream.getvalue())


def test_exif_orientation_is_applied_before_metadata_is_removed():
    stream=io.BytesIO(); exif=Image.Exif(); exif[274]=6
    Image.new('RGB',(80,40)).save(stream,format='JPEG',exif=exif)
    result=auth.prepare_image(stream.getvalue())
    assert result['sent_dimensions']==[40,80]
    with Image.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as decoded:
        assert not decoded.getexif()


def test_mpf_jpeg_uses_primary_photo_and_strips_auxiliary_frames():
    stream=io.BytesIO();exif=Image.Exif();exif[274]=6;exif[270]='private comment'
    Image.new('RGB',(120,80),'red').save(stream,format='MPO',save_all=True,
        append_images=[Image.new('RGB',(30,20),'blue')],exif=exif)
    content=stream.getvalue()
    assert content.startswith(b'\xff\xd8\xff')
    with Image.open(io.BytesIO(content)) as source:
        assert source.format=='MPO' and source.n_frames==2
    result=auth.prepare_image(content)
    assert result['original_dimensions']==[80,120]
    with Image.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as image:
        assert image.format=='JPEG' and getattr(image,'n_frames',1)==1
        assert image.size==(80,120) and not image.getexif()
        red,green,blue=image.getpixel((40,60))
        assert red>240 and green<10 and blue<10


def test_unsupported_format_error_identifies_actual_data_format():
    stream=io.BytesIO();Image.new('RGB',(10,10)).save(stream,format='TIFF')
    with pytest.raises(ValueError,match='detected: TIFF'):auth.prepare_image(stream.getvalue())
