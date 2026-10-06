"""Exercise the journey's actual capture/check expressions without a browser."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from authentication_fixtures import image_bytes


@pytest.fixture
def capture():
    tree = ast.parse(Path(__file__).with_name('browser_user_journeys.py').read_text())
    callback = next(node.args[1] for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'on' and len(node.args) == 2
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'request')
    credential_check = next(node.test for node in ast.walk(tree)
                            if isinstance(node, ast.Assert) and isinstance(node.test, ast.Call)
                            and isinstance(node.test.func, ast.Name) and node.test.func.id == 'all')
    sent = []
    namespace = {'sent': sent}
    callback = eval(compile(ast.Expression(callback), 'browser-request-capture', 'eval'), namespace)
    check = compile(ast.Expression(credential_check), 'browser-credential-check', 'eval')
    return callback, sent, lambda: eval(check, namespace)


def test_binary_multipart_and_empty_requests_are_captured_without_utf8_decoding(capture):
    callback, sent, check = capture
    multipart = b'--boundary\r\nContent-Type: image/png\r\n\r\n' + image_bytes() + b'\r\n--boundary--'
    with pytest.raises(UnicodeDecodeError):
        multipart.decode('utf-8')

    class BinaryRequest:
        post_data_buffer = multipart

        @property
        def post_data(self):
            raise AssertionError('Binary request bodies must not use text decoding')

    callback(BinaryRequest())
    callback(SimpleNamespace(post_data_buffer=None))
    callback(SimpleNamespace(post_data_buffer=b'{"fixture":true}'))
    assert sent == [multipart, b'', b'{"fixture":true}']
    assert check()


@pytest.mark.parametrize('credential', [b'discarded@example.invalid', b'not-a-real-secret'])
def test_credential_discard_check_still_detects_credentials_in_binary_payloads(capture, credential):
    callback, sent, check = capture
    callback(SimpleNamespace(post_data_buffer=b'\x89PNG\xff\x00' + credential + b'\xff'))
    assert not check()
