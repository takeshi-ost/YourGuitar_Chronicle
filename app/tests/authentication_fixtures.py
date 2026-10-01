import io
from PIL import Image

def image_bytes(color='white'):
    stream=io.BytesIO()
    Image.new('RGB',(320,240),color).save(stream,format='PNG')
    return stream.getvalue()


def reading(text):
    return {'status':'readable' if text else 'not_visible','text':text,'note':'画像だけを確認'}


def transcription(serial='ISSB25003873',challenge='N3G8PQTS'):
    return {'serial':reading(serial),'challenge':reading(challenge)}


def comparison():
    return {'identity':{'status':'supported','supporting_features':[{'location':'B/C ブリッジ下',
              'observation':'曲がった木目が対応'}],'differences':[], 'ambiguous_differences':[], 'comparison_coverage':'sufficient', 'limitations':['傷の細部は不鮮明']},
            'photography':{'status':'different_capture_supported','reasons':['反射と撮影角度が異なる']},
            'closeup_link':{'status':'uncertain','reasons':['同色のネック'],
                            'limitations':['ヘッドからボディまで連続して見えない']}}


def measurement():
    def image(name):
        return {'image':name,'original_dimensions':[300,400],'sent_dimensions':[300,400],
                'serial':{'status':'readable','expected':'ABC123','text':'ABC123','note':'明瞭','match_status':'matched'},
                'challenge':{'status':'readable','expected':'TEST1234','text':'TEST1234','note':'明瞭','match_status':'matched'}}
    return {'images':[image('serial_closeup'),image('guitar_overview')],
            'reference':'Uploaded target','provider':'OpenAI','model':'test-vision',
            'prompt_version':'test','duration_seconds':1.,'calls':[],
            'comparison':{'identity':{'status':'supported',
                'supporting_features':[{'location':'ブリッジ下','observation':'曲がった木目が対応'}],
                'differences':[], 'ambiguous_differences':[], 'comparison_coverage':'sufficient','limitations':['小さな傷は不鮮明']},
                'photography':{'status':'different_capture_supported','reasons':['角度が異なる']},
                'closeup_link':{'status':'uncertain','reasons':[],'limitations':['直接つながって見えない']}},
            'reference_note':'Uploaded reference','limitations':['AI may err'],'decision':'No approval'}


