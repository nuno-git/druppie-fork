#!/usr/bin/env bash
# Quick smoke test — runs the simplest scenario (latency-50, 1 run, no warmup)
# Usage: bash benchmarks/quick-test.sh [model]
# Example: bash benchmarks/quick-test.sh GPT-5-MINI

set -e
cd "$(dirname "$0")/.."

MODEL_ARG=""
if [ -n "$1" ]; then
    MODEL_ARG="--model $1"
fi

python -m benchmarks.runner $MODEL_ARG --scenario latency-50 --runs 1 --warmup 0
