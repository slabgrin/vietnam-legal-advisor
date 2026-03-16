#!/usr/bin/env python3
"""
generator.py
Renders analyzed_laws.json + profile.json into output/index.html
using the Jinja2 template.
"""

import os
import json
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader

BASE_DIR      = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR      = os.path.join(BASE_DIR, "data")
TEMPLATE_DIR  = os.path.join(BASE_DIR, "templates")
OUTPUT_PATH   = os.path.join(BASE_DIR, "output", "index.html")

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    profile  = load_json(os.path.join(DATA_DIR, "profile.json"))
    laws     = load_json(os.path.join(DATA_DIR, "analyzed_laws.json"))

    counts = {"High": 0, "Medium": 0, "Low": 0, "Not Applicable": 0}
    for law in laws:
        level = law.get("analysis", {}).get("impact_level", "Not Applicable")
        counts[level] = counts.get(level, 0) + 1

    relevant_count = sum(1 for l in laws if l.get("analysis", {}).get("relevant"))

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("index.html.j2")

    html = template.render(
        profile        = profile,
        laws           = laws,
        counts         = counts,
        total_laws     = len(laws),
        relevant_count = relevant_count,
        generated_at   = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC"),
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[generator] ✅ index.html written → {OUTPUT_PATH}")
    print(f"[generator] {relevant_count} relevant / {len(laws)} total laws rendered.")

if __name__ == "__main__":
    main()
