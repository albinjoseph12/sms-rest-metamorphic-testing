#!/usr/bin/env python3
"""
Sampling frame construction and randomised target selection.

Frame F2 is the repository index published by Kludex/awesome-fastapi-projects (repos_index.json),
a scraped catalogue of public GitHub projects that depend on FastAPI, with per-repository
dependency lists and star counts. Eligibility is decided mechanically from that metadata:

  E1  depends on fastapi
  E2  depends on at least one relational persistence library
      (sqlalchemy, sqlmodel, tortoise-orm, gino, databases, asyncpg, psycopg2, aiosqlite, alembic)
  E3  star count in [100, 20000]  - lower bound excludes abandoned scratch repositories,
      upper bound excludes very large platforms that cannot be provisioned in the evaluation environment
  E4  not already present in frame F1 (the awesome-fastapi / awesome-flask application lists)

Eligible repositories are then permuted with a fixed seed (SEED) and attempted in that order;
targets enter the study in permutation order until the target-count budget is met. Selection is
therefore independent of anything we observe about a repository's defects.
"""
import json, os, random, sys

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
SEED = 20260906
INDEX = f"{SMS_HOME}/targets/Kludex_awesome-fastapi-projects/repos_index.json"
F1 = "/tmp/frames/candidates.txt"
REL = {"sqlalchemy", "sqlmodel", "tortoise-orm", "tortoise", "gino", "databases", "asyncpg",
       "psycopg2", "psycopg2-binary", "psycopg", "aiosqlite", "alembic", "sqlalchemy-utils"}


def main():
    repos = json.load(open(INDEX))["repos"]
    f1 = {l.split("\t")[0].lower() for l in open(F1).read().strip().split("\n")}
    elig = []
    for r in repos:
        deps = {d["name"].lower() for d in r.get("dependencies", [])}
        slug = r["url"].replace("https://github.com/", "").strip("/")
        e1 = "fastapi" in deps
        e2 = bool(deps & REL)
        e3 = 100 <= r.get("stars", 0) <= 20000
        e4 = slug.lower() not in f1
        if e1 and e2 and e3 and e4:
            elig.append({"repo": slug, "stars": r["stars"], "n_deps": len(deps),
                         "rel": sorted(deps & REL)[:4]})
    rng = random.Random(SEED)
    rng.shuffle(elig)
    json.dump({"seed": SEED, "n_index": len(repos), "n_eligible": len(elig), "order": elig},
              open(f"{SMS_HOME}/frame2_order.json", "w"), indent=1)
    print(f"index={len(repos)}  eligible={len(elig)}  seed={SEED}")
    for i, e in enumerate(elig[:40]):
        print(f"{i:3d} {e['repo']:55s} {e['stars']:6d} {','.join(e['rel'])}")


if __name__ == "__main__":
    main()
