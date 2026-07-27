# Observability contract

Arahus uses **one** canonical report per pipeline run.

## Source of truth

1. `PipelineProfiler` (`src/monitoring/pipeline_profiler.py`) times stages and binds `CostTracker`.
2. On finish it builds a `PipelineReport` (`src/monitoring/pipeline_metrics.py`).
3. Console / JSON export goes through `src/monitoring/report.py`.

`MetricsCollector` remains the in-memory latency sample store (tokens, retries, per-metric series). Studio `result.metrics` embeds the profiler/report payload under `profiler` / `pipeline_report` keys.

## Stage timing rules

- **Total** is wall-clock elapsed for the whole run (not the sum of stage rows).
- Nested detail stages (Prompt Composer, RunPod submission/polling, Upload) may overlap parent stages; do not add them to Total.
- When metrics are disabled (`METRICS_ENABLED=false`), profilers become no-ops aside from minimal logging.

## Export

Set `METRICS_EXPORT_PATH` to a file path to write the JSON report after each run.
