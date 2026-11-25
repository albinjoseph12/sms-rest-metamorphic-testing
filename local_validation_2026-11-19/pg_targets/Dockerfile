# One SMS target with PostgreSQL-backed state, reproducing the campaign VM (ENVIRONMENT.md) inside one offline
# container: Ubuntu 24.04, PostgreSQL 16.15 and Redis 7.0.15 (the current noble archive still carries exactly these),
# CPython 3.11 via uv, target pinned at the commit in TARGET_MANIFEST.md, dependencies installed by the harness's
# own boot.prepare with uv resolving as of 2026-09-12.
FROM ubuntu:24.04
ARG SNAP=20260912T000000Z
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      postgresql-16 redis-server git curl ca-certificates build-essential libpq-dev python3 >/dev/null && rm -rf /var/lib/apt/lists/*
ENV PATH=/root/.local/bin:$PATH SMS_HOME=/opt/sms UV_EXCLUDE_NEWER=2026-09-12T00:00:00Z
RUN (curl -LsSf https://astral.sh/uv/0.12.13/install.sh | sh || curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh) >/dev/null 2>&1 && uv --version
RUN uv python install 3.11.16 2>/dev/null || uv python install 3.11
RUN uv venv -q /opt/harness --python 3.11 && uv pip install -q --python /opt/harness/bin/python httpx==0.28.1 psycopg2-binary==2.9.13
ARG REPO
ARG COMMIT
ARG MANIFEST
RUN mkdir -p /opt/sms/targets /opt/sms/manifests && git clone -q https://github.com/$REPO /opt/sms/targets/$(echo $REPO | tr / _) \
 && cd /opt/sms/targets/$(echo $REPO | tr / _) && git checkout -q $COMMIT && git rev-parse HEAD > /opt/sms/target_commit.txt
COPY harness /opt/sms/harness
COPY $MANIFEST /opt/sms/manifests/
COPY setup_env.sh /opt/sms/setup_env.sh
RUN cd /opt/sms && /opt/harness/bin/python -c "import sys; sys.path.insert(0,'harness'); import boot; m=boot.load('manifests/$MANIFEST'); r=boot.prepare(m); print(r); assert r['ok'], r" \
 && uv pip freeze --python /opt/sms/venvs/*/bin/python > /opt/sms/target_freeze.txt
