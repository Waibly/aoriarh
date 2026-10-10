"""Exercise the complete probe wiring, including the empty telemetry health body."""
import os
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import external_check


def test_all_external_checks_accept_their_real_response_contracts():
    def respond(request, **kwargs):
        url = request.full_url
        if url.endswith('/public/ask'):
            raise HTTPError(url, 403, '', {}, BytesIO(b'{}'))
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = (
            b'{"status":"ok"}' if url == 'https://api.aoriarh.fr/health' else b''
        )
        return response

    with patch('urllib.request.urlopen', side_effect=respond), \
         patch.dict(os.environ, {'AORIA_SLACK_WEBHOOK_URL': 'configured',
                                 'PREVIOUS_CONCLUSION': 'failure'}), \
         patch.object(external_check, 'send_slack', return_value=True) as slack:
        assert external_check.main() == 0
        slack.assert_called_once()
        assert 'répondent à nouveau' in slack.call_args.args[0]


def test_unhealthy_delivery_still_triggers_an_alert():
    def respond(request, **kwargs):
        url = request.full_url
        status = 403 if url.endswith('/public/ask') else 503
        if url.endswith('/public/ask') or url.endswith('/telemetry/health'):
            raise HTTPError(url, status, '', {}, BytesIO(b''))
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"status":"ok"}'
        return response

    with patch('urllib.request.urlopen', side_effect=respond), \
         patch.object(external_check, 'send_slack', return_value=True) as slack:
        assert external_check.main() == 1
        slack.assert_called_once()
        assert 'incident_delivery' in slack.call_args.args[0]
