FROM python:3.12-slim

WORKDIR /app

# Install system deps and the app.
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# The generated sql_generated.py is created at build time by
# `pysquirrel generate`, so it must exist before this COPY.
COPY migrations/ migrations/
COPY sql/ sql/
COPY sql_generated.py sql_generated.py
COPY main.py main.py

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
