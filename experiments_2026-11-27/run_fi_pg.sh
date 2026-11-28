#!/usr/bin/env bash
set -u
BASE=/Users/albinjoseph/sms-research/local_validation_2026-11-19
PG=$BASE/pg_targets
CS=/Users/albinjoseph/sms-research/corrected_sms
OUT=$BASE/results/fault_injection_2026-11-27/v2
mkdir -p "$OUT"

run_pg_fi() {
  local fid=$1 target=$2 mf=$3 variant=$4 patch_py=$5
  local cname="sms-v2-${fid}-${variant}"
  local out_json="$OUT/${fid}_${target}_${variant}.json"
  docker rm -f "$cname" >/dev/null 2>&1
  docker run -d --name "$cname" --network none "sms-pg-${target}:latest" sleep infinity >/dev/null
  docker cp "$PG/setup_local.sh" "$cname":/opt/sms/setup_local.sh >/dev/null
  docker exec "$cname" timeout 120 bash /opt/sms/setup_local.sh > "$OUT/${fid}_${variant}.setup.log" 2>&1
  for p in sms harness run_sms.py; do docker cp "$CS/$p" "$cname":/opt/sms/ >/dev/null; done
  docker cp "$PG/run_local_pg.py" "$cname":/opt/sms/run_local_pg.py >/dev/null
  docker exec "$cname" /opt/harness/bin/python -c "$patch_py" > "$OUT/${fid}_${variant}.patch.log" 2>&1 || { echo "PATCH FAILED $fid"; cat "$OUT/${fid}_${variant}.patch.log"; docker rm -f "$cname" >/dev/null; return 1; }
  local t0=$(date +%s)
  docker exec -w /opt/sms "$cname" timeout 600 /opt/harness/bin/python run_local_pg.py "manifests/$mf" \
      --variant "$variant" --seed 1234 --quiet-window 1.0 --out /opt/sms/results/out.json > "$OUT/${fid}_${variant}.log" 2>&1
  docker cp "$cname":/opt/sms/results/out.json "$out_json" >/dev/null 2>&1 || echo "FAILED $fid $variant"
  docker rm -f "$cname" >/dev/null
  echo "$(date +%H:%M:%S) done $fid ($target $variant) wall=$(( $(date +%s)-t0 ))s"
}

PATCH_FI1='
p = "/opt/sms/targets/nsidnev_fastapi-realworld-example-app/app/api/routes/articles/articles_resource.py"
s = open(p).read()
old = """@router.put(
    "/{slug}",
    response_model=ArticleInResponse,
    name="articles:update-article",
    dependencies=[Depends(check_article_modification_permissions)],
)
async def update_article_by_slug(
    article_update: ArticleInUpdate = Body(..., embed=True, alias="article"),
    current_article: Article = Depends(get_article_by_slug_from_path),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ArticleInResponse:"""
new = """@router.put(
    "/{slug}",
    response_model=ArticleInResponse,
    name="articles:update-article",
)
async def update_article_by_slug(
    article_update: ArticleInUpdate = Body(..., embed=True, alias="article"),
    current_article: Article = Depends(get_article_by_slug_from_path),
    user: User = Depends(get_current_user_authorizer()),
    articles_repo: ArticlesRepository = Depends(get_repository(ArticlesRepository)),
) -> ArticleInResponse:
    if current_article.author.username != user.username:
        await articles_repo.connection.execute("UPDATE articles SET body = \x27fi1_mutated_by_B\x27 WHERE slug = $1", current_article.slug)
        raise HTTPException(status_code=403, detail="not author")"""
assert old in s, "FI1 anchor not found"
open(p, "w").write(s.replace(old, new, 1))
print("FI1 patched OK")
'

PATCH_FI2='
p = "/opt/sms/targets/nsidnev_fastapi-realworld-example-app/app/api/routes/users.py"
s = open(p).read()
s = s.replace("from fastapi import APIRouter, Body, Depends, HTTPException",
              "from typing import Optional\nfrom fastapi import APIRouter, Body, Depends, HTTPException")
old = """async def update_current_user(
    user_update: UserInUpdate = Body(..., embed=True, alias="user"),
    current_user: User = Depends(get_current_user_authorizer()),
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
    settings: AppSettings = Depends(get_app_settings),
) -> UserInResponse:"""
new = """async def update_current_user(
    user_update: UserInUpdate = Body(..., embed=True, alias="user"),
    current_user: Optional[User] = Depends(get_current_user_authorizer(required=False)),
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
    settings: AppSettings = Depends(get_app_settings),
) -> UserInResponse:
    if current_user is None:
        await users_repo.connection.execute("INSERT INTO tags (tag) VALUES (\x27fi2_unauth_leak\x27) ON CONFLICT DO NOTHING")
        raise HTTPException(status_code=401, detail="authentication required")"""
assert old in s, "FI2 anchor not found"
open(p, "w").write(s.replace(old, new, 1))
print("FI2 patched OK")
'

PATCH_FI3='
p = "/opt/sms/targets/guduchango_fastapi-booking/app/api/endpoints.py"
s = open(p).read()
if "from app.models import models" not in s:
    s = "from app.models import models\n" + s
s = s.replace(
    "if not unit:\n        raise HTTPException(status_code=404, detail=\"Unit not found\")",
    "if not unit:\n        db.add(models.Guest(name=\"fi3_orphan\", email=f\"fi3u_{reservation.unit_id}@invalid.local\"))\n        db.commit()\n        raise HTTPException(status_code=404, detail=\"Unit not found\")"
)
s = s.replace(
    "if not guest:\n        raise HTTPException(status_code=404, detail=\"Guest not found\")",
    "if not guest:\n        db.add(models.Guest(name=\"fi3_orphan\", email=f\"fi3g_{reservation.guest_id}@invalid.local\"))\n        db.commit()\n        raise HTTPException(status_code=404, detail=\"Guest not found\")"
)
assert "fi3_orphan" in s, "FI3 anchor not found"
open(p, "w").write(s)
print("FI3 patched OK")
'

# Copy already-verified FI2 full into v2
cp "$BASE/results/fault_injection_2026-11-27/FI2_realworld_full.json" "$OUT/FI2_realworld_full.json"

run_pg_fi FI1 realworld realworld.json full "$PATCH_FI1"
run_pg_fi FI1 realworld realworld.json no-state "$PATCH_FI1"
run_pg_fi FI2 realworld realworld.json no-state "$PATCH_FI2"
run_pg_fi FI3 booking booking.json full "$PATCH_FI3"
run_pg_fi FI3 booking booking.json no-state "$PATCH_FI3"
echo "PG FI COMPLETE"
