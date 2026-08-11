import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.api.public_tools import (
    DismissalToolSummary,
    MutualTerminationToolSummary,
    _email_html,
    _mutual_termination_email_html,
)


def _valid_payload() -> dict:
    return {
        "usage_id": "fbe32de8-7a43-4e3c-87ef-d43c1fd71b13",
        "schema_version": "1",
        "tool_id": "dismissal_indemnity",
        "turnstile_token": "verified-token",
        "agreement_scope": "ccn_0413",
        "professional_category": "non_cadre",
        "salary_mode": "stable_monthly",
        "salary_bracket": "3k_4k",
        "seniority_bracket": "5y_10y",
        "legal_amount_bracket": "10k_25k",
        "agreement_amount_bracket": "25k_50k",
        "selected_amount_bracket": "25k_50k",
        "result_scope": "comparison",
        "outcome": "agreement",
        "has_absences": False,
        "has_variable_compensation": True,
        "has_complex_case": False,
        "viewport": "desktop",
        "browser_language": "fr-FR",
        "timezone": "Europe/Paris",
        "acquisition": {
            "utm_source": "google",
            "utm_medium": "organic",
            "utm_campaign": "outil-licenciement",
            "referrer_domain": "www.google.com",
        },
    }


def test_summary_accepts_only_the_closed_anonymised_contract() -> None:
    summary = DismissalToolSummary.model_validate_json(json.dumps(_valid_payload()))
    assert summary.usage_id == UUID("fbe32de8-7a43-4e3c-87ef-d43c1fd71b13")

    with pytest.raises(ValidationError):
        DismissalToolSummary.model_validate_json(
            json.dumps({**_valid_payload(), "salary_exact": 3456})
        )

    with pytest.raises(ValidationError):
        DismissalToolSummary.model_validate_json(
            json.dumps({**_valid_payload(), "viewport": "smart-fridge"})
        )


def test_email_escapes_acquisition_values_and_never_contains_turnstile() -> None:
    payload = _valid_payload()
    payload["acquisition"]["utm_campaign"] = "<img src=x onerror=alert(1)>"
    summary = DismissalToolSummary.model_validate_json(json.dumps(payload))

    rendered = _email_html(summary)

    assert "<img src=x" not in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "verified-token" not in rendered
    assert "3k 4k" in rendered


def test_hcr_scope_is_accepted_and_labelled() -> None:
    payload = {**_valid_payload(), "agreement_scope": "ccn_1979"}
    summary = DismissalToolSummary.model_validate_json(json.dumps(payload))

    rendered = _email_html(summary)

    assert "HCR (IDCC 1979)" in rendered


def _valid_mutual_termination_payload() -> dict:
    return {
        "usage_id": "7c9e6a8d-75e1-4998-bc7e-45a794706ceb",
        "schema_version": "1",
        "tool_id": "mutual_termination",
        "turnstile_token": "verified-token",
        "result_scope": "detailed_estimate",
        "protected_status": "no",
        "agreement_scope": "supported_ccn",
        "minimum_source": "conventional",
        "selected_amount_bracket": "10k_25k",
        "has_proposed_amount": True,
        "viewport": "desktop",
        "browser_language": "fr-FR",
        "timezone": "Europe/Paris",
        "acquisition": {
            "utm_source": "google",
            "utm_medium": "organic",
            "utm_campaign": "outil-rupture",
            "referrer_domain": "www.google.com",
        },
    }


def test_mutual_termination_summary_is_anonymised_and_closed() -> None:
    summary = MutualTerminationToolSummary.model_validate_json(
        json.dumps(_valid_mutual_termination_payload())
    )
    rendered = _mutual_termination_email_html(summary)

    assert "Rupture conventionnelle" in rendered
    assert "Minimum conventionnel" in rendered
    assert "verified-token" not in rendered

    with pytest.raises(ValidationError):
        MutualTerminationToolSummary.model_validate_json(
            json.dumps(
                {
                    **_valid_mutual_termination_payload(),
                    "reference_salary_exact": 345_678,
                }
            )
        )
