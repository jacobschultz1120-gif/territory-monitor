"""
monitor.py — Territory News Monitor
────────────────────────────────────────────────────────────────────────────
Flow:
  1. Fetch PRNewswire, BusinessWire, GlobeNewswire RSS feeds
  2. Keyword filter: trigger + industry + geography (free, instant)
  3. AI score each match with Claude (1–10 + revenue estimate + reason)
  4. Route by score:
       8–10  →  #urgent      (act today)
       6–7   →  #watch-list  (review when convenient)
       <6    →  suppressed   (logged but no Discord alert)

Runs every 20 minutes via GitHub Actions.
"""

import os
import re
import sys
import json
import html
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import anthropic
import requests

from config import (
    TERRITORY_US_STATES, TERRITORY_US_ABBREVIATIONS,
    TERRITORY_US_CITIES, TERRITORY_CANADA,
    INDUSTRY_KEYWORDS, TRIGGER_KEYWORDS, TRIGGER_LABELS, TRIGGER_COLORS,
    ENTERPRISE_EXCLUSION_KEYWORDS, RSS_FEEDS,
    LOOKBACK_MINUTES, URGENT_THRESHOLD, WATCHLIST_MIN,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

ALL_GEO_TERMS = (
    TERRITORY_US_STATES + TERRITORY_US_ABBREVIATIONS +
    TERRITORY_US_CITIES + TERRITORY_CANADA
)


# ─────────────────────────────────────────────────────────────────────────────
# TEXT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def lower(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def word_match(term: str, text: str) -> bool:
    return bool(re.search(r"\b" + re.escape(term.lower()) + r"\b", lower(text)))


# ─────────────────────────────────────────────────────────────────────────────
# KEYWORD FILTERS
# ─────────────────────────────────────────────────────────────────────────────

def find_trigger(text: str) -> str | None:
    for trigger_type, keywords in TRIGGER_KEYWORDS.items():
        for kw in keywords:
            if word_match(kw, text):
                return trigger_type
    return None


def find_industry(text: str) -> str | None:
    for kw in INDUSTRY_KEYWORDS:
        if word_match(kw, text):
            return kw
    return None


def find_geo(text: str) -> str | None:
    for term in ALL_GEO_TERMS:
        if word_match(term, text):
            return term
    return None


def is_enterprise(text: str) -> bool:
    return any(kw.lower() in lower(text) for kw in ENTERPRISE_EXCLUSION_KEYWORDS)


def extract_company(title: str) -> str:
    for verb in [
        " Announces", " Reports", " Appoints", " Names", " Launches",
        " Opens", " Acquires", " Closes", " Completes", " Signs",
        " Wins", " Awarded", " Introduces", " Expands", " Enters",
        " Raises", " Secures", " Receives", " Partners",
    ]:
        if verb in title:
            return title.split(verb)[0].strip()
    words = title.split()
    return " ".join(words[:5]) + ("…" if len(words) > 5 else "")


# ─────────────────────────────────────────────────────────────────────────────
# RSS FETCHING
# ─────────────────────────────────────────────────────────────────────────────

def source_name(url: str) -> str:
    if "prnewswire" in url:    return "PRNewswire"
    if "businesswire" in url:  return "BusinessWire"
    if "globenewswire" in url: return "GlobeNewswire"
    return "PR Wire"


def parse_date(entry) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        import calendar
        return datetime.fromtimestamp(
            calendar.timegm(entry.published_parsed), tz=timezone.utc
        )
    if hasattr(entry, "published") and entry.published:
        try:
            return parsedate_to_datetime(entry.published)
        except Exception:
            pass
    return None


def fetch_feed(url: str, lookback: datetime) -> list[dict]:
    src = source_name(url)
    log.info(f"  Fetching {src}…")
    try:
        parsed = feedparser.parse(url)
    except Exception as e:
        log.warning(f"    Could not fetch {src}: {e}")
        return []

    candidates = []
    for entry in parsed.entries:
        pub = parse_date(entry)
        if pub is None or pub < lookback:
            continue

        title   = getattr(entry, "title", "")
        summary = strip_html(getattr(entry, "summary",
                             getattr(entry, "description", "")))
        link    = getattr(entry, "link", "")
        full    = title + " " + summary

        if is_enterprise(full):                     continue
        trigger  = find_trigger(full);              
        if not trigger:                             continue
        industry = find_industry(full);             
        if not industry:                            continue
        geo      = find_geo(full);                  
        if not geo:                                 continue

        candidates.append({
            "title":          title,
            "summary":        summary[:500],
            "url":            link,
            "company":        extract_company(title),
            "trigger_type":   trigger,
            "industry_match": industry,
            "geo_match":      geo,
            "source":         src,
            "pub_date":       pub.strftime("%b %d %Y  %H:%M UTC") if pub else "—",
        })
        log.info(f"    ✓ [{trigger}]  {title[:65]}")

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# AI SCORING  (Claude Haiku — fast and inexpensive)
# ─────────────────────────────────────────────────────────────────────────────

SCORE_PROMPT = """\
You are a sales intelligence analyst for a NetSuite ERP account executive.

The rep sells NetSuite to mid-market companies in these industries:
  • Food & Beverage (manufacturers, distributors, brands)
  • Consumer Goods / CPG
  • Manufacturing & Industrial
  • Building Materials (lumber, flooring, roofing, hardware, HVAC, etc.)
  • Retail / E-commerce / Wholesale Distribution

Territory covers: Alaska, Arizona, California, Colorado, Hawaii, Idaho, Kansas, \
Minnesota, Montana, Nebraska, Nevada, New Mexico, North Dakota, Oklahoma, Oregon, \
South Dakota, Utah, Washington, Wyoming — plus British Columbia, Saskatchewan, \
Northwest Territories, and Yukon in Canada.

Sweet spot: $5M–$100M annual revenue. Note if a company appears significantly \
larger or smaller.

Read the press release. Return ONLY a valid JSON object — no markdown, no \
backticks, no explanation outside the JSON.

{
  "score": <integer 1–10>,
  "reason": <one plain-English sentence explaining the NetSuite opportunity or lack of one>,
  "revenue_estimate": <best estimate of annual revenue, e.g. "$10M–$30M" — use any \
signals in the release: funding size, deal value, employee count, geographic scope, \
industry benchmarks. If genuinely unknown, write "Unknown">,
  "revenue_confidence": <"low", "medium", or "high">,
  "company_website": <company website URL if explicitly stated in the release, else null>
}

Score 9–10: Clear, immediate ERP trigger — post-acquisition consolidation, new CFO \
at a scaling company, first government contract requiring compliance and audit trail.
Score 7–8: Strong signal — major geo expansion, new revenue channel, substantial \
funding with operational growth mandate.
Score 5–6: Moderate — company is growing but ERP urgency is not evident.
Score 3–4: Weak — right industry, no clear ERP driver.
Score 1–2: Not relevant — wrong industry, too large, or pure vanity PR.

PRESS RELEASE:
"""


def score_with_ai(item: dict) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("    ANTHROPIC_API_KEY not set — skipping AI, defaulting score to 5")
        item.update({
            "ai_score": 5, "ai_reason": "AI scoring unavailable (API key not set)",
            "revenue_estimate": "Unknown", "revenue_confidence": "low",
            "company_website": None,
        })
        return item

    text = f"HEADLINE: {item['title']}\n\nSUMMARY: {item['summary']}"

    try:
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": SCORE_PROMPT + text}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",       "", raw)

        parsed = json.loads(raw)
        item.update({
            "ai_score":           int(parsed.get("score", 0)),
            "ai_reason":          str(parsed.get("reason", "—")),
            "revenue_estimate":   str(parsed.get("revenue_estimate", "Unknown")),
            "revenue_confidence": str(parsed.get("revenue_confidence", "low")),
            "company_website":    parsed.get("company_website"),
        })
        log.info(f"    Score {item['ai_score']}/10 — {item['ai_reason'][:80]}")

    except json.JSONDecodeError:
        log.warning(f"    AI returned invalid JSON — raw: {raw[:120]}")
        item.update({
            "ai_score": 5, "ai_reason": "AI scoring failed (JSON parse error)",
            "revenue_estimate": "Unknown", "revenue_confidence": "low",
            "company_website": None,
        })
    except Exception as e:
        log.warning(f"    AI scoring error: {e}")
        item.update({
            "ai_score": 5, "ai_reason": f"AI scoring error: {str(e)[:80]}",
            "revenue_estimate": "Unknown", "revenue_confidence": "low",
            "company_website": None,
        })

    return item


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD ALERTS
# ─────────────────────────────────────────────────────────────────────────────

def score_bar(score: int) -> str:
    return f"`{'█' * score}{'░' * (10 - score)}`"


def channel_label(score: int) -> str:
    return "🔴  URGENT" if score >= URGENT_THRESHOLD else "🔵  WATCH LIST"


def select_webhook(score: int) -> str:
    """Return the correct webhook URL based on alert priority."""
    if score >= URGENT_THRESHOLD:
        url = os.environ.get("DISCORD_URGENT_WEBHOOK_URL", "")
        if url:
            return url
        log.warning("    DISCORD_URGENT_WEBHOOK_URL not set — falling back to watch-list")
    return os.environ.get("DISCORD_WATCHLIST_WEBHOOK_URL", "")


def send_alert(item: dict) -> bool:
    score   = item.get("ai_score", 0)
    trigger = item.get("trigger_type", "other")
    webhook = select_webhook(score)

    if not webhook:
        log.error("    No Discord webhook URL configured — cannot send alert")
        return False

    color = TRIGGER_COLORS.get(trigger, 0x888780)

    revenue_str = item.get("revenue_estimate", "Unknown")
    confidence  = item.get("revenue_confidence", "low")
    if revenue_str != "Unknown":
        revenue_str = f"{revenue_str}  ({confidence} confidence)"

    fields = [
        {
            "name":   f"Score  {score}/10  •  {channel_label(score)}",
            "value":  score_bar(score),
            "inline": False,
        },
        {
            "name":   "Why this matters",
            "value":  item.get("ai_reason", "—"),
            "inline": False,
        },
        {
            "name":   "Estimated revenue",
            "value":  revenue_str,
            "inline": True,
        },
        {
            "name":   "Trigger",
            "value":  TRIGGER_LABELS.get(trigger, "Signal"),
            "inline": True,
        },
        {
            "name":   "Territory match",
            "value":  f"{item.get('geo_match', '—')}  •  {item.get('industry_match', '—').title()}",
            "inline": False,
        },
    ]

    website = item.get("company_website")
    if website:
        fields.append({"name": "Company website", "value": website, "inline": False})

    fields.append({
        "name":   "Before you reach out",
        "value":  "Confirm revenue in ZoomInfo — this is an AI estimate",
        "inline": False,
    })

    embed = {
        "title":       f"📰  {item.get('company', 'Unknown')}  —  {TRIGGER_LABELS.get(trigger, 'Signal')}",
        "url":         item.get("url", ""),
        "color":       color,
        "description": (item.get("summary", "")[:280] +
                        ("…" if len(item.get("summary", "")) > 280 else "")),
        "fields":      fields,
        "footer":      {
            "text": (
                f"{item.get('source', '—')}  •  "
                f"Published {item.get('pub_date', '—')}  •  "
                f"Territory Monitor"
            )
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        r = requests.post(
            webhook,
            json={"username": "Territory Monitor", "embeds": [embed]},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error(f"    Discord POST failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Require at least the watch-list webhook to be set
    if not os.environ.get("DISCORD_WATCHLIST_WEBHOOK_URL"):
        log.error("DISCORD_WATCHLIST_WEBHOOK_URL is not set. Add it as a GitHub Secret.")
        sys.exit(1)

    lookback = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    log.info(f"\nTerritory Monitor — News")
    log.info(f"Lookback: {LOOKBACK_MINUTES} min  (since {lookback.strftime('%H:%M UTC')})")
    log.info(f"Routing:  score {URGENT_THRESHOLD}–10 → #urgent  |  {WATCHLIST_MIN}–{URGENT_THRESHOLD-1} → #watch-list")
    log.info("─" * 60)

    # Step 1 — keyword filter
    candidates, seen_urls = [], set()
    for feed_url in RSS_FEEDS:
        for item in fetch_feed(feed_url, lookback):
            if item["url"] not in seen_urls:
                candidates.append(item)
                seen_urls.add(item["url"])

    log.info(f"\nKeyword filter: {len(candidates)} candidate(s)")

    if not candidates:
        log.info("No candidates — nothing to score.")
        return

    # Step 2 — AI score
    log.info("\nAI scoring…")
    scored = [score_with_ai(item) for item in candidates]

    # Step 3 — route and send
    urgent    = sorted([i for i in scored if i["ai_score"] >= URGENT_THRESHOLD],
                       key=lambda x: x["ai_score"], reverse=True)
    watchlist = sorted([i for i in scored if WATCHLIST_MIN <= i["ai_score"] < URGENT_THRESHOLD],
                       key=lambda x: x["ai_score"], reverse=True)
    suppressed = [i for i in scored if i["ai_score"] < WATCHLIST_MIN]

    log.info(f"\nResults: {len(urgent)} urgent  |  {len(watchlist)} watch-list  |  {len(suppressed)} suppressed")

    if suppressed:
        log.info("Suppressed:")
        for i in suppressed:
            log.info(f"  [{i['ai_score']}/10]  {i['company']}  —  {i['ai_reason'][:70]}")

    sent = 0
    for item in urgent + watchlist:
        ch = "#urgent" if item["ai_score"] >= URGENT_THRESHOLD else "#watch-list"
        log.info(f"\nSending [{item['ai_score']}/10] → {ch}:  {item['company']}")
        if send_alert(item):
            sent += 1

    log.info(f"\n{'─' * 60}")
    log.info(f"Done — {sent} alert(s) sent")


if __name__ == "__main__":
    main()
