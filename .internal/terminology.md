## Terminology

### General

| Term | Definition |
|------|------------|
| slam ecosystem | A collection of lightweight libraries covering the full lifecycle of foundational models (LLMs, vision, time series etc.): data generation, supervised training, RL, evaluation and experiment monitoring. Consists of `slam-core` (the core library) and domain libraries such as `slam-eval`. |
| slam-eval | The evaluation library of the slam ecosystem, located at `../slam-eval`. It produces all measurements behind VM1-VM6 (TTFT/TPOT records, GPU memory samples, quality scores) via its hydra-configured main script and stores the results as output artifacts. |
| TTFT (time to first token) | The wall-clock time in seconds between sending a request to a deployed model and receiving the first generated token. Measured per request by slam-eval. |
| TPOT (time per output token) | The wall-clock time in seconds per generated output token, measured per request by slam-eval. |
| VRAM | GPU memory usage of the deployment, sampled by slam-eval during the evaluation run. |
| Solution deployment | The vLLM deployment of the model produced by the solution implementation being validated (with `solution_overrides` applied). |
| Baseline deployment | The vLLM deployment of the original model precision with no extra-options, launched through the same solution invocation path as the solution deployment. It serves as the reference for VM6. |
| Validation metric (VM) | A quantity computed by the validation service for a given implementation and used in acceptance criteria: VM1 median TTFT, VM2 q90 TTFT, VM3 median TPOT, VM4 q90 TPOT, VM5 peak VRAM, VM6 accuracy loss. |
| Acceptance criterion (AC) | A condition over one or more validation metrics (e.g. `VM1 < AC1.threshold`) whose evaluation yields a status: accepted, valid or invalid. AC1-AC6 are defined in section 3 of the validation spec. |
| Validation profile | A named, complete validation configuration stored as `config/profiles/<name>.yaml`: the subset of acceptance criteria in scope, per-criterion threshold overrides and the definition of full and partial validation for the profile. The validation spec (section 4) is the source of truth for profiles. |
| Full validation | The complete validation procedure over the profile's datasets; the only scope whose results may certify the "accepted" status. |
| Partial validation | The same validation procedure on a reduced configuration (e.g., a small eval-case collection); its results are diagnostic only. |
| Validation scope | Either full validation or partial validation. |
| Solution invocation contract | The definition (in sections 3.2 and 3.3 of the `llm-deployment` constitution spec) of how the validation service invokes the solution's scripts and what output the solution produces. |
| `solution_overrides` | Whitespace-separated arguments passed by the validation service to the solution's scripts when creating the solution deployment. |

### Validation service components

| Term | Definition |
|------|------------|
| Validation engine | The orchestrator shared by all entry points: resolves the profile and scope, drives the solution runner and the slam-eval adapter, passes measured metric values to the metrics evaluator and delegates response assembly to the response builder. |
| Profile loader | Loads `config/profiles/<name>.yaml`, checks it against the validation spec and exposes the resolved configuration to the validation engine. |
| Solution runner | Clones the solution repository, checks out the commit, applies `solution_overrides` and invokes the solution's scripts; also launches the baseline deployment. |
| slam-eval adapter | The only component interacting with slam-eval: configures and runs the measurement and maps slam-eval output artifacts to raw VM1-VM6 values (computing VM6 as the difference of the solution and baseline deployment quality scores). |
| Metrics evaluator | Computes `computation_status`, `acceptance_status` and the criterion status for every acceptance criterion in scope, from measured metric values and profile-resolved thresholds. |
| Response builder | Assembles the response JSON defined in section 5.1; for CLI runs, writes it to `output_json`. |
| CLI entry points | `validation_cli.py` (full validation) and `validation_cli_partial.py` (partial validation) with the interface defined in section 5.1. |
| HTTP service | `validation_service.py` exposing the `/validate` and `/validate_partial` endpoints defined in section 5.1. |
