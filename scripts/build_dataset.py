"""Build the labelled dataset data/seed_journals.csv by random sampling (seed 42).

    Legitimate (40)  OpenAlex: 15 CWTS-core journals + 15 DOAJ journals + 10 Indian DOAJ journals,
                     computing and engineering titles, with a known homepage
    Predatory (40)   Beall's archive standalone journals in engineering/technology/computing whose
                     website is reachable and shows a valid ISSN; titles now in DOAJ or Scopus are
                     dropped as likely label noise
    Hijacked (15)    clone websites from the Retraction Watch Hijacked Journal Checker that still load
    External (13)    the mini-project journals with their manual verdicts (never used for training)

Run scripts/build_lists.py first.
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
from journalcheck.util import fetch, normalize_issn  # noqa: E402

SEED = 42
random.seed(SEED)
OUT = config.DATA / "seed_journals.csv"
TOPIC_WORDS = re.compile(r"comput|software|engineer|electr|informat|intelligen|machine learning|data|network|robot|automat|signal|cyber|technolog|communication", re.I)
BEALL_WORDS = re.compile(r"engineer|technolog|comput|software|electr|informat|innovat|advanced research|science and|scientific research", re.I)

MINI = [  # jid, title, issn, url, label (mini verdict), group
    ("M01", "IEEE Access", "2169-3536", "https://ieeeaccess.ieee.org/", "legitimate"),
    ("M02", "Expert Systems with Applications", "0957-4174", "https://www.sciencedirect.com/journal/expert-systems-with-applications", "legitimate"),
    ("M03", "PeerJ Computer Science", "2376-5992", "https://peerj.com/computer-science/", "legitimate"),
    ("M04", "Sadhana", "0256-2499", "https://link.springer.com/journal/12046", "legitimate"),
    ("M05", "Journal of Machine Learning Research", "1532-4435", "https://www.jmlr.org/", "legitimate"),
    ("M06", "Journal of Open Source Software", "2475-9066", "https://joss.theoj.org/", "legitimate"),
    ("M07", "Computational Intelligence and Neuroscience", "1687-5265", "https://www.hindawi.com/journals/cin/", "compromised"),
    ("M08", "International Journal of Engineering Research & Technology", "2278-0181", "https://www.ijert.org/", "predatory"),
    ("M09", "International Research Journal of Engineering and Technology", "2395-0056", "https://www.irjet.net/", "predatory"),
    ("M10", "Journal of Computer Science & Systems Biology", "0974-7230", "https://www.omicsonline.org/computer-science-systems-biology.php", "predatory"),
    ("M11", "WASET periodicals", "", "https://waset.org/", "predatory"),
]
MINI_HIJACKED_TITLES = {"M12": "seybold", "M13": "romanian society for cell biology"}


def openalex_pool(filter_: str, n_pages: int = 4) -> list[dict]:
    pool = []
    for word in ["computer", "computing", "software", "engineering", "electronics", "intelligence",
                 "information", "networks", "data", "robotics", "signal", "communications"]:
        for page in range(1, n_pages + 1):
            res = fetch("https://api.openalex.org/sources",
                        params={"search": word, "filter": filter_, "per-page": 50, "page": page})
            for s in ((res.get("data") or {}).get("results") or []):
                if s.get("homepage_url") and s.get("issn_l") and (s.get("works_count") or 0) >= 50 \
                        and TOPIC_WORDS.search(s.get("display_name") or ""):
                    pool.append(s)
    uniq = {s["id"]: s for s in pool}
    return sorted(uniq.values(), key=lambda s: s["id"])


def legit_rows(st) -> list[list]:
    rows, used = [], set()
    for group, filt, n in (("core", "type:journal,is_core:true", 15),
                           ("doaj", "type:journal,is_in_doaj:true", 15),
                           ("doaj_india", "type:journal,is_in_doaj:true,country_code:IN", 10)):
        pool = [s for s in openalex_pool(filt) if s["id"] not in used]
        random.shuffle(pool)
        k = 0
        for s in pool:
            b = st.bealls(s["display_name"], s.get("host_organization_name"), s.get("homepage_url"))
            if b and b["listed"]:
                continue  # never label a Beall-listed title as legitimate
            used.add(s["id"])
            k += 1
            rows.append([f"L{len(rows) + 1:02d}", s["display_name"], s["issn_l"], s["homepage_url"],
                         "legitimate", group, "OpenAlex " + filt, "train"])
            if k >= n:
                break
        print(f"  legitimate/{group}: {k} of {n} (pool {len(pool)})", flush=True)
    return rows


def predatory_rows(st, n: int = 40) -> list[list]:
    cands = [r for r in st.rows["bealls"] or [] if r.get("kind") == "journal" and r.get("url") and BEALL_WORDS.search(r["name"])]
    random.shuffle(cands)
    rows = []
    for r in cands:
        if len(rows) >= n:
            break
        site = fetch_site(r["url"], deep=False)
        if site.get("status") != "found" or len(site.get("text") or "") < 500:
            continue  # dead or parked site
        issn = (site.get("issns_found") or [""])[0]
        if issn:
            oa = reg.openalex_source(issn)
            if oa.get("is_in_doaj") or st.in_scopus([issn] + list(oa.get("issn") or [])):
                continue  # now whitelisted: likely label noise, as the archive itself warns
        rows.append([f"P{len(rows) + 1:02d}", r["name"], issn, site.get("final_url") or r["url"],
                     "predatory", "beall", "Beall's archive (standalone journals)", "train"])
        print(f"  predatory {len(rows)}: {r['name'][:60]}", flush=True)
    return rows


def hijacked_rows(st, n: int = 15) -> tuple[list[list], list[list]]:
    cands = [r for r in st.rows["hijacked"] or [] if r.get("hijacked_url")]
    random.shuffle(cands)
    rows, mini, seen = [], [], set()
    # the two hijacked journals from the mini project first
    for jid, key in MINI_HIJACKED_TITLES.items():
        for r in cands:
            if key in (r.get("title") or "").lower():
                site = fetch_site(r["hijacked_url"], deep=False)
                if site.get("status") == "found":
                    mini.append([jid, r["title"] + " (clone)", "", site.get("final_url") or r["hijacked_url"],
                                 "hijacked", "mini", "Mini project; Retraction Watch Hijacked Journal Checker", "external"])
                    seen.add(r["hijacked_url"])
                    break
    for r in cands:
        if len(rows) >= n:
            break
        u = r["hijacked_url"]
        if u in seen:
            continue
        seen.add(u)
        site = fetch_site(u, deep=False)
        if site.get("status") != "found":
            continue
        rows.append([f"H{len(rows) + 1:02d}", r["title"] + " (clone)", "", site.get("final_url") or u,
                     "hijacked", "hijacked", "Retraction Watch Hijacked Journal Checker", "train"])
        print(f"  hijacked {len(rows)}: {u}", flush=True)
    return rows, mini


def main() -> None:
    st = store()
    missing = [k for k in ("bealls", "hijacked") if not st.available[k]]
    if missing:
        print(f"Missing lists {missing}: run scripts/build_lists.py first.")
    rows = legit_rows(st)
    rows += predatory_rows(st)
    hj, mini_hj = hijacked_rows(st)
    rows += hj
    rows += [[jid, t, normalize_issn(i) or "", u, lab, "mini", "Mini project manual verdict", "external"] for jid, t, i, u, lab in MINI]
    rows += mini_hj
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["jid", "title", "issn", "url", "label", "group", "label_source", "split"])
        w.writerows(rows)
    by = {}
    for r in rows:
        by[(r[4], r[7])] = by.get((r[4], r[7]), 0) + 1
    print(f"Wrote {len(rows)} journals to {OUT}: {by}")


if __name__ == "__main__":
    main()
