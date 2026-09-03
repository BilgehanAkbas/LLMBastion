FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY . /code

# Build the frozen SemanticGuard v2 runtime artifact from the training split only.
RUN python ml/build_semantic_guard_v2_artifact.py

EXPOSE 8000

# Production schema changes are explicit and versioned through Alembic.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
