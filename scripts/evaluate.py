"""Evaluate rules, machine learning and the hybrid on data/features.csv.

Positive class = high risk (predatory or hijacked). A journal counts as flagged when its
verdict is High risk. Results go to results/ as CSV and JSON, plus PNG figures.

    python scripts/evaluate.py
    python scripts/evaluate.py --exclude H04,H08,H10 --out results_sensitivity   # sensitivity check
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.base import clone  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import (accuracy_score, cohen_kappa_score, confusion_matrix, f1_score,  # noqa: E402
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import RepeatedStratifiedKFold  # noqa: E402

from journalcheck import config, scoring  # noqa: E402

OUT = config.RESULTS
POS = {"predatory", "hijacked"}
REPEATS, FOLDS, SEED = 10, 5, 42


def verdicts_from(trust: np.ndarray, df: pd.DataFrame | None = None, overrides: bool = False) -> np.ndarray:
    v = np.array([scoring.band(t) for t in trust], dtype=object)
    if overrides and df is not None:
        hard = (df["k1"] == 1) | (df["k2"] == 1) | (df["k3"] == 1)
        v[hard.values] = "High risk"
        cap = (df["integrity"] == 1).values & (v == "Low risk")
        v[cap] = "Caution"
    return v


def metrics(y: np.ndarray, verdict: np.ndarray, trust: np.ndarray) -> dict:
    pred = (verdict == "High risk").astype(int)
    flagged = (verdict != "Low risk").astype(int)
    return {
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
        "accuracy": accuracy_score(y, pred),
        "roc_auc": roc_auc_score(y, 100 - trust) if len(set(y)) > 1 else np.nan,
        "legit_flagged_rate": flagged[y == 0].mean() if (y == 0).any() else np.nan,
        "high_risk_missed_rate": (flagged[y == 1] == 0).mean() if (y == 1).any() else np.nan,
    }


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", default="", help="comma-separated journal ids to leave out")
    ap.add_argument("--out", default="", help="output folder (default results/)")
    args = ap.parse_args()
    if args.out:
        OUT = config.ROOT / args.out
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(config.DATA / "features.csv")
    if args.exclude:
        drop = {j.strip() for j in args.exclude.split(",") if j.strip()}
        df = df[~df["jid"].isin(drop)].reset_index(drop=True)
        print(f"Excluded {len(drop)} journals: {sorted(drop)}")
    train = df[(df["split"] == "train") & df["label"].isin(["legitimate", "predatory", "hijacked"])].reset_index(drop=True)
    ext = df[df["split"] == "external"].reset_index(drop=True)
    X, y = train[scoring.FEATURES], train["label"].isin(POS).astype(int).values
    print(f"Training set: {len(train)} journals ({y.sum()} high risk, {(y == 0).sum()} legitimate); external: {len(ext)}")

    models = scoring.make_models(SEED)
    rskf = RepeatedStratifiedKFold(n_splits=FOLDS, n_repeats=REPEATS, random_state=SEED)
    rows, oof_first = [], {}
    splits = list(rskf.split(X, y))
    for rep in range(REPEATS):
        oof = {name: np.zeros(len(y)) for name in models}
        for tr, te in splits[rep * FOLDS:(rep + 1) * FOLDS]:
            for name, m in models.items():
                mm = clone(m).fit(X.iloc[tr], y[tr])
                oof[name][te] = mm.predict_proba(X.iloc[te])[:, 1]
        t_lr, t_rf = 100 * (1 - oof["logistic"]), 100 * (1 - oof["forest"])
        t_hyb = config.HYBRID_WEIGHT_RULES * train["rule_trust"].values + (1 - config.HYBRID_WEIGHT_RULES) * t_lr
        setups = {
            "Rules (all 21 indicators)": (train["rule_trust"].values, verdicts_from(train["rule_trust"].values, train, True)),
            "Rules without list indicators": (train["rule_trust_nolist"].values, verdicts_from(train["rule_trust_nolist"].values)),
            "Logistic regression": (t_lr, verdicts_from(t_lr)),
            "Random forest": (t_rf, verdicts_from(t_rf)),
            "Hybrid (rules + logistic)": (t_hyb, verdicts_from(t_hyb, train, True)),
        }
        for name, (t, v) in setups.items():
            rows.append({"setup": name, "repeat": rep, **metrics(y, v, t)})
        if rep == 0:
            oof_first = {k: v for k, v in setups.items()}
    m = pd.DataFrame(rows)
    summary = m.groupby("setup", sort=False).agg(["mean", "std"]).drop(columns="repeat")
    summary.columns = [f"{a}_{b}" for a, b in summary.columns]
    summary.round(3).to_csv(OUT / "metrics_cv.csv")
    print(summary[[c for c in summary.columns if c.endswith("mean")]].round(3).to_string())

    # ROC points and confusion matrix from the first repeat
    roc_rows = []
    for name, (t, v) in oof_first.items():
        fpr, tpr, _ = roc_curve(y, 100 - t)
        roc_rows += [{"setup": name, "fpr": round(a, 4), "tpr": round(b, 4)} for a, b in zip(fpr, tpr)]
    pd.DataFrame(roc_rows).to_csv(OUT / "roc_points.csv", index=False)
    per_class = []
    for name, (t, v) in oof_first.items():
        r = {"setup": name}
        for cls in ("legitimate", "predatory", "hijacked"):
            m_ = (train["label"] == cls).values
            r[f"{cls}_high_risk"] = round(float((v[m_] == "High risk").mean()), 3)
            r[f"{cls}_low_risk"] = round(float((v[m_] == "Low risk").mean()), 3)
        r["median_trust_legitimate"] = round(float(np.median(t[train["label"].values == "legitimate"])), 1)
        r["median_trust_high_risk"] = round(float(np.median(t[y == 1])), 1)
        per_class.append(r)
    pd.DataFrame(per_class).to_csv(OUT / "per_class_first_repeat.csv", index=False)
    print(pd.DataFrame(per_class).to_string())
    t_h, v_h = oof_first["Hybrid (rules + logistic)"]
    cm = confusion_matrix(y, (v_h == "High risk").astype(int), labels=[0, 1])
    verdict_table = pd.crosstab(train["label"], pd.Series(v_h, name="verdict"))
    verdict_table.to_csv(OUT / "hybrid_verdicts_by_label.csv")

    # error analysis (first repeat, hybrid)
    err = train.assign(hybrid_trust=np.round(t_h, 1), hybrid_verdict=v_h)
    wrong = err[((err["label"] == "legitimate") & (err["hybrid_verdict"] != "Low risk")) |
                ((err["label"] != "legitimate") & (err["hybrid_verdict"] == "Low risk"))]
    ind_cols = list(config.INDICATORS)
    wrong = wrong.assign(failed=wrong[ind_cols].apply(lambda r: " ".join(k for k in ind_cols if r[k] == "fail"), axis=1),
                         unknown=wrong[ind_cols].apply(lambda r: int((r == "unknown").sum()), axis=1))
    wrong[["jid", "title", "label", "group", "rule_trust", "hybrid_trust", "hybrid_verdict", "coverage", "failed", "unknown"]] \
        .to_csv(OUT / "errors_hybrid.csv", index=False)

    # final models on all training data -> used by the app and the external test
    final = {name: clone(mm).fit(X, y) for name, mm in models.items()}
    for name, mm in final.items():
        scoring.save_model(mm, OUT / f"model_{name}.joblib")

    lr = final["logistic"]
    names = list(lr.named_steps["impute"].get_feature_names_out(scoring.FEATURES))
    coef = pd.DataFrame({"feature": [scoring.pretty(n) for n in names], "coefficient": lr.named_steps["clf"].coef_[0]})
    coef.reindex(coef["coefficient"].abs().sort_values(ascending=False).index).round(3).to_csv(OUT / "lr_coefficients.csv", index=False)
    # permutation importance measured on held-out folds (first repeat), so it reflects generalisation
    imps = {name: [] for name in models}
    for tr, te in splits[:FOLDS]:
        for name, mm in models.items():
            fitted = clone(mm).fit(X.iloc[tr], y[tr])
            pi = permutation_importance(fitted, X.iloc[te], y[te], n_repeats=20, random_state=SEED, scoring="roc_auc")
            imps[name].append(pi.importances_mean)
    imp = pd.DataFrame({"feature": [scoring.pretty(f) for f in scoring.FEATURES],
                        "importance": np.mean(imps["forest"], axis=0), "sd": np.std(imps["forest"], axis=0),
                        "importance_logistic": np.mean(imps["logistic"], axis=0)})
    imp = imp.sort_values("importance", ascending=False).round(4)
    imp.to_csv(OUT / "rf_importance.csv", index=False)

    # indicator pass rates by class (like the mini project's discrimination table)
    rates = []
    for k in ind_cols:
        known = train[train[k] != "unknown"]
        r = {"indicator": k, "name": config.INDICATORS[k]["name"]}
        for cls, sub in (("legitimate", known[known["label"] == "legitimate"]), ("predatory", known[known["label"] == "predatory"]),
                         ("hijacked", known[known["label"] == "hijacked"])):
            r[f"pass_{cls}"] = round((sub[k] == "pass").mean(), 3) if len(sub) else np.nan
            r[f"n_{cls}"] = len(sub)
        r["unknown_share"] = round((train[k] == "unknown").mean(), 3)
        rates.append(r)
    rates = pd.DataFrame(rates)
    rates["gap_legit_vs_predatory"] = (rates["pass_legitimate"] - rates["pass_predatory"]).round(3)
    rates.sort_values("gap_legit_vs_predatory", ascending=False).to_csv(OUT / "indicator_rates.csv", index=False)

    # external test: the 13 mini-project journals
    ext_out = {}
    if len(ext):
        Xe = ext[scoring.FEATURES]
        p = lr.predict_proba(Xe)[:, 1]
        t_ml = 100 * (1 - p)
        t_hyb = config.HYBRID_WEIGHT_RULES * ext["rule_trust"].values + (1 - config.HYBRID_WEIGHT_RULES) * t_ml
        v = verdicts_from(t_hyb, ext, True)
        manual = ext["label"].map({"legitimate": "Low risk", "compromised": "Caution", "predatory": "High risk", "hijacked": "High risk"})
        table = ext[["jid", "title", "label", "rule_trust", "coverage"]].assign(ml_trust=np.round(t_ml, 1), hybrid_trust=np.round(t_hyb, 1),
                                                                                hybrid_verdict=v, manual_verdict=manual.values)
        table.to_csv(OUT / "external_test.csv", index=False)
        agree = (table["hybrid_verdict"] == table["manual_verdict"])
        ext_out = {"n": int(len(table)), "agreement": round(float(agree.mean()), 3),
                   "kappa": round(float(cohen_kappa_score(table["manual_verdict"], table["hybrid_verdict"])), 3)}
        print(table.to_string())

    # hijack test
    hj = df[df["label"] == "hijacked"]
    lg = df[df["label"] == "legitimate"]
    t_lr_first = oof_first["Logistic regression"][0]
    hj_train = train["label"].values == "hijacked"
    hj_out = {"n": int(len(hj)),
              "possible_clone_flag": int(hj.get("possible_clone", pd.Series(dtype=int)).sum()),
              "possible_clone_flag_on_legitimate": int(lg.get("possible_clone", pd.Series(dtype=int)).sum()),
              "model_only_high_risk (train, out-of-fold)": int((t_lr_first[hj_train] < config.BAND_CAUTION).sum()),
              "model_only_flagged (train, out-of-fold)": int((t_lr_first[hj_train] < config.BAND_LOW_RISK).sum()),
              "n_train": int(hj_train.sum()),
              "flagged_high_risk_by_rules": int((hj["rule_verdict"] == "High risk").sum()),
              "k1_any": int(hj["k1"].sum()),
              "k1_without_list (I3 and I4 fail)": int(((hj["I3"] == "fail") & (hj["I4"] == "fail")).sum()),
              "I3_fail": int((hj["I3"] == "fail").sum()), "I4_fail": int((hj["I4"] == "fail").sum()),
              "I19_fail": int((hj["I19"] == "fail").sum())}

    summary_json = {
        "dataset": {f"{s}/{l}": int(n) for (s, l), n in df.groupby(["split", "label"]).size().items()},
        "cv": f"{REPEATS} x {FOLDS}-fold stratified",
        "hybrid_confusion_first_repeat": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]), "fn": int(cm[1, 0]), "tp": int(cm[1, 1])},
        "external_test": ext_out,
        "hijack_test": hj_out,
        "median_seconds_per_journal": float(df["seconds"].median()),
        "mean_coverage": round(float(df["coverage"].mean()), 3),
    }
    (OUT / "summary.json").write_text(json.dumps(summary_json, indent=2))
    print(json.dumps(summary_json, indent=2))
    _figures(oof_first, y, rates, imp)


def _figures(oof_first, y, rates, imp) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return
    fig, ax = plt.subplots(figsize=(6, 5))
    for name, (t, _) in oof_first.items():
        fpr, tpr, _ = roc_curve(y, 100 - t)
        ax.plot(fpr, tpr, label=f"{name} (AUC {roc_auc_score(y, 100 - t):.2f})")
    ax.plot([0, 1], [0, 1], ls="--", c="grey", lw=0.8)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "fig_roc.png", dpi=150)
    fig, ax = plt.subplots(figsize=(7, 6))
    r = rates.sort_values("gap_legit_vs_predatory")
    ax.barh(r["indicator"] + " " + r["name"], r["gap_legit_vs_predatory"])
    ax.set_xlabel("Pass rate: legitimate minus predatory")
    fig.tight_layout()
    fig.savefig(OUT / "fig_indicator_gap.png", dpi=150)
    fig, ax = plt.subplots(figsize=(7, 5))
    top = imp.head(12).iloc[::-1]
    ax.barh(top["feature"].str.slice(0, 45), top["importance"], xerr=top["sd"])
    ax.set_xlabel("Permutation importance (drop in ROC-AUC)")
    fig.tight_layout()
    fig.savefig(OUT / "fig_rf_importance.png", dpi=150)


if __name__ == "__main__":
    main()
