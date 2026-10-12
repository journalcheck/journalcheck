"""Explanation report: every verdict comes with the evidence behind it."""
from __future__ import annotations

import html

from . import config

ICON = {"pass": "PASS", "fail": "FAIL", "unknown": "not checked"}


def to_markdown(a: dict) -> str:
    j, d, r = a["journal"], a["decision"], a["rule"]
    lines = [
        f"# JournalCheck report: {j.get('title') or 'Unknown journal'}",
        "",
        f"ISSN {a.get('issn') or 'n/a'} · Publisher {j.get('publisher') or 'n/a'} · Website {j.get('website') or 'n/a'} · Checked {a.get('collected_at')}",
        "",
        f"## Verdict: {d['verdict']}" + (" – review before submitting" if d["verdict"] != "Low risk" else ""),
        "",
        f"- Trust score: **{d['trust']:.0f} / 100** (rules {r['trust']:.0f}" + (f", model {a['ml_trust']:.0f}" if a.get("ml_trust") is not None else "") + ")",
        f"- Evidence coverage: {r['coverage']:.0%} of indicator points could be checked",
    ]
    if d["overrides"]:
        lines.append("- Overrides: " + "; ".join(d["overrides"]))
    if d["needs_review"]:
        lines.append("- **Human review needed:** " + "; ".join(d["review_reasons"]))
    lines += ["", "## Indicators", "", "| ID | Indicator | Result | Points | Evidence |", "| --- | --- | --- | --- | --- |"]
    for k, v in a["indicators"].items():
        lines.append(f"| {k} | {v['name']} | {ICON[v['result']]} | {v['points']:g}/{v['max']} | {v['evidence'].replace('|', '/')} |")
    lines += ["", "## Score by category", "", "| Category | Points |", "| --- | --- |"]
    for c, s in r["by_category"].items():
        lines.append(f"| {c}. {config.CATEGORY_NAMES[c]} | {s['earned']:g} / {s['max']:g} |")
    if a.get("ml_factors"):
        lines += ["", "## What moved the model", "", "Positive values push towards high risk.", ""]
        lines += [f"- {f['feature']}: {f['contribution']:+.2f}" for f in a["ml_factors"]]
    lines += ["", "## Checks for a person", ""]
    lines += [f"- [ ] {k}: {v}" for k, v in config.MANUAL_CHECKS.items()]
    if a["flags"].get("cope_claim"):
        lines.append("- The website mentions COPE: confirm membership (M4).")
    lines += ["", "*JournalCheck is a triage aid. A High-risk verdict means the journal should be checked by a person before you submit; it is not a finding that the journal is predatory.*"]
    return "\n".join(lines)


def to_html(a: dict) -> str:
    j, d, r = a["journal"], a["decision"], a["rule"]
    colour = {"Low risk": "#1a7f37", "Caution": "#9a6700", "High risk": "#cf222e"}[d["verdict"]]
    rows = "".join(
        f"<tr><td>{k}</td><td>{html.escape(v['name'])}</td><td class='{v['result']}'>{ICON[v['result']]}</td>"
        f"<td>{v['points']:g}/{v['max']}</td><td>{html.escape(v['evidence'])}</td></tr>"
        for k, v in a["indicators"].items())
    review = ("<p><b>Human review needed:</b> " + html.escape("; ".join(d["review_reasons"])) + "</p>") if d["needs_review"] else ""
    over = ("<p><b>Overrides:</b> " + html.escape("; ".join(d["overrides"])) + "</p>") if d["overrides"] else ""
    factors = "".join(f"<li>{html.escape(f['feature'])}: {f['contribution']:+.2f}</li>" for f in a.get("ml_factors") or [])
    manual = "".join(f"<li>{k}: {html.escape(v)}</li>" for k, v in config.MANUAL_CHECKS.items())
    model = f", model {a['ml_trust']:.0f}" if a.get("ml_trust") is not None else ""
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>JournalCheck – {html.escape(j.get('title') or '')}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1f2328}}
.verdict{{border-left:6px solid {colour};padding:8px 16px;background:#f6f8fa}}table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border:1px solid #d0d7de;padding:4px 8px;vertical-align:top}}.fail{{color:#cf222e;font-weight:600}}.pass{{color:#1a7f37}}.unknown{{color:#57606a}}</style></head><body>
<h1>{html.escape(j.get('title') or 'Unknown journal')}</h1>
<p>ISSN {html.escape(a.get('issn') or 'n/a')} · {html.escape(j.get('publisher') or '')} · {html.escape(j.get('website') or '')} · checked {html.escape(a.get('collected_at') or '')}</p>
<div class='verdict'><h2 style='color:{colour}'>{d['verdict']}</h2><p>Trust score <b>{d['trust']:.0f}/100</b> (rules {r['trust']:.0f}{model}); evidence coverage {r['coverage']:.0%}</p>{over}{review}</div>
<h2>Indicators</h2><table><tr><th>ID</th><th>Indicator</th><th>Result</th><th>Points</th><th>Evidence</th></tr>{rows}</table>
{('<h2>What moved the model</h2><p>Positive values push towards high risk.</p><ul>' + factors + '</ul>') if factors else ''}
<h2>Checks for a person</h2><ul>{manual}</ul>
<p><i>JournalCheck is a triage aid, not a blacklist. A High-risk verdict means: check this journal carefully before submitting.</i></p></body></html>"""
