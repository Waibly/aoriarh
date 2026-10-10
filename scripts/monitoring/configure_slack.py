#!/usr/bin/env python3
"""Configure a channel-bound incoming webhook without exposing it in history.

Run locally from the AORIA repository. Input is masked. Requires SSH and gh.
"""
import getpass
import json
from pathlib import Path
import shlex
import subprocess
import sys
import urllib.request

REMOTE = r'''
import importlib.util, json, os, pathlib, subprocess, sys
value = json.load(sys.stdin)['webhook']
root = pathlib.Path.home() / 'aoriarh'
path = root / '.env'
lines = path.read_text().splitlines()
lines = [line for line in lines if not line.startswith('AORIA_SLACK_WEBHOOK_URL=')]
lines.append('AORIA_SLACK_WEBHOOK_URL=' + value)
# Atomic replacement, no plaintext output.
temp = path.with_name('.env.slack-tmp')
fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write('\n'.join(lines) + '\n')
os.chmod(temp, 0o600)
os.replace(temp,path)
os.chdir(root)
env = {**os.environ, 'AORIA_SLACK_WEBHOOK_URL':value}
subprocess.run(['docker','compose','-f','docker-compose.prod.yml','up','-d','--no-deps','incident-notifier'],check=True,env=env)
subprocess.run(['python3','scripts/monitoring/provision_alerts.py'],check=True,env=env)
'''


def main():
    root = Path(__file__).resolve().parents[2]
    webhook = getpass.getpass('Webhook du canal Slack AORIA (saisie masquée) : ').strip()
    from urllib.parse import urlsplit
    url = urlsplit(webhook)
    if url.scheme != 'https' or url.netloc != 'hooks.slack.com' or not url.path.startswith('/services/') or url.query or url.fragment:
        raise SystemExit('URL de webhook Slack invalide.')
    # The test is deliberately identifiable and contains no production data.
    try:
        req = urllib.request.Request(webhook, data=json.dumps({'text':'AORIA RH — TEST de configuration du canal incidents. Aucun incident utilisateur. Procédure : https://github.com/Waibly/aoriarh/blob/main/docs/exploitation/INCIDENTS_SLACK.md'}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as response:
            if response.status != 200 or response.read(100) != b'ok':
                raise RuntimeError()
    except Exception:
        raise SystemExit('Slack n’a pas accepté le message de test. Aucun secret configuré.') from None
    subprocess.run(['ssh','-p','2222','aoriadmin@79.137.14.24','python3 -c '+shlex.quote(REMOTE)],
                   input=json.dumps({'webhook':webhook}),text=True,check=True,cwd=root)
    subprocess.run(['gh','secret','set','AORIA_SLACK_WEBHOOK_URL','--repo','Waibly/aoriarh'],
                   input=webhook,text=True,check=True,cwd=root)
    subprocess.run(['gh','workflow','run','availability.yml','--repo','Waibly/aoriarh'],check=True,cwd=root)
    print('Configuration appliquée. Vérifier le canal, /admin/incidents et le contrôle extérieur.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError:
        sys.exit('Une étape de configuration a échoué. Vérifier les étapes déjà appliquées avant reprise.')
