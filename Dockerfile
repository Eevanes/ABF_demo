FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.18
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV ARENA_DATA_DIR=/data
EXPOSE 8765
CMD ["uv", "run", "--frozen", "--no-dev", "arena", "serve", "--host", "0.0.0.0", "--port", "8765"]
