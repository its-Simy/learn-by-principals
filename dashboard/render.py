"""The usage dashboard as one self-contained HTML page: inline CSS, inline SVG, a few lines of
inline JS for tooltips. No CDN, no network. Light and dark themes from the same palette."""

from __future__ import annotations

from html import escape

from core.providers.state import ProviderState
from dashboard.data import DashboardData, ProviderRuns

# Categorical slots in fixed order (validated palette: adjacent CVD ΔE >= 8.4 in both modes).
SYNC_ORDER = ("synced", "stale", "deferred", "link", "failed", "pending")
# Health state -> status role; the CSS pairs each role's color with an icon, beside the label.
STATUS = {
    ProviderState.AVAILABLE: "good",
    ProviderState.LIMITED: "warning",
    ProviderState.RATE_LIMITED: "serious",
    ProviderState.AUTH_EXPIRED: "critical",
    ProviderState.BROKEN: "critical",
    ProviderState.DISABLED: "off",
}

BAR = 16  # bar thickness, px (<= 24)
ROW = 28  # row pitch, px
LABEL_W = 150
CHART_W = 640

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --series-4: #eda100; --series-5: #e87ba4; --series-6: #008300;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --series-4: #c98500; --series-5: #d55181; --series-6: #008300;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --series-4: #c98500; --series-5: #d55181; --series-6: #008300;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--text-primary);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
header h1 { font-size: 22px; margin: 0 0 4px; }
.muted { color: var(--text-muted); }
.secondary { color: var(--text-secondary); }
section {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 20px; margin-top: 16px;
}
h2 { font-size: 16px; margin: 0 0 12px; }
h3 { font-size: 13px; margin: 16px 0 6px; color: var(--text-secondary); font-weight: 600; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px;
  margin-bottom: 12px; }
.tile { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.tile .label { color: var(--text-secondary); font-size: 12px; }
.tile .value { font-size: 24px; font-weight: 600; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; color: var(--text-secondary); font-weight: 600; }
th, td { padding: 5px 10px 5px 0; border-bottom: 1px solid var(--grid); white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
svg { display: block; overflow: visible; }  /* drawn at 1:1; narrow screens scroll the card */
svg text { fill: var(--text-secondary); font-size: 12px; }
svg .axis { stroke: var(--axis); stroke-width: 1; }
svg .mark { cursor: default; outline: none; }
svg .mark:hover path, svg .mark:focus path { opacity: 0.8; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 0 0 8px; font-size: 12px;
  color: var(--text-secondary); }
.legend span::before { content: ""; display: inline-block; width: 10px; height: 10px;
  border-radius: 2px; margin-right: 6px; vertical-align: -1px; background: var(--swatch); }
.status::before { font-weight: 700; margin-right: 6px; }
.status.good::before { content: "✓"; color: var(--good); }
.status.warning::before { content: "!"; color: var(--warning); }
.status.serious::before { content: "⏸"; color: var(--serious); }
.status.critical::before { content: "✕"; color: var(--critical); }
.status.off::before { content: "–"; color: var(--text-muted); }
#tip {
  position: fixed; pointer-events: none; z-index: 10; background: var(--surface-1);
  color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 8px; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.empty { color: var(--text-muted); margin: 4px 0; }
"""

JS = """
(() => {
  const tip = document.getElementById("tip");
  const place = (x, y) => {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(x + 12, window.innerWidth - w - 8) + "px";
    tip.style.top = Math.max(y - h - 12, 8) + "px";
  };
  document.querySelectorAll("[data-tip]").forEach((el) => {
    const show = () => { tip.textContent = el.getAttribute("data-tip"); tip.hidden = false; };
    el.addEventListener("pointermove", (e) => { show(); place(e.clientX, e.clientY); });
    el.addEventListener("pointerleave", () => { tip.hidden = true; });
    el.addEventListener("focus", () => {
      show(); const r = el.getBoundingClientRect(); place(r.right, r.top);
    });
    el.addEventListener("blur", () => { tip.hidden = true; });
  });
})();
"""


def _n(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def _ms(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:,.1f} s" if value >= 1000 else f"{value:,.0f} ms"


def _bar_path(x: float, y: float, w: float, h: float, round_end: bool = True) -> str:
    """A bar from the baseline at ``x``: square at the baseline, 4px rounded at its data end."""
    r = min(4.0, w / 2, h / 2) if round_end else 0.0
    if r <= 0:
        return f"M{x:.1f},{y:.1f}h{w:.1f}v{h:.1f}h{-w:.1f}z"
    return (
        f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
        f"a{r},{r} 0 0 1 {-r},{r}h{-(w - r):.1f}z"
    )


def hbar_chart(rows: list[tuple[str, float, str]], label: str) -> str:
    """One series of horizontal bars: (category, value, tooltip). Value labels at the tips."""
    if not rows:
        return '<p class="empty">No data yet.</p>'
    top = max(v for _, v, _ in rows) or 1
    plot_w = CHART_W - LABEL_W - 60
    height = ROW * len(rows) + 4
    parts = [
        f'<div class="scroll"><svg width="{CHART_W}" height="{height}" '
        f'viewBox="0 0 {CHART_W} {height}" role="img" aria-label="{escape(label)}">',
        f'<line class="axis" x1="{LABEL_W}" y1="0" x2="{LABEL_W}" y2="{height}"/>',
    ]
    for i, (category, value, tip) in enumerate(rows):
        y = i * ROW + (ROW - BAR) / 2
        w = plot_w * value / top
        parts.append(
            f'<g class="mark" tabindex="0" data-tip="{escape(tip)}">'
            f'<rect x="0" y="{i * ROW}" width="{CHART_W}" height="{ROW}" fill="transparent"/>'
            f'<text x="{LABEL_W - 8}" y="{y + BAR - 4}" text-anchor="end">{escape(category)}</text>'
            + (f'<path d="{_bar_path(LABEL_W, y, w, BAR)}" fill="var(--series-1)"/>' if w else "")
            + f'<text x="{LABEL_W + w + 6}" y="{y + BAR - 4}">{_n(value)}</text></g>'
        )
    parts.append("</svg></div>")
    return "".join(parts)


def stacked_chart(rows: list[tuple[str, dict[str, int]]], order: tuple[str, ...]) -> str:
    """Stacked horizontal bars, one per category, 2px surface gaps between segments."""
    if not rows:
        return '<p class="empty">Nothing synced yet.</p>'
    top = max(sum(counts.values()) for _, counts in rows) or 1
    plot_w = CHART_W - LABEL_W - 60
    height = ROW * len(rows) + 4
    legend = "".join(
        f'<span style="--swatch: var(--series-{n})">{escape(state)}</span>'
        for n, state in enumerate(order, start=1)
    )
    parts = [
        f'<div class="legend">{legend}</div>',
        f'<div class="scroll"><svg width="{CHART_W}" height="{height}" '
        f'viewBox="0 0 {CHART_W} {height}" role="img" aria-label="Sync status per course">',
        f'<line class="axis" x1="{LABEL_W}" y1="0" x2="{LABEL_W}" y2="{height}"/>',
    ]
    for i, (category, counts) in enumerate(rows):
        y = i * ROW + (ROW - BAR) / 2
        parts.append(
            f'<text x="{LABEL_W - 8}" y="{y + BAR - 4}" text-anchor="end">{escape(category)}</text>'
        )
        present = [(n, s, counts[s]) for n, s in enumerate(order, start=1) if counts.get(s)]
        x = float(LABEL_W)
        for j, (n, state, count) in enumerate(present):
            w = plot_w * count / top
            last = j == len(present) - 1
            draw = w if last else max(w - 2, 0.5)  # the 2px gap is surface showing through
            tip = f"{category} · {state} · {count:,}"
            parts.append(
                f'<g class="mark" tabindex="0" data-tip="{escape(tip)}">'
                f'<path d="{_bar_path(x, y, draw, BAR, round_end=last)}" fill="var(--series-{n})"/>'
                "</g>"
            )
            x += w
        total = sum(counts.values())
        parts.append(f'<text x="{x + 6}" y="{y + BAR - 4}">{total:,}</text>')
    parts.append("</svg></div>")
    return "".join(parts)


def _table(headers: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    """``headers``: (title, numeric). Cells are already escaped HTML."""
    head = "".join(f'<th class="{"num" if num else ""}">{escape(h)}</th>' for h, num in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"num" if headers[i][1] else ""}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    return f'<div class="scroll">{table}</div>'


def _tile(label: str, value: str) -> str:
    return (
        f'<div class="tile"><div class="label">{escape(label)}</div>'
        f'<div class="value">{value}</div></div>'
    )


def _runs_section(data: DashboardData) -> str:
    today = {r.provider: r for r in data.today}
    week = {r.provider: r for r in data.week}
    providers = sorted(set(today) | set(week))
    tiles = "".join(
        [
            _tile("Calls today (UTC)", _n(sum(r.calls for r in data.today))),
            _tile("Failures today", _n(sum(r.failures for r in data.today))),
            _tile("Calls, last 7 days", _n(sum(r.calls for r in data.week))),
            _tile("Fallbacks, last 7 days", _n(sum(r.fallbacks for r in data.week))),
        ]
    )

    def tip(r: ProviderRuns) -> str:
        return (
            f"{r.provider} · {r.calls:,} calls · {r.failures:,} failed · median {_ms(r.median_ms)}"
        )

    chart = hbar_chart(
        [(r.provider, r.calls, tip(r)) for r in sorted(data.week, key=lambda r: -r.calls)],
        "Calls per provider, last 7 days",
    )
    empty = ProviderRuns("", 0, 0, None, 0)
    rows = [
        [
            escape(p),
            _n(today.get(p, empty).calls),
            _n(today.get(p, empty).failures),
            _n(week.get(p, empty).calls),
            _n(week.get(p, empty).failures),
            _ms(week.get(p, empty).median_ms),
            _n(week.get(p, empty).fallbacks),
        ]
        for p in providers
    ]
    table = (
        _table(
            [
                ("Provider", False),
                ("Today", True),
                ("Failed today", True),
                ("7 days", True),
                ("Failed", True),
                ("Median duration", True),
                ("Fallbacks", True),
            ],
            rows,
        )
        if rows
        else ""
    )
    return (
        f'<section id="runs"><h2>Model runs</h2><div class="tiles">{tiles}</div>'
        f"<h3>Calls per provider, last 7 days</h3>{chart}{table}</section>"
    )


def _health_section(data: DashboardData) -> str:
    if not data.health:
        return (
            '<section id="health"><h2>Provider health</h2>'
            '<p class="empty">No checks recorded yet; the router records one on each run.</p>'
            "</section>"
        )
    rows = []
    for h in data.health:
        kind = STATUS.get(h.state, "off")
        cooling = (
            h.cooldown_until.isoformat(timespec="minutes")
            if h.cooldown_until and h.cooldown_until > data.generated_at
            else "—"
        )
        rows.append(
            [
                escape(h.provider),
                f'<span class="status {kind}">{escape(str(h.state))}</span>',
                escape(h.checked_at.isoformat(timespec="minutes")),
                escape(cooling),
                f'<span class="secondary">{escape((h.detail or "")[:80])}</span>',
            ]
        )
    table = _table(
        [
            ("Provider", False),
            ("State", False),
            ("Last check", False),
            ("Cooldown until", False),
            ("Detail", False),
        ],
        rows,
    )
    return f'<section id="health"><h2>Provider health</h2>{table}</section>'


def _benchmarks_section(data: DashboardData) -> str:
    if not data.benchmarks:
        return (
            '<section id="benchmarks"><h2>Benchmarks</h2>'
            '<p class="empty">No measured runs yet.</p></section>'
        )
    parts = ['<section id="benchmarks"><h2>Benchmarks</h2>']
    for task_type in sorted({b.task_type for b in data.benchmarks}):
        marks = sorted(
            (b for b in data.benchmarks if b.task_type == task_type),
            key=lambda b: -(b.score or 0),
        )
        rows = [
            [
                escape(b.provider),
                _n(b.sample_count),
                _n(b.accuracy, 2),
                _n(b.groundedness, 2),
                _n(b.format_compliance, 2),
                _ms(b.latency_ms),
                _n(b.learner_rating, 1),
                _n(b.score, 2),
            ]
            for b in marks
        ]
        parts.append(f"<h3>{escape(task_type)}</h3>")
        parts.append(
            _table(
                [
                    ("Provider", False),
                    ("Runs", True),
                    ("Accuracy", True),
                    ("Groundedness", True),
                    ("Format", True),
                    ("Latency", True),
                    ("Rating", True),
                    ("Score", True),
                ],
                rows,
            )
        )
    parts.append("</section>")
    return "".join(parts)


def _notebooklm_section(data: DashboardData) -> str:
    tiles = "".join(
        _tile(
            label,
            f"{_n(data.artifacts_week.get(label, 0))}"
            f' <span class="muted" style="font-size:12px;font-weight:400">'
            f"of {_n(total)} total</span>",
        )
        for label, total in data.artifacts_total.items()
    )
    tiles += _tile("Podcast episodes recorded", _n(data.podcasts))
    return (
        '<section id="notebooklm"><h2>NotebookLM artifacts</h2>'
        '<p class="muted">Generated in the last 7 days, of all time.</p>'
        f'<div class="tiles">{tiles}</div></section>'
    )


def _sync_section(data: DashboardData) -> str:
    rows = sorted(data.sync.items())
    chart = stacked_chart(rows, SYNC_ORDER)
    table = (
        _table(
            [("Course", False), *((s, True) for s in SYNC_ORDER), ("Total", True)],
            [
                [escape(course), *(_n(c.get(s, 0)) for s in SYNC_ORDER), _n(sum(c.values()))]
                for course, c in rows
            ],
        )
        if rows
        else ""
    )
    return f'<section id="sync"><h2>Sync status per course</h2>{chart}{table}</section>'


def _weakest_section(data: DashboardData) -> str:
    if not data.weakest:
        return (
            '<section id="weakest"><h2>Weakest concepts</h2>'
            '<p class="empty">No concepts yet; run <code>brightlearn concepts seed</code>.</p>'
            "</section>"
        )
    rows = [
        [escape(w.name), escape(w.course), f"{w.level}/5", _n(w.retention, 2), _n(w.confidence, 2)]
        for w in data.weakest
    ]
    table = _table(
        [
            ("Concept", False),
            ("Course", False),
            ("Level", True),
            ("Retention", True),
            ("Confidence", True),
        ],
        rows,
    )
    return f'<section id="weakest"><h2>Weakest {len(rows)} concepts</h2>{table}</section>'


def render(data: DashboardData) -> str:
    stamp = data.generated_at.isoformat(timespec="minutes")
    body = "".join(
        [
            _runs_section(data),
            _health_section(data),
            _benchmarks_section(data),
            _notebooklm_section(data),
            _sync_section(data),
            _weakest_section(data),
        ]
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>BrightLearn usage</title><style>{CSS}</style></head><body><main>"
        f'<header><h1>BrightLearn usage</h1><p class="muted">Generated {escape(stamp)} UTC from '
        "the local ledger. Every chart's numbers are also in the table below it.</p></header>"
        f'{body}</main><div id="tip" role="tooltip" hidden></div><script>{JS}</script>'
        "</body></html>\n"
    )
