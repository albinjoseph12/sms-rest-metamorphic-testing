FROM python:3.11-slim
RUN pip install --no-cache-dir uv==0.8.17 || pip install --no-cache-dir uv
COPY src /app
WORKDIR /app
# dependencies resolved as of the campaign date (requirements.txt is unpinned)
RUN uv pip install --system --exclude-newer 2026-09-12 -r requirements.txt uvicorn httpx
RUN rm -f /app/account_manager.db
CMD ["python","-m","uvicorn","main:app","--host","0.0.0.0","--port","9110","--log-level","warning"]
