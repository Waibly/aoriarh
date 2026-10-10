import json
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
from io import BytesIO

from probe import check


class ProbeTests(unittest.TestCase):
    def test_contract_expects_antibot_rejection_not_schema_error(self):
        for status, expected in [(403, True), (422, False), (500, False)]:
            error = urllib.error.HTTPError('https://example.test/ask', status, '', {}, BytesIO(b'{}'))
            with patch('urllib.request.urlopen', side_effect=error):
                self.assertEqual(check('https://example.test/ask', {'message':'test'}, 403), expected)

    def test_health_checks_dependency_status(self):
        for status, expected in [('ok', True), ('degraded', False)]:
            response = MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            response.read.return_value = json.dumps({'status':status}).encode()
            with patch('urllib.request.urlopen', return_value=response):
                self.assertEqual(check('https://example.test/health', None, 200), expected)


if __name__ == '__main__':
    unittest.main()
