#!/usr/bin/env bash
# Apply the dashboard section order change to another EsySunhomeClient checkout.
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"
if [[ ! -f config/night_charge.json || ! -f scripts/plan_night_charge.py ]]; then
  echo "Run this script from an EsySunhomeClient checkout." >&2
  exit 1
fi
patch_file="$(mktemp)"
trap 'rm -f "$patch_file"' EXIT

base64 -d <<'PAGE_ORDER_PATCH' | gzip -d > "$patch_file"
H4sIAAAAAAAAE9WUTW4aMRTH95ziaTZtRZzhIyFqRUaJkohEikgE6SJLM34wVofxyDah7HKH3qFX6L5HyUlqDwzMF+mUXdkAf7/v
Z/8Yn06BkBnXQF3FNbo8Yvj9ONDzECZFpZH8hO5Z5+xzu3t83Gt3pp1uG9qtVu/kpEEIKUdpNJvNikgXF0DaJ52jHjTtV7cHFxcN
SD/9GPyQKnXu4AtZUhnxaKYc4KwgBJwxjLy+G3upc99V6GsuIqM0mhttI6VBA660kCsyk2IRO0AlpySkEwxDZJPVuRPxWaCJH1A5
Q6K5DtHx0lgmWoCUoawMRuyZqS1rbzwYf8kJuQ5XOJFi6XiD0d01XN1ejgZ3wwH8/gXXo2cYfR0m3eWdg24yi6o6B5IzSCRTBjD0
uTKdq74bdPeWsC6dofIlj+2gHO+eKg2nkGRQthjq6wUN4YWGC1QwR6oWEhm0el9arbfXH50T830E3De5wBfzmEoEHeAcllwH9hfE
IY0+KJgKib6NboIqDM1mgK7z2KPEMjVR8DESu2a4ghilOZybxCvUn4qT6bv5QZumk1VlJSo190NMW7fBzQipZOWVpTaaTkIkS0lj
pzjC5Ci1sw2SRCnaWUtbSkm2B7JCTRxA+SJGU6MIHW9oJ9R3dVDL+nqz99oOYxFSabaZrLK2172g7ACnJZr1jx+u/tn1Eem3gxxH
qBbhvvEZubwDa1u1sb6eCLYqPz/zhFV57ev99rV5kiJUMY3OnTMnd19wHuvVepLmjr+9/jSJmbevJJu7eAfd5Mr95SFsrv1Wy2Cy
uUVnAZObvxmm7RIk8bNVlHl2ezd+ehg9J4/U4r7TaVvONzun7aMC7nflbZUMxUl1eQdRnGxz1qM4ybSY9JwRKrse3g1un9YYv4HH
+8vh8GZUhHk+xqEw31PJfw3z7Ljd/Lx3MN9J78G8sLlKmOdHuB/mObsdzAvyBuYl9V2Y17DOw7yGQwXMa3iVYV7LqRrmNVyrYV7D
MQvz8grcih1sYV5a5Lswr9zvoTAvl7SGOSmoa5i/+xC2tEzJuKMl2RJ0KoTe8W39L4dw24F3M36G8SIKxBwBI5SzFTCqgokwj8iE
tSYFl2RaKqKxCoQZmFhE2vFS0z9Bcu4VUAwAAA==
PAGE_ORDER_PATCH

if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Dashboard section order is already updated."
  exit 0
fi
if ! git apply --check "$patch_file"; then
  echo "Patch does not apply cleanly. Update this checkout to the matching source version first; no files were changed." >&2
  exit 1
fi
git apply "$patch_file"
echo "Dashboard section order updated. Review with git diff -- site/index.html."