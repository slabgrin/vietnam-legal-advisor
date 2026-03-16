#!/usr/bin/env python3
"""
scraper.py
Fetches the latest Vietnamese legal updates.

Strategy:
  Primary   — Perplexity Sonar API (web-search enabled) for recent law summaries
  Fallback  — Direct HTML scrape of vbpl.vn listing page
"""

import os
import json
import hashlib
import requests
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from openai import OpenAI

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
SEEN_PATH   = os.path.join(DATA_DIR, "seen_laws.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "raw_laws.json")

VBPL_SEARCH_URL = (
    "https://vbpl.vn/TW/Pages/vbpq-timkiem.aspx"
    "?IsVietNamese=True&PageIndex=1&PageSize=20"
)

# ─── helpers ──────────────────────────────────────────────────────────────────

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def law_id(title: str, date: str) -> str:
    """Stable dedup key from title + date."""
    return hashlib.md5(f"{title.strip().lower()}{date}".encode()).hexdigest()


# ─── Primary: Perplexity Sonar with web search ────────────────────────────────

SONAR_PROMPT = """
You are a Vietnamese legal monitor. Search for Vietnamese laws, decrees, and 
circulars that were PUBLISHED or came INTO EFFECT in the last {days} days.

Return a JSON array of objects. Each object must have EXACTLY these fields:
  - id          : a unique slug, e.g. "decree-12-2026-nd-cp"
  - title       : English title of the document
  - doc_number  : official document number, e.g. "Decree 12/2026/NĐ-CP"
  - type        : one of ["Law", "Decree", "Circular", "Resolution", "Decision", "Other"]
  - published   : ISO date string, e.g. "2026-03-01"
  - effective   : ISO date string or null
  - issuer      : issuing body, e.g. "Ministry of Finance"
  - summary     : 2–3 sentence plain-English summary of what the document does
  - url         : source URL if available, else null

Return ONLY the raw JSON array. No prose, no markdown fences.
""".strip()

def fetch_via_sonar(client: OpenAI, model: str, lookback_days: int) -> list[dict]:
    prompt = SONAR_PROMPT.format(days=lookback_days)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if model adds them anyway
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


# ─── Fallback: scrape vbpl.vn ─────────────────────────────────────────────────

def fetch_via_vbpl(lookback_days: int) -> list[dict]:
    """
    Scrapes the vbpl.vn search listing for documents published in the
    last `lookback_days` days. Returns a normalised list.
    """
    from bs4 import BeautifulSoup

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; VietnamLegalBot/1.0)"}

    resp = requests.get(VBPL_SEARCH_URL, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for item in soup.select("div.vbTitle, li.vbTitle, .title-vb"):
        try:
            title_el = item.select_one("a")
            date_el  = item.select_one(".ngayBanHanh, .date, .pubdate")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            href  = title_el.get("href", "")
            url   = f"https://vbpl.vn{href}" if href.startswith("/") else href
            pub_str = date_el.get_text(strip=True) if date_el else ""

            try:
                pub_date = dateparser.parse(pub_str, dayfirst=True)
                if pub_date and pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
            except Exception:
                pub_date = None

            if pub_date and pub_date < cutoff:
                continue

            results.append({
                "id":        law_id(title, pub_str),
                "title":     title,
                "doc_number": "",
                "type":      "Other",
                "published": pub_date.date().isoformat() if pub_date else None,
                "effective": None,
                "issuer":    "",
                "summary":   "",
                "url":       url,
                "_source":   "vbpl_scrape",
            })
        except Exception:
            continue

    return results


# ─── Deduplication ────────────────────────────────────────────────────────────

def deduplicate(laws: list[dict], seen: dict) -> tuple[list[dict], dict]:
    new_laws = []
    for law in laws:
        lid = law.get("id") or law_id(law["title"], law.get("published", ""))
        law["id"] = lid
        if lid not in seen["seen_ids"]:
            new_laws.append(law)
            seen["seen_ids"].append(lid)
    seen["last_checked"] = datetime.now(timezone.utc).isoformat()
    return new_laws, seen


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    config = load_json(CONFIG_PATH)
    seen   = load_json(SEEN_PATH)

    api_key      = os.environ.get("PERPLEXITY_API_KEY")
    lookback     = config["scraper"]["lookback_days"]
    sonar_model  = config["llm"]["models"]["summarizer"]

    laws = []

    if api_key:
        print(f"[scraper] Querying Perplexity ({sonar_model}) for last {lookback} days...")
        client = OpenAI(
            api_key=api_key,
            base_url=config["llm"]["base_url"]
        )
        try:
            laws = fetch_via_sonar(client, sonar_model, lookback)
            for law in laws:
                law["_source"] = "sonar"
            print(f"[scraper] Sonar returned {len(laws)} laws.")
        except Exception as e:
            print(f"[scraper] Sonar failed ({e}), falling back to vbpl.vn scrape.")
            laws = []

    if not laws:
        print("[scraper] Scraping vbpl.vn directly...")
        laws = fetch_via_vbpl(lookback)
        print(f"[scraper] vbpl.vn returned {len(laws)} laws.")

    new_laws, updated_seen = deduplicate(laws, seen)
    print(f"[scraper] {len(new_laws)} new (unseen) laws after dedup.")

    save_json(OUTPUT_PATH,  new_laws)
    save_json(SEEN_PATH, updated_seen)
    print(f"[scraper] Saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
