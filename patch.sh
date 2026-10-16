#!/usr/bin/env bash
# Apply the opportunistic EV solar charging changes to another checkout.
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"
if [[ ! -f config/ev_charge.json || ! -f scripts/plan_ev_charge.py ]]; then
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

base64 -d <<'EV_CHARGE_PATCH' | gzip -d > "$patch_file"
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
EV_CHARGE_PATCH

files=(README.md config/ev_charge.json scripts/plan_ev_charge.py tests/test_plan_ev_charge.py)
if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "EV charging changes are already applied."
  exit 0
fi
if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
  echo "EV charging changes applied. Review with git diff -- ${files[*]}."
  exit 0
fi

base_revision=82a7be06adc4fa3b57c930f09866cbb6c02f7210
if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "Cannot apply the EV patch and its base commit is unavailable; no files were changed." >&2
  exit 1
fi
merge_dir="$(mktemp -d)"
for file_path in "${files[@]}"; do
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
for file_path in "${files[@]}"; do
  if ! git merge-file -p "$file_path" "$merge_dir/base/$file_path" "$merge_dir/desired/$file_path" > "$merge_dir/merged/$file_path"; then
    echo "Cannot safely merge $file_path; no files were changed." >&2
    exit 1
  fi
done
for file_path in "${files[@]}"; do
  cp "$merge_dir/merged/$file_path" "$file_path"
done
echo "EV charging changes merged. Review with git diff -- ${files[*]}."