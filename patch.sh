#!/usr/bin/env bash
# Apply the dashboard load labels and Grid Charging result explanations to another checkout.
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"
if [[ ! -f config/night_charge.json || ! -f scripts/plan_night_charge.py ]]; then
  echo "Run this script from an EsySunhomeClient checkout." >&2
  exit 1
fi
patch_file="$(mktemp)"
trap 'rm -f "$patch_file"' EXIT

base64 -d <<'LOAD_LABEL_PATCH' | gzip -d > "$patch_file"
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
LOAD_LABEL_PATCH

if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Dashboard labels and result explanations are already updated."
  exit 0
fi
if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
  echo "Dashboard labels and result explanations updated. Review with git diff -- README.md site/."
  exit 0
fi

base_revision=01f4397277e1043d498caf227fb017bc6ae70864
if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "The patch base commit is unavailable in this checkout; no files were changed." >&2
  exit 1
fi
merge_dir="$(mktemp -d)"
trap 'rm -f "$patch_file"; rm -r "$merge_dir"' EXIT
for file_path in README.md site/app.js site/index.html site/styles.css; do
  if [[ ! -f "$file_path" ]]; then
    echo "Missing $file_path; no files were changed." >&2
    exit 1
  fi
  for folder in base desired merged; do
    mkdir -p "$merge_dir/$folder/$(dirname "$file_path")"
  done
  git show "$base_revision:$file_path" > "$merge_dir/base/$file_path"
  cp "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path"
done
(cd "$merge_dir/desired" && git apply "$patch_file")
for file_path in README.md site/app.js site/index.html site/styles.css; do
  local_copy="$file_path"
  if [[ "$file_path" == "site/index.html" ]] && grep -Fq 'id="ev-planned-energy"' "$file_path"; then
    local_copy="$merge_dir/normalized-index.html"
    sed -e 's@<link rel="stylesheet" href="styles.css?v=21">@<link rel="stylesheet" href="styles.css?v=22">@' \
        -e 's@<script src="app.js?v=22" defer></script>@<script src="app.js?v=23" defer></script>@' \
        "$file_path" > "$local_copy"
  fi
  if ! git merge-file -p "$local_copy" "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path" > "$merge_dir/merged/$file_path"; then
    echo "Cannot safely merge $file_path; no files were changed. Review this file's differences on the target checkout." >&2
    exit 1
  fi
done
for file_path in README.md site/app.js site/index.html site/styles.css; do
  cp "$merge_dir/merged/$file_path" "$file_path"
done
echo "Dashboard labels and result explanations merged. Review with git diff -- README.md site/."