"""Pure Hub response decoding; no credentials, network, storage or scheduling."""
import gzip
import io
import json
import zlib

MAX_BODY = 16 * 1024 * 1024
MAX_DECODED_BODY = 64 * 1024 * 1024


class ResponseError(ValueError):
    """A fixed diagnostic code, never an upstream response body."""


def decode_json(raw, content_encoding=None, decoded_limit=MAX_DECODED_BODY):
    if len(raw) > MAX_BODY:
        raise ResponseError('response_too_large')
    try:
        if (content_encoding or '').strip().lower() == 'gzip':
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded = stream.read(decoded_limit + 1)
        else:
            decoded = raw
        if len(decoded) > decoded_limit:
            raise ResponseError('decoded_response_too_large')
        return json.loads(decoded) if decoded else {}
    except ResponseError:
        raise
    except (OSError, EOFError, ValueError, zlib.error):
        raise ResponseError('invalid_upstream_response') from None


def valid_response(path, data):
    if not isinstance(data, dict):
        return False
    if path == '/api/stats':
        return isinstance(data.get('devices'), list) and isinstance(data.get('periods'), dict)
    if path == '/api/devices':
        return isinstance(data.get('devices'), list)
    if path == '/api/health':
        return data.get('role') == 'hub'
    return True
