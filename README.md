# JournalCheck

**An explainable framework and prototype for detecting predatory and hijacked journals.**
B.Tech major project, School of Technology, Woxsen University, 2026.

🌐 **Website:** <https://journalcheck.github.io/>. Browse the dataset, open any journal's evidence report, or check a journal against the registries from your browser.

JournalCheck turns the 20-criterion manual checklist from our mini project into **21 automated indicators worth 40 points**. The evidence comes from OpenAlex, Crossref, DOAJ, RDAP domain records, the journal's own website and snapshot lists: the Retraction Watch Hijacked Journal Checker, the Beall's list archive, SCImago (Scopus) and the Retraction Watch database.

A **rule engine** and a **logistic-regression model** score the same evidence. The **trust score** is their average, and it gives one of three verdicts: Low risk (80+), Caution (50–79) or High risk (below 50). Override rules handle decisive evidence, and uncertain cases go to a **human-review** step. Every verdict comes with an evidence report.

| Result (10 × 5-fold cross-validation, 95 journals) | Value |
| --- | --- |
| Hybrid precision / recall / F1 | 0.954 / 0.911 / **0.932** |
| ROC-AUC | 0.969 |
| Legitimate journals flagged (any verdict other than Low risk) | 24% |
| External test: agreement with the mini project's manual verdicts | **12 of 13** (Cohen's κ 0.865) |
| Live hijacked clones caught by the list indicator (I19) | 15 of 15 |

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/journalcheck/journalcheck
cd journalcheck
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/build_lists.py        # download the snapshot lists into data/lists/
streamlit run app.py                 # web interface at http://localhost:8501
```

On a Mac you can instead double-click **`run_journalcheck.command`**. It sets up the environment, downloads the lists the first time, and opens the app.

Optional: set `JOURNALCHECK_MAILTO=you@example.org` to send a contact address to OpenAlex and Crossref (their "polite pool").

## The dataset

`data/seed_journals.csv` lists the **108 labelled journals**, and `data/features.csv` holds their indicator results, numeric features and rule scores. A per-journal table with model and hybrid scores is at [`docs/data/journalcheck_dataset.csv`](docs/data/journalcheck_dataset.csv). The data dictionary is in [`data/README.md`](data/README.md).

| Class | Training | External test | Source of the label |
| --- | ---: | ---: | --- |
| Legitimate | 40 | 6 | OpenAlex core sources, DOAJ, Indian Scopus titles (SCImago) |
| Predatory | 39 | 4 | Beall's list archive (standalone journals) |
| Hijacked | 16 | 2 | Retraction Watch Hijacked Journal Checker |
| Compromised | – | 1 | Mini project manual verdict |
| **Total** | **95** | **13** | |

The 13 external journals are the ones we checked by hand in the mini project. They were never used for training.

## Reproducing the evaluation

```bash
python scripts/build_lists.py        # snapshot lists
python scripts/build_dataset.py      # labelled sample -> data/seed_journals.csv (seed 42)
python scripts/add_india.py          # 10 Indian Scopus journals
python scripts/collect.py            # evidence -> data/evidence/*.json and data/features.csv
python scripts/evaluate.py           # metrics, models and figures -> results/
python scripts/evaluate.py --exclude H04,H08,H10 --out results_sensitivity   # without the lapsed clones
python scripts/build_site.py         # data for the website -> docs/data/
pytest                               # offline unit tests
```

`evaluate.py` needs only `data/features.csv`, so you can reproduce every number in the report without going online. Collecting fresh evidence gives slightly different results, because websites and lists change.

## Repository layout

| Path | What it holds |
| --- | --- |
| `journalcheck/config.py` | Indicator weights, thresholds and phrase rules (every number the tool uses) |
| `journalcheck/collectors/` | OpenAlex, Crossref, DOAJ, RDAP, website and snapshot-list collectors |
| `journalcheck/features.py` | Evidence → 21 indicators and 14 numeric features |
| `journalcheck/scoring.py` | Rule engine, ML model, hybrid decision and overrides |
| `journalcheck/pipeline.py` | End-to-end check of one journal |
| `journalcheck/report.py` | Evidence report (Markdown / HTML) |
| `app.py` | Streamlit web interface |
| `scripts/` | Lists, dataset, evidence collection, evaluation, website data |
| `data/` | Labelled dataset and features (see `data/README.md`) |
| `results/` | Version 2 results: metrics, error analysis, external test, trained models, figures |
| `results_sensitivity/` | Version 2 without the three lapsed clones |
| `results_v1/`, `data/archive/` | Version 1 results and inputs, kept for the iteration analysis |
| `docs/` | Source of the website, published at <https://journalcheck.github.io/> from the [journalcheck.github.io](https://github.com/journalcheck/journalcheck.github.io) repository |

Not in the repository:

- `data/lists/*.csv`: third-party lists, which `build_lists.py` downloads.
- `data/evidence/`: the raw evidence. It contains copied website text, and `collect.py` regenerates it.
- `data/cache/`: the API response cache.

## Responsible use

JournalCheck is a **triage aid, not a blacklist**. A High-risk verdict means a person should check the journal before submitting. It is not a finding that the journal is predatory.

Country and language are deliberately not used as features. Even so, Indian legitimate journals were flagged more often than others in our evaluation (5 of 11, against 3 of 29), so regional journals deserve a careful human review.

## Authors

Rhea Ishani Chemudupati (23WU0101028) and Himanshu Maurya (23WU0102068). Guide: Dr. M. Upendra Kumar, School of Technology, Woxsen University.

Course: Research Writing, Intellectual Property and Scholarly Publishing (25TU08MI16).

## Licence

Code: [MIT](LICENSE). Dataset labels, features and scores in `data/`, `results*/` and `docs/data/`: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The third-party lists keep their own terms and are not redistributed here.
