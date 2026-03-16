#!/usr/bin/env python3
"""analyzer.py — Analyzes raw_laws.json against profile.json using Perplexity sonar-pro."""
import os, json, time
from openai import OpenAI

DATA_DIR     = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_PATH  = os.path.join(DATA_DIR, "config.json")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")
RAW_PATH     = os.path.join(DATA_DIR, "raw_laws.json")
OUTPUT_PATH  = os.path.join(DATA_DIR, "analyzed_laws.json")

ANALYSIS_PROMPT = """
You are a Vietnamese legal analyst. Assess whether this law affects the user based on their profile.

## User Profile
{profile}

## Law / Regulation
{law}

Respond with ONLY a JSON object with exactly these fields:

{{
  "relevant":      true or false,
  "impact_level":  one of ["High", "Medium", "Low", "Not Applicable"],
  "affects":       list of strings describing what specifically affects them, [] if not relevant,
  "explanation":   2-3 sentence plain English explanation written to the user as "you",
                   "" if not relevant,
  "action_needed": true or false,
  "action_items":  list of concrete action strings if action_needed, [] otherwise,
  "confidence":    one of ["High", "Medium", "Low"],
  "citation_url":  object with "label" and "url" pointing to the official vbpl.vn or
                   thuvienphapluat.vn page for this specific document.
                   Use the url/url_vn from the law data if available.
                   Format: {{"label": "Decree 12/2026/NĐ-CP on vbpl.vn", "url": "https://vbpl.vn/..."}}
                   null if no URL is available.
}}

Return ONLY the raw JSON object. No prose, no markdown fences.
""".strip()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def analyze_law(client, model, law, profile):
    prompt = ANALYSIS_PROMPT.format(profile=json.dumps(profile, indent=2), law=json.dumps(law, indent=2))
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=1024,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw)

def main():
    config  = load_json(CONFIG_PATH)
    profile = load_json(PROFILE_PATH)
    laws    = load_json(RAW_PATH)
    if not laws:
        print("[analyzer] No new laws to analyze.")
        save_json(OUTPUT_PATH, [])
        return
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key: raise EnvironmentError("PERPLEXITY_API_KEY not set.")
    model  = config["llm"]["models"]["analyzer"]
    client = OpenAI(api_key=api_key, base_url=config["llm"]["base_url"])
    print(f"[analyzer] Analyzing {len(laws)} laws with {model}...")
    results = []
    for i, law in enumerate(laws):
        print(f"[analyzer] ({i+1}/{len(laws)}) {law.get('title','')[:60]}...")
        try:
            analysis = analyze_law(client, model, law, profile)
            results.append({**law, "analysis": analysis})
        except Exception as e:
            print(f"[analyzer] ⚠ Failed: {e}")
            results.append({**law, "analysis": {
                "relevant": False, "impact_level": "Not Applicable",
                "affects": [], "explanation": "", "action_needed": False,
                "action_items": [], "confidence": "Low", "citation_url": None, "_error": str(e)
            }})
        if i < len(laws) - 1: time.sleep(1.5)
    impact_order = {"High": 0, "Medium": 1, "Low": 2, "Not Applicable": 3}
    results.sort(key=lambda x: (
        0 if x["analysis"]["relevant"] else 1,
        impact_order.get(x["analysis"]["impact_level"], 99)
    ))
    save_json(OUTPUT_PATH, results)
    relevant = [r for r in results if r["analysis"]["relevant"]]
    actions  = [r for r in results if r["analysis"].get("action_needed")]
    print(f"[analyzer] {len(relevant)}/{len(results)} relevant. {len(actions)} need action.")

if __name__ == "__main__":
    main()
