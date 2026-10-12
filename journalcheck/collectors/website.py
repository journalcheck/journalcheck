"""Website collector: fetches a journal's home page (and a few linked pages) and
extracts the title, visible text, links, contact emails and ISSNs."""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import config
from ..util import fetch, find_issns, registered_domain

MAX_DEEP_PAGES = 3


def _parse(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    og = soup.find("meta", attrs={"property": "og:site_name"})
    h1 = soup.find(["h1", "h2"])
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    links = []
    for a in soup.find_all("a", href=True):
        label = " ".join(a.get_text(" ").split())[:120]
        href = urljoin(base_url, a["href"])
        if href.startswith("mailto:"):
            continue
        links.append({"text": label, "href": href})
    mailtos = [a["href"][7:].split("?")[0] for a in soup.find_all("a", href=True) if a["href"].lower().startswith("mailto:")]
    # ISSNs often appear only as a link to the ISSN Portal or in an image's alt text
    hints = [a["href"] for a in soup.find_all("a", href=True) if "issn" in a["href"].lower()]
    hints += [img.get("alt", "") for img in soup.find_all("img") if "issn" in (img.get("alt") or "").lower()]
    emails = sorted({e.lower().strip(".") for e in config.EMAIL_PATTERN.findall(text) + mailtos})
    return {
        "title": title,
        "site_name": (og.get("content") or "").strip() if og else "",
        "heading": " ".join(h1.get_text(" ").split())[:200] if h1 else "",
        "text": text[:300_000],
        "links": links[:600],
        "emails": emails[:50],
        "issn_hints": " ".join(h.replace("/", " ") for h in hints)[:5000],
    }


def fetch_site(url: str, deep: bool = True) -> dict:
    """Home page plus up to three same-site pages such as fees or call for papers."""
    if not url:
        return {"status": "error", "error": "no url"}
    if "://" not in url:
        url = "http://" + url
    res = fetch(url, as_json=False)
    out = {"status": "found" if res.get("ok") and res.get("text") else ("not_found" if res.get("status") in (404, 410) else "error"),
           "url": url, "final_url": res.get("final_url") or url, "http_status": res.get("status"),
           "tls_error": bool(res.get("tls_error")), "fetched_at": res.get("fetched_at"), "error": res.get("error")}
    if out["status"] != "found":
        return out
    page = _parse(res["text"], out["final_url"])
    out.update(page)
    out["https"] = out["final_url"].lower().startswith("https://")
    texts = [page["text"]]
    deep_pages = []
    if deep:
        site = registered_domain(out["final_url"])
        seen = {out["final_url"].rstrip("/")}
        for link in page["links"]:
            if len(deep_pages) >= MAX_DEEP_PAGES:
                break
            href = link["href"].split("#")[0].rstrip("/")
            if href in seen or registered_domain(href) != site or href.lower().endswith((".pdf", ".doc", ".docx", ".jpg", ".png")):
                continue
            if config.LINK_PATTERNS["deep"].search(link["text"] or ""):
                seen.add(href)
                sub = fetch(href, as_json=False)
                if sub.get("ok") and sub.get("text"):
                    p = _parse(sub["text"], href)
                    texts.append(p["text"])
                    out["emails"] = sorted(set(out["emails"]) | set(p["emails"]))
                    deep_pages.append(href)
    out["deep_pages"] = deep_pages
    out["all_text"] = " \n ".join(texts)[:600_000]
    out["issns_found"] = find_issns(page.get("issn_hints", "") + " " + out["all_text"])
    return out
