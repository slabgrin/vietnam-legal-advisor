# 🇻🇳 Vietnam Legal Advisor

A static site that automatically monitors Vietnamese law changes and tells you — in plain language — whether they affect you.

## How It Works

1. GitHub Actions runs weekly on a cron schedule
2. The scraper fetches new laws from vbpl.vn's RSS feed
3. Each new law is analyzed by Perplexity's Sonar API against your `profile.json`
4. A static `index.html` is generated and deployed to GitHub Pages

## Setup

1. Clone this repo
2. Add your `PERPLEXITY_API_KEY` as a GitHub Actions secret
3. Edit `data/profile.json` to match your personal/professional situation
4. Push to `main` — GitHub Pages handles the rest

## Manual Run

```bash
pip install -r requirements.txt
export PERPLEXITY_API_KEY=your_key_here
python scripts/scraper.py
python scripts/analyzer.py
python scripts/generator.py
```

## Project Structure

```
├── .github/workflows/update.yml   # Scheduled pipeline
├── scripts/
│   ├── scraper.py                 # Fetches new laws from RSS
│   ├── analyzer.py                # LLM relevance analysis
│   └── generator.py               # Renders HTML output
├── templates/index.html.j2        # HTML template
├── data/
│   ├── profile.json               # YOUR profile — edit this
│   ├── config.json                # Model + source config
│   └── seen_laws.json             # Dedup cache (auto-managed)
└── output/index.html              # Generated site (auto-managed)
```
