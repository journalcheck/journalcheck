"""Add 10 Indian legitimate journals to data/seed_journals.csv (seed 42).

Sampled from the SCImago list (Scopus-indexed titles) with country India and a computer
science or engineering category; homepages come from free single-journal OpenAlex lookups.
"""
from __future__ import annotations

import csv
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from journalcheck import config  # noqa: E402
from journalcheck.collectors import registries as reg  # noqa: E402
from journalcheck.collectors.lists import store  # noqa: E402
from journalcheck.collectors.website import fetch_site  # noqa: E402
from journalcheck.util import normalize_issn  # noqa: E402

random.seed(42)
CATS = re.compile(r"computer|software|engineering|electr|information systems|artificial intelligence|signal", re.I)
st = store()
rows = [r for r in st.rows["scimago"] or [] if (r.get("country") or "").strip().lower() == "india" and CATS.search(r.get("categories") or "")]
random.shuffle(rows)
seed_path = config.DATA / "seed_journals.csv"
seed = list(csv.DictReader(seed_path.open(newline="", encoding="utf-8")))
have = {s["issn"] for s in seed if s.get("issn")}
added = []
for r in rows:
    if len(added) >= 10:
        break
    issns = [normalize_issn(x) for x in re.split(r"[,;\s]+", r["issns"]) if normalize_issn(x)]
    if not issns or set(issns) & have:
        continue
    oa = {}
    for i in issns:
        oa = reg.openalex_source(i)
        if oa.get("status") == "found":
            break
    if oa.get("status") != "found" or not oa.get("homepage_url"):
        continue
    b = st.bealls(oa.get("title"), oa.get("publisher"), oa.get("homepage_url"))
    if b and b["listed"]:
        continue
    site = fetch_site(oa["homepage_url"], deep=False)
    if site.get("status") != "found":
        continue
    n = sum(1 for s in seed if s["jid"].startswith("L")) + len(added) + 1
    added.append({"jid": f"L{n:02d}", "title": oa.get("title") or r["title"], "issn": oa.get("issn_l") or issns[0],
                  "url": oa["homepage_url"], "label": "legitimate", "group": "scopus_india",
                  "label_source": "SCImago list (Scopus), country India", "split": "train"})
    print(f"  added {added[-1]['jid']}: {added[-1]['title']}", flush=True)
with seed_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(seed[0].keys()))
    w.writeheader()
    w.writerows(seed + added)
print(f"Added {len(added)} Indian journals; dataset now {len(seed) + len(added)} rows")
