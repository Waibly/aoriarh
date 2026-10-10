#!/usr/bin/env python3
"""Public availability checks from GitHub Actions, independent of the VPS.

No LLM call, no user content. Slack delivery retries only technical failures.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from probe import CHECKS, check


def send_slack(text):
    webhook = os.environ.get('AORIA_SLACK_WEBHOOK_URL', '')
    if not webhook:
        print('External Slack delivery not configured.')
        return False
    if not webhook.startswith('https://hooks.slack.com/services/'):
        print('Invalid Slack webhook host.')
        return False
    for attempt in range(3):
        req = urllib.request.Request(webhook, data=json.dumps({'text': text}).encode(),
                                     headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                return response.status == 200 and response.read(100) == b'ok'
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                print('Slack rejected notification:',exc.code)
                return False
            delay = min(60, max(1, int(exc.headers.get('Retry-After','10'))))
        except (urllib.error.URLError, TimeoutError):
            delay = 10
        if attempt < 2:
            time.sleep(delay)
    print('External Slack delivery exhausted its three attempts.')
    return False


def main():
    failures = []
    checks = {**CHECKS, 'incident_delivery': ('GET','https://api.aoriarh.fr/api/v1/telemetry/health',200,None)}
    for name,args in checks.items():
        try:
            success = check(*args)
        except Exception:
            success = False
        print(name + ': ' + ('ok' if success else 'failed'))
        if not success:
            failures.append(name)
    if failures:
        send_slack('🔴 AORIA RH — contrôle extérieur en échec : '+', '.join(failures)+'. Consulter GitHub Actions : https://github.com/Waibly/aoriarh/actions/workflows/availability.yml')
        return 1
    if os.environ.get('PREVIOUS_CONCLUSION') == 'failure':
        if not send_slack('🟢 AORIA RH — les contrôles extérieurs répondent à nouveau. Ce contrôle ne valide pas une génération IA.'):
            return 1
    if not os.environ.get('AORIA_SLACK_WEBHOOK_URL'):
        print('Checks passed, but external Slack delivery is not configured.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
