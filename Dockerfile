# Build stage
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files and required package metadata
COPY pyproject.toml uv.lock LICENSE README.md ./

# Sync dependencies (automatically creates virtual environment)
RUN uv sync --frozen --no-dev

# Copy source code
COPY src ./src

# Install the package in production mode
RUN uv pip install .

# Runtime stage
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app

# Install tini for proper signal handling and zombie process reaping
RUN apt-get update && apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/src"

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash castrel && \
    chown -R castrel:castrel /app

USER castrel

# Health check - verify the package can be imported
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import castrel_proxy" || exit 1

# Use tini as init system
ENTRYPOINT ["/usr/bin/tini", "--", "castrel-proxy"]
CMD ["--help"]
