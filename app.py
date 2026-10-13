import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from collections import defaultdict
import re
import requests

st.set_page_config(page_title="ATR Unique Steamers", layout="wide")
st.title("At The Races – Unique Steamers (≥ 33%)")
st.caption("Horses that have shortened by at least 33% and are the only such horse in their race")

THRESHOLD = 33.0

def odds_to_decimal(odds_str: str) -> float:
    """Convert fractional odds (or Evens) to decimal. Returns large number if unparsable."""
    if not odds_str:
        return 999.0
    odds_str = odds_str.strip().lower()
    if odds_str in ("evens", "evs", "1/1"):
        return 2.0
    if "/" in odds_str:
        try:
            num, den = odds_str.split("/")
            return float(num) / float(den) + 1.0
        except Exception:
            return 999.0
    try:
        return float(odds_str) + 1.0
    except Exception:
        return 999.0


@st.cache_data(ttl=300)
def scrape_with_spider():
    """Use Spider.cloud free (keyless) scrape endpoint."""
    url = "https://api.spider.cloud/scrape"
    payload = {
        "url": "https://www.attheraces.com/market-movers",
        "return_format": "html",
        "request": "browser",
        "proxy_enabled": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            html = data[0].get("content", "")
            st.session_state["diag"] = f"Spider status: {data[0].get('status')} | Length: {len(html)}"
            return html
        else:
            st.session_state["diag"] = f"Unexpected response: {data}"
            return ""
    except Exception as e:
        st.session_state["diag"] = f"Spider error: {e}"
        return ""


def parse_steamers(html: str):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    all_tables = soup.find_all("table")
    
    # Skip the first table (top steamers summary) to avoid double-counting
    tables_to_parse = all_tables[1:] if len(all_tables) > 1 else all_tables
    
    rows = []
    for table in tables_to_parse:
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue

            # Find the percentage move
            mov = 0.0
            mov_idx = -1
            for i, cell in enumerate(cells):
                match = re.search(r"([\d.]+)\s*%", cell)
                if match:
                    mov = float(match.group(1))
                    mov_idx = i
                    break
            if mov <= 0 or mov_idx == -1:
                continue

            horse = cells[0]
            race = cells[1] if len(cells) > 1 else "Unknown"
            last_price = cells[mov_idx - 2] if mov_idx >= 2 else ""
            first_show = cells[mov_idx - 1] if mov_idx >= 1 else ""

            # Only keep if Last Price is shorter than 1st Show
            last_dec = odds_to_decimal(last_price)
            first_dec = odds_to_decimal(first_show)
            if last_dec >= first_dec:
                continue

            atr = cells[mov_idx + 1] if mov_idx + 1 < len(cells) else ""

            rows.append({
                "Horse": horse,
                "Race": race,
                "Last Price": last_price,
                "1st Show": first_show,
                "Mov %": mov,
                "ATR Index": atr,
            })

    # Deduplicate
    seen = set()
    unique_rows = []
    for r in rows:
        key = (r["Horse"], r["Race"])
        if key not in seen:
            seen.add(key)
            unique_rows.append(r)
    return unique_rows


def filter_unique_shorteners(rows, threshold=THRESHOLD):
    by_race = defaultdict(list)
    for r in rows:
        if r["Mov %"] >= threshold:
            by_race[r["Race"]].append(r)
    unique = []
    for race, horses in by_race.items():
        if len(horses) == 1:
            unique.append(horses[0])
    unique.sort(key=lambda x: x["Mov %"], reverse=True)
    return unique


# ---------- UI ----------
col1, col2 = st.columns([1, 4])
with col1:
    if st.button("Refresh data", type="primary"):
        st.cache_data.clear()
        st.rerun()
with col2:
    st.info("Data is cached for 5 minutes. Click Refresh to force a new scrape.")

with st.spinner("Fetching via Spider.cloud..."):
    html = scrape_with_spider()

if "diag" in st.session_state:
    st.caption(st.session_state["diag"])

if not html:
    st.error("Could not retrieve page content from Spider.")
    st.stop()

raw_rows = parse_steamers(html)
unique_steamers = filter_unique_shorteners(raw_rows)

st.subheader(f"Unique Steamers (≥ {THRESHOLD}%)")
st.metric("Horses found", len(unique_steamers))

if unique_steamers:
    df = pd.DataFrame(unique_steamers)
    df["Mov %"] = df["Mov %"].map(lambda x: f"{x:.1f}%")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Horse": st.column_config.TextColumn("Horse", width="large"),
            "Race": st.column_config.TextColumn("Race"),
            "Mov %": st.column_config.TextColumn("Shortened by"),
        }
    )
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, "unique_steamers.csv", "text/csv")
else:
    st.warning("No unique steamers matching the criteria found right now.")

with st.expander("Raw steamers parsed (for debugging)"):
    if raw_rows:
        st.dataframe(pd.DataFrame(raw_rows), use_container_width=True)
    else:
        st.write("No steamer rows parsed.")
        st.write("Page length:", len(html))
