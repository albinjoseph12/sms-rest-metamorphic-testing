#!/usr/bin/env bash
cd "${SMS_HOME:-/home/claude/sms}/targets"
clone_one() {
  r="$1"; d=$(echo "$r" | tr / _)
  [ -d "$d" ] && return
  timeout 180 git clone --depth 1 --quiet "https://github.com/$r.git" "$d" 2>/dev/null && echo "OK $r" || echo "FAIL $r"
}
export -f clone_one
cut -f1 /tmp/frames/candidates.txt | xargs -P 6 -I{} bash -c 'clone_one "$@"' _ {}
