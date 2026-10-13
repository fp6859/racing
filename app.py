import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from collections import defaultdict
import re
import requests

st.set_page_config(
    page_title="MILES Horse racing",
    page_icon="🏇",
    layout="wide"
)
st.title("MILES Best Daily Value Horses")

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


def looks_like_race(text: str) -> bool:
    """Return True if the text looks like a race identifier (course + time)."""
    if not text:
        return False
    text = text.strip()
    if re.search(r"\d{1,2}:\d{2}", text):
        return True
    if re.search(r"^[A-Za-z]{2,5}\s+\d", text):
        return True
    return False


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
            return data[0].get("content", "")
        return ""
    except Exception:
        return ""


def parse_steamers(html: str):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue

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
            race = cells[1] if len(cells) > 1 else ""
            
            if not looks_like_race(race):
                continue

            last_price = cells[mov_idx - 2] if mov_idx >= 2 else ""
            first_show = cells[mov_idx - 1] if mov_idx >= 1 else ""

            last_dec = odds_to_decimal(last_price)
            first_dec = odds_to_decimal(first_show)
            if last_dec >= first_dec:
                continue

            rows.append({
                "Horse": horse,
                "Race": race,
                "Last Price": last_price,
                "Mov %": mov,
            })

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

with st.spinner("Fetching latest data..."):
    html = scrape_with_spider()

if not html:
    st.error("Could not retrieve page content.")
    st.stop()

raw_rows = parse_steamers(html)
unique_steamers = filter_unique_shorteners(raw_rows)

if unique_steamers:
    df = pd.DataFrame(unique_steamers)[["Horse", "Race", "Last Price"]]
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Horse": st.column_config.TextColumn("Horse", width="large"),
            "Race": st.column_config.TextColumn("Race"),
            "Last Price": st.column_config.TextColumn("Last Price"),
        }
    )
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, "best_value_horses.csv", "text/csv")
else:
    st.warning("No matching horses found right now.")
