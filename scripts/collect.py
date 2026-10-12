"""Collect evidence for every journal in data/seed_journals.csv.

Writes data/evidence/<jid>.json (raw evidence, kept for audit) and data/features.csv
(one row per journal: label, the 21 indicator results, numeric features, rule score).

    python scripts/collect.py              # all journals (cached answers are reused)
    python scripts/collect.py --limit 5    # quick trial
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from journalcheck import config, features, scoring  # noqa: E402
from journalcheck.pipeline import collect_evidence  # noqa: E402


def one(row: dict) -> dict:
    path = config.EVIDENCE / f"{row['jid']}.json"
    t0 = time.time()
    try:
        ev = collect_evidence(issn=row.get("issn") or None, title=row.get("title") if not row.get("url") else None,
                              url=row.get("url") or None, deep=True)
    except Exception as e:  # keep going; record the failure
        return {"row": row, "error": f"{e.__class__.__name__}: {e}"}
    ev["seed"] = row
    path.write_text(json.dumps(ev, default=str)[:5_000_000])
    f = features.compute(ev)
    f["flags"]["k2_court_finding"] = bool(ev.get("court_findings"))
    rule = scoring.rule_score(f["indicators"])
    rule_nolist = scoring.rule_score(f["indicators"], exclude=tuple(config.LIST_INDICATORS))
    d = scoring.decide(rule, None, f["flags"])
    out = {k: row[k] for k in ("jid", "title", "label", "group", "split")}
    out.update({"issn_resolved": ev.get("issn"), "website": ev.get("display", {}).get("website"),
                "site_status": (ev.get("site") or {}).get("status"), "seconds": round(time.time() - t0, 1),
                "rule_trust": round(rule["trust"], 2), "rule_trust_nolist": round(rule_nolist["trust"], 2),
                "coverage": round(rule["coverage"], 3), "rule_verdict": d["verdict"],
                "k1": int(bool(f["flags"]["k1_hijacked"])), "possible_clone": int(bool(f["flags"]["possible_clone"])), "k2": int(bool(f["flags"].get("k2_court_finding"))),
                "k3": int(bool(f["flags"]["k3_false_claims"])), "integrity": int(bool(f["flags"]["integrity_alert"]))})
    for k, v in f["indicators"].items():
        out[k] = v["result"]
    out.update(scoring.feature_row(f))
    return {"row": row, "features": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    config.EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (config.DATA / "seed_journals.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]
    results, errors = [], []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one, r): r for r in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            if "error" in res:
                errors.append({"jid": res["row"]["jid"], "error": res["error"]})
                print(f"[{i}/{len(rows)}] {res['row']['jid']} ERROR {res['error'][:120]}", flush=True)
            else:
                ft = res["features"]
                results.append(ft)
                print(f"[{i}/{len(rows)}] {ft['jid']} {ft['label']:<11} rule {ft['rule_trust']:5.1f} cov {ft['coverage']:.2f} "
                      f"{ft['rule_verdict']:<9} site={ft['site_status']} {ft['seconds']}s", flush=True)
    results.sort(key=lambda r: r["jid"])
    if results:
        cols = list(results[0].keys())
        with (config.DATA / "features.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(results)
    (config.DATA / "collect_errors.json").write_text(json.dumps(errors, indent=2))
    print(f"Done: {len(results)} journals, {len(errors)} errors, {time.time() - t0:.0f}s total")


if __name__ == "__main__":
    main()
