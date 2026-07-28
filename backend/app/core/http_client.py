"""Client HTTP asynchrone partagé pour les appels du chemin de requête.

Créer un httpx.AsyncClient PAR APPEL (« async with AsyncClient() ») refait un
handshake TCP+TLS à chaque fois : mesuré à l'audit du 27/07/2026, une grosse
part des 300-450 ms de chaque embedding Voyage (×4-6 par question). Ce module
fournit un client persistant avec pool de connexions keep-alive.

Le client est cachetté PAR EVENT LOOP : en prod chaque worker uvicorn n'a
qu'une loop (un seul client), mais les tests créent une loop par test — un
client lié à une loop fermée déclencherait des erreurs.
"""
from __future__ import annotations

import asyncio

import httpx

_clients: dict[int, httpx.AsyncClient] = {}


def get_shared_async_client() -> httpx.AsyncClient:
    """Client httpx partagé (keep-alive) pour la loop courante.

    Ne PAS l'utiliser en context manager ni le fermer : il vit aussi
    longtemps que la loop. Les timeouts par défaut restent ceux du client ;
    passer un timeout par requête si un appel doit être plus strict.
    """
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=30.0,
            ),
        )
        _clients[loop_id] = client
    return client
