FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry==1.8.5 && \
    poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-dev --no-interaction --no-ansi

COPY . .

CMD ["python", "main.py"]
