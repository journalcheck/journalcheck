"""Build the data files for the project website (docs/) from the evidence and features.

For every journal in data/features.csv it recomputes the 21 indicators from the saved
evidence (data/evidence/<id>.json), the rule score, the model score and the hybrid
verdict, and writes them to docs/data/journals.json. Model scores for the 95 training
journals are out-of-fold (first repeat of the cross-validation in evaluate.py), so no
journal is scored by a model that saw it; the 13 external journals are scored by the
final model, exactly as in the report.

Website text is not copied to the site: only the short evidence lines the indicators
produce, with the user part of e-mail addresses hidden.

    python scripts/build_site.py                       # evidence in data/evidence/
    python scripts/build_site.py --evidence /path/to/evidence
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.base import clone  # noqa: E402
from sklearn.model_selection import RepeatedStratifiedKFold  # noqa: E402

from journalcheck import config, features, scoring  # noqa: E402

POS = {"predatory", "hijacked"}
REPEATS, FOLDS, SEED = 10, 5, 42          # same splits as scripts/evaluate.py
DOCS = config.ROOT / "docs" / "data"
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def tidy(text: str) -> str:
    return EMAIL.sub(lambda m: "…@" + m.group(1), text or "")


def rnd(v, n=1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(config.EVIDENCE))
    args = ap.parse_args()
    ev_dir = Path(args.evidence)

    df = pd.read_csv(config.DATA / "features.csv")
    seed = pd.read_csv(config.DATA / "seed_journals.csv").set_index("jid")
    train = df[df["split"] == "train"].reset_index(drop=True)
    ext = df[df["split"] == "external"].reset_index(drop=True)
    X, y = train[scoring.FEATURES], train["label"].isin(POS).astype(int).values

    # model scores: out-of-fold for training journals, final model for the external test
    lr = scoring.make_models(SEED)["logistic"]
    splits = list(RepeatedStratifiedKFold(n_splits=FOLDS, n_repeats=REPEATS, random_state=SEED).split(X, y))
    ml, factors = {}, {}
    for tr, te in splits[:FOLDS]:
        m = clone(lr).fit(X.iloc[tr], y[tr])
        for i in te:
            row = X.iloc[i].to_dict()
            jid = train.loc[i, "jid"]
            ml[jid] = scoring.ml_trust(m, row)
            factors[jid] = scoring.explain_logistic(m, row)
    final = clone(lr).fit(X, y)
    for i in range(len(ext)):
        row = ext.loc[i, scoring.FEATURES].to_dict()
        jid = ext.loc[i, "jid"]
        ml[jid] = scoring.ml_trust(final, row)
        factors[jid] = scoring.explain_logistic(final, row)

    out, mismatches = [], []
    for _, r in df.iterrows():
        jid = r["jid"]
        ev = json.loads((ev_dir / f"{jid}.json").read_text())
        f = features.compute(ev)
        f["flags"]["k2_court_finding"] = bool(ev.get("court_findings"))
        rule = scoring.rule_score(f["indicators"])
        dec = scoring.decide(rule, ml[jid], f["flags"])
        for k, v in f["indicators"].items():
            if v["result"] != r[k]:
                mismatches.append(f"{jid} {k}: {v['result']} vs {r[k]}")
        s = seed.loc[jid]
        disp = ev.get("display") or {}
        out.append({
            "id": jid,
            "title": re.sub(r"\s*\(clone\)$", "", str(s["title"])),
            "issn": None if pd.isna(s["issn"]) else s["issn"],
            "issn_resolved": None if pd.isna(r["issn_resolved"]) else r["issn_resolved"],
            "url": None if pd.isna(s["url"]) else s["url"],
            "website": disp.get("website"),
            "publisher": disp.get("publisher"),
            "label": s["label"],
            "group": s["group"],
            "label_source": s["label_source"],
            "split": s["split"],
            "collected_at": ev.get("collected_at"),
            "rule": rnd(rule["trust"]),
            "coverage": rnd(rule["coverage"], 3),
            "model": rnd(ml[jid]),
            "hybrid": rnd(dec["trust"]),
            "verdict": dec["verdict"],
            "overrides": dec["overrides"],
            "review": dec["review_reasons"],
            "by_category": {c: [rnd(v["earned"], 2), v["max"]] for c, v in rule["by_category"].items()},
            "indicators": [{"id": k, "result": v["result"], "points": v["points"], "max": v["max"],
                            "evidence": tidy(v["evidence"])} for k, v in f["indicators"].items()],
            "factors": [{"feature": x["feature"], "value": round(x["contribution"], 2)} for x in factors[jid]],
            "notes": [tidy(n) for n in ev.get("notes", [])],
        })
    if mismatches:
        print(f"warning: {len(mismatches)} indicator results differ from features.csv, e.g. {mismatches[:3]}")

    DOCS.mkdir(parents=True, exist_ok=True)
    meta = {
        "indicators": {k: {"name": v["name"], "category": v["cat"], "points": v["points"], "ml": v["ml"]}
                       for k, v in config.INDICATORS.items()},
        "categories": config.CATEGORY_NAMES,
        "manual_checks": config.MANUAL_CHECKS,
        "bands": {"low": config.BAND_LOW_RISK, "caution": config.BAND_CAUTION},
        "lists": json.loads((config.LISTS / "manifest.json").read_text()) if (config.LISTS / "manifest.json").exists() else {},
    }
    res = config.RESULTS
    metrics = pd.read_csv(res / "metrics_cv.csv")
    meta["metrics"] = metrics.round(3).to_dict(orient="records")
    meta["summary"] = json.loads((res / "summary.json").read_text())
    (DOCS / "journals.json").write_text(json.dumps({"meta": meta, "journals": out}, ensure_ascii=False, separators=(",", ":")))

    flat = pd.DataFrame([{k: j[k] for k in ("id", "title", "issn", "url", "label", "group", "label_source", "split",
                                             "rule", "model", "hybrid", "verdict", "coverage")} for j in out])
    for k in config.INDICATORS:
        flat[k] = [next(i["result"] for i in j["indicators"] if i["id"] == k) for j in out]
    flat.to_csv(DOCS / "journalcheck_dataset.csv", index=False)

    v = pd.Series([j["verdict"] for j in out])
    print(f"{len(out)} journals -> {DOCS / 'journals.json'}")
    print(pd.crosstab(pd.Series([j['label'] for j in out], name="label"), v.rename("verdict")))


if __name__ == "__main__":
    main()
