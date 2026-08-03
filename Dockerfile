FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py dashboard.html ./

# Persisted state lives here (see docker-compose.yml's volume mount) so it
# survives container restarts/rebuilds instead of redoing the whole backfill
# or losing coach-created rosters.
ENV CACHE_FILE=/app/data/roster_cache.json
ENV ROSTERS_FILE=/app/data/rosters.json
RUN mkdir -p /app/data

EXPOSE 8050

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8050", "--workers", "1", "--timeout", "120"]
