import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from collections import defaultdict
import re
import os
import subprocess
import sys

st.set_page_config(page_title="ATR Unique Steamers", layout="wide")
st.title("At The Races – Unique Steamers (≥ 33%)")
st.caption("Horses that have shortened by at least 33% and are the only such horse in their race")

THRESHOLD = 33.0

# ---------- Playwright browser install helper ----------
def ensure_playwright_browsers():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
            return True
    except Exception:
        try:
            st.info("Installing Chromium… this may take a minute on first run.")
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                timeout=300
            )
            st.success("Chromium installed. Reloading…")
            st.rerun()
        except Exception as e:
            st.error(f"Could not install Playwright browsers: {e}")
            st.stop()
    return False

ensure_playwright_browsers()
from playwright.sync_api import sync_playwright

# ---------- Scraping ----------
@st.cache_data(ttl=300)
def scrape_market_movers():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto("https://www.attheraces.com/market-movers", timeout=90000)
            page.wait_for_timeout(6000)
            try:
                page.click("button:has-text('Accept')", timeout=4000)
            except Exception:
                pass
            html = page.content()
        except Exception as e:
            st.error(f"Failed to load page: {e}")
            html = ""
        finally:
            browser.close()
    return html


def parse_steamers(html: str):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # Look for any table that might contain mover data
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue

            # Try to find a percentage in any cell
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

            # Heuristic: horse is usually first cell, race second or third
            horse = cells[0]
            race = cells[1] if len(cells) > 1 else "Unknown"
            last_price = cells[mov_idx - 2] if mov_idx >= 2 else ""
            first_show = cells[mov_idx - 1] if mov_idx >= 1 else ""
            atr = cells[mov_idx + 1] if mov_idx + 1 < len(cells) else ""

            rows.append({
                "Horse": horse,
                "Race": race,
                "Last Price": last_price,
                "1st Show": first_show,
                "Mov %": mov,
                "ATR Index": atr,
            })

    # Deduplicate roughly by horse+race
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

with st.spinner("Scraping At The Races Market Movers..."):
    html = scrape_market_movers()

if not html:
    st.error("Could not retrieve page content. The site may be blocking automated access.")
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
        st.write("No steamer rows parsed. The page structure may have changed.")
        st.write("Page length:", len(html))
