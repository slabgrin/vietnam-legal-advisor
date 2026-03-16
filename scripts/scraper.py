#!/usr/bin/env python3
"""
scraper.py — Fetches Vietnamese legal updates.
Primary:  Perplexity Sonar API (web-search enabled)
Fallback: Direct HTML scrape of vbpl.vn
"""
import os, json, hashlib, requests
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from openai import OpenAI

DATA_DIR        = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_PATH     = os.path.join(DATA_DIR, "config.json")
PROFILE_PATH    = os.path.join(DATA_DIR, "profile.json")
SEEN_PATH       = os.path.join(DATA_DIR, "seen_laws.json")
OUTPUT_PATH     = os.path.join(DATA_DIR, "raw_laws.json")
VBPL_SEARCH_URL = "https://vbpl.vn/TW/Pages/vbpq-timkiem.aspx?IsVietNamese=True&PageIndex=1&PageSize=20"

def load_json(path):
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def law_id(title, date):
    return hashlib.md5(f"{title.strip().lower()}{date}".encode()).hexdigest()

SONAR_PROMPT = """
You are a Vietnamese legal monitor with two tasks:

TASK 1 - NEW LAWS:
Find Vietnamese laws, decrees, and circulars PUBLISHED or effective in the
last {days} days that could affect someone with this profile:
{profile_summary}

TASK 2 - ALWAYS-APPLICABLE LAWS:
Regardless of when they were passed, list key EXISTING Vietnamese laws that
permanently govern someone with this profile. Include laws covering:
  - Foreigners living and working in Vietnam (immigration, work permits,
    expulsion procedures, TRC requirements)
  - Employees at Vietnamese companies (labor code, PIT, social insurance)
  - Crypto/digital asset holders
  - Motorbike/vehicle owners in Hanoi
  - People planning to permanently leave Vietnam
  - Vietnam-Singapore tax treaty obligations

Combine TASK 1 and TASK 2 into ONE JSON array. Mark each with:
  "is_new": true   (published in last {days} days)
  "is_new": false  (existing always-applicable law)

Each object must have EXACTLY these fields:
  - id          : unique slug
  - title       : English title
  - doc_number  : official number e.g. "Decree 59/2026/ND-CP"
  - type        : one of ["Law","Decree","Circular","Resolution","Decision","Other"]
  - published   : ISO date string or null
  - effective   : ISO date string or null
  - issuer      : issuing body
  - summary     : 2-3 sentence plain-English summary
  - is_new      : true or false
  - url         : vbpl.vn URL preferred, then thuvienphapluat.vn, else null
  - url_vn      : Vietnamese-language URL on vbpl.vn or thuvienphapluat.vn, else null

Return ONLY the raw JSON array. No prose, no markdown fences.
""".strip()

def build_profile_summary(profile):
    p  = profile.get("personal", {})
    e  = profile.get("employment", {})
    a  = profile.get("assets", {})
    le = profile.get("life_events", {})
    lines = [
        f"Nationality: {p.get('nationality','unknown')}",
        f"Location: {p.get('location','Vietnam')}",
        f"Is foreigner: {p.get('is_foreigner', False)}",
        f"Holds work permit: {p.get('holds_work_permit', False)}",
        f"Employment: {e.get('type','unknown')} at Vietnamese company: {e.get('employer_is_vietnamese_company',False)}",
        f"Industry: {e.get('industry','unknown')}",
        f"Owns vehicle: {a.get('owns_vehicle', False)} ({', '.join(a.get('vehicle_types', []))})",
        f"Holds crypto: {a.get('holds_crypto', False)}",
        f"Foreign bank account country: {a.get('foreign_bank_account_country','none')}",
        f"Planning to leave Vietnam permanently: {le.get('planning_to_leave_vietnam', False)}",
        f"Departure in: {le.get('departure_timeline','N/A')}",
        f"Destination: {le.get('destination_country','N/A')}",
    ]
    return "\n".join(lines)

def fetch_via_sonar(client, model, lookback_days, profile):
    profile_summary = build_profile_summary(profile)
    prompt = SONAR_PROMPT.format(days=lookback_days, profile_summary=profile_summary)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw)

def fetch_via_vbpl(lookback_days):
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
            if not title_el: continue
            title   = title_el.get_text(strip=True)
            href    = title_el.get("href", "")
            url     = f"https://vbpl.vn{href}" if href.startswith("/") else href
            pub_str = date_el.get_text(strip=True) if date_el else ""
            try:
                pub_date = dateparser.parse(pub_str, dayfirst=True)
                if pub_date and pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
            except Exception:
                pub_date = None
            if pub_date and pub_date < cutoff: continue
            results.append({
                "id": law_id(title, pub_str), "title": title, "doc_number": "",
                "type": "Other", "published": pub_date.date().isoformat() if pub_date else None,
                "effective": None, "issuer": "", "summary": "",
                "is_new": True, "url": url, "url_vn": url, "_source": "vbpl_scrape",
            })
        except Exception:
            continue
    return results

def deduplicate(laws, seen):
    new_laws = []
    for law in laws:
        lid = law.get("id") or law_id(law["title"], law.get("published", ""))
        law["id"] = lid
        if not law.get("is_new", True):
            new_laws.append(law)
        elif lid not in seen["seen_ids"]:
            new_laws.append(law)
            seen["seen_ids"].append(lid)
    seen["last_checked"] = datetime.now(timezone.utc).isoformat()
    return new_laws, seen

def main():
    config  = load_json(CONFIG_PATH)
    profile = load_json(PROFILE_PATH)
    seen    = load_json(SEEN_PATH)
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    lookback = config["scraper"]["lookback_days"]
    laws = []
    if api_key:
        print(f"[scraper] Querying Perplexity - last {lookback} days + always-applicable laws...")
        client = OpenAI(api_key=api_key, base_url=config["llm"]["base_url"])
        try:
            laws = fetch_via_sonar(client, config["llm"]["models"]["summarizer"], lookback, profile)
            for law in laws: law["_source"] = "sonar"
            new_c    = sum(1 for l in laws if l.get("is_new", True))
            always_c = sum(1 for l in laws if not l.get("is_new", True))
            print(f"[scraper] {new_c} new + {always_c} always-applicable laws.")
        except Exception as e:
            print(f"[scraper] Sonar failed ({e}), falling back to vbpl.vn scrape.")
    if not laws:
        print("[scraper] Scraping vbpl.vn directly...")
        laws = fetch_via_vbpl(lookback)
        print(f"[scraper] vbpl.vn returned {len(laws)} laws.")
    to_analyze, updated_seen = deduplicate(laws, seen)
    print(f"[scraper] {len(to_analyze)} laws queued for analysis.")
    save_json(OUTPUT_PATH, to_analyze)
    save_json(SEEN_PATH, updated_seen)

if __name__ == "__main__":
    main()
