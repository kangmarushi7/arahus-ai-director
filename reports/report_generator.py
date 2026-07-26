"""Generate a simple HTML benchmark report from benchmark_results.json."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def score_class(score: float | None) -> str:
    """Return a CSS class for a review score."""
    if score is None:
        return "score-missing"
    if score >= 90:
        return "score-green"
    if score >= 75:
        return "score-yellow"
    return "score-red"


def score_label(score: float | None) -> str:
    """Format a review score for display."""
    if score is None:
        return "—"
    return f"{score:.0f}"


class ReportGenerator:
    """Build ``report.html`` from benchmark JSON using plain HTML/CSS."""

    def __init__(
        self,
        results_path: str | Path = "artifacts/benchmark_results.json",
        output_path: str | Path = "artifacts/report.html",
    ) -> None:
        """Configure input and output paths.

        Args:
            results_path: Path to ``benchmark_results.json``.
            output_path: Destination HTML file.
        """
        self.results_path = Path(results_path)
        self.output_path = Path(output_path)

    def load_results(self) -> dict[str, Any]:
        """Load and validate the benchmark JSON document."""
        if not self.results_path.exists():
            raise FileNotFoundError(f"Benchmark results not found: {self.results_path}")
        payload = json.loads(self.results_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "rows" not in payload:
            raise ValueError("benchmark_results.json must contain a top-level 'rows' list")
        return payload

    def generate(self, results: dict[str, Any] | None = None) -> Path:
        """Render the HTML report and write it to disk.

        Args:
            results: Optional pre-loaded benchmark payload. Loaded from disk
                when omitted.

        Returns:
            Path to the written ``report.html``.
        """
        payload = results if results is not None else self.load_results()
        document = self._render_document(payload)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(document, encoding="utf-8")
        return self.output_path

    def _render_document(self, payload: dict[str, Any]) -> str:
        """Compose the full HTML document."""
        rows = payload.get("rows") or []
        summary = payload.get("summary") or {}
        cards = "\n".join(self._render_topic_card(row) for row in rows)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Director Benchmark Report</title>
  <style>
{self._css()}
  </style>
</head>
<body>
  <header class="page-header">
    <h1>AI Director Benchmark Report</h1>
    <p class="meta">
      Started: {html.escape(str(payload.get("started_at", "—")))}<br />
      Finished: {html.escape(str(payload.get("finished_at", "—")))}<br />
      Success: {html.escape(str(payload.get("success_count", 0)))}/
      {html.escape(str(payload.get("topic_count", len(rows))))}
    </p>
    <section class="summary">
      <div class="stat"><span>Mean pipeline</span><strong>{html.escape(str(summary.get("mean_pipeline_seconds", "—")))}s</strong></div>
      <div class="stat"><span>Mean score</span><strong>{html.escape(str(summary.get("mean_review_score", "—")))}</strong></div>
      <div class="stat"><span>Mean images</span><strong>{html.escape(str(summary.get("mean_image_count", "—")))}</strong></div>
    </section>
  </header>
  <main>
{cards if cards else '    <p class="empty">No benchmark topics found.</p>'}
  </main>
</body>
</html>
"""

    def _render_topic_card(self, row: dict[str, Any]) -> str:
        """Render one topic block: score, timing, images, expandable JSON."""
        topic = html.escape(str(row.get("topic", "Untitled")))
        status = html.escape(str(row.get("status", "unknown")))
        score = row.get("review_score")
        score_css = score_class(score if isinstance(score, (int, float)) else None)
        score_text = score_label(score if isinstance(score, (int, float)) else None)
        approved = row.get("approved")
        approved_text = (
            "Yes" if approved is True else "No" if approved is False else "—"
        )

        timing_rows = [
            ("Pipeline", row.get("pipeline_seconds")),
            ("Research", row.get("research_seconds")),
            ("Director", row.get("director_seconds")),
            ("Prompt", row.get("prompt_seconds")),
            ("Review", row.get("review_seconds")),
            ("Image", row.get("image_seconds")),
        ]
        timing_html = "\n".join(
            f'          <tr><th>{html.escape(label)}</th>'
            f"<td>{html.escape(self._fmt_seconds(value))}</td></tr>"
            for label, value in timing_rows
        )

        images_html = self._render_images(row.get("images") or [])
        details = row.get("details") or {
            key: value
            for key, value in row.items()
            if key not in {"details"}
        }
        details_json = html.escape(
            json.dumps(details, indent=2, ensure_ascii=False)
        )
        error = row.get("error") or ""
        error_html = (
            f'      <p class="error">{html.escape(str(error))}</p>\n'
            if error
            else ""
        )

        return f"""    <article class="topic-card">
      <header class="topic-header">
        <div>
          <h2>{topic}</h2>
          <p class="status">Status: <strong>{status}</strong> · Approved: <strong>{approved_text}</strong></p>
        </div>
        <div class="score-badge {score_css}" title="Review score">
          <span class="score-label">Review score</span>
          <span class="score-value">{score_text}</span>
        </div>
      </header>
{error_html}      <section class="panel">
        <h3>Timing</h3>
        <table class="timing-table">
          <tbody>
{timing_html}
          </tbody>
        </table>
      </section>
      <section class="panel">
        <h3>Generated images</h3>
{images_html}
      </section>
      <section class="panel">
        <details>
          <summary>Expandable JSON</summary>
          <pre>{details_json}</pre>
        </details>
      </section>
    </article>"""

    def _render_images(self, images: list[dict[str, Any]]) -> str:
        """Render the generated-images gallery for one topic."""
        if not images:
            return '        <p class="empty">No generated images.</p>'

        cards: list[str] = []
        for image in images:
            title = html.escape(
                str(image.get("title") or f"Scene {image.get('scene_id', '?')}")
            )
            status = html.escape(str(image.get("status", "")))
            url = image.get("url") or ""
            if url:
                safe_url = html.escape(str(url), quote=True)
                media = (
                    f'<a href="{safe_url}" target="_blank" rel="noopener">'
                    f'<img src="{safe_url}" alt="{title}" loading="lazy" /></a>'
                )
            else:
                media = f'<div class="image-placeholder">{status or "No URL"}</div>'
            cards.append(
                f"""        <figure class="image-card">
          {media}
          <figcaption>Scene {html.escape(str(image.get("scene_id", "?")))}: {title}</figcaption>
        </figure>"""
            )
        return '        <div class="image-grid">\n' + "\n".join(cards) + "\n        </div>"

    @staticmethod
    def _fmt_seconds(value: Any) -> str:
        """Format a timing value as seconds."""
        try:
            return f"{float(value):.2f}s"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _css() -> str:
        """Return embedded report styles."""
        return """    :root {
      --bg: #f4f1ea;
      --card: #fffdf8;
      --ink: #1c1917;
      --muted: #57534e;
      --line: #d6d3d1;
      --green: #166534;
      --green-bg: #dcfce7;
      --yellow: #854d0e;
      --yellow-bg: #fef9c3;
      --red: #991b1b;
      --red-bg: #fee2e2;
      --missing: #78716c;
      --missing-bg: #e7e5e4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.8), transparent 40%),
        linear-gradient(180deg, #efe7d8 0%, var(--bg) 40%, #e7e0d4 100%);
      line-height: 1.45;
    }
    .page-header, main {
      width: min(1100px, calc(100% - 2rem));
      margin: 0 auto;
    }
    .page-header {
      padding: 2.5rem 0 1rem;
    }
    h1, h2, h3 {
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    h1 { margin: 0 0 0.5rem; font-size: 2.2rem; }
    h2 { margin: 0 0 0.35rem; font-size: 1.45rem; }
    h3 { margin: 0 0 0.75rem; font-size: 1.05rem; }
    .meta, .status, .empty { color: var(--muted); }
    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.75rem;
      margin-top: 1.25rem;
    }
    .stat {
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
      padding: 0.9rem 1rem;
    }
    .stat span {
      display: block;
      color: var(--muted);
      font-size: 0.85rem;
      margin-bottom: 0.25rem;
    }
    .stat strong { font-size: 1.35rem; }
    .topic-card {
      background: var(--card);
      border: 1px solid var(--line);
      margin: 0 0 1.25rem;
      padding: 1.25rem;
    }
    .topic-header {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: flex-start;
      margin-bottom: 1rem;
    }
    .score-badge {
      min-width: 7rem;
      text-align: center;
      padding: 0.75rem 0.9rem;
      border: 1px solid transparent;
    }
    .score-label {
      display: block;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 0.2rem;
    }
    .score-value { font-size: 1.8rem; font-weight: 700; }
    .score-green { background: var(--green-bg); color: var(--green); border-color: #86efac; }
    .score-yellow { background: var(--yellow-bg); color: var(--yellow); border-color: #fde047; }
    .score-red { background: var(--red-bg); color: var(--red); border-color: #fca5a5; }
    .score-missing { background: var(--missing-bg); color: var(--missing); border-color: var(--line); }
    .panel { margin-top: 1rem; }
    .timing-table {
      width: 100%;
      border-collapse: collapse;
    }
    .timing-table th, .timing-table td {
      border-bottom: 1px solid var(--line);
      padding: 0.45rem 0.2rem;
      text-align: left;
    }
    .timing-table th { width: 40%; color: var(--muted); font-weight: 600; }
    .image-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
    }
    .image-card {
      margin: 0;
      border: 1px solid var(--line);
      background: #fff;
      padding: 0.5rem;
    }
    .image-card img {
      display: block;
      width: 100%;
      height: 180px;
      object-fit: cover;
      background: #e7e5e4;
    }
    .image-placeholder {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 180px;
      background: #e7e5e4;
      color: var(--muted);
      text-align: center;
      padding: 0.75rem;
    }
    figcaption {
      margin-top: 0.45rem;
      font-size: 0.9rem;
      color: var(--muted);
    }
    details {
      border: 1px solid var(--line);
      padding: 0.75rem 1rem;
      background: #fff;
    }
    summary {
      cursor: pointer;
      font-weight: 700;
    }
    pre {
      margin: 0.75rem 0 0;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.82rem;
      line-height: 1.4;
    }
    .error {
      color: var(--red);
      background: var(--red-bg);
      border: 1px solid #fca5a5;
      padding: 0.65rem 0.8rem;
    }
    @media (max-width: 720px) {
      .summary, .image-grid, .topic-header { grid-template-columns: 1fr; display: grid; }
      .topic-header { align-items: stretch; }
    }"""


def main() -> int:
    """CLI entry point: build report.html from the latest benchmark JSON."""
    path = ReportGenerator().generate()
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
