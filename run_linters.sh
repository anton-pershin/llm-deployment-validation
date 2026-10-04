#!/usr/bin/env bash
set -euo pipefail

black llm_deployment_validation/
isort llm_deployment_validation/
pylint llm_deployment_validation/
mypy llm_deployment_validation/
