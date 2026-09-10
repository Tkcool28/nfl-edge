#!/usr/bin/env bash
set -euo pipefail

runtime_root="${1:-/var/lib/nfl-edge/prospective_card_log_v1}"
evidence_root="${2:-/var/lib/nfl-edge/prospective_repo_v1}"
production_root="${3:-/root/nfl-edge}"
evidence_branch="${4:-ops/prospective-card-evidence-v1}"

fail() {
  echo "PROSPECTIVE_PERSISTENCE_ERROR: $*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is unavailable"
test -d "${runtime_root}" || fail "runtime evidence root is missing: ${runtime_root}"
test -d "${evidence_root}" || fail "isolated evidence checkout is missing: ${evidence_root}"

resolved_evidence="$(readlink -f "${evidence_root}")"
resolved_production="$(readlink -f "${production_root}")"
test "${resolved_evidence}" != "${resolved_production}" || fail "evidence checkout cannot be production worktree"
case "${resolved_evidence}/" in
  "${resolved_production}/"*) fail "evidence checkout cannot live inside production worktree" ;;
esac
case "${resolved_production}/" in
  "${resolved_evidence}/"*) fail "production worktree cannot live inside evidence checkout" ;;
esac

git -C "${evidence_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || fail "evidence root is not a Git worktree"
current_branch="$(git -C "${evidence_root}" symbolic-ref --quiet --short HEAD)" \
  || fail "evidence checkout is detached"
test "${current_branch}" = "${evidence_branch}" \
  || fail "wrong evidence branch: expected ${evidence_branch}, found ${current_branch}"

# Never begin a new sync on top of uncommitted state. A previous failed push may
# leave committed local evidence; that is handled separately below.
test -z "$(git -C "${evidence_root}" status --porcelain=v1 --untracked-files=all)" \
  || fail "evidence checkout has uncommitted changes"

git -C "${evidence_root}" fetch --quiet origin "refs/heads/${evidence_branch}:refs/remotes/origin/${evidence_branch}" \
  || fail "remote evidence branch must already exist"

remote_ref="origin/${evidence_branch}"
remote_ahead="$(git -C "${evidence_root}" rev-list --count "HEAD..${remote_ref}")"
local_ahead="$(git -C "${evidence_root}" rev-list --count "${remote_ref}..HEAD")"

test "${remote_ahead}" = "0" \
  || fail "remote evidence branch advanced; refusing automatic merge/rebase"

if [ "${local_ahead}" != "0" ]; then
  bad_local="$(
    git -C "${evidence_root}" diff --name-only "${remote_ref}..HEAD" \
      | grep -Ev '^prospective/cards/' || true
  )"
  test -z "${bad_local}" \
    || fail "unpushed local commits modify paths outside prospective/cards"
  # Safe retry for a prior failed push. Never force.
  git -C "${evidence_root}" push --porcelain origin "HEAD:refs/heads/${evidence_branch}"
  git -C "${evidence_root}" fetch --quiet origin "refs/heads/${evidence_branch}:refs/remotes/origin/${evidence_branch}"
  test "$(git -C "${evidence_root}" rev-parse HEAD)" = "$(git -C "${evidence_root}" rev-parse "${remote_ref}")" \
    || fail "local/remote evidence branch mismatch after push retry"
fi

"${NFL_EDGE_PROSPECTIVE_PYTHON:-${production_root}/.venv/bin/python}" "${production_root}/scripts/sync_prospective_evidence_v1.py" sync \
  --runtime-root "${runtime_root}" \
  --evidence-root "${evidence_root}" \
  --production-worktree "${production_root}"

status="$(git -C "${evidence_root}" status --porcelain=v1 --untracked-files=all)"
if [ -z "${status}" ]; then
  echo "PROSPECTIVE_PERSISTENCE_NO_CHANGES"
  exit 0
fi

bad_paths="$(
  printf '%s\n' "${status}" \
    | cut -c4- \
    | grep -Ev '^prospective/cards/' || true
)"
test -z "${bad_paths}" \
  || fail "sync modified paths outside prospective/cards"

git -C "${evidence_root}" add -- prospective/cards

bad_staged="$(
  git -C "${evidence_root}" diff --cached --name-only \
    | grep -Ev '^prospective/cards/' || true
)"
test -z "${bad_staged}" \
  || fail "staged paths escaped prospective/cards"

test -z "$(git -C "${evidence_root}" ls-files --others --exclude-standard)" \
  || fail "untracked files remain after prospective-only staging"
git -C "${evidence_root}" diff --quiet \
  || fail "unstaged tracked changes remain after prospective-only staging"

git -C "${evidence_root}" commit -m "prospective: persist production card evidence"
git -C "${evidence_root}" push --porcelain origin "HEAD:refs/heads/${evidence_branch}"
echo "PROSPECTIVE_PERSISTENCE_PUSHED branch=${evidence_branch} head=$(git -C "${evidence_root}" rev-parse HEAD)"
