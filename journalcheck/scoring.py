"""Rule engine, machine-learning model and the hybrid decision."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

ML_INDICATORS = [k for k, v in config.INDICATORS.items() if v["ml"]]
NUMERIC = ["papers_last_year", "log_works_count", "journal_age", "domain_age", "apc_usd",
           "two_yr_mean_citedness", "log_h_index", "cites_per_paper", "top_field_share",
           "max_growth", "red_flag_phrases", "site_reachable", "https", "tls_error"]
FEATURES = [f"ind_{k}" for k in ML_INDICATORS] + NUMERIC
_ENC = {"pass": 1.0, "fail": 0.0, "unknown": 0.5}

# ------------------------------------------------------------------ rules

def rule_score(indicators: dict, exclude: tuple[str, ...] = ()) -> dict:
    use = {k: v for k, v in indicators.items() if k not in exclude}
    earned = sum(v["points"] for v in use.values())
    maximum = sum(v["max"] for v in use.values())
    known = sum(v["max"] for v in use.values() if v["result"] != "unknown")
    by_cat: dict[str, list[float]] = {}
    for v in use.values():
        e, m = by_cat.get(v["category"], [0.0, 0.0])
        by_cat[v["category"]] = [e + v["points"], m + v["max"]]
    return {"trust": 100 * earned / maximum, "earned": earned, "max": maximum,
            "coverage": known / maximum, "by_category": {k: {"earned": e, "max": m} for k, (e, m) in sorted(by_cat.items())}}

# ------------------------------------------------------------------ ML

def feature_row(features: dict) -> dict:
    row = {f"ind_{k}": _ENC[features["indicators"][k]["result"]] for k in ML_INDICATORS}
    for k in NUMERIC:
        v = features["numeric"].get(k)
        row[k] = float(v) if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)) else np.nan
    return row


def make_models(seed: int = 42) -> dict:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "logistic": Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(C=0.5, class_weight="balanced", max_iter=5000)),
        ]),
        "forest": Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("clf", RandomForestClassifier(n_estimators=400, min_samples_leaf=2, class_weight="balanced_subsample",
                                           random_state=seed, n_jobs=-1)),
        ]),
    }


def save_model(model, path: Path) -> None:
    import joblib
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES}, path)


def load_model(path: Path | None = None):
    import joblib
    path = path or (config.RESULTS / "model_logistic.joblib")
    if not Path(path).exists():
        return None
    blob = joblib.load(path)
    return blob["model"]


def ml_trust(model, row: dict) -> float | None:
    if model is None:
        return None
    X = pd.DataFrame([row], columns=FEATURES)
    p = float(model.predict_proba(X)[0, 1])
    return 100 * (1 - p)


def explain_logistic(model, row: dict, top: int = 5) -> list[dict]:
    """Per-feature contribution to the log-odds of 'high risk' (coefficient x scaled value)."""
    if model is None or "clf" not in model.named_steps or not hasattr(model.named_steps["clf"], "coef_"):
        return []
    X = pd.DataFrame([row], columns=FEATURES)
    imputed = model.named_steps["impute"].transform(X)
    scaled = model.named_steps["scale"].transform(imputed)[0]
    names = list(model.named_steps["impute"].get_feature_names_out(FEATURES))
    coefs = model.named_steps["clf"].coef_[0]
    contrib = sorted(({"feature": pretty(n), "contribution": float(c * s)} for n, c, s in zip(names, coefs, scaled)),
                     key=lambda d: -abs(d["contribution"]))
    return [c for c in contrib if abs(c["contribution"]) > 0.05][:top]


def pretty(name: str) -> str:
    if name.startswith("missingindicator_"):
        return pretty(name[len("missingindicator_"):]) + " (missing)"
    if name.startswith("ind_"):
        k = name[4:]
        return f"{k} {config.INDICATORS[k]['name']}"
    return name.replace("_", " ")

# ------------------------------------------------------------------ hybrid decision

def band(trust: float) -> str:
    if trust >= config.BAND_LOW_RISK:
        return "Low risk"
    if trust >= config.BAND_CAUTION:
        return "Caution"
    return "High risk"


def decide(rule: dict, t_ml: float | None, flags: dict) -> dict:
    w = config.HYBRID_WEIGHT_RULES
    t = rule["trust"] if t_ml is None else w * rule["trust"] + (1 - w) * t_ml
    verdict = band(t)
    overrides = []
    if flags.get("k1_hijacked"):
        overrides.append("K1 hijacked clone: website listed on the Retraction Watch Hijacked Journal Checker")
    for c in flags.get("k3_false_claims") or []:
        overrides.append(f"K3 false indexing claim: {c}")
    if flags.get("k2_court_finding"):
        overrides.append("K2 court or regulator finding")
    if overrides:
        verdict = "High risk"
    if flags.get("integrity_alert") and verdict == "Low risk":
        verdict = "Caution"
        overrides.append("Integrity alert: verdict capped at Caution")
    review = []
    if verdict == "Caution":
        review.append("verdict is Caution")
    if overrides:
        review.append("an override fired")
    if t_ml is not None and abs(rule["trust"] - t_ml) >= config.REVIEW_DISAGREEMENT:
        review.append(f"rules and model disagree by {abs(rule['trust'] - t_ml):.0f} points")
    if flags.get("possible_clone"):
        review.append("possible clone: the website's domain differs from the registry's and was registered late")
    if rule["coverage"] < config.REVIEW_MIN_COVERAGE:
        review.append(f"only {rule['coverage']:.0%} of the evidence could be checked")
    return {"trust": t, "band": band(t), "verdict": verdict, "overrides": overrides,
            "needs_review": bool(review), "review_reasons": review}
