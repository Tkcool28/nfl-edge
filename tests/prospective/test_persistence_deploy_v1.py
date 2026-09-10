from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from nfl_edge.prospective.runtime_v1 import capture_published_product

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
SCRIPT = ROOT / "deploy/scripts/persist_prospective_evidence_v1.sh"
SERVICE = ROOT / "deploy/systemd/nfl-edge-prospective-persistence.service"
TIMER = ROOT / "deploy/systemd/nfl-edge-prospective-persistence.timer"
BRANCH = "ops/prospective-card-evidence-v1"


def _run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


def _git(repo: Path, *args: str) -> str:
    return _run("git", "-C", str(repo), *args).stdout.strip()


def _runtime_fixture(runtime: Path) -> None:
    product = json.loads(FIXTURE.read_text(encoding="utf-8"))
    capture_published_product(
        product,
        runtime_root=runtime,
        published_at_utc="2026-09-02T14:00:05Z",
    )


def _evidence_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    evidence = tmp_path / "evidence"
    _run("git", "init", "--bare", str(remote))
    _run("git", "clone", str(remote), str(evidence))
    _git(evidence, "config", "user.name", "NFL EDGE Prospective Test")
    _git(evidence, "config", "user.email", "prospective-test@example.invalid")
    _git(evidence, "checkout", "-b", BRANCH)
    (evidence / "BASELINE").write_text("isolated evidence branch\n", encoding="utf-8")
    _git(evidence, "add", "BASELINE")
    _git(evidence, "commit", "-m", "test: initialize evidence branch")
    _git(evidence, "push", "-u", "origin", BRANCH)
    return remote, evidence


def test_git_persistence_wrapper_pushes_only_evidence_and_never_dirties_production(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _runtime_fixture(runtime)
    remote, evidence = _evidence_clone(tmp_path)

    before = _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all")
    env = dict(os.environ)
    env["NFL_EDGE_PROSPECTIVE_PYTHON"] = sys.executable

    first = _run(
        "bash",
        str(SCRIPT),
        str(runtime),
        str(evidence),
        str(ROOT),
        BRANCH,
        env=env,
    )
    assert "PROSPECTIVE_PERSISTENCE_PUSHED" in first.stdout
    assert _git(evidence, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all") == before

    changed = _git(evidence, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    assert changed
    assert all(path.startswith("prospective/cards/") for path in changed)
    assert any(path.endswith(".json") for path in changed)

    remote_files = _run(
        "git",
        "--git-dir",
        str(remote),
        "ls-tree",
        "-r",
        "--name-only",
        BRANCH,
    ).stdout.splitlines()
    assert any(path.startswith("prospective/cards/2026/week-01/publications/") for path in remote_files)
    assert "prospective/cards/2026/week-01/episodes.json" in remote_files

    second = _run(
        "bash",
        str(SCRIPT),
        str(runtime),
        str(evidence),
        str(ROOT),
        BRANCH,
        env=env,
    )
    assert "PROSPECTIVE_PERSISTENCE_NO_CHANGES" in second.stdout
    assert _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all") == before


def test_git_persistence_wrapper_refuses_wrong_branch(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _runtime_fixture(runtime)
    _, evidence = _evidence_clone(tmp_path)
    _git(evidence, "checkout", "-b", "wrong-branch")

    env = dict(os.environ)
    env["NFL_EDGE_PROSPECTIVE_PYTHON"] = sys.executable
    result = subprocess.run(
        ["bash", str(SCRIPT), str(runtime), str(evidence), str(ROOT), BRANCH],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "wrong evidence branch" in result.stderr


def test_persistence_deployment_contract_is_isolated_and_non_billable() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    assert "ops/prospective-card-evidence-v1" in script
    assert "grep -Ev '^prospective/cards/'" in script
    assert "git clean" not in script
    assert "push --force" not in script
    assert "rebase" not in script
    assert "HEAD:refs/heads/main" not in script
    assert "ODDS_API_KEY" not in script

    assert "WorkingDirectory=/var/lib/nfl-edge/prospective_repo_v1" in service
    assert "ReadOnlyPaths=/root/nfl-edge /var/lib/nfl-edge/prospective_card_log_v1" in service
    assert "ReadWritePaths=/var/lib/nfl-edge/prospective_repo_v1" in service
    assert "ExecStart=/bin/bash /root/nfl-edge/deploy/scripts/persist_prospective_evidence_v1.sh" in service
    assert "ODDS_API_KEY" not in service
    assert "systemctl restart" not in service

    assert "OnCalendar=*-*-* 00:20:00 UTC" in timer
    assert "OnCalendar=*-*-* 12:20:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "nfl-edge-prospective-persistence.service" in timer
    assert "ODDS_API_KEY" not in timer
