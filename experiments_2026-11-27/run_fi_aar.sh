#!/usr/bin/env bash
set -u
BASE=/Users/albinjoseph/sms-research/local_validation_2026-11-19
CS=/Users/albinjoseph/sms-research/corrected_sms
OUT=$BASE/results/fault_injection_2026-11-27/v2
mkdir -p "$OUT"

run_aar_fi() {
  local fid=$1 variant=$2 patch_py=$3
  local cname="sms-v2-${fid}-${variant}"
  local out_json="$OUT/${fid}_aar_${variant}.json"
  docker rm -f "$cname" >/dev/null 2>&1
  docker run -d --name "$cname" --network none sms-eng:ba10042 sleep infinity >/dev/null
  for p in sms harness run_sms.py; do docker cp "$CS/$p" "$cname":/opt/sms/ >/dev/null; done
  docker exec "$cname" mkdir -p /opt/sms/manifests
  docker cp "$CS/manifests/auto_any-auto-register.json" "$cname":/opt/sms/manifests/ >/dev/null
  docker cp "$BASE/run_local.py" "$cname":/opt/sms/run_local.py >/dev/null
  docker exec "$cname" /opt/harness/bin/python -c "$patch_py" > "$OUT/${fid}_${variant}.patch.log" 2>&1 || { echo "PATCH FAILED $fid"; cat "$OUT/${fid}_${variant}.patch.log"; docker rm -f "$cname" >/dev/null; return 1; }
  local t0=$(date +%s)
  # Use --quiet-window 0.5 (which already removes the MR5 background-writer FP in half the wall time)
  docker exec -w /opt/sms "$cname" timeout 600 /opt/harness/bin/python run_local.py manifests/auto_any-auto-register.json \
      --variant "$variant" --seed 1234 --quiet-window 0.5 --out /opt/sms/results/out.json > "$OUT/${fid}_${variant}.log" 2>&1
  docker cp "$cname":/opt/sms/results/out.json "$out_json" >/dev/null 2>&1 || echo "FAILED $fid $variant"
  docker rm -f "$cname" >/dev/null
  echo "$(date +%H:%M:%S) done $fid (aar $variant) wall=$(( $(date +%s)-t0 ))s"
}

PATCH_FI4='
p = "/app/api/proxies.py"
s = open(p).read()
old = """@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: int):
    result = service.delete_proxy(proxy_id)
    if not result["ok"]:
        raise HTTPException(404, "代理不存在")
    return result"""
new = """@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: int):
    result = service.delete_proxy(proxy_id)
    if not result["ok"]:
        if proxy_id < 1000:
            service.create_proxy(ProxyCreateCommand(url=f"http://fi4-tombstone-{proxy_id}.local:8080", region="deleted"))
        raise HTTPException(404, "代理不存在")
    return result"""
assert old in s, "FI4 anchor not found"
open(p, "w").write(s.replace(old, new, 1))
print("FI4 patched OK")
'

PATCH_FI5='
p = "/app/api/proxies.py"
s = open(p).read()
old = """@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: int):
    result = service.delete_proxy(proxy_id)
    if not result["ok"]:
        raise HTTPException(404, "代理不存在")
    return result"""
new = """@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: int):
    result = service.delete_proxy(proxy_id)
    if not result["ok"]:
        if proxy_id >= 1000:
            service.create_proxy(ProxyCreateCommand(url=f"http://fi5-absent-{proxy_id}.local:8080", region="audit"))
        raise HTTPException(404, "代理不存在")
    return result"""
assert old in s, "FI5 anchor not found"
open(p, "w").write(s.replace(old, new, 1))
print("FI5 patched OK")
'

run_aar_fi FI4 full "$PATCH_FI4"
run_aar_fi FI4 no-state "$PATCH_FI4"
run_aar_fi FI5 full "$PATCH_FI5"
run_aar_fi FI5 no-state "$PATCH_FI5"
echo "AAR FI COMPLETE"
