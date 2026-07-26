"""BenchmarkRunner – time the full DirectorPipeline across historical topics."""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.api import build_pipeline
from src.config import reload_settings
from src.models.pipeline import PipelineResult
from src.pipeline import DirectorPipeline, PipelineValidationError

# Force UTF-8 on Windows consoles when printing the summary table.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - best-effort for non-standard streams
    pass

BENCHMARK_TOPICS: tuple[str, ...] = (
    "Fall of Constantinople",
    "Battle of Thermopylae",
    "Julius Caesar assassination",
    "Titanic sinking",
    "Apollo 11 Moon Landing",
    "Pompeii eruption",
    "Black Death",
    "Construction of the Taj Mahal",
    "Battle of Waterloo",
    "Great Fire of London",
)

RESULT_FIELDS: tuple[str, ...] = (
    "topic",
    "status",
    "pipeline_seconds",
    "research_seconds",
    "director_seconds",
    "prompt_seconds",
    "review_seconds",
    "image_seconds",
    "review_score",
    "approved",
    "image_count",
    "error",
)


@dataclass
class BenchmarkRow:
    """One topic's measured pipeline run."""

    topic: str
    status: str
    pipeline_seconds: float = 0.0
    research_seconds: float = 0.0
    director_seconds: float = 0.0
    prompt_seconds: float = 0.0
    review_seconds: float = 0.0
    image_seconds: float = 0.0
    review_score: float | None = None
    approved: bool | None = None
    image_count: int = 0
    error: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the row for JSON/CSV export."""
        return asdict(self)

    def to_csv_dict(self) -> dict[str, Any]:
        """Serialize flat columns only for CSV export."""
        payload = self.to_dict()
        return {key: payload.get(key) for key in RESULT_FIELDS}


@dataclass
class BenchmarkReport:
    """Full benchmark run with per-topic rows and aggregate summary."""

    started_at: str
    finished_at: str
    topic_count: int
    success_count: int
    failure_count: int
    rows: list[BenchmarkRow] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report for JSON export."""
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "topic_count": self.topic_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "summary": self.summary,
            "rows": [row.to_dict() for row in self.rows],
        }


class BenchmarkRunner:
    """Run DirectorPipeline across a fixed set of historical topics."""

    def __init__(
        self,
        topics: Sequence[str] = BENCHMARK_TOPICS,
        *,
        pipeline: DirectorPipeline | None = None,
        output_dir: str | Path = "artifacts",
    ) -> None:
        """Configure topics, pipeline, and output directory.

        Args:
            topics: Historical topics to benchmark.
            pipeline: Optional pre-built pipeline; built from env when omitted.
            output_dir: Directory for JSON/CSV artifacts.
        """
        self.topics = tuple(topics)
        self.output_dir = Path(output_dir)
        self._pipeline = pipeline

    def run(self) -> BenchmarkReport:
        """Execute every topic and return the collected report."""
        reload_settings()
        pipeline = self._pipeline or build_pipeline()
        started_at = datetime.now(timezone.utc).isoformat()
        rows: list[BenchmarkRow] = []

        for index, topic in enumerate(self.topics, start=1):
            print(f"[{index}/{len(self.topics)}] Benchmarking: {topic}")
            rows.append(self._run_topic(pipeline, topic))

        finished_at = datetime.now(timezone.utc).isoformat()
        success_count = sum(1 for row in rows if row.status == "ok")
        report = BenchmarkReport(
            started_at=started_at,
            finished_at=finished_at,
            topic_count=len(rows),
            success_count=success_count,
            failure_count=len(rows) - success_count,
            rows=rows,
            summary=self._build_summary(rows),
        )
        self.write_outputs(report)
        self.print_summary_table(report)
        return report

    def _run_topic(self, pipeline: DirectorPipeline, topic: str) -> BenchmarkRow:
        """Run one topic and capture timings / scores."""
        wall_started = time.perf_counter()
        try:
            result = pipeline.generate(topic)
            return self._row_from_result(topic, result, time.perf_counter() - wall_started)
        except PipelineValidationError as exc:
            return BenchmarkRow(
                topic=topic,
                status="rejected",
                pipeline_seconds=round(time.perf_counter() - wall_started, 6),
                review_score=exc.review.overall_score,
                approved=False,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - keep the suite running
            traceback.print_exc()
            return BenchmarkRow(
                topic=topic,
                status="error",
                pipeline_seconds=round(time.perf_counter() - wall_started, 6),
                error=f"{type(exc).__name__}: {exc}",
            )

    def _row_from_result(
        self,
        topic: str,
        result: PipelineResult,
        wall_seconds: float,
    ) -> BenchmarkRow:
        """Convert a successful pipeline result into a benchmark row."""
        metrics = result.metrics
        successful_images = sum(1 for image in result.images if image.url)
        images = [
            {
                "scene_id": image.scene_id,
                "title": image.title,
                "url": image.url,
                "status": image.status,
                "prompt": image.prompt,
            }
            for image in result.images
        ]
        details = {
            "research": result.research.model_dump(mode="json"),
            "plan": result.plan.model_dump(mode="json"),
            "storyboard": result.storyboard.model_dump(mode="json"),
            "review": result.review.model_dump(mode="json"),
            "metrics": {k: v for k, v in metrics.items() if k != "raw"},
            "images": images,
        }
        return BenchmarkRow(
            topic=topic,
            status="ok",
            pipeline_seconds=round(
                float(metrics.get("pipeline_duration_seconds", wall_seconds)),
                6,
            ),
            research_seconds=round(float(metrics.get("research_seconds", 0.0)), 6),
            director_seconds=round(float(metrics.get("director_seconds", 0.0)), 6),
            prompt_seconds=round(float(metrics.get("prompt_seconds", 0.0)), 6),
            review_seconds=round(float(metrics.get("review_seconds", 0.0)), 6),
            image_seconds=round(float(metrics.get("image_seconds", 0.0)), 6),
            review_score=float(result.review.overall_score),
            approved=bool(result.review.approved),
            image_count=successful_images or int(metrics.get("images_generated", 0)),
            error="",
            images=images,
            details=details,
        )

    def _build_summary(self, rows: Sequence[BenchmarkRow]) -> dict[str, Any]:
        """Aggregate mean/median timings and scores for successful rows."""
        ok_rows = [row for row in rows if row.status == "ok"]
        if not ok_rows:
            return {
                "successful_topics": 0,
                "mean_pipeline_seconds": None,
                "median_pipeline_seconds": None,
                "mean_review_score": None,
                "mean_image_count": None,
            }

        pipeline_times = [row.pipeline_seconds for row in ok_rows]
        review_scores = [
            row.review_score for row in ok_rows if row.review_score is not None
        ]
        return {
            "successful_topics": len(ok_rows),
            "mean_pipeline_seconds": round(statistics.mean(pipeline_times), 3),
            "median_pipeline_seconds": round(statistics.median(pipeline_times), 3),
            "mean_research_seconds": round(
                statistics.mean(row.research_seconds for row in ok_rows),
                3,
            ),
            "mean_director_seconds": round(
                statistics.mean(row.director_seconds for row in ok_rows),
                3,
            ),
            "mean_prompt_seconds": round(
                statistics.mean(row.prompt_seconds for row in ok_rows),
                3,
            ),
            "mean_review_seconds": round(
                statistics.mean(row.review_seconds for row in ok_rows),
                3,
            ),
            "mean_image_seconds": round(
                statistics.mean(row.image_seconds for row in ok_rows),
                3,
            ),
            "mean_review_score": (
                round(statistics.mean(review_scores), 2) if review_scores else None
            ),
            "mean_image_count": round(
                statistics.mean(row.image_count for row in ok_rows),
                2,
            ),
        }

    def write_outputs(self, report: BenchmarkReport) -> tuple[Path, Path]:
        """Write ``benchmark_results.json`` and ``benchmark_results.csv``."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.output_dir / "benchmark_results.json"
        csv_path = self.output_dir / "benchmark_results.csv"

        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            for row in report.rows:
                writer.writerow(row.to_csv_dict())

        print(f"Wrote {json_path}")
        print(f"Wrote {csv_path}")

        try:
            from reports.report_generator import ReportGenerator

            html_path = ReportGenerator(
                results_path=json_path,
                output_path=self.output_dir / "report.html",
            ).generate()
            print(f"Wrote {html_path}")
        except Exception as exc:  # noqa: BLE001 - report is best-effort
            print(f"HTML report skipped: {exc}")

        return json_path, csv_path

    def print_summary_table(self, report: BenchmarkReport) -> None:
        """Print a compact markdown-style summary table to stdout."""
        headers = [
            "Topic",
            "Status",
            "Pipeline(s)",
            "Research",
            "Director",
            "Prompt",
            "Review",
            "Image",
            "Score",
            "Images",
        ]
        rows: list[list[str]] = []
        for row in report.rows:
            rows.append(
                [
                    row.topic,
                    row.status,
                    f"{row.pipeline_seconds:.1f}",
                    f"{row.research_seconds:.1f}",
                    f"{row.director_seconds:.1f}",
                    f"{row.prompt_seconds:.1f}",
                    f"{row.review_seconds:.1f}",
                    f"{row.image_seconds:.1f}",
                    "—" if row.review_score is None else f"{row.review_score:.0f}",
                    str(row.image_count),
                ]
            )

        widths = [
            max(len(headers[i]), *(len(row[i]) for row in rows))
            for i in range(len(headers))
        ]

        def fmt(cells: list[str]) -> str:
            return "| " + " | ".join(
                cell.ljust(widths[i]) for i, cell in enumerate(cells)
            ) + " |"

        print("\n=== Benchmark Summary ===")
        print(fmt(headers))
        print("| " + " | ".join("-" * width for width in widths) + " |")
        for row in rows:
            print(fmt(row))

        summary = report.summary
        print(
            "\nSuccess: "
            f"{report.success_count}/{report.topic_count} | "
            f"Mean pipeline: {summary.get('mean_pipeline_seconds')}s | "
            f"Mean score: {summary.get('mean_review_score')} | "
            f"Mean images: {summary.get('mean_image_count')}"
        )


def main() -> int:
    """CLI entry point for the historical-topic benchmark suite."""
    report = BenchmarkRunner().run()
    return 0 if report.failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
