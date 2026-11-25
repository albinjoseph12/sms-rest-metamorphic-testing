#!/usr/bin/env bash
# The campaign's 11 configurations for each PostgreSQL-backed target, with the original oracle and with the
# quiescence-controlled oracle; every run in a fresh offline container (CPUs 8-13, away from other benchmarks).
#   run_pg_matrix.sh <image-suffix> <manifest> [variant seed oracle]
set -u
cd "$(dirname "$0")"; CS=~/sms-research/corrected_sms
T=$1; MF=$2; OUT=results/$T; mkdir -p $OUT
run() { # variant seed oracle
  local v=$1 s=$2 o=$3 f="$OUT/${T}_${1}_s${2}_${3}.json"
  [ -s "$f" ] && { echo "skip $f"; return; }
  docker rm -f sms-pg >/dev/null 2>&1
  docker run -d --name sms-pg --network none --cpuset-cpus 8-13 sms-pg-$T sleep infinity >/dev/null
  docker cp setup_local.sh sms-pg:/opt/sms/setup_local.sh >/dev/null; docker exec sms-pg timeout 120 bash /opt/sms/setup_local.sh > "$OUT/${v}_s${s}_${o}.setup.log" 2>&1 || echo "SETUP FAILED $T $v $s $o"
  for p in sms harness run_sms.py; do docker cp "$CS/$p" sms-pg:/opt/sms/ >/dev/null; done
  docker cp run_local_pg.py sms-pg:/opt/sms/run_local_pg.py >/dev/null
  local q=""; [ "$o" = quiet ] && q="--quiet-window 1.0"
  local t0=$(date +%s)
  docker exec -w /opt/sms sms-pg timeout 10800 /opt/harness/bin/python run_local_pg.py manifests/$MF \
      --variant $v --seed $s $q --out /opt/sms/results/out.json > "$OUT/${v}_s${s}_${o}.log" 2>&1
  docker cp sms-pg:/opt/sms/results/out.json "$f" >/dev/null 2>&1 || echo "FAILED $T $v $s $o"
  docker exec sms-pg bash -c "cat /opt/sms/run/*.log" > "$OUT/${v}_s${s}_${o}.server.log" 2>/dev/null
  docker rm -f sms-pg >/dev/null
  echo "$(date +%H:%M:%S) done $T $v s$s $o $(( $(date +%s)-t0 ))s"
}
if [ $# -eq 5 ]; then run "$3" "$4" "$5"; exit; fi
for o in original quiet; do
  for s in 1234 2718 3141 4142 5772; do run full $s $o; done
  for v in no-state no-contract; do for s in 1234 2718 3141; do run $v $s $o; done; done
done
echo "ALL DONE $T"
