FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY . /code

# Build the frozen SemanticGuard v2 runtime artifact from the training split only.
# This avoids requiring a generated .joblib file in Git or reusing the held-out test set.
RUN python ml/build_semantic_guard_v2_artifact.py

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
