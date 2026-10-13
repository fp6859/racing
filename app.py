import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from collections import defaultdict
import re
import time

st.set_page_config(page_title="ATR Unique Steamers", layout="wide")
st.title("At The Races – Unique Steamers (≥ 33%)")
st.caption("Horses that have shortened by at least 33% and are the only such horse in their race")

THRESHOLD = 33.0

@st.cache_data(ttl=300)  # Cache for 5 minutes
def scrape_market_movers():
    """Scrape the market movers page using Playwright to bypass protections."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto("https://www.attheraces.com/market-movers", timeout=60000)
            # Wait for content to load (adjust if needed)
            page.wait_for_timeout(5000)
            # Optional: try to dismiss cookie banners
            try:
                page.click("button:has-text('Accept')", timeout=3000)
            except:
                pass
            html = page.content()
        except Exception as e:
            st.error(f"Failed to load page: {e}")
            html = ""
        finally:
            browser.close()
    
    return html


def parse_steamers(html: str):
    """Parse steamer rows from the HTML tables."""
    if not html:
        return []
    
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    
    # Look for tables that contain market mover data
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any(h in " ".join(headers) for h in ["horse", "mov", "price", "race"]):
            continue
            
        for tr in table.find_all("tr")[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 5:
                continue
            
            # Typical columns: Horse | Race | Last Price | 1st Show | Mov | ATR Index
            horse = cells[0]
            race = cells[1] if len(cells) > 1 else "Unknown"
            last_price = cells[2] if len(cells) > 2 else ""
            first_show = cells[3] if len(cells) > 3 else ""
            mov_text = cells[4] if len(cells) > 4 else "0%"
            atr = cells[5] if len(cells) > 5 else ""
            
            # Extract percentage
            mov_match = re.search(r"([\d.]+)\s*%", mov_text)
            mov = float(mov_match.group(1)) if mov_match else 0.0
            
            # Only keep positive movers (steamers / shorteners)
            if mov > 0:
                rows.append({
                    "Horse": horse,
                    "Race": race,
                    "Last Price": last_price,
                    "1st Show": first_show,
                    "Mov %": mov,
                    "ATR Index": atr,
                })
    
    return rows


def filter_unique_shorteners(rows, threshold=THRESHOLD):
    """Keep only horses ≥ threshold that are the sole such horse in their race."""
    by_race = defaultdict(list)
    for r in rows:
        if r["Mov %"] >= threshold:
            by_race[r["Race"]].append(r)
    
    unique = []
    for race, horses in by_race.items():
        if len(horses) == 1:
            unique.append(horses[0])
    
    # Sort by move percentage descending
    unique.sort(key=lambda x: x["Mov %"], reverse=True)
    return unique


# --- UI ---
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
    # Nice formatting
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
    
    # Download
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, "unique_steamers.csv", "text/csv")
else:
    st.warning("No unique steamers matching the criteria found right now.")

# Debug expander
with st.expander("Raw steamers parsed (for debugging)"):
    if raw_rows:
        st.dataframe(pd.DataFrame(raw_rows), use_container_width=True)
    else:
        st.write("No steamer rows parsed. The page structure may have changed.")
        st.write("Page length:", len(html))
