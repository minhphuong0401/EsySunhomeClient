#!/usr/bin/env bash
set -euo pipefail

cd "${1:-.}"
cd "$(git rev-parse --show-toplevel)"

patch_file="$(mktemp)"
trap 'rm -f "$patch_file"' EXIT

base64 -d <<'SO_FAR_PATCH' | gzip -dc > "$patch_file"
H4sIAAAAAAAAA81X3VLjNhS+z1OoHmYnmdhKCCGhsAF2+GnpULYD6XDBMBthy4kWW/JICpBhMrOX
7XX7hDxJjywntoOhu912p1xg+5xP5/fTURSwMESeN2YakZZimrZIkuCPCt0Uv2qMB/QBrff7JAi6
GHe634edjRu03m73ut2a53nl1bVms7liYX8feb32httHTfsAQTjlvmaCo5jc0h+Z0kLOhuQmovWJ
/XDRPXgW90c8aKDHGkJIUj2VHGmD2qmheQ3VvJKZc8LH9JRxWo/IDY1cFApJfaI02BLSPIivpwQU
ahqG7MFFWlIeuCiR4iP1NQ3QAIUkUtR4bP5HtgEhjoksuoLkfMGVRlLcgzwQ/jSmXGNfUqLpUUTN
V93R0mns5GBOYvoaepKhDQ4rXyQG7YALZ8e2ZL3jdtahJ+bZftaUr884D9UiD2gUQQjGuHmt56V5
8yaDDOmDRt8NIM6nT386aA+Nnn7/Da095tr5CG0XwC5ykohwL6CasEh5VpNlzkKUO2kUosCa6ciU
45fz9z8dHQyPDj8MT4anR8tVaSqlFYmkCcjqJvqh0Z5AahkOvHnINA8D4w3IlNzNE4XKxUS/i8UU
GpOX0dat0XgJmZU5h+XhZB7tjgDH8DmveSv74QfJgs9r4CohvTIhv4wODrq9nDgu4tNFnKai1gc0
mk/jGyrfyzNQ1+2aRtryFG823sqCKmZku2a5FYR+bSuohPCMEijFYj8iSp3ZDWQJZMROEaLB4YHg
GiwYkBJQHumk+dhegwmduTiYsChYNh9Wg7OmwRUIVNaCbm4g35g0qEyadIg2/yXSNJe2/zlf3NKM
NFWEKtWyLhfzBMf1OxJN6SJV0yOgxWC3OE8t19CgTLp0XakYC1zGQpg7dv5so9Hao1ViLU6FTyJ6
oSXj47pDuffuVwj7EdJ9YPE0PpYkLeMhgyNVbaN1NG/M1x5tePORHbr9fs9dh6Hb72+aZ3HomlFC
5RkbT4BPRI7pubhXdW6+lYtonOjZz1QpMqYr7I/gxMx26aEdg/YkvbIgtNIP50JE0Ll27+nTH50u
ZEAfknRC4uTuXaipvEwP3g/QlaxXVQpljLR7Q9Hp5i1Mx6HCqW55EEC1Uo8NdxEPxrhe6kja7T1w
c5yRxPjIp4Ldc+ZvD12VkxkVkoFaGztDFtP5KKPQis1cemkSOyCKlsX2qyqfi5SR13Zf/x9iWe4V
LYHO14viImDt1XVe7JXmnwoSVPU+AvkL3a9UGeEL7TeqYvf/vvFmxZe3Pk+lstqrRovyyoobRWXN
jeIz2v/t4/kKCoRmzgVkBlbN+YcDmBuz08zjHl7wolp7vwjX8uAYbB2SWWWcqbyKC6XDxjFviMWJ
kLqKnWNQn6TaFzj6CsCeMwVEyjC3Fjy7/6RXHTzRcbS4weSS7B60udnrdwnBONjqBf121T2osKZw
FypIzTnQ2TLXofT//r4tyduI8Vs4BaKBAz82YbRzyN1BE0nDgTPROlHbrZYfcLhSBTRidxJzCnpf
CqWEhEOH7z4zpPQsompC6dKQlWBfqb27QbftLNYoX7JEIyX9l521eBK3fDibNIj3u7iLt1oBHD6Z
bBoHOGZmiYMCGlK5+7Zlze7abVxyYi+HEMRG/zm8+Qp86zncgFsTSgL7eiOC2SKvmDCO0p97UFY4
OyHhvwBDvEIN+Q4AAA==
SO_FAR_PATCH

expected_sha=9929154c1c1b4f12f920c9571651e36219068519f7f906cd2c3317b73fc21f5b
if command -v shasum > /dev/null 2>&1; then
  actual_sha="$(shasum -a 256 "$patch_file")"
elif command -v sha256sum > /dev/null 2>&1; then
  actual_sha="$(sha256sum "$patch_file")"
else
  echo "A SHA-256 checksum tool (shasum or sha256sum) is required." >&2
  exit 1
fi
if [[ "${actual_sha%% *}" != "$expected_sha" ]]; then
  echo "Patch checksum mismatch; no files were changed." >&2
  exit 1
fi

if git apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "Consistent so-far labels are already applied."
  exit 0
fi
if ! git apply --check "$patch_file"; then
  echo "Patch does not apply cleanly; no files were changed. Update this checkout and retry." >&2
  exit 1
fi
git apply "$patch_file"
echo "Consistent so-far labels applied. Review with git diff and run python3 -m unittest discover -s tests -q."