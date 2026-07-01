#!/bin/bash
set -e

echo "Starting local development container"

echo "Activating virtual environment..."
ln -s /home/pyaedt/.venv /home/pyaedt/pyaedt-mcp/.venv_pyaedt && echo "Linking venv original dir"
# shellcheck disable=SC1091
source ./.venv_pyaedt/bin/activate

echo "Installing PyAEDT-MCP package and dependencies for development"
git fetch && git pull
pip install -e .[tests]

echo "Setting pre-commit..."
pre-commit install --install-hooks

echo "Done! Enjoy PyAEDT!"
