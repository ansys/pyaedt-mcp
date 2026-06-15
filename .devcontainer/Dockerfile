FROM python:3.12-slim

ENV USERNAME=pyaedt
USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV ON_CODESPACES=false
ENV ON_LOCAL=true
ENV ON_UBUNTU=true
ENV ON_CI=true

RUN apt-get -qq update && apt-get -qq install -y \
    gcc g++ \
    python3-pip \
    python3-venv \
    git \
    && apt-get -qq clean && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash ${USERNAME} \
    && usermod -a -G sudo ${USERNAME}

RUN mkdir -p /home/${USERNAME}/pyaedt-mcp

WORKDIR /home/${USERNAME}
USER ${USERNAME}

COPY requirements.txt requirements.txt

RUN python3 -m venv ./.venv && \
    . ./.venv/bin/activate && \
    pip install --upgrade pip && \
    pip install pre-commit && \
    pip install -r requirements.txt && \
    echo 'source /home/pyaedt/.venv/bin/activate' >> ~/.bashrc && \
    rm requirements.txt

WORKDIR /home/${USERNAME}/pyaedt-mcp
