import gzip
import unittest
from hub_protocol import decode_json, valid_response, ResponseError


class HubProtocolTests(unittest.TestCase):
    def test_plain_and_compressed(self):
        raw = b'{"role":"hub"}'
        self.assertEqual(decode_json(raw), decode_json(gzip.compress(raw), ' GZIP '))
        self.assertTrue(valid_response('/api/health', decode_json(raw)))

    def test_bounded_gzip_including_multiple_members(self):
        for raw in (gzip.compress(b'a' * 1024), gzip.compress(b'a' * 80) * 2):
            with self.assertRaisesRegex(ResponseError, '^decoded_response_too_large$'):
                decode_json(raw, 'gzip', decoded_limit=100)

    def test_corrupt_bodies_have_fixed_diagnostics(self):
        for raw, encoding in ((b'private upstream text', None), (b'bad gzip', 'gzip'), (gzip.compress(b'{}')[:-5], 'gzip')):
            with self.assertRaisesRegex(ResponseError, '^invalid_upstream_response$'):
                decode_json(raw, encoding)

    def test_endpoint_shapes(self):
        self.assertTrue(valid_response('/api/stats', {'devices': [], 'periods': {}}))
        self.assertFalse(valid_response('/api/stats', {'devices': []}))
        self.assertFalse(valid_response('/api/health', {'role': 'client'}))
        self.assertFalse(valid_response('/api/history', []))
