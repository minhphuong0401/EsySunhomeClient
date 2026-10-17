#!/usr/bin/env bash
# Apply the Grid Charging date and charge-plan labels to another checkout.
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

base64 -d <<'GRID_DATE_PATCH' | gzip -d > "$patch_file"
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
GRID_DATE_PATCH

if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Grid charging date labels are already updated."
  exit 0
fi
if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
  echo "Grid charging date labels updated. Review with git diff -- ${files[*]}."
  exit 0
fi

base_revision=9a776cc901c9085f60fe337c54b6759094696863
if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "Cannot apply the patch and its base commit is unavailable; no files were changed." >&2
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
echo "Grid charging date labels merged. Review with git diff -- ${files[*]}."