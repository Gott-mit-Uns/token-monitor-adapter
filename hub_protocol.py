"""Pure Hub response decoding; no credentials, network, storage or scheduling."""
import gzip
import io
import json
import zlib

MAX_BODY = 16 * 1024 * 1024
MAX_DECODED_BODY = 64 * 1024 * 1024
SYNC_CONTENT = '/api/sync/content'
SYNC_SETTINGS = {'/api/sync/settings/modelAliases', '/api/sync/settings/customPricing'}
SYNC_READS = SYNC_SETTINGS | {SYNC_CONTENT}


def valid_policy(data):
    return isinstance(data, dict) and type(data.get('enabled')) is bool and type(data.get('generation')) is int and 0 <= data['generation'] <= 9007199254740991


def sync_conflict(data):
    # Return only the protocol's conflict document, never server diagnostics.
    if isinstance(data, dict) and valid_response('/api/sync/settings/modelAliases', data):
        return {key: data[key] for key in ('version', 'revision', 'updatedAt', 'value') if key in data} | {'error': 'stale_write'}
    return {'error': 'upstream_rejected'}


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
    if path == SYNC_CONTENT:
        return data.get('version') == 1 and type(data.get('sharedSettings')) is bool and isinstance(data.get('sessionTitles'), dict) and type(data['sessionTitles'].get('enabled')) is bool
    if path in SYNC_SETTINGS:
        return data.get('version') == 1 and type(data.get('revision')) is int and 0 <= data['revision'] <= 9007199254740991 and isinstance(data.get('updatedAt'), str) and 'value' in data and (data['value'] is None or isinstance(data['value'], (dict, list)))
    if path.startswith('/api/sync/titles/'):
        return valid_policy(data)
    return True
