"""JournalCheck web interface.  Run:  streamlit run app.py"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from journalcheck import config, scoring
from journalcheck.collectors.lists import store
from journalcheck.pipeline import assess
from journalcheck.report import to_html, to_markdown

st.set_page_config(page_title="JournalCheck", page_icon="🔎", layout="wide")
COLOUR = {"Low risk": "green", "Caution": "orange", "High risk": "red"}


@st.cache_resource
def _model():
    return scoring.load_model()


st.title("JournalCheck")
st.caption("Explainable checks for predatory and hijacked journals. A triage aid: every verdict shows its evidence, and anything other than Low risk should be reviewed by a person.")

with st.sidebar:
    st.header("About the data")
    lists = store().available
    for name, ok in lists.items():
        st.write(("✅ " if ok else "⚪ ") + name.replace("_", " "))
    manifest = config.LISTS / "manifest.json"
    if manifest.exists():
        st.json(json.loads(manifest.read_text()), expanded=False)
    st.write("ML model: " + ("loaded" if _model() is not None else "not trained yet (rules only)"))
    deep = st.checkbox("Also read fees / call-for-papers pages", value=True)

c1, c2, c3 = st.columns(3)
issn = c1.text_input("ISSN", placeholder="2395-0056")
title = c2.text_input("Journal title", placeholder="optional")
url = c3.text_input("Website the journal uses", placeholder="https://… (the site you were sent to)")

if st.button("Check journal", type="primary", disabled=not (issn or title or url)):
    with st.spinner("Collecting evidence from OpenAlex, Crossref, DOAJ, RDAP and the website…"):
        a = assess(issn=issn or None, title=title or None, url=url or None, deep=deep, model=_model())
    d, r = a["decision"], a["rule"]
    st.subheader(f"{a['journal'].get('title') or 'Unknown journal'}")
    st.markdown(f"### :{COLOUR[d['verdict']]}[{d['verdict']}]")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trust score", f"{d['trust']:.0f} / 100")
    m2.metric("Rules", f"{r['trust']:.0f}")
    m3.metric("Model", f"{a['ml_trust']:.0f}" if a.get("ml_trust") is not None else "–")
    m4.metric("Evidence coverage", f"{r['coverage']:.0%}")
    for o in d["overrides"]:
        st.error(o)
    if d["needs_review"]:
        st.warning("Human review needed: " + "; ".join(d["review_reasons"]))
    st.write(f"ISSN {a.get('issn') or '–'} · {a['journal'].get('publisher') or ''} · {a['journal'].get('website') or ''} · {a.get('seconds')} s")

    tab1, tab2, tab3 = st.tabs(["Indicators", "Model factors", "Checks for a person"])
    with tab1:
        rows = [{"ID": k, "Indicator": v["name"], "Result": v["result"], "Points": f"{v['points']:g}/{v['max']}", "Evidence": v["evidence"]}
                for k, v in a["indicators"].items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        cats = pd.DataFrame([{"Category": f"{c}. {config.CATEGORY_NAMES[c]}", "Share": s["earned"] / s["max"]} for c, s in r["by_category"].items()])
        st.bar_chart(cats, x="Category", y="Share")
    with tab2:
        if a.get("ml_factors"):
            st.write("Positive values push the model towards high risk.")
            st.dataframe(pd.DataFrame(a["ml_factors"]), hide_index=True)
        else:
            st.write("No model loaded; the verdict uses the rules only.")
    with tab3:
        for k, v in config.MANUAL_CHECKS.items():
            st.checkbox(f"{k}: {v}", key=k)
        if a["flags"].get("cope_claim"):
            st.info("The website mentions COPE: confirm membership on publicationethics.org (M4).")
    st.download_button("Download report (HTML)", to_html(a), file_name=f"journalcheck_{a.get('issn') or 'report'}.html", mime="text/html")
    st.download_button("Download report (Markdown)", to_markdown(a), file_name=f"journalcheck_{a.get('issn') or 'report'}.md")
