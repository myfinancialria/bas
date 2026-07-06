from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPORTS_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"
DOCS_REPORTS_DIR = DOCS_DIR / "reports"
MANIFEST_PATH = DOCS_REPORTS_DIR / "manifest.json"
INDEX_PATH = DOCS_DIR / "index.html"


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Pre-market report"


def sync_reports() -> None:
    DOCS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for path in SOURCE_REPORTS_DIR.glob("*.md"):
        shutil.copy2(path, DOCS_REPORTS_DIR / path.name)
    for stale_path in DOCS_REPORTS_DIR.glob("*.md"):
        if not (SOURCE_REPORTS_DIR / stale_path.name).exists():
            stale_path.unlink()


def build_manifest() -> list[dict[str, str]]:
    report_files = sorted(SOURCE_REPORTS_DIR.glob("*.md"), key=lambda path: path.name, reverse=True)
    entries: list[dict[str, str]] = []
    for path in report_files:
        text = path.read_text(encoding="utf-8")
        title = extract_title(text)
        match = re.match(r"(?P<date>\d{4}-\d{2}-\d{2})", path.stem)
        displayed_date = match.group("date") if match else path.stem
        entries.append(
            {
                "filename": path.name,
                "title": title,
                "date": displayed_date,
                "url": f"reports/{path.name}",
            }
        )
    return entries


def write_manifest(entries: list[dict[str, str]]) -> None:
    DOCS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def write_index_html() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        """<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Pre-Market Report Dashboard</title>
    <style>
      :root {
        color-scheme: dark;
        --bg: #07111f;
        --panel: #0f1b2d;
        --panel-2: #14253d;
        --text: #e4eefc;
        --muted: #8da4bf;
        --accent: #4ecdc4;
        --accent-2: #ff6b6b;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: linear-gradient(135deg, var(--bg), #111c2b);
        color: var(--text);
      }
      header {
        padding: 1.5rem 2rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        background: rgba(15, 27, 45, 0.9);
        backdrop-filter: blur(12px);
      }
      .layout {
        display: grid;
        grid-template-columns: 320px minmax(0, 1fr);
        min-height: calc(100vh - 88px);
      }
      aside {
        padding: 1.25rem;
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        background: rgba(20, 37, 61, 0.82);
      }
      .report-list {
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
      }
      .report-link {
        display: block;
        padding: 0.8rem 0.95rem;
        border-radius: 0.8rem;
        border: 1px solid transparent;
        background: var(--panel);
        color: var(--text);
        text-decoration: none;
        transition: transform 0.2s ease, border-color 0.2s ease;
      }
      .report-link:hover,
      .report-link.active {
        transform: translateY(-1px);
        border-color: var(--accent);
      }
      .report-link small {
        display: block;
        margin-top: 0.25rem;
        color: var(--muted);
      }
      main {
        padding: 1.5rem 2rem 2rem;
      }
      .card {
        background: rgba(15, 27, 45, 0.92);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 1rem;
        padding: 1.3rem;
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.25);
      }
      .loading {
        color: var(--muted);
        font-style: italic;
      }
      .report-content h1, .report-content h2, .report-content h3 {
        color: #fff;
      }
      .report-content table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
      }
      .report-content th, .report-content td {
        border: 1px solid rgba(255,255,255,0.12);
        padding: 0.6rem 0.75rem;
        text-align: left;
      }
      .report-content code {
        background: rgba(255,255,255,0.08);
        padding: 0.15rem 0.35rem;
        border-radius: 0.35rem;
      }
      @media (max-width: 900px) {
        .layout { grid-template-columns: 1fr; }
        aside { border-right: none; border-bottom: 1px solid rgba(255,255,255,0.08); }
      }
    </style>
  </head>
  <body>
    <header>
      <h1>Pre-Market Report Dashboard</h1>
      <p>Browse the latest generated reports and trade ideas from this project.</p>
    </header>
    <div class="layout">
      <aside>
        <h2>Reports</h2>
        <div id="report-list" class="report-list"></div>
      </aside>
      <main>
        <div id="content" class="card">
          <div class="loading">Loading available reports…</div>
        </div>
      </main>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
      const listEl = document.getElementById('report-list');
      const contentEl = document.getElementById('content');
      let reports = [];

      function renderList(items) {
        listEl.innerHTML = '';
        if (!items.length) {
          listEl.innerHTML = '<div class="loading">No reports generated yet.</div>';
          return;
        }
        items.forEach((report) => {
          const link = document.createElement('a');
          link.className = 'report-link';
          link.href = '#';
          link.innerHTML = `<strong>${report.title}</strong><small>${report.date}</small>`;
          link.addEventListener('click', (event) => {
            event.preventDefault();
            openReport(report.filename);
          });
          listEl.appendChild(link);
        });
      }

      async function openReport(filename) {
        const report = reports.find((item) => item.filename === filename);
        if (!report) return;

        contentEl.innerHTML = '<div class="loading">Loading report…</div>';
        const response = await fetch(`reports/${filename}`);
        if (!response.ok) {
          contentEl.innerHTML = '<div class="loading">The selected report could not be loaded.</div>';
          return;
        }
        const markdown = await response.text();
        if (window.marked) {
          contentEl.innerHTML = `<div class="report-content">${window.marked.parse(markdown)}</div>`;
        } else {
          contentEl.innerHTML = `<pre class="report-content">${markdown}</pre>`;
        }
        document.querySelectorAll('.report-link').forEach((link) => {
          link.classList.toggle('active', link.textContent.includes(report.title));
        });
      }

      async function loadReports() {
        const response = await fetch('reports/manifest.json');
        if (!response.ok) {
          contentEl.innerHTML = '<div class="loading">Report manifest is not available yet.</div>';
          return;
        }
        reports = await response.json();
        renderList(reports);
        if (reports.length) {
          openReport(reports[0].filename);
        } else {
          contentEl.innerHTML = '<div class="loading">No reports generated yet. Run the report workflow to create the first report.</div>';
        }
      }

      loadReports();
    </script>
  </body>
</html>
""",
        encoding="utf-8",
    )


def write_nojekyll() -> None:
    """Disable Jekyll so GitHub Pages serves the docs/ folder verbatim."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")


def main() -> None:
    sync_reports()
    entries = build_manifest()
    write_manifest(entries)
    write_index_html()
    write_nojekyll()
    print(f"Wrote {MANIFEST_PATH} and {INDEX_PATH}")


if __name__ == "__main__":
    main()
