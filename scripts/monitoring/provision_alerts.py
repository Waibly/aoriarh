#!/usr/bin/env python3
"""Provisionne les alertes AORIA sur Grafana local, sans afficher de secret.

Exécuter sur le VPS. AORIA_SLACK_WEBHOOK_URL doit être fourni via un environnement
protégé pour activer Slack. Sans cette variable, seules les règles sont installées.
"""
import base64
import json
import os
import subprocess
import urllib.error
import urllib.request


def api_client():
    container = json.loads(subprocess.check_output(
        ['docker', 'inspect', 'aoriarh-grafana-1']))[0]
    env = dict(item.split('=', 1) for item in container['Config']['Env'])
    ip = next(n['IPAddress'] for n in container['NetworkSettings']['Networks'].values()
              if n['IPAddress'])
    auth = base64.b64encode((env.get('GF_SECURITY_ADMIN_USER', 'admin') + ':' +
                            env['GF_SECURITY_ADMIN_PASSWORD']).encode()).decode()

    def call(path, data=None, method=None):
        request = urllib.request.Request('http://' + ip + ':3000' + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'},
            method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            # Ne pas imprimer une réponse susceptible de contenir un webhook.
            raise RuntimeError(f'Grafana {path}: HTTP {error.code}') from None
    return call


def definitions():
    return [
        ('aoria-incidents-delivery', 'Incidents : livraison Slack défaillante', 'Prometheus',
         '(aoria_incidents_failed > 0) or (aoria_incidents_oldest_pending_seconds > 120) or ((aoria_incidents_slack_configured == 0) + 1) or vector(0)',
         '1m', 'Des incidents attendent ou ont épuisé les tentatives. Consulter /admin/incidents.'),
        ('aoria-incidents-monitor', 'Incidents : surveillance indisponible', 'Prometheus',
         '(up{job="incident-notifier"} == 0) + 1 or absent(up{job="incident-notifier"}) or (time() - aoria_incidents_loop_timestamp > 60) or (time() - aoria_incidents_watchdog_timestamp > 180) or (time() - aoria_incidents_worker_timestamp > 90) or vector(0)',
         '1m', 'La collecte documentaire ou la livraison des incidents ne fonctionne plus.'),
        ('aoria-incidents-persistence', 'Incidents : écriture locale impossible', 'Loki',
         'sum(count_over_time({service=~"backend|worker"} |= "aoria_incident_persistence_failed" [5m])) or vector(0)',
         '0s', 'Vérifier le volume des incidents et l’espace disque.'),
        ('aoria-public-probe', 'Parcours public : sonde en échec', 'Prometheus',
         '(1 - aoria_public_probe_success) or absent(aoria_public_probe_success)',
         '1m', 'Une page publique, la santé API ou le contrat de la démo ne répond plus comme attendu.'),
        ('aoria-probe-missing', 'Surveillance publique : sonde indisponible', 'Prometheus',
         '(1 - up{job="public-probe"}) or absent(up{job="public-probe"}) or (time() - aoria_public_probe_timestamp_seconds > bool 180)',
         '1m', 'La sonde publique est indisponible ou ses mesures ont plus de trois minutes.'),
        ('aoria-demo-validation', 'Démo : requête incompatible avec l’API', 'Loki',
         'sum(count_over_time({service="backend"} |= "demo_request_validation_failed" [5m])) or vector(0)',
         '0s', 'Une requête de démonstration a échoué sur le contrat API. Vérifier frontend et backend.'),
        ('aoria-demo-stream', 'Démo : échec du flux de réponse', 'Loki',
         'sum(count_over_time({service="backend"} |= "demo_stream_failed" [5m])) or vector(0)',
         '0s', 'La démo a renvoyé une erreur technique ou un flux incomplet. Consulter les logs.'),
        ('aoria-api-errors', 'API : erreur serveur', 'Loki',
         'sum(count_over_time({service="backend"} | json | event="http_request" | status >= 500 [5m])) or vector(0)',
         '0s', 'Une requête API a reçu une erreur HTTP 5xx.'),
        ('aoria-backend-down', 'API : backend indisponible', 'Prometheus',
         '(1 - up{job="backend"}) or absent(up{job="backend"})',
         '1m', 'Prometheus ne peut plus joindre le backend AORIA.'),
    ]


def main():
    api = api_client()
    folders = api('/api/folders')
    folder = next((f for f in folders if f['uid'] == 'aoria-operations'), None)
    if folder is None:
        api('/api/folders', {'uid': 'aoria-operations', 'title': 'AORIA — Exploitation'})
    datasources = {d['name']: d for d in api('/api/datasources')}
    existing = {r['uid'] for r in api('/api/v1/provisioning/alert-rules')}
    for uid, title, source, expression, duration, description in definitions():
        ds = datasources[source]
        query = {'refId': 'A', 'expr': expression, 'instant': True,
                 'queryType': 'instant', 'editorMode': 'code',
                 'datasource': {'type': ds['type'], 'uid': ds['uid']},
                 'intervalMs': 1000, 'maxDataPoints': 43200}
        condition = {'refId': 'B', 'type': 'threshold', 'expression': 'A',
                     'conditions': [{'type': 'query', 'evaluator': {'type': 'gt', 'params': [0]},
                                     'operator': {'type': 'and'}, 'query': {'params': ['B']},
                                     'reducer': {'type': 'last', 'params': []}}]}
        rule = {'uid': uid, 'title': title, 'folderUID': 'aoria-operations',
                'ruleGroup': 'AORIA public service', 'orgID': 1, 'condition': 'B',
                'for': duration, 'noDataState': 'Alerting', 'execErrState': 'Alerting',
                'labels': {'service': 'aoriarh', 'severity': 'critical'},
                'annotations': {'summary': title, 'description': description},
                'isPaused': False, 'data': [
                    {'refId': 'A', 'relativeTimeRange': {'from': 600, 'to': 0},
                     'datasourceUid': ds['uid'], 'model': query},
                    {'refId': 'B', 'relativeTimeRange': {'from': 0, 'to': 0},
                     'datasourceUid': '__expr__', 'model': condition}]}
        api('/api/v1/provisioning/alert-rules' + ('/' + uid if uid in existing else ''),
            rule, 'PUT' if uid in existing else 'POST')
        print('Règle installée:', uid)
    webhook = os.environ.get('AORIA_SLACK_WEBHOOK_URL')
    if not webhook:
        print('ATTENTION : règles actives, livraison Slack NON configurée (webhook absent).')
        return
    if not webhook.startswith('https://hooks.slack.com/services/'):
        raise RuntimeError('Le webhook doit être une URL entrante Slack officielle.')
    points = api('/api/v1/provisioning/contact-points')
    point = {'uid': 'aoria-slack', 'name': 'AORIA Slack', 'type': 'slack',
             'disableResolveMessage': False, 'settings': {'url': webhook}}
    exists = any(p['uid'] == point['uid'] for p in points)
    api('/api/v1/provisioning/contact-points' + ('/aoria-slack' if exists else ''),
        point, 'PUT' if exists else 'POST')
    policy = api('/api/v1/provisioning/policies')
    routes = [r for r in policy.get('routes', []) if r.get('receiver') != 'AORIA Slack']
    routes.append({'receiver': 'AORIA Slack', 'object_matchers': [['service', '=', 'aoriarh']],
                   'group_by': ['alertname'], 'group_wait': '10s', 'group_interval': '5m',
                   'repeat_interval': '1h'})
    policy['routes'] = routes
    api('/api/v1/provisioning/policies', policy, 'PUT')
    print('Routage Slack installé pour AORIA ; tester la réception avant de conclure.')


if __name__ == '__main__':
    main()
