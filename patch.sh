#!/usr/bin/env bash
# Apply solar-first EV daytime charging and three-day sufficiency advice to another checkout.
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"
files=(README.md config/ev_charge.json scripts/plan_ev_charge.py site/app.js site/index.html tests/test_plan_ev_charge.py)
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

base64 -d <<'EV_SOLAR_PATCH' | gzip -d > "$patch_file"
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
qvHvbxJa/wZE5u8LQDAAAA==
EV_SOLAR_PATCH

if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "EV solar-priority advice is already updated."
  exit 0
fi
if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
  echo "EV solar-priority advice updated. Review with git diff -- ${files[*]}."
  exit 0
fi

base_revision=f70193fa86524d7da2b1e61c69e7bf6e3042e823
if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "Cannot apply the EV patch and its base commit is unavailable; no files were changed." >&2
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
echo "EV solar-priority advice merged. Review with git diff -- ${files[*]}."