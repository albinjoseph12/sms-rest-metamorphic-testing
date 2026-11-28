#!/usr/bin/env bash
set -u
cd /Users/albinjoseph/sms-research/local_validation_2026-11-19
OUT=results/quiescence_sweep_2026-11-27
CS=/Users/albinjoseph/sms-research/corrected_sms

for w in 0.25 0.5 1.0 2.0 5.0; do
  f="$OUT/aar_full_s1234_q${w}.json"
  cname="sms-qs-${w//./_}"
  docker rm -f "$cname" >/dev/null 2>&1
  docker run -d --name "$cname" --network none sms-eng:ba10042 sleep infinity >/dev/null
  for p in sms harness run_sms.py; do docker cp "$CS/$p" "$cname":/opt/sms/ >/dev/null; done
  docker exec "$cname" mkdir -p /opt/sms/manifests
  docker cp "$CS/manifests/auto_any-auto-register.json" "$cname":/opt/sms/manifests/ >/dev/null
  docker cp run_local.py "$cname":/opt/sms/run_local.py >/dev/null
  t0=$(date +%s)
  docker exec -w /opt/sms "$cname" /opt/harness/bin/python run_local.py manifests/auto_any-auto-register.json \
      --variant full --seed 1234 --quiet-window "$w" --out /opt/sms/results/out.json > "$OUT/q${w}.log" 2>&1
  docker cp "$cname":/opt/sms/results/out.json "$f" >/dev/null 2>&1 || echo "FAILED q=$w"
  docker rm -f "$cname" >/dev/null
  echo "$(date +%H:%M:%S) done q=${w}s wall=$(( $(date +%s)-t0 ))s"
done
echo "QUIESCENCE SWEEP COMPLETE"
