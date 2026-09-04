#!/usr/bin/env bash
set -euo pipefail

# Activate the exact merged frontend/ tree as a versioned Caddy-served release.
# Usage: sync_frontend_v1.sh [repo_root] [frontend_deploy_root]
# Defaults match the integrated production contract.

repo_root="${1:-/root/nfl-edge}"
deploy_root="${2:-/srv/nfl-edge/frontend}"
source_dir="${repo_root}/frontend"
releases_dir="${deploy_root}/releases"
current_link="${deploy_root}/current"

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 2; }
command -v rsync >/dev/null 2>&1 || { echo "rsync is required" >&2; exit 2; }

if [[ ! -d "${repo_root}/.git" ]]; then
    echo "not a Git working tree: ${repo_root}" >&2
    exit 2
fi
if [[ ! -d "${source_dir}" ]]; then
    echo "frontend source missing: ${source_dir}" >&2
    exit 2
fi

# Tracked changes make the release impossible to tie to one reviewed commit.
if ! git -C "${repo_root}" diff --quiet || ! git -C "${repo_root}" diff --cached --quiet; then
    echo "refusing frontend activation with tracked/staged repository changes" >&2
    exit 3
fi

required=(
    index.html
    api.js
    app.js
    ui-core.js
    styles.css
    manifest.webmanifest
    sw.js
    offline.html
    icons/icon-192.png
    icons/icon-512.png
)
for relative in "${required[@]}"; do
    [[ -f "${source_dir}/${relative}" ]] || {
        echo "required frontend asset missing: ${relative}" >&2
        exit 4
    }
done

sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
release_dir="${releases_dir}/${sha}"
previous=""
if [[ -L "${current_link}" ]]; then
    previous="$(readlink -f "${current_link}" || true)"
elif [[ -e "${current_link}" ]]; then
    echo "refusing to replace non-symlink current path: ${current_link}" >&2
    exit 5
fi

mkdir -p "${releases_dir}"

if [[ ! -d "${release_dir}" ]]; then
    stage="${releases_dir}/.${sha}.stage.$$"
    cleanup() { rm -rf "${stage}"; }
    trap cleanup EXIT
    mkdir -p "${stage}"
    rsync --archive --delete "${source_dir}/" "${stage}/"
    chmod -R a+rX,go-w "${stage}"
    mv "${stage}" "${release_dir}"
    trap - EXIT
fi

next_link="${deploy_root}/.current.next.$$"
ln -s "${release_dir}" "${next_link}"
mv -Tf "${next_link}" "${current_link}"

printf 'NFL_EDGE_FRONTEND_ACTIVATED\n'
printf 'repository_sha=%s\n' "${sha}"
printf 'release=%s\n' "${release_dir}"
printf 'previous=%s\n' "${previous:-NONE}"
printf 'current=%s\n' "$(readlink -f "${current_link}")"
