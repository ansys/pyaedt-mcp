# PyAEDT MCP Server Dockerfile
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml LICENSE README.md ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd -m -s /bin/bash pyaedt && \
    chown -R pyaedt:pyaedt /app

USER pyaedt

# Default command - STDIO transport
CMD ["ansys-aedt-mcp"]

# Labels
LABEL maintainer="PyAnsys Team"
LABEL description="PyAEDT MCP Server for AI-driven AEDT automation"
LABEL version="0.1.0"
