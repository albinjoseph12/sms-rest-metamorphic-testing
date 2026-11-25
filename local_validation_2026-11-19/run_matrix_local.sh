#!/usr/bin/env bash
# any-auto-register: the campaign's 11 configurations, each with the original oracle and with the
# quiescence-controlled oracle, every run in a fresh offline container.
set -u
cd "$(dirname "$0")"
OUT=results/engine; mkdir -p $OUT
CS=~/sms-research/corrected_sms
run() { # variant seed oracle
  local v=$1 s=$2 o=$3 f="$OUT/any-auto-register_${1}_s${2}_${3}.json"
  [ -s "$f" ] && { echo "skip $f"; return; }
  docker rm -f sms-eng >/dev/null 2>&1
  docker run -d --name sms-eng --network none sms-eng:ba10042 sleep infinity >/dev/null
  for p in sms harness run_sms.py; do docker cp "$CS/$p" sms-eng:/opt/sms/ ; done
  docker exec sms-eng mkdir -p /opt/sms/manifests
  docker cp "$CS/manifests/auto_any-auto-register.json" sms-eng:/opt/sms/manifests/
  docker cp run_local.py sms-eng:/opt/sms/run_local.py
  local q=""; [ "$o" = quiet ] && q="--quiet-window 1.0"
  local t0=$(date +%s)
  docker exec -w /opt/sms sms-eng /opt/harness/bin/python run_local.py manifests/auto_any-auto-register.json \
      --variant $v --seed $s $q --out /opt/sms/results/out.json > "$OUT/${v}_s${s}_${o}.log" 2>&1
  docker cp sms-eng:/opt/sms/results/out.json "$f" 2>/dev/null || echo "FAILED $v $s $o"
  docker cp sms-eng:/opt/sms/run/any-auto-register.log "$OUT/${v}_s${s}_${o}.server.log" 2>/dev/null
  docker rm -f sms-eng >/dev/null
  echo "$(date +%H:%M:%S) done $v s$s $o $(( $(date +%s)-t0 ))s"
}
if [ $# -eq 3 ]; then run "$@"; exit; fi
for o in ${ORACLES:-original quiet}; do
  for s in 1234 2718 3141 4142 5772; do run full $s $o; done
  for v in no-state no-contract; do for s in 1234 2718 3141; do run $v $s $o; done; done
done
echo ALL DONE
