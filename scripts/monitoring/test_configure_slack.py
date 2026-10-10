"""No network or production mutation: secret handling and setup ordering."""
import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

import configure_slack


class ConfigurationTests(unittest.TestCase):
    def test_secret_only_travels_over_stdin_and_https(self):
        webhook = 'https://hooks.slack.com/services/TEST/TEST/not-a-real-secret'
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'ok'
        with patch.object(configure_slack.getpass, 'getpass', return_value=webhook), \
             patch.object(configure_slack.urllib.request, 'urlopen', return_value=response) as send, \
             patch.object(configure_slack.subprocess, 'run') as run, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            configure_slack.main()
        self.assertEqual(send.call_count, 2)  # identified test, then operational procedure
        self.assertEqual(run.call_count, 3)   # server, Actions secret, external check
        for call in run.call_args_list:
            self.assertNotIn(webhook, str(call.args))
        self.assertNotIn(webhook, output.getvalue())
        self.assertIn(webhook, run.call_args_list[0].kwargs['input'])
        self.assertEqual(webhook, run.call_args_list[1].kwargs['input'])

    def test_invalid_host_cannot_receive_the_secret(self):
        with patch.object(configure_slack.getpass, 'getpass', return_value='https://hooks.slack.com.evil.test/services/a'), \
             patch.object(configure_slack.urllib.request, 'urlopen') as send:
            with self.assertRaises(SystemExit):
                configure_slack.main()
        send.assert_not_called()

    def test_rejected_test_does_not_change_production(self):
        with patch.object(configure_slack.getpass, 'getpass', return_value='https://hooks.slack.com/services/TEST'), \
             patch.object(configure_slack.urllib.request, 'urlopen', side_effect=TimeoutError()), \
             patch.object(configure_slack.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                configure_slack.main()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
