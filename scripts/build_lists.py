"""Download the snapshot lists used by indicators I5 and I19-I21 into data/lists/.

Each list is optional: if a download fails the script says so and the tool marks the
indicators that depend on it as "not checked". Run again to refresh the snapshots.

    python scripts/build_lists.py            # all lists
    python scripts/build_lists.py bealls     # one list
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from journalcheck import config  # noqa: E402
from journalcheck.util import norm_title  # noqa: E402

S = requests.Session()
S.headers.update({"User-Agent": config.USER_AGENT})
OUT = config.LISTS
OUT.mkdir(parents=True, exist_ok=True)
MANIFEST = OUT / "manifest.json"
# some sites refuse unknown clients; these downloads identify as a normal browser
BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
           "Referer": "https://www.scimagojr.com/journalrank.php"}


def _write(name: str, header: list[str], rows: list[list], source: str) -> None:
    with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    man[name] = {"rows": len(rows), "source": source, "downloaded": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    MANIFEST.write_text(json.dumps(man, indent=2))
    print(f"  {name}: {len(rows)} rows from {source}")


def _get(url: str, **kw) -> requests.Response:
    r = S.get(url, timeout=60, **kw)
    r.raise_for_status()
    return r

# ------------------------------------------------------------------ Beall's list archive

def bealls() -> None:
    rows = []
    for url, kind in (("https://beallslist.net/standalone-journals/", "journal"), ("https://beallslist.net/", "publisher")):
        soup = BeautifulSoup(_get(url).text, "html.parser")
        main = soup.find("article") or soup.find("main") or soup
        for li in main.find_all("li"):
            a = li.find("a", href=True)
            name = " ".join(li.get_text(" ").split())
            if not name or len(name) < 4 or len(name) > 250:
                continue
            href = a["href"] if a else ""
            if "beallslist.net" in href:
                continue
            rows.append([name, href, kind])
    rows = list({(r[0], r[2]): r for r in rows}.values())
    _write("bealls", ["name", "url", "kind"], rows, "beallslist.net (standalone journals + publishers)")

# ------------------------------------------------------------------ Retraction Watch Hijacked Journal Checker

RW_PAGE = "https://retractionwatch.com/the-retraction-watch-hijacked-journal-checker/"


def _sheet_csv_urls(html: str) -> list[str]:
    urls = []
    for pub_id in re.findall(r"docs\.google\.com/spreadsheets/d/e/([\w-]+)", html):
        urls.append(f"https://docs.google.com/spreadsheets/d/e/{pub_id}/pub?output=csv")
    for sid in re.findall(r"docs\.google\.com/spreadsheets/d/([\w-]{25,})", html):
        if sid != "e":
            urls.append(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv")
    return list(dict.fromkeys(urls))


def hijacked() -> None:
    page = _get(RW_PAGE).text
    urls = _sheet_csv_urls(page)
    if not urls:
        raise RuntimeError("no Google Sheet link found on the Retraction Watch page")
    last_err = None
    for u in urls:
        try:
            text = _get(u).content.decode("utf-8", "replace")
            table = list(csv.reader(io.StringIO(text)))
            break
        except Exception as e:  # try the next link
            last_err = e
    else:
        raise RuntimeError(f"could not download the sheet: {last_err}")
    # find the header row and the columns holding titles and hijacked URLs
    hdr_i = next(i for i, r in enumerate(table[:15])
                 if any("url" in c.lower() and "hijack" in c.lower() for c in r) or
                 (any("title" in c.lower() for c in r) and any("issn" in c.lower() for c in r)))
    hdr = [c.lower() for c in table[hdr_i]]
    title_col = next((i for i, c in enumerate(hdr) if "title" in c), next((i for i, c in enumerate(hdr) if "journal" in c), 0))
    url_cols = [i for i, c in enumerate(hdr) if "hijack" in c and ("url" in c or "website" in c or "link" in c or "domain" in c)]
    if not url_cols:
        url_cols = [i for i, c in enumerate(hdr) if "hijack" in c]
    issn_cols = [i for i, c in enumerate(hdr) if "issn" in c and "original" not in c] or [i for i, c in enumerate(hdr) if "issn" in c]
    rows = []
    for r in table[hdr_i + 1:]:
        if len(r) <= max(url_cols + [title_col]):
            continue
        title = r[title_col].strip()
        issns = " ".join(r[i] for i in issn_cols if i < len(r))
        for col in url_cols:
            for tok in re.split(r"[\s,;]+", r[col]):
                tok = tok.strip().strip(".")
                if re.search(r"[a-z0-9-]+\.[a-z]{2,}", tok, re.I):
                    rows.append([title, tok, issns])
    _write("hijacked", ["title", "hijacked_url", "issns"], rows, "Retraction Watch Hijacked Journal Checker (Google Sheet)")

# ------------------------------------------------------------------ SCImago (Scopus-indexed titles)

def scimago() -> None:
    r = _get("https://www.scimagojr.com/journalrank.php", params={"out": "xls"}, headers=BROWSER)
    text = r.content.decode("utf-8", "replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    hdr = [h.strip().lower() for h in next(reader)]
    ti, ii = hdr.index("title"), hdr.index("issn")
    ci = hdr.index("country") if "country" in hdr else None
    ki = hdr.index("categories") if "categories" in hdr else None
    oi = hdr.index("open access") if "open access" in hdr else None
    get = lambda row, i: row[i] if i is not None and i < len(row) else ""
    rows = [[row[ti], row[ii], get(row, ci), get(row, ki), get(row, oi)] for row in reader if len(row) > ii]
    _write("scimago", ["title", "issns", "country", "categories", "open_access"], rows, "SCImago Journal Rank download (Scopus titles)")

# ------------------------------------------------------------------ Retraction Watch database (via Crossref)

def retractions() -> None:
    url = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"
    r = _get(url, stream=True)
    raw = r.content.decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(raw))
    col = next(c for c in reader.fieldnames if c.strip().lower() == "journal")
    nature = next((c for c in reader.fieldnames if c.strip().lower() in ("retractionnature", "retraction nature")), None)
    counts: Counter = Counter()
    for row in reader:
        if nature and row.get(nature) and "retraction" not in row[nature].lower():
            continue  # keep retractions, skip corrections and expressions of concern
        counts[norm_title(row[col])] += 1
    rows = [[j, n] for j, n in counts.most_common() if j]
    _write("retractions", ["journal", "retractions"], rows, "Retraction Watch database (Crossref GitLab)")

# ------------------------------------------------------------------ court and regulator findings (curated)

def court_findings() -> None:
    rows = [
        ["OMICS", "omicsonline.org", "US federal court judgment of $50.1 million for deceptive practices (FTC v. OMICS, 2019)"],
        ["iMedPub", "imedpub.com", "Co-defendant in FTC v. OMICS (2019)"],
        ["Conference Series", "conferenceseries.com", "Co-defendant in FTC v. OMICS (2019)"],
    ]
    _write("court_findings", ["publisher", "domain", "finding"], rows, "Curated from the FTC press release (April 2019)")


STEPS = {"court_findings": court_findings, "bealls": bealls, "hijacked": hijacked, "scimago": scimago, "retractions": retractions}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(STEPS)
    for name in wanted:
        print(f"[lists] {name} ...", flush=True)
        try:
            STEPS[name]()
        except Exception as e:
            print(f"  {name}: FAILED ({e.__class__.__name__}: {str(e)[:200]})", flush=True)
    print("[lists] Optional extras you can add by hand: data/lists/scopus_discontinued.csv and data/lists/doaj_withdrawn.csv (columns: title, issns[, reason]).")
