#!/usr/bin/env bash
# Apply the two-row Vehicle Charging layout to another checkout.
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"
files=(site/app.js site/index.html site/styles.css)
for file_path in "${files[@]}"; do
  if [[ ! -f "$file_path" ]]; then
    echo "Missing $file_path; run this script from an EsySunhomeClient checkout." >&2
    exit 1
  fi
done

patch_file="$(mktemp)"
merge_dir=""
cleanup() {
  rm -f "$patch_file"
  if [[ -n "$merge_dir" ]]; then
    rm -r "$merge_dir"
  fi
}
trap cleanup EXIT

base64 -d <<'EV_LAYOUT_PATCH' | gzip -d > "$patch_file"
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
EV_LAYOUT_PATCH

if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Vehicle Charging layout is already updated."
  exit 0
fi
if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
  echo "Vehicle Charging layout updated. Review with git diff -- ${files[*]}."
  exit 0
fi

base_revision=8b8659184c820baa240333a930c270f72d39bc18
if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "Cannot apply the layout patch and its base commit is unavailable; no files were changed." >&2
  exit 1
fi
merge_dir="$(mktemp -d)"
for file_path in "${files[@]}"; do
  for folder in base desired merged; do
    mkdir -p "$merge_dir/$folder/$(dirname "$file_path")"
  done
  git show "$base_revision:$file_path" > "$merge_dir/base/$file_path"
  cp "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path"
done
(cd "$merge_dir/desired" && git apply "$patch_file")
for file_path in "${files[@]}"; do
  if ! git merge-file -p "$file_path" "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path" > "$merge_dir/merged/$file_path"; then
    echo "Cannot safely merge $file_path; no files were changed." >&2
    exit 1
  fi
done
for file_path in "${files[@]}"; do
  cp "$merge_dir/merged/$file_path" "$file_path"
done
echo "Vehicle Charging layout merged. Review with git diff -- ${files[*]}."