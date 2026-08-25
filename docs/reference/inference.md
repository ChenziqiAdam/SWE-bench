# Inference API Reference

This section documents the various tools available for running inference with SWE-bench datasets.

## Overview

The inference module provides tools to generate model completions for SWE-bench tasks using:
- API-based models (OpenAI, Anthropic)
- Local models (SWE-Llama)
- Live inference on open GitHub issues

In particular, we provide the following important scripts and sub-packages:

- `make_datasets`: Contains scripts to generate new datasets for SWE-bench inference with your own prompts and issues
- `run_api.py`: Generates completions using API models (OpenAI, Anthropic) for a given dataset
- `run_llama.py`: Runs inference using Llama models (e.g., SWE-Llama)
- `run_live.py`: Generates model completions for new issues on GitHub in real time

## Installation

Depending on your inference needs, you can install different dependency sets:

```bash
# For dataset generation and API-based inference
pip install -e ".[datasets]"

# For local model inference (requires GPU with CUDA)
pip install -e ".[inference]"
```

## Available Tools

### Dataset Generation (`make_datasets`)

This package contains scripts to generate new datasets for SWE-bench inference with custom prompts and issues. The datasets follow the format required for SWE-bench evaluation.

For detailed usage instructions, see the [Make Datasets Guide](../guides/create_rag_datasets.md).

### Running API Inference (`run_api.py`)

This script runs inference on a dataset using either the OpenAI or Anthropic API. It sorts instances by length and continually writes outputs to a specified file, so the script can be stopped and restarted without losing progress.

```bash
# Example with Anthropic Claude
export ANTHROPIC_API_KEY=<your key>
python -m swebench.inference.run_api \
    --dataset_name_or_path princeton-nlp/SWE-bench_oracle \
    --model_name_or_path claude-2 \
    --output_dir ./outputs
```

#### Parameters

- `--dataset_name_or_path`: HuggingFace dataset name or local path
- `--model_name_or_path`: Model name (e.g., "gpt-4", "claude-2")
- `--output_dir`: Directory to save model outputs
- `--split`: Dataset split to use (default: "test")
- `--shard_id`, `--num_shards`: To process only a portion of data
- `--model_args`: Comma-separated key=value pairs (e.g., "temperature=0.2,top_p=0.95")
- `--max_cost`: Maximum spending limit for API calls

### Running Local Inference (`run_llama.py`)

This script is similar to `run_api.py` but designed to run inference using Llama models locally. You can use it with [SWE-Llama](https://huggingface.co/princeton-nlp/SWE-Llama-13b) or other compatible models.

```bash
python -m swebench.inference.run_llama \
    --dataset_path princeton-nlp/SWE-bench_oracle \
    --model_name_or_path princeton-nlp/SWE-Llama-13b \
    --output_dir ./outputs \
    --temperature 0
```

#### Parameters

- `--dataset_path`: HuggingFace dataset name or local path
- `--model_name_or_path`: Local or HuggingFace model path
- `--output_dir`: Directory to save model outputs
- `--split`: Dataset split to use (default: "test")
- `--shard_id`, `--num_shards`: For processing only a portion of data
- `--temperature`: Sampling temperature (default: 0)
- `--top_p`: Top-p sampling parameter (default: 1)
- `--peft_path`: Path to PEFT adapter

### Live Inference on GitHub Issues (`run_live.py`)

This tool allows you to apply SWE-bench models to real, open GitHub issues. It can be used to test models on new, unseen issues without the need for manual dataset creation.

```bash
export OPENAI_API_KEY=<your key>
python -m swebench.inference.run_live \
    --model_name gpt-3.5-turbo-1106 \
    --issue_url https://github.com/huggingface/transformers/issues/26706
```

#### Prerequisites

For live inference, you'll need to install additional dependencies:
- [Pyserini](https://github.com/castorini/pyserini): For BM25 retrieval
- [Faiss](https://github.com/facebookresearch/faiss): For vector search

Follow the installation instructions on their respective GitHub repositories:
- Pyserini: [Installation Guide](https://github.com/castorini/pyserini/blob/master/docs/installation.md)
- Faiss: [Installation Guide](https://github.com/facebookresearch/faiss/blob/main/INSTALL.md)

## Output Format

All inference scripts produce outputs in a format compatible with the SWE-bench evaluation harness. The output contains the model's generated patch for each issue, which can then be evaluated using the evaluation harness.

## Tips and Best Practices

### mini-swe-agent host backend

Install the external CLI separately; it is not a required SWE-bench package
dependency:

```bash
uv pip install mini-swe-agent
```

The `mini_swe_agent` backend assumes the official mini-swe-agent v2
[`mini` interface](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/run/mini.py)
and also discovers its equivalent `mini-swe-agent` console script. It supports
`fix`, `test_generation`, and `coverage_generation` in disposable,
history-isolated local clones:

```bash
# Issue fix (use --eval_mode test_generation for regression-test generation)
python -m swebench.eval_pipeline.run_pipeline \
  --agent_backend mini_swe_agent \
  --mini_swe_agent_model openai/gpt-5 \
  --eval_mode fix

# Standalone coverage generation
python -m swebench.eval_pipeline.run_pipeline \
  --agent_backend mini_swe_agent \
  --eval_mode coverage_generation \
  --repo_url https://github.com/owner/repository.git \
  --base_commit <full-commit-sha>
```

`--mini_swe_agent_model` falls back to `--model`. Optional controls are
`--mini_swe_agent_config`, `--mini_swe_agent_timeout` (900 seconds),
`--mini_swe_agent_command_timeout` (300 seconds), and
`--mini_swe_agent_cost_limit` (0 disables the limit). A custom config may
change agent/model behavior, but the pipeline always overrides its environment
to mini-swe-agent's local host environment and the disposable clone.

For an OpenAI-compatible `--endpoint`, the backend configures LiteLLM's
`model.model_kwargs.api_base` and prefixes an unqualified model with `openai/`.
The API key is passed only through `OPENAI_API_KEY`; it is not written to the
generated configuration, trajectory, or logs. With the default `model-only`
policy, use a loopback endpoint such as `http://127.0.0.1:4000/v1`; direct
provider access requires the explicitly unsafe `unrestricted` debugging mode.
Nested mini-swe-agent Docker environments are intentionally unsupported under
`model-only`; this integration always uses the guarded host CLI.

- When running inference on large datasets, use sharding to split the workload
- For API models, monitor costs carefully and set appropriate `--max_cost` limits
- For local models, ensure you have sufficient GPU memory for the model size
- Save intermediate outputs frequently to avoid losing progress
- When running live inference, ensure your retrieval corpus is appropriate for the repository of the issue 
- For Claude Code runs through LiteLLM, start LiteLLM separately before launching
  the SWE-bench pipeline. Claude Code expects an Anthropic-compatible endpoint,
  so point the pipeline `--endpoint` at the LiteLLM proxy, for example
  `http://127.0.0.1:4000`.
- Keep provider keys in the proxy environment. For a DeepSeek-backed LiteLLM
  proxy, export `DEEPSEEK_API_KEY` where LiteLLM runs; pass `--api_key` to the
  SWE-bench pipeline only if the proxy itself requires client authentication.
- Before processing the first uncached Claude Code instance, the pipeline sends
  one authenticated, minimal request to the endpoint's `/v1/messages` route
  through the same network guard. It aborts before inference if the gateway is
  unreachable, the key/model alias is rejected, or the response is not
  Anthropic-compatible. A `/health` response alone is not sufficient.
- On Linux, install Bubblewrap (Ubuntu: `sudo apt-get install bubblewrap`).
  The default `model-only` policy then automatically runs host agent processes
  in an isolated network namespace. A fixed Unix-socket relay exposes only the
  configured loopback model port; `/run`, `/tmp`, proxy variables, and the SSH
  agent socket are hidden from the agent. Direct public endpoints are rejected.
  Verify the boundary on the execution host before a formal run:

  ```bash
  python -m swebench.eval_pipeline.linux_network_guard \
    --verify \
    --allow-endpoint http://127.0.0.1:4000
  ```

  Verification succeeds only when the model port is reachable inside the
  namespace and a connection to `1.1.1.1:443` is denied. If Bubblewrap or
  unprivileged namespaces are unavailable, the pipeline remains fail-closed;
  configure a separately audited `SWE_BENCH_NETWORK_GUARD` rather than using
  `--inference_network_policy unrestricted` for formal results.
  On hosts without sudo, extract the distribution's Bubblewrap package into a
  user-owned directory and set `SWE_BENCH_BWRAP` to the resulting absolute
  executable path. Rootless execution still requires the host kernel to permit
  unprivileged user namespaces; the `--verify` command is the acceptance test.
- If old per-instance logs show `ConnectionRefused`, start/fix the gateway and
  use a fresh output directory for leak-free results. `--force_inference
  --retry_empty_predictions` is appropriate only when deliberately repairing
  the same experiment lineage.
- In `model-only` mode, host inference backends also hide the active output
  directory, the repository's `outputs/` and `logs/` trees, research process
  notes, and input spreadsheets. Use repeatable `--inference_hidden_path`
  arguments for evaluation or cache directories stored elsewhere. Disposable
  inference clones are created outside result directories, and cached
  predictions are reused only when their complete instance-input hash matches.
