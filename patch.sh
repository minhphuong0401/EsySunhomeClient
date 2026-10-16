#!/usr/bin/env bash
# Apply the Grid Charging table display changes to another checkout.
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"
if [[ ! -f site/app.js || ! -f site/index.html ]]; then
  echo "Run this script from an EsySunhomeClient checkout." >&2
  exit 1
fi

patch_file="$(mktemp)"
merge_dir=""
cleanup() {
  rm -f "$patch_file"
  if [[ -n "$merge_dir" ]]; then
    rm -r "$merge_dir"
  fi
}
trap cleanup EXIT

base64 -d <<'GRID_UI_PATCH' | gzip -d > "$patch_file"
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
qYS0m5w/W+pGaABPKmhUF/0vR+W7MSIYAAA=
GRID_UI_PATCH

files=(site/app.js site/index.html)
if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Grid charging display is already updated."
  exit 0
fi
if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
  echo "Grid charging display updated. Review with git diff -- ${files[*]}."
  exit 0
fi

base_revision=1f2a056bd3efada261a04e9ec02f800a602333b5
if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "Cannot apply the grid UI patch and its base commit is unavailable; no UI files were changed." >&2
  exit 1
fi
merge_dir="$(mktemp -d)"
for file_path in "${files[@]}"; do
  if [[ ! -f "$file_path" ]]; then
    echo "Missing $file_path; no UI files were changed." >&2
    exit 1
  fi
  for folder in base desired merged; do
    mkdir -p "$merge_dir/$folder/$(dirname "$file_path")"
  done
  git show "$base_revision:$file_path" > "$merge_dir/base/$file_path"
  cp "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path"
done
(cd "$merge_dir/desired" && git apply "$patch_file")
for file_path in "${files[@]}"; do
  if ! git merge-file -p "$file_path" "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path" > "$merge_dir/merged/$file_path"; then
    echo "Cannot safely merge $file_path; no UI files were changed." >&2
    exit 1
  fi
done
for file_path in "${files[@]}"; do
  cp "$merge_dir/merged/$file_path" "$file_path"
done
echo "Grid charging display merged. Review with git diff -- ${files[*]}."