FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY api/pyproject.toml api/
RUN pip install -e "api[postgres]" 2>/dev/null || pip install fastapi "uvicorn[standard]" sqlalchemy alembic pydantic pydantic-settings pyjwt bcrypt shapely pyproj pyshp numpy httpx python-multipart reportlab cryptography mcp "psycopg[binary]"
COPY api/ api/
COPY workers/ workers/
COPY console/standalone console/standalone
COPY field-app field-app
COPY ui ui
COPY demo demo
WORKDIR /srv/api
ENV PYTHONPATH=/srv/api:/srv
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
