"""Vérifie le client réel contre le modèle serveur, sans LLM ni réseau."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.api.public import PublicAskRequest


def test_real_frontend_request_matches_backend_schema():
    root = Path(__file__).resolve().parents[2]
    available = shutil.which("node") and (root / "frontend/node_modules/typescript").is_dir()
    if not available:
        if os.getenv("CI"):
            pytest.fail("Node et les dépendances frontend sont requis pour le contrat démo en CI")
        pytest.skip("Installer les dépendances frontend pour le test croisé")
    result = subprocess.run(
        ["node", str(root / "frontend/scripts/demo-request-contract.cjs")],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    request = PublicAskRequest.model_validate(payload)
    assert request.message == "Question de contrat technique"
    assert request.turnstile_token == "test-token"
