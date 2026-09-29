"""Publication-safety guard: defence in depth against accidental data leaks.

The guard inspects what a public commit of this repository would contain and
reports anything that conflicts with the project's data-rights policy:

1. data files that are publishable only if declared in ``data/demo/demo_manifest.yaml``;
2. release records whose provenance is undeclared, mislabelled, or linked to a
   source not classified as reusable (``config/data_sources.yaml``);
3. price series whose origin is not synthetic or explicitly redistributable;
4. restricted/unresolved-source values left in the public source audit;
5. private data locations, raw data exports and credential files that would be
   published by an ordinary ``git add .``;
6. credential-like strings, personal absolute paths and e-mail addresses in
   publishable text files.

IMPORTANT: passing these checks is NOT legal verification. The guard only
detects known-prohibited categories and obvious mistakes.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.economic_calendar.historical_models import DataOrigin, HistoricalRelease

from .source_registry import (
    RedistributionStatus,
    SourceRegistry,
    load_source_registry,
)

REGISTRY_RELATIVE_PATH = Path("config") / "data_sources.yaml"
DEMO_MANIFEST_RELATIVE_PATH = Path("data") / "demo" / "demo_manifest.yaml"
SOURCE_AUDIT_GLOB = "config/historical_release_audits/*source_audit*.yaml"

PUBLIC_DATA_DIRECTORIES = ("data/demo/",)

PRIVATE_PATH_PREFIXES = (
    "data/historical_releases/",
    "data/raw/",
    "data/processed/",
    "data/reports/",
    "data/private/",
)

PLACEHOLDER_FILE_NAMES = frozenset({".gitkeep", "README.md"})

DATA_FILE_SUFFIXES = frozenset(
    {
        ".csv",
        ".jsonl",
        ".parquet",
        ".feather",
        ".xlsx",
        ".xls",
        ".pkl",
        ".pickle",
        ".h5",
        ".hdf5",
        ".db",
        ".sqlite",
        ".hcc",
        ".hst",
    }
)

CREDENTIAL_FILE_NAMES = frozenset(
    {".env", "credentials.json", "secrets.yaml", "secrets.yml", "id_rsa"}
)
CREDENTIAL_FILE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})

FORBIDDEN_DIRECTORY_PARTS = frozenset(
    {".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)

BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".parquet", ".pyc", ".zip", ".ico"}
)

PUBLISHABLE_PRICE_ORIGINS = frozenset({"synthetic", "authentic_redistributable"})

AUDIT_VALUE_KEYS = frozenset(
    {
        "stored_actual",
        "verified_actual",
        "stored_previous",
        "verified_previous",
        "stored_forecast",
        "verified_forecast",
        "corrected_text",
    }
)

WITHHELD_MARKER = "withheld"

NUMERIC_VALUE_IN_TEXT = re.compile(
    r"(?<![\w.])[-+]?\d+(?:\.\d+)?\s*(?:percent|%|index points|points)\b",
    re.IGNORECASE,
)

URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)]+")

SENSITIVE_TEXT_PATTERNS: dict[str, re.Pattern[str]] = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "API secret key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "credential assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
        r"['\"][^'\"\s]{8,}['\"]"
    ),
    "Windows absolute path": re.compile(r"\b[A-Za-z]:\\\\?[A-Za-z0-9_.$ -]"),
    "personal home-directory path": re.compile(
        r"(?<![\w.:/-])(?:/home/|/Users/)[A-Za-z0-9_.-]+/"
    ),
    "e-mail address": re.compile(
        r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9-]+"
        r"(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
    ),
}

MAX_SCANNED_TEXT_BYTES = 5_000_000


@dataclass(frozen=True, slots=True)
class Finding:
    """One publication-safety problem."""

    check: str
    path: str
    message: str


@dataclass(slots=True)
class GuardReport:
    """Result of a complete publication-safety run."""

    file_listing_method: str
    files_considered: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


# ---------------------------------------------------------------------------
# Demo manifest
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DemoManifestFile(_StrictModel):
    """One publishable data file declared in the demo manifest."""

    path: str = Field(min_length=1)
    kind: Literal["historical_releases", "price_series"]
    data_origin: Literal[
        "synthetic",
        "authentic",
        "authentic_redistributable",
        "authentic_private",
    ]
    source_keys: list[str] = Field(min_length=1)
    time_basis: str | None = None
    description: str = Field(min_length=1)


class DemoManifest(_StrictModel):
    """Declaration of every data file published under data/demo/."""

    schema_version: Literal[1]
    files: list[DemoManifestFile] = Field(min_length=1)


def load_demo_manifest(manifest_path: str | Path) -> DemoManifest:
    """Load and validate the demo manifest."""

    path = Path(manifest_path)

    with path.open("r", encoding="utf-8") as file:
        raw: Any = yaml.safe_load(file)

    return DemoManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# Release-record checks
# ---------------------------------------------------------------------------


def _iter_jsonl_releases(
    path: Path,
) -> Iterator[tuple[int, HistoricalRelease | None, str | None]]:
    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                yield line_number, HistoricalRelease.model_validate_json(line), None
            except ValidationError as exc:
                yield line_number, None, str(exc).splitlines()[0]


def _release_text_fields(release: HistoricalRelease) -> Iterator[str]:
    for value in (release.release_summary, release.notes):
        if value:
            yield value

    for component in release.components:
        for value in (component.actual, component.forecast, component.previous):
            if isinstance(value, str):
                yield value


def check_release_file(
    path: Path,
    registry: SourceRegistry,
    *,
    declared_origin: str,
    declared_source_keys: Iterable[str],
    display_path: str | None = None,
) -> list[Finding]:
    """Check every release in a publishable JSONL file."""

    shown = display_path or path.as_posix()
    allowed_keys = set(declared_source_keys)
    findings: list[Finding] = []

    def add(line_number: int, message: str) -> None:
        findings.append(Finding("release_records", f"{shown}:{line_number}", message))

    for line_number, release, error in _iter_jsonl_releases(path):
        if release is None:
            add(line_number, f"Record fails HistoricalRelease validation: {error}")
            continue

        if release.data_origin is None:
            add(line_number, "data_origin is not declared (synthetic/authentic).")
            continue

        if release.data_origin.value != declared_origin:
            add(
                line_number,
                f"data_origin {release.data_origin.value!r} does not match the "
                f"manifest declaration {declared_origin!r}.",
            )

        urls = [
            url
            for url in (release.official_source_url, release.forecast_source_url)
            if url
        ]
        urls.extend(
            match.group(0)
            for text in _release_text_fields(release)
            for match in URL_IN_TEXT.finditer(text)
        )

        for url in urls:
            source = registry.source_for_url(url)

            if source is None:
                add(line_number, f"URL belongs to no registered source: {url}")
            elif not source.is_publishable:
                add(
                    line_number,
                    f"URL belongs to {source.source_key!r} "
                    f"({source.redistribution_status.value}): {url}",
                )
            elif source.source_key not in allowed_keys:
                add(
                    line_number,
                    f"URL source {source.source_key!r} is not declared for this "
                    f"file in the demo manifest: {url}",
                )

        if release.data_origin == DataOrigin.SYNTHETIC:
            if "SYNTHETIC" not in release.official_source_name.upper():
                add(
                    line_number,
                    "Synthetic records must name their source as SYNTHETIC.",
                )

            continue

        if not release.official_source_url:
            add(line_number, "Authentic records require official_source_url.")

        if not registry.event_key_is_publishable(release.event_key):
            add(
                line_number,
                f"event_key {release.event_key!r} maps to a source that is not "
                "classified as reusable.",
            )

        has_forecast_values = any(
            component.forecast is not None for component in release.components
        )

        if has_forecast_values and not release.forecast_source_url:
            add(
                line_number,
                "Forecast values present without a rights-cleared forecast source.",
            )

    return findings


# ---------------------------------------------------------------------------
# Price-series and manifest checks
# ---------------------------------------------------------------------------

MT5_HEADER_PREFIX = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>"


def check_demo_directory(
    project_root: Path,
    registry: SourceRegistry,
) -> list[Finding]:
    """Check the demo manifest and every data file under ``data/demo``."""

    findings: list[Finding] = []
    manifest_path = project_root / DEMO_MANIFEST_RELATIVE_PATH

    if not manifest_path.is_file():
        return [
            Finding(
                "demo_manifest",
                DEMO_MANIFEST_RELATIVE_PATH.as_posix(),
                "Demo manifest is missing.",
            )
        ]

    try:
        manifest = load_demo_manifest(manifest_path)
    except (ValidationError, yaml.YAMLError) as exc:
        return [
            Finding(
                "demo_manifest",
                DEMO_MANIFEST_RELATIVE_PATH.as_posix(),
                f"Invalid demo manifest: {str(exc).splitlines()[0]}",
            )
        ]

    declared_paths = {entry.path for entry in manifest.files}
    demo_dir = manifest_path.parent

    for data_file in sorted(demo_dir.rglob("*")):
        relative = data_file.relative_to(project_root).as_posix()

        if (
            data_file.is_file()
            and data_file.suffix.lower() in DATA_FILE_SUFFIXES
            and relative not in declared_paths
        ):
            findings.append(
                Finding(
                    "demo_manifest",
                    relative,
                    "Data file is not declared in the demo manifest.",
                )
            )

    for entry in manifest.files:
        path = project_root / entry.path

        if not entry.path.startswith(PUBLIC_DATA_DIRECTORIES):
            findings.append(
                Finding(
                    "demo_manifest",
                    entry.path,
                    "Manifest entries must live under data/demo/.",
                )
            )

        if not path.is_file():
            findings.append(
                Finding("demo_manifest", entry.path, "Declared file does not exist.")
            )
            continue

        for source_key in entry.source_keys:
            try:
                source = registry.get(source_key)
            except KeyError:
                findings.append(
                    Finding(
                        "demo_manifest",
                        entry.path,
                        f"Unknown source_key {source_key!r}.",
                    )
                )
                continue

            if not source.is_publishable:
                findings.append(
                    Finding(
                        "demo_manifest",
                        entry.path,
                        f"Source {source_key!r} is "
                        f"{source.redistribution_status.value}; its data cannot "
                        "be published.",
                    )
                )

            if entry.data_origin == "synthetic" and (
                source.redistribution_status != RedistributionStatus.PROJECT_GENERATED
            ):
                findings.append(
                    Finding(
                        "demo_manifest",
                        entry.path,
                        "Synthetic files may only reference project_generated "
                        "sources.",
                    )
                )

        if entry.kind == "historical_releases":
            if entry.data_origin not in {"synthetic", "authentic"}:
                findings.append(
                    Finding(
                        "demo_manifest",
                        entry.path,
                        "Release files must declare data_origin synthetic or "
                        "authentic.",
                    )
                )
                continue

            findings.extend(
                check_release_file(
                    path,
                    registry,
                    declared_origin=entry.data_origin,
                    declared_source_keys=entry.source_keys,
                    display_path=entry.path,
                )
            )
            continue

        if entry.data_origin not in PUBLISHABLE_PRICE_ORIGINS:
            findings.append(
                Finding(
                    "price_series",
                    entry.path,
                    f"Price data with origin {entry.data_origin!r} must not be "
                    "published (allowed: synthetic, authentic_redistributable).",
                )
            )

        if entry.data_origin == "synthetic" and "SYNTHETIC" not in path.name.upper():
            findings.append(
                Finding(
                    "price_series",
                    entry.path,
                    "Synthetic price files must carry SYNTHETIC in the file name.",
                )
            )

        first_line = path.read_text(encoding="utf-8").splitlines()[:1]

        if not first_line or not first_line[0].startswith(MT5_HEADER_PREFIX):
            findings.append(
                Finding(
                    "price_series",
                    entry.path,
                    "Price file does not use the MT5 export header.",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Source-audit checks
# ---------------------------------------------------------------------------


def _walk_values(node: Any, trail: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_values(value, f"{trail}.{key}" if trail else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_values(value, f"{trail}[{index}]")
    else:
        yield trail, node


def check_source_audit(
    path: Path,
    registry: SourceRegistry,
    *,
    display_path: str | None = None,
) -> list[Finding]:
    """Reject observation values kept for restricted/unresolved sources."""

    shown = display_path or path.as_posix()
    findings: list[Finding] = []

    with path.open("r", encoding="utf-8") as file:
        raw: Any = yaml.safe_load(file)

    audits = raw.get("release_audits", []) if isinstance(raw, dict) else []

    for audit in audits:
        if not isinstance(audit, dict):
            continue

        event_key = str(audit.get("event_key", ""))
        release_id = str(audit.get("release_id", "?"))

        if registry.event_key_is_publishable(event_key):
            continue

        for trail, value in _walk_values(audit):
            leaf_key = trail.rsplit(".", 1)[-1]

            if isinstance(value, str) and value.startswith(WITHHELD_MARKER):
                continue

            if leaf_key in AUDIT_VALUE_KEYS and value is not None:
                findings.append(
                    Finding(
                        "source_audit",
                        shown,
                        f"{release_id}: {trail} holds a value from a "
                        "non-reusable source.",
                    )
                )
            elif isinstance(value, str) and NUMERIC_VALUE_IN_TEXT.search(value):
                findings.append(
                    Finding(
                        "source_audit",
                        shown,
                        f"{release_id}: {trail} quotes a numeric observation "
                        "from a non-reusable source.",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Publishable file listing, path policy and text scan
# ---------------------------------------------------------------------------


def _run_git(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        check=False,
    )


def list_publishable_files(project_root: Path) -> tuple[list[str], str]:
    """Return the files an ordinary ``git add .`` would publish.

    Uses the repository's own index when it is a Git work tree; otherwise it
    simulates ``git add .`` with a throw-away Git directory so ``.gitignore``
    rules are honoured exactly. Falls back to an approximate filesystem walk
    when Git is not installed.
    """

    root = project_root.resolve()

    if shutil.which("git") is None:
        files = [
            path.relative_to(root).as_posix()
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and ".git" not in path.relative_to(root).parts
            and not FORBIDDEN_DIRECTORY_PARTS.intersection(path.relative_to(root).parts)
        ]
        return files, "filesystem walk (git not installed; .gitignore NOT applied)"

    inside = _run_git(["-C", str(root), "rev-parse", "--show-toplevel"])

    if (
        inside.returncode == 0
        and Path(inside.stdout.decode().strip()).resolve() == root
    ):
        listing = _run_git(
            [
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ]
        )
        method = "git index + untracked files not ignored by .gitignore"
    else:
        with tempfile.TemporaryDirectory() as temp_dir:
            git_dir = Path(temp_dir) / "probe.git"
            _run_git(["init", "--quiet", "--bare", str(git_dir)])
            listing = _run_git(
                [
                    f"--git-dir={git_dir}",
                    f"--work-tree={root}",
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ]
            )
        method = "simulated `git add .` (temporary Git directory, .gitignore applied)"

    if listing.returncode != 0:
        raise RuntimeError(
            "git ls-files failed: " + listing.stderr.decode(errors="replace")
        )

    files = sorted(
        {
            name
            for name in listing.stdout.decode("utf-8").split("\0")
            if name and (root / name).is_file()
        }
    )

    return files, method


def check_publishable_paths(files: Iterable[str]) -> list[Finding]:
    """Flag private locations, raw data exports and credential files."""

    findings: list[Finding] = []

    for relative in files:
        path = Path(relative)
        name = path.name

        if FORBIDDEN_DIRECTORY_PARTS.intersection(path.parts):
            findings.append(
                Finding("paths", relative, "Environment/cache file would be published.")
            )
            continue

        if relative.startswith(PRIVATE_PATH_PREFIXES):
            if name not in PLACEHOLDER_FILE_NAMES:
                findings.append(
                    Finding(
                        "paths",
                        relative,
                        "File in a private/generated data location would be "
                        "published.",
                    )
                )
            continue

        if path.suffix.lower() in DATA_FILE_SUFFIXES and not relative.startswith(
            PUBLIC_DATA_DIRECTORIES
        ):
            findings.append(
                Finding(
                    "paths",
                    relative,
                    "Data file outside data/demo/ would be published.",
                )
            )

        if name.lower() in CREDENTIAL_FILE_NAMES or (
            path.suffix.lower() in CREDENTIAL_FILE_SUFFIXES
        ):
            findings.append(
                Finding("paths", relative, "Credential-like file would be published.")
            )

        if "MT5" in name.upper() and "SYNTHETIC" not in name.upper():
            findings.append(
                Finding(
                    "paths",
                    relative,
                    "Broker (MT5) export would be published; only SYNTHETIC "
                    "MT5-format files are allowed.",
                )
            )

    return findings


def check_code_for_restricted_urls(
    project_root: Path,
    files: Iterable[str],
    registry: SourceRegistry,
) -> list[Finding]:
    """Flag Python files that reference restricted/unresolved-source URLs.

    Source URLs are acceptable metadata in YAML audits and documentation, but
    in application code they usually signal an embedded data catalogue (the
    pattern that made the original seed script unpublishable). Test modules
    are exempt because they use such URLs as negative fixtures for this guard;
    they must still never contain restricted observation values.
    """

    findings: list[Finding] = []

    for relative in files:
        if not relative.endswith(".py") or relative.startswith("tests/"):
            continue

        try:
            text = (project_root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for match in URL_IN_TEXT.finditer(text):
            source = registry.source_for_url(match.group(0))

            if source is not None and not source.is_publishable:
                line_number = text.count("\n", 0, match.start()) + 1
                findings.append(
                    Finding(
                        "code_urls",
                        f"{relative}:{line_number}",
                        f"Code references a {source.redistribution_status.value} "
                        f"source ({source.source_key}); embedded catalogue "
                        "content belongs in private data files.",
                    )
                )

    return findings


def scan_text_files(project_root: Path, files: Iterable[str]) -> list[Finding]:
    """Scan publishable text files for credentials, personal paths and e-mails."""

    findings: list[Finding] = []

    for relative in files:
        path = project_root / relative

        if path.suffix.lower() in BINARY_SUFFIXES:
            continue

        try:
            if path.stat().st_size > MAX_SCANNED_TEXT_BYTES:
                continue

            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for label, pattern in SENSITIVE_TEXT_PATTERNS.items():
            for match in pattern.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                findings.append(
                    Finding(
                        "text_scan",
                        f"{relative}:{line_number}",
                        f"Possible {label}.",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_publication_checks(project_root: str | Path) -> GuardReport:
    """Run every publication-safety check for a project checkout."""

    root = Path(project_root).resolve()
    registry = load_source_registry(root / REGISTRY_RELATIVE_PATH)

    files, method = list_publishable_files(root)

    report = GuardReport(file_listing_method=method, files_considered=len(files))
    report.findings.extend(check_publishable_paths(files))
    report.findings.extend(scan_text_files(root, files))
    report.findings.extend(check_code_for_restricted_urls(root, files, registry))
    report.findings.extend(check_demo_directory(root, registry))

    for audit_path in sorted(root.glob(SOURCE_AUDIT_GLOB)):
        report.findings.extend(
            check_source_audit(
                audit_path,
                registry,
                display_path=audit_path.relative_to(root).as_posix(),
            )
        )

    return report


def report_as_json(report: GuardReport) -> str:
    """Serialise a guard report deterministically."""

    return json.dumps(
        {
            "passed": report.passed,
            "file_listing_method": report.file_listing_method,
            "files_considered": report.files_considered,
            "findings": [
                {"check": f.check, "path": f.path, "message": f.message}
                for f in report.findings
            ],
        },
        indent=2,
        sort_keys=True,
    )
