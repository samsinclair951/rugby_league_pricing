FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Remove broken Yarn repository from the base image
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    /etc/apt/sources.list.d/yarn.sources

# Install useful system packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        git \
        make \
        build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /workspace