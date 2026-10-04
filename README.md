# llm-deployment-validation

Validation service for the `llm-deployment` SDD subproject (see
`.internal/validation-spec.md` and `.internal/specs/01-validation-service-kiss-spec.md`).

The service validates an `llm-deployment` implementation against the acceptance
criteria of the validation spec by deploying the solution (and the baseline
defined by the profile's `(repo, commit)` reference), running slam-eval
measurements against the deployed OpenAI-compatible endpoint and evaluating
the acceptance criteria.

## Structure (hydra repo)

- `llm_deployment_validation/` - python package
- `llm_deployment_validation/scripts/` - executable scripts:
  - `validation_cli.py` - full validation CLI
  - `validation_cli_partial.py` - partial validation CLI (diagnostic only)
  - `validation_service.py` - HTTP service (`/validate`, `/validate_partial`)
- `llm_deployment_validation/utils/` - shared helpers
- `config/` - hydra configs; `config/profile/` - validation profiles
- `tests/` - pytest test suite
- `run_linters.sh` - linters (black, isort, pylint, mypy)

## Usage

```bash
python llm_deployment_validation/scripts/validation_cli.py \
  repo=<clonable link to repo> commit=<commit hash> \
  output_json=<path to output json> \
  solution_overrides="<args separated by whitespaces>" profile=default

python llm_deployment_validation/scripts/validation_service.py port=8456 profile=default
# then POST http://localhost:8456/validate or /validate_partial
```

## Measurement stack

The service runs slam-eval from its own environment (slam-core and slam-eval
installed non-editable, pinned in `config/tool_pins.txt`). The solution being
validated always runs in fresh temporary venvs created per run.

## Tests

```bash
pytest
```
