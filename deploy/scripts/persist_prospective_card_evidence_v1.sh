#!/usr/bin/env bash
set -euo pipefail

: "${NFL_EDGE_REPO_ROOT:=/root/nfl-edge}"
: "${NFL_EDGE_PROSPECTIVE_RUNTIME_ROOT:=/var/lib/nfl-edge/prospective_card_log_v1}"
: "${NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE:?set NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE}"
: "${NFL_EDGE_PROSPECTIVE_EVIDENCE_BRANCH:=prospective-evidence-v1}"
: "${NFL_EDGE_PROSPECTIVE_SEASON:?set NFL_EDGE_PROSPECTIVE_SEASON}"
: "${NFL_EDGE_PROSPECTIVE_WEEK:?set NFL_EDGE_PROSPECTIVE_WEEK}"

LOCK_FILE="${NFL_EDGE_PROSPECTIVE_PERSIST_LOCK:-/var/lib/nfl-edge/prospective_card_log_v1/.git-persist.lock}"
mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo '{"status":"LOCKED"}'
  exit 75
fi

if [[ ! -d "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" ]]; then
  echo "evidence worktree does not exist: $NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" >&2
  exit 2
fi

current_branch="$(git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" branch --show-current)"
if [[ "$current_branch" != "$NFL_EDGE_PROSPECTIVE_EVIDENCE_BRANCH" ]]; then
  echo "refusing persistence from unexpected branch: $current_branch" >&2
  exit 3
fi

if [[ -n "$(git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" status --porcelain)" ]]; then
  echo "evidence worktree is dirty before sync; refusing to mix changes" >&2
  exit 4
fi

# Credentials are never passed on the command line. The remote must already be
# authenticated through the VPS's approved Git mechanism.
git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" fetch --quiet origin "$NFL_EDGE_PROSPECTIVE_EVIDENCE_BRANCH"
git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" merge --ff-only --quiet "origin/$NFL_EDGE_PROSPECTIVE_EVIDENCE_BRANCH"

PYTHONPATH="$NFL_EDGE_REPO_ROOT/src" \
  "$NFL_EDGE_REPO_ROOT/.venv/bin/python" \
  "$NFL_EDGE_REPO_ROOT/scripts/sync_prospective_card_evidence_v1.py" \
  --runtime-root "$NFL_EDGE_PROSPECTIVE_RUNTIME_ROOT" \
  --evidence-repo-root "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" \
  --season "$NFL_EDGE_PROSPECTIVE_SEASON" \
  --week "$NFL_EDGE_PROSPECTIVE_WEEK"

git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" add -- prospective/cards

mapfile -t staged_paths < <(git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" diff --cached --name-only)
if (( ${#staged_paths[@]} == 0 )); then
  echo '{"status":"NO_CHANGES"}'
  exit 0
fi

for path in "${staged_paths[@]}"; do
  case "$path" in
    prospective/cards/*) ;;
    *)
      echo "refusing staged path outside prospective/cards: $path" >&2
      git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" reset --quiet
      exit 5
      ;;
  esac
done

commit_message="prospective: sync ${NFL_EDGE_PROSPECTIVE_SEASON} week ${NFL_EDGE_PROSPECTIVE_WEEK} evidence"
git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" commit --quiet -m "$commit_message"
git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" push --quiet origin "HEAD:$NFL_EDGE_PROSPECTIVE_EVIDENCE_BRANCH"

printf '{"status":"PUSHED","branch":"%s","head":"%s"}\n' \
  "$NFL_EDGE_PROSPECTIVE_EVIDENCE_BRANCH" \
  "$(git -C "$NFL_EDGE_PROSPECTIVE_EVIDENCE_WORKTREE" rev-parse HEAD)"
