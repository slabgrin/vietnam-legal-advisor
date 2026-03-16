#!/usr/bin/env python3
"""
analyzer.py
Reads raw_laws.json, checks each law against profile.json using
Perplexity sonar-pro, and writes analyzed_laws.json with impact verdicts.
"""

import os
import json
import time
from openai import OpenAI

DATA_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_PATH   = os.path.join(DATA_DIR, "config.json")
PROFILE_PATH  = os.path.join(DATA_DIR, "profile.json")
RAW_PATH      = os.path.join(DATA_DIR, "raw_laws.json")
OUTPUT_PATH   = os.path.join(DATA_DIR, "analyzed_laws.json")

IMPACT_LEVELS = ["High", "Medium", "Low", "Not Applicable"]

ANALYSIS_PROMPT = """
You are a Vietnamese legal analyst. Your job is to assess whether a specific 
Vietnamese law or regulation affects a specific person, based on their profile.

## User Profile
{profile}

## Law / Regulation
{law}

Analyze whether this law affects this person. Respond with ONLY a JSON object 
with exactly these fields:

{{
  "relevant":      true or false,
  "impact_level":  one of ["High", "Medium", "Low", "Not Applicable"],
  "affects":       short list of strings describing what specifically affects them,
                   e.g. ["freelance income tax", "VAT registration threshold"]
                   Empty array [] if not relevant.
  "explanation":   2-3 sentence plain English explanation of how it affects them,
                   written directly to the user as "you". 
                   Empty string "" if not relevant.
  "action_needed": true or false — does the user need to DO something?
  "action_items":  list of concrete action strings if action_needed is true.
                   e.g. ["Register for VAT by April 30", "Update invoice templates"]
                   Empty array [] if no action needed.
  "confidence":    one of ["High", "Medium", "Low"] — how confident you are in 
                   this assessment given available information.
}}

Return ONLY the raw JSON object. No prose, no markdown fences.
""".strip()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def analyze_law(client: OpenAI, model: str, law: dict, profile: dict) -> dict:
    prompt = ANALYSIS_PROMPT.format(
        profile=json.dumps(profile, indent=2),
        law=json.dumps(law, indent=2),
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1024,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)

def main():
    config  = load_json(CONFIG_PATH)
    profile = load_json(PROFILE_PATH)
    laws    = load_json(RAW_PATH)

    if not laws:
        print("[analyzer] No new laws to analyze. Exiting.")
        save_json(OUTPUT_PATH, [])
        return

    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise EnvironmentError("PERPLEXITY_API_KEY not set.")

    model = config["llm"]["models"]["analyzer"]
    client = OpenAI(
        api_key=api_key,
        base_url=config["llm"]["base_url"],
    )

    print(f"[analyzer] Analyzing {len(laws)} laws with model: {model}")
    results = []

    for i, law in enumerate(laws):
        print(f"[analyzer] ({i+1}/{len(laws)}) {law.get('title', 'Untitled')[:60]}...")
        try:
            analysis = analyze_law(client, model, law, profile)
            results.append({**law, "analysis": analysis})
        except Exception as e:
            print(f"[analyzer] ⚠ Failed to analyze law '{law.get('id')}': {e}")
            results.append({
                **law,
                "analysis": {
                    "relevant": False,
                    "impact_level": "Not Applicable",
                    "affects": [],
                    "explanation": "",
                    "action_needed": False,
                    "action_items": [],
                    "confidence": "Low",
                    "_error": str(e),
                }
            })
        # Polite rate limiting — sonar-pro allows ~50 req/min
        if i < len(laws) - 1:
            time.sleep(1.5)

    # Sort: relevant + High impact first
    impact_order = {level: i for i, level in enumerate(IMPACT_LEVELS)}
    results.sort(key=lambda x: (
        0 if x["analysis"]["relevant"] else 1,
        impact_order.get(x["analysis"]["impact_level"], 99),
    ))

    save_json(OUTPUT_PATH, results)

    relevant = [r for r in results if r["analysis"]["relevant"]]
    actions  = [r for r in results if r["analysis"].get("action_needed")]
    print(f"[analyzer] Done. {len(relevant)}/{len(results)} laws relevant to your profile.")
    print(f"[analyzer] {len(actions)} law(s) require action from you.")
    print(f"[analyzer] Saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
