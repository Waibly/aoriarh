"""Capture the real chat route offline; compare technical evidence without grading.

From backend, using the development dependencies:
  .venv/bin/python -m scripts.audit_answers capture --output ../tmp/answers-reference
  .venv/bin/python -m scripts.audit_answers compare BEFORE AFTER --output comparison.json

Capture uses pytest's isolated SQLite database, local Qdrant and simulated model
transports. It never measures legal answer quality, real API latency or real cost.
There is deliberately no paid/live mode in this first reference tool.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
PROTOCOL = BACKEND / "scripts/audit/answer_cases.json"
CAPTURE_TEST = "tests/test_answer_audit_reference.py::test_capture_http_reference"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    """Private, exclusive writes: never overwrite a previous experiment."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def parse_sse(text: str) -> list[dict]:
    """Decode transport events; JSON string values remain verbatim."""
    events = []
    name = "message"
    data = []
    # SSE recognizes CR and LF, not Unicode line separators inside JSON strings.
    for line in [*text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), ""]:
        if not line:
            if data:
                events.append({"event": name, "data": json.loads("\n".join(data))})
            name, data = "message", []
        elif line.startswith("event:"):
            name = line[6:].removeprefix(" ")
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    return events


def provenance() -> dict:
    paths = sorted(
        {
            *BACKEND.glob("app/**/*.py"),
            *BACKEND.glob("scripts/**/*.py"),
            *BACKEND.glob("scripts/audit/*.json"),
            BACKEND / "tests/test_answer_audit_reference.py",
            BACKEND / "tests/test_answer_audit_tools.py",
            BACKEND / "tests/test_rag_stream_preservation.py",
            BACKEND / "tests/conftest.py",
            BACKEND / "pyproject.toml",
            ROOT / "AGENTS.md",
        }
    )
    versions = {}
    for package in (
        "fastapi",
        "starlette",
        "openai",
        "httpx",
        "pydantic",
        "sqlalchemy",
        "qdrant-client",
        "aiosqlite",
        "pytest",
        "pytest-asyncio",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": git("rev-parse", "HEAD"),
        "working_tree_status": git("status", "--short"),
        "python": platform.python_version(),
        "dependencies": versions,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths},
    }


def capture(output: Path) -> int:
    output = output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    write_json(output / "protocol.json", protocol)
    manifest = {
        "format": "aoriarh-answer-reference-v1",
        "mode": "offline_transport_fixtures",
        "status": "started",
        "protocol_sha256": digest((output / "protocol.json").read_bytes()),
        "provenance": provenance(),
        "limitations": protocol["limitations"],
    }
    source_bundle = output / "source_bundle.zip"
    fd = os.open(source_bundle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with (
        os.fdopen(fd, "wb") as stream,
        zipfile.ZipFile(
            stream,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as bundle,
    ):
        for relative, expected_hash in manifest["provenance"]["source_sha256"].items():
            payload = (ROOT / relative).read_bytes()
            if digest(payload) != expected_hash:
                raise RuntimeError("Source changed while building the reference bundle")
            bundle.writestr(relative, payload)
    write_json(output / "manifest.json", manifest)
    # Even before the fixture installs its network guard, imports receive no
    # working service credentials or application database/index/storage endpoint.
    env = {
        **os.environ,
        "AORIARH_AUDIT_OUTPUT": str(output),
        "POSTGRES_HOST": "offline.invalid",
        "POSTGRES_DB": "offline_reference",
        "POSTGRES_USER": "offline",
        "POSTGRES_PASSWORD": "offline-only",
        "QDRANT_HOST": "offline.invalid",
        "MINIO_ENDPOINT": "offline.invalid:9000",
        "MINIO_ACCESS_KEY": "offline-reference",
        "MINIO_SECRET_KEY": "offline-reference",
        "OPENAI_API_KEY": "offline-reference-no-network",
        "VOYAGE_API_KEY": "offline-reference-no-network",
        "BREVO_API_KEY": "",
        "STRIPE_SECRET_KEY": "",
        "SECURITY_ALERTS_ENABLED": "false",
        "SECRET_KEY": "offline-reference-not-a-production-key",
    }
    # No shell; the test node and all paths are passed as literal arguments.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", CAPTURE_TEST],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    expected = set(protocol["technical_scenarios"])
    recorded = {p.stem for p in output.glob("case-*.json")}
    missing = sorted(expected - {name.removeprefix("case-") for name in recorded})
    changed_sources = [
        relative
        for relative, expected_hash in manifest["provenance"]["source_sha256"].items()
        if not (ROOT / relative).is_file()
        or digest((ROOT / relative).read_bytes()) != expected_hash
    ]
    complete = result.returncode == 0 and not missing and not changed_sources
    write_json(
        output / "completion.json",
        {
            "status": "complete" if complete else "failed",
            "pytest_exit_code": result.returncode,
            "missing_cases": missing,
            "changed_sources_during_capture": changed_sources,
            "files_sha256": {
                path.name: digest(path.read_bytes()) for path in sorted(output.glob("*.json"))
            }
            | {"source_bundle.zip": digest(source_bundle.read_bytes())},
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    print(result.stdout, end="")
    print(f"Capture {'complete' if complete else 'failed'}: {output}")
    return 0 if complete else 1


def compare(before: Path, after: Path) -> dict:
    """Report input compatibility and technical observations, never semantic scores."""

    def read(directory, name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    left, right = [read(path, "manifest.json") for path in (before, after)]
    completions = [read(path, "completion.json") for path in (before, after)]
    issues = []
    for field in ("format", "mode", "protocol_sha256"):
        if left.get(field) != right.get(field):
            issues.append(f"different_{field}")
    for field in ("python", "dependencies"):
        if (left.get("provenance") or {}).get(field) != (right.get("provenance") or {}).get(field):
            issues.append(f"different_{field}")
    if any(item["status"] != "complete" for item in completions):
        issues.append("incomplete_capture")
    for label, path, completion in zip(
        ("before", "after"), (before, after), completions, strict=True
    ):
        hashes = completion.get("files_sha256")
        if not hashes:
            issues.append(f"missing_integrity_manifest:{label}")
        for name, expected_hash in (hashes or {}).items():
            # A manifest may refer only to the files in its own directory.
            if Path(name).name != name or not (path / name).is_file():
                issues.append(f"missing_artifact:{label}:{name}")
            elif digest((path / name).read_bytes()) != expected_hash:
                issues.append(f"changed_artifact:{label}:{name}")
    left_cases = {p.name for p in before.glob("case-*.json")}
    right_cases = {p.name for p in after.glob("case-*.json")}
    if left_cases != right_cases:
        issues.append("different_case_sets")
    rows = []
    for name in sorted(left_cases & right_cases):
        a, b = [read(path, name) for path in (before, after)]
        if a["input_sha256"] != b["input_sha256"]:
            issues.append(f"different_inputs:{a['case_id']}")
        if a["runtime"] != b["runtime"]:
            issues.append(f"different_runtime:{a['case_id']}")
        rows.append(
            {
                "case_id": a["case_id"],
                "http_status": [a["http_status"], b["http_status"]],
                "event_names": [a["event_names"], b["event_names"]],
                "errors": [a["errors"], b["errors"]],
                "warnings": [a.get("warnings", []), b.get("warnings", [])],
                "branch_errors": [a.get("branch_errors", []), b.get("branch_errors", [])],
                "model_calls": [len(a["model_calls"]), len(b["model_calls"])],
                "answer_bytes_equal": a["answer"] == b["answer"],
            }
        )
    if not rows:
        issues.append("no_common_cases")
    return {
        "format": "aoriarh-answer-comparison-v1",
        "compatible_inputs": not issues,
        "incompatibilities": issues,
        "scope": "technical_only_simulated_transports_no_quality_or_performance_conclusion",
        "before": str(before.resolve()),
        "after": str(after.resolve()),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    take = commands.add_parser("capture")
    take.add_argument("--output", type=Path, required=True)
    diff = commands.add_parser("compare")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        return capture(args.output)
    report = compare(args.before, args.after)
    write_json(args.output, report)
    print(f"Technical comparison: {args.output}")
    return 0 if report["compatible_inputs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
