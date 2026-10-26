"""Artifact integrity and protocol checks; no judgement of generated content."""

import json
import stat

import pytest

from scripts.audit_answers import compare, digest, parse_sse, write_json


def archive(
    path,
    *,
    runtime=None,
    input_hash="same",
    status="complete",
    protocol_hash="same",
    provenance=None,
):
    path.mkdir()
    write_json(
        path / "manifest.json",
        {
            "format": "aoriarh-answer-reference-v1",
            "mode": "offline_transport_fixtures",
            "protocol_sha256": protocol_hash,
            "provenance": provenance or {"python": "3.12", "dependencies": {"example": "1"}},
        },
    )
    write_json(
        path / "case-example.json",
        {
            "case_id": "example",
            "input_sha256": input_hash,
            "runtime": runtime or {"model": "A"},
            "http_status": 200,
            "event_names": ["chat_done"],
            "errors": [],
            "warnings": [],
            "branch_errors": [],
            "model_calls": [],
            "answer": "  Original\n",
        },
    )
    write_json(
        path / "completion.json",
        {
            "status": status,
            "files_sha256": {file.name: digest(file.read_bytes()) for file in path.glob("*.json")},
        },
    )
    return path


def test_sse_preserves_json_text_and_multiline_data():
    original = "  Réponse\n<script>texte uniquement</script>\u2028\u0085  \n"
    wire = (
        ": heartbeat\r\n\r\n"
        "event: chat_delta\r\n"
        'data: {"content":\r\n'
        f"data: {json.dumps(original, ensure_ascii=False)}}}\r\n\r\n"
    )
    assert parse_sse(wire) == [{"event": "chat_delta", "data": {"content": original}}]


def test_invalid_transport_json_is_not_repaired():
    with pytest.raises(json.JSONDecodeError):
        parse_sse("event: chat_delta\ndata: {broken\n\n")


def test_private_artifact_cannot_be_overwritten(tmp_path):
    target = tmp_path / "raw.json"
    write_json(target, {"answer": "  Original\n"})
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_json(target, {"answer": "replacement"})
    assert json.loads(target.read_text())["answer"] == "  Original\n"


def test_comparison_reports_technical_evidence_without_quality_scores(tmp_path):
    before = archive(tmp_path / "before")
    after = archive(tmp_path / "after")
    report = compare(before, after)
    assert report["compatible_inputs"]
    assert report["scope"] == (
        "technical_only_simulated_transports_no_quality_or_performance_conclusion"
    )
    assert report["cases"][0]["answer_bytes_equal"]


@pytest.mark.parametrize(
    "change,issue",
    [
        ({"input_hash": "other"}, "different_inputs:example"),
        ({"runtime": {"model": "B"}}, "different_runtime:example"),
        ({"status": "failed"}, "incomplete_capture"),
        ({"protocol_hash": "other"}, "different_protocol_sha256"),
        ({"provenance": {"python": "3.13", "dependencies": {"example": "1"}}}, "different_python"),
        (
            {"provenance": {"python": "3.12", "dependencies": {"example": "2"}}},
            "different_dependencies",
        ),
    ],
)
def test_incompatible_captures_are_explicit(tmp_path, change, issue):
    before = archive(tmp_path / "before")
    after = archive(tmp_path / "after", **change)
    report = compare(before, after)
    assert not report["compatible_inputs"]
    assert issue in report["incompatibilities"]


def test_changed_artifact_is_detected_even_if_declared_input_hash_is_unchanged(tmp_path):
    before = archive(tmp_path / "before")
    after = archive(tmp_path / "after")
    artifact = after / "case-example.json"
    data = json.loads(artifact.read_text())
    data["answer"] = "modified"
    artifact.write_text(json.dumps(data))
    report = compare(before, after)
    assert not report["compatible_inputs"]
    assert "changed_artifact:after:case-example.json" in report["incompatibilities"]


def test_missing_case_is_not_omitted_from_comparison_silently(tmp_path):
    before = archive(tmp_path / "before")
    after = archive(tmp_path / "after")
    (after / "case-example.json").unlink()
    report = compare(before, after)
    assert not report["compatible_inputs"]
    assert "different_case_sets" in report["incompatibilities"]
    assert "missing_artifact:after:case-example.json" in report["incompatibilities"]


def test_empty_captures_cannot_be_comparable(tmp_path):
    before = archive(tmp_path / "before")
    after = archive(tmp_path / "after")
    for directory in (before, after):
        (directory / "case-example.json").unlink()
    report = compare(before, after)
    assert not report["compatible_inputs"]
    assert "no_common_cases" in report["incompatibilities"]
