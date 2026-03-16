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
You are a Vietnamese legal analyst. Assess whether this law is relevant to the user
based on their profile.

## User Profile
{profile}

## Law / Regulation
{law}

A law is RELEVANT if ANY of the following are true:
  1. It directly regulates a category the user belongs to (foreigner, employee,
     vehicle owner, crypto holder, tech worker, person leaving Vietnam, etc.)
  2. It imposes obligations, deadlines, or procedures the user must follow
  3. It grants rights or benefits the user can claim
  4. It changes rules that currently govern the user's situation
  5. It is a law the user should simply be AWARE of given their profile,
     even if no immediate action is needed (e.g. a foreigner should know
     about expulsion procedures, even if they are law-abiding)

Do NOT mark as "Not Applicable" just because the user is not currently
violating the law or because the impact seems small. Err on the side of
marking relevant if there is any reasonable connection.

Respond with ONLY a JSON object with exactly these fields:

{{
  "relevant":      true or false,
  "impact_level":  one of ["High", "Medium", "Low", "Not Applicable"],
  "affects":       list of strings describing what specifically applies to them,
                   [] only if truly not applicable,
  "explanation":   2-3 sentence plain English explanation written to the user as "you".
                   For awareness-only laws, explain what the law covers and why
                   a person in your situation should know about it.
                   "" only if truly not applicable,
  "action_needed": true or false,
  "action_items":  list of concrete action strings if action_needed, [] otherwise,
  "confidence":    one of ["High", "Medium", "Low"],
  "citation_url":  object with "label" and "url" pointing to the official vbpl.vn or
                   thuvienphapluat.vn page for this specific document.
                   Use the url/url_vn from the law data if available.
                   Format: {{"label": "Decree 59/2026/ND-CP on vbpl.vn", "url": "https://vbpl.vn/..."}}
                   null if no URL is available.
}}

Return ONLY the raw JSON object. No prose, no markdown fences.
""".strip()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def analyze_law(client, model, law, profile):
    prompt = ANALYSIS_PROMPT.format(
        profile=json.dumps(profile, indent=2),
        law=json.dumps(law, indent=2)
    )
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
            print(f"[analyzer] Failed: {e}")
            results.append({**law, "analysis": {
                "relevant": False, "impact_level": "Not Applicable",
                "affects": [], "explanation": "", "action_needed": False,
                "action_items": [], "confidence": "Low",
                "citation_url": None, "_error": str(e)
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
