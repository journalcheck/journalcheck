# JournalCheck dataset

108 journals labelled from independent public sources, with the evidence-based features that JournalCheck computed for them in October 2026 (lists downloaded on 11 October 2026; see `lists/manifest.json`).

## Files

| File | Rows | What it holds |
| --- | ---: | --- |
| `seed_journals.csv` | 108 | The labelled sample: ID, title, ISSN, website, label, sampling group, label source, split |
| `features.csv` | 108 | The 21 indicator results, 14 numeric features, rule scores and override flags for each journal |
| `lists/court_findings.csv` | 3 | Hand-curated court and regulator findings (FTC v. OMICS, 2019), used by override K2 |
| `lists/manifest.json` | – | Sources, row counts and download dates of the snapshot lists |
| `archive/` | – | Version 1 inputs, kept for the iteration analysis in the report |

## `seed_journals.csv`

| Column | Meaning |
| --- | --- |
| `jid` | Journal ID: L = legitimate, P = predatory, H = hijacked clone, M = mini-project (external test) |
| `title` | Journal title; "(clone)" marks a hijacked clone's copied title |
| `issn` | ISSN as given (blank when the clone shows none) |
| `url` | The website that was checked. For a clone, this is the clone's address, not the genuine journal's |
| `label` | `legitimate`, `predatory`, `hijacked` or `compromised` |
| `group` | Sampling group: `core`, `doaj`, `doaj_india`, `scopus_india`, `beall`, `beall_hijacked`, `hijacked`, `mini` |
| `label_source` | Where the label comes from |
| `split` | `train` (95 journals, used for cross-validation) or `external` (13 mini-project journals, never trained on) |

## `features.csv`

| Columns | Meaning |
| --- | --- |
| `jid`, `title`, `label`, `group`, `split` | As above |
| `issn_resolved`, `website`, `site_status` | ISSN and website after resolution; whether the website loaded |
| `seconds` | Time taken to collect the evidence (cached run) |
| `rule_trust` | Rule score, 0–100 (points earned / 40 × 100) |
| `rule_trust_nolist` | Rule score without the four list indicators (I5, I19–I21) |
| `coverage` | Share of indicator points that could be checked |
| `rule_verdict` | Verdict from the rules alone, after overrides |
| `k1`, `k2`, `k3`, `integrity`, `possible_clone` | Override and review flags: K1 hijacked listing, K2 court finding, K3 false indexing claim, integrity alert, possible clone (I3 and I4 both fail) |
| `I1` … `I21` | Indicator results: `pass`, `fail` or `unknown` |
| `ind_I1` … `ind_I18` | The same results encoded for the model (1, 0, 0.5); list indicators are excluded |
| `papers_last_year` … `tls_error` | The 14 numeric features given to the model (see `journalcheck/features.py`) |

The indicator definitions, points and thresholds are in `journalcheck/config.py`.

## How to read the labels

The labels come from public lists and registries, so they carry some noise. A predatory label means only that the journal is in the Beall's list archive, not that we found it predatory. Three hijacked clones (H04, H08, H10) had lapsed by the time the evidence was collected; `results_sensitivity/` repeats the evaluation without them.

## Licence

CC BY 4.0. Please cite the project (see `CITATION.cff`).
