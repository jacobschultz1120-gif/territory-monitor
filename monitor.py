"""
monitor.py — Territory News Monitor (Railway continuous-loop edition)
────────────────────────────────────────────────────────────────────────────
This script runs forever. It wakes up every 5 minutes, checks the RSS feeds,
scores any ICP matches with Claude, routes alerts to Discord, then sleeps.

Deduplication: a URL that has already been alerted on is remembered for 24
hours — so even with a small lookback overlap, each release fires exactly once.

Heartbeat: once per day at 8 AM Pacific, a check-in card is sent to
#watch-list confirming the monitor is running normally.

Start command:  python monitor.py
Railway will restart it automatically if it ever crashes.
"""

import os
import re
import sys
import json
import html
import time
import logging
from collections import OrderedDict
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
    POLL_INTERVAL_SECONDS, LOOKBACK_MINUTES,
    URGENT_THRESHOLD, WATCHLIST_MIN,
    HEARTBEAT_HOUR_UTC, HEARTBEAT_MINUTE_UTC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

ALL_GEO_TERMS = (
    TERRITORY_US_STATES + TERRITORY_US_ABBREVIATIONS +
    TERRITORY_US_CITIES + TERRITORY_CANADA
)

# ─────────────────────────────────────────────────────────────────────────────
# DEDUPLICATION
# URLs are stored with their first-seen timestamp.
# Entries older than 24 hours are pruned automatically.
# ─────────────────────────────────────────────────────────────────────────────

_seen: OrderedDict = OrderedDict()   # url → datetime first seen
_SEEN_TTL_HOURS = 24


def is_new(url: str) -> bool:
    """Return True if this URL has not been seen in the last 24 hours."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_SEEN_TTL_HOURS)

    # Prune expired entries
    stale = [u for u, t in _seen.items() if t < cutoff]
    for u in stale:
        del _seen[u]

    if url in _seen:
        return False

    _seen[url] = now
    return True


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


def parse_pub_date(entry) -> datetime | None:
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
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except requests.Timeout:
        log.warning(f"  {src} timed out after 20s — skipping this cycle")
        return []
    except requests.RequestException as e:
        log.warning(f"  Could not fetch {src}: {e}")
        return []
    except Exception as e:
        log.warning(f"  Unexpected error fetching {src}: {e}")
        return []

    candidates = []
    for entry in parsed.entries:
        pub = parse_pub_date(entry)
        if pub is None or pub < lookback:
            continue

        title   = getattr(entry, "title", "")
        summary = strip_html(getattr(entry, "summary",
                             getattr(entry, "description", "")))
        link    = getattr(entry, "link", "")
        full    = title + " " + summary

        # Deduplication — skip if already alerted
        if not is_new(link):
            continue

        # Keyword gates
        if is_enterprise(full):                  continue
        trigger  = find_trigger(full)
        if not trigger:                          continue
        industry = find_industry(full)
        if not industry:                         continue
        geo      = find_geo(full)
        if not geo:                              continue

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
        log.info(f"  Keyword match: [{trigger}]  {extract_company(title)}  ({geo})")

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# AI SCORING
# ─────────────────────────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a sales intelligence analyst for a NetSuite ERP account executive covering an open territory.

TERRITORY: AK, AZ, CA, CO, HI, ID, KS, MN, MT, NE, NV, NM, ND, OK, OR, SD, UT, WA, WY plus British Columbia, Saskatchewan, Northwest Territories, Yukon.
Show the signal if the company HQ is in territory — even if the event happened elsewhere.

REVENUE SWEET SPOT: $0–$20M annual revenue. Companies that appear significantly above $20M (large enterprise, publicly traded, Fortune 500) should score 1–2 regardless of trigger. ZoomInfo often undercodes revenue — lean inclusive on companies that could be larger than they appear.

AUTO-SUPPRESS (score 1–2 no matter what):
  • Publicly traded / NYSE / NASDAQ companies — too large, wrong buyer profile
  • Pre-seed or pre-revenue startups with no operating business yet
  • Companies clearly headquartered outside territory with no territory connection

SCORING FRAMEWORK — apply in order:

Step 1 — WHY NOW (the catalyst):
  The single most important dimension. A clear catalyst can reach 8–10 on its own.

  Strongest catalysts (can reach 9–10 alone):
    • New CFO, Controller, VP Finance, or Director of Finance hire
    • Acquisition or merger — two entities, two systems, one finance team
    • First significant government or enterprise contract win — compliance forced

  Strong catalysts (can reach 7–8 alone):
    • Funding round (Series A–C) — board demands auditability and scale
    • New geographic location, subsidiary, or entity formation
    • Strategic partnership or major distribution agreement

  Moderate catalysts (reach 5–7, need complexity to go higher):
    • Product launch or new channel (DTC, ecommerce, wholesale)
    • Expansion announcement without clear entity complexity

  Weak or no catalyst (score 3–5 max):
    • General growth announcement with no specific event
    • Award, recognition, or milestone with no operational change

Step 2 — OPERATIONAL COMPLEXITY (adds 1–2 points when present):
  Any of the following signals push the score up:
    • Multi-entity, multi-location, or multi-subsidiary structure
    • Multi-currency or cross-border operations
    • High transaction volume (distribution, fulfillment, manufacturing at scale)
    • Inventory management complexity (SKUs, warehousing, supply chain)
    • Revenue recognition complexity (subscriptions, contracts, milestones)
    • Rapid headcount or revenue growth indicating system strain

Step 3 — INDUSTRY FIT:
  Highest fit: Food & Beverage, Manufacturing, Building Materials, Consumer Goods / CPG, Wholesale Distribution, Retail / E-commerce
  Good fit: Software / SaaS, Healthcare services, Professional services, Nonprofits, Hospitality, Transportation / Logistics
  Lower fit: Pure financial services, Real estate investment, Media / Publishing, Government agencies

REVENUE ESTIMATION:
  Use every available clue — funding size, deal value, employee count, number of locations, industry benchmarks, customer names mentioned.
  Flag if a company appears to be miscoded (e.g. described as mid-market but mentions 500+ employees or national scale).

Return ONLY a valid JSON object — no markdown, no backticks, nothing outside the JSON.

{
  "score": <integer 1–10>,
  "reason": <one plain-English sentence — the most important factor driving this score>,
  "why_now": <the specific catalyst identified, e.g. "New CFO hire" or "Series B funding" or "None visible">,
  "complexity_signals": <list of operational complexity signals found, e.g. ["multi-location", "inventory management"] or []>,
  "revenue_estimate": <best estimate, e.g. "$5M–$20M" or "Unknown">,
  "revenue_confidence": <"low", "medium", or "high">,
  "publicly_traded": <true if company appears to be publicly traded, false otherwise>,
  "company_website": <company website URL if stated in release, otherwise infer from company name as www.companyname.com and append "(inferred)" — null only if name is too generic to guess>
}

PRESS RELEASE:
"""


def score_with_ai(item: dict) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        item.update({
            "ai_score": 5, "ai_reason": "AI scoring unavailable — API key not set",
            "why_now": "—", "complexity_signals": [], "publicly_traded": False,
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
            "why_now":            str(parsed.get("why_now", "—")),
            "complexity_signals": parsed.get("complexity_signals", []),
            "publicly_traded":    bool(parsed.get("publicly_traded", False)),
            "revenue_estimate":   str(parsed.get("revenue_estimate", "Unknown")),
            "revenue_confidence": str(parsed.get("revenue_confidence", "low")),
            "company_website":    parsed.get("company_website"),
        })
        log.info(f"  Score {item['ai_score']}/10 | Why now: {item['why_now']} | {item['ai_reason'][:60]}")

    except json.JSONDecodeError:
        log.warning(f"  AI returned invalid JSON — raw snippet: {raw[:100]}")
        item.update({
            "ai_score": 5, "ai_reason": "AI scoring failed (JSON error)",
            "revenue_estimate": "Unknown", "revenue_confidence": "low",
            "company_website": None,
        })
    except Exception as e:
        log.warning(f"  AI scoring error: {e}")
        item.update({
            "ai_score": 5, "ai_reason": f"AI error: {str(e)[:80]}",
            "why_now": "—", "complexity_signals": [], "publicly_traded": False,
            "revenue_estimate": "Unknown", "revenue_confidence": "low",
            "company_website": None,
        })

    return item


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD ALERTS
# ─────────────────────────────────────────────────────────────────────────────

def score_bar(score: int) -> str:
    return f"`{'█' * score}{'░' * (10 - score)}`"


def channel_tag(score: int) -> str:
    return "🔴  URGENT" if score >= URGENT_THRESHOLD else "🔵  WATCH LIST"


def get_webhook(score: int) -> str:
    if score >= URGENT_THRESHOLD:
        url = os.environ.get("DISCORD_URGENT_WEBHOOK_URL", "")
        if url:
            return url
        log.warning("  DISCORD_URGENT_WEBHOOK_URL not set — falling back to watch-list")
    return os.environ.get("DISCORD_WATCHLIST_WEBHOOK_URL", "")


def send_alert(item: dict) -> bool:
    score   = item.get("ai_score", 0)
    trigger = item.get("trigger_type", "other")
    webhook = get_webhook(score)

    if not webhook:
        log.error("  No Discord webhook configured")
        return False

    revenue_str = item.get("revenue_estimate", "Unknown")
    if revenue_str != "Unknown":
        revenue_str = f"{revenue_str}  ({item.get('revenue_confidence', 'low')} confidence)"

    color = TRIGGER_COLORS.get(trigger, 0x888780)

    # Build complexity signal string
    complexity = item.get("complexity_signals", [])
    complexity_str = "  •  ".join(complexity) if complexity else "None identified"
    traded_note = "  ⚠️  Publicly traded" if item.get("publicly_traded") else ""

    fields = [
        {
            "name":   f"Score  {score}/10  •  {channel_tag(score)}",
            "value":  score_bar(score),
            "inline": False,
        },
        {
            "name":   "Why this matters",
            "value":  item.get("ai_reason", "—"),
            "inline": False,
        },
        {
            "name":   "Why now",
            "value":  item.get("why_now", "—") + traded_note,
            "inline": True,
        },
        {
            "name":   "Trigger type",
            "value":  TRIGGER_LABELS.get(trigger, "Signal"),
            "inline": True,
        },
        {
            "name":   "Operational complexity",
            "value":  complexity_str,
            "inline": False,
        },
        {
            "name":   "Estimated revenue",
            "value":  revenue_str,
            "inline": True,
        },
        {
            "name":   "Territory match",
            "value":  f"{item.get('geo_match', '—')}  •  {item.get('industry_match', '—').title()}",
            "inline": True,
        },
    ]

    if item.get("company_website"):
        fields.append({
            "name":   "Company website",
            "value":  item["company_website"],
            "inline": False,
        })

    fields.append({
        "name":   "Before you reach out",
        "value":  "Confirm revenue in ZoomInfo — this is an AI estimate",
        "inline": False,
    })

    summary = item.get("summary", "")
    embed = {
        "title":       f"📰  {item.get('company', 'Unknown')}  —  {TRIGGER_LABELS.get(trigger, 'Signal')}",
        "url":         item.get("url", ""),
        "color":       color,
        "description": summary[:280] + ("…" if len(summary) > 280 else ""),
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
        log.error(f"  Discord POST failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DAILY HEARTBEAT
# ─────────────────────────────────────────────────────────────────────────────

_last_heartbeat: datetime | None = None


def maybe_send_heartbeat() -> None:
    """Send a daily check-in once per day in the configured UTC window."""
    global _last_heartbeat

    now = datetime.now(timezone.utc)

    # Only fire in the configured 6-minute window
    if not (now.hour == HEARTBEAT_HOUR_UTC and now.minute < HEARTBEAT_MINUTE_UTC + 6):
        return

    # Only fire once per day
    if _last_heartbeat and (now - _last_heartbeat).total_seconds() < 23 * 3600:
        return

    webhook = os.environ.get("DISCORD_WATCHLIST_WEBHOOK_URL", "")
    if not webhook:
        return

    embed = {
        "title":  "🟢  Territory Monitor — Daily Check-in",
        "color":  0x1D9E75,
        "description": (
            "Running normally on Railway — checking feeds every 5 minutes.\n"
            "No alerts today means no press releases matched your ICP. "
            "That's normal on quiet news days."
        ),
        "fields": [
            {
                "name":   "Status",
                "value":  "✅  Running continuously (5-minute polling)",
                "inline": False,
            },
            {
                "name":   "Check-in time",
                "value":  now.strftime("%A, %B %d %Y  •  %H:%M UTC"),
                "inline": False,
            },
            {
                "name":   "Score routing",
                "value":  (
                    f"**{URGENT_THRESHOLD}–10** → #urgent  (act today)\n"
                    f"**{WATCHLIST_MIN}–{URGENT_THRESHOLD - 1}** → #watch-list"
                ),
                "inline": False,
            },
            {
                "name":   "Feeds",
                "value":  "PRNewswire  •  BusinessWire  •  GlobeNewswire",
                "inline": False,
            },
            {
                "name":   "Territory",
                "value":  "20 US states  +  BC, SK, NT, YT",
                "inline": True,
            },
            {
                "name":   "Industries",
                "value":  "Food & Bev  •  Manufacturing  •  Building Materials  •  Consumer Goods  •  Retail",
                "inline": False,
            },
        ],
        "footer":    {"text": "Territory Monitor  •  Daily heartbeat"},
        "timestamp": now.isoformat(),
    }

    try:
        r = requests.post(
            webhook,
            json={"username": "Territory Monitor", "embeds": [embed]},
            timeout=10,
        )
        r.raise_for_status()
        _last_heartbeat = now
        log.info("Heartbeat sent to #watch-list")
    except requests.RequestException as e:
        log.warning(f"Heartbeat failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE POLL CYCLE
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle() -> dict:
    """Run one complete fetch → filter → score → alert cycle."""
    lookback  = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    log.info(f"Polling feeds (lookback {LOOKBACK_MINUTES} min)…")

    candidates = []
    for feed_url in RSS_FEEDS:
        candidates.extend(fetch_feed(feed_url, lookback))

    if not candidates:
        return {"candidates": 0, "alerted": 0}

    log.info(f"Keyword filter: {len(candidates)} new match(es) — scoring with AI…")

    scored = [score_with_ai(item) for item in candidates]

    urgent    = [i for i in scored if i["ai_score"] >= URGENT_THRESHOLD]
    watchlist = [i for i in scored if WATCHLIST_MIN <= i["ai_score"] < URGENT_THRESHOLD]
    suppressed = [i for i in scored if i["ai_score"] < WATCHLIST_MIN]

    if suppressed:
        for i in suppressed:
            log.info(f"  Suppressed [{i['ai_score']}/10]: {i['company']} — {i['ai_reason'][:60]}")

    sent = 0
    for item in sorted(urgent + watchlist, key=lambda x: x["ai_score"], reverse=True):
        ch = "#urgent" if item["ai_score"] >= URGENT_THRESHOLD else "#watch-list"
        log.info(f"Sending [{item['ai_score']}/10] → {ch}: {item['company']}")
        if send_alert(item):
            sent += 1

    return {"candidates": len(candidates), "alerted": sent}


# ─────────────────────────────────────────────────────────────────────────────
# STARTUP VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_env() -> bool:
    """Check required environment variables before starting the loop."""
    missing = []
    required = {
        "DISCORD_WATCHLIST_WEBHOOK_URL": "your #watch-list Discord webhook",
        "DISCORD_URGENT_WEBHOOK_URL":    "your #urgent Discord webhook",
        "ANTHROPIC_API_KEY":             "your Anthropic API key",
    }
    for var, description in required.items():
        if not os.environ.get(var):
            missing.append(f"  {var}  ({description})")

    if missing:
        log.error("Missing required environment variables:")
        for m in missing:
            log.error(m)
        log.error("Add these in your Railway project → Variables tab.")
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import signal
    def _shutdown(sig, frame):
        log.info("Shutdown signal received — exiting cleanly")
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("=" * 60)
    log.info("Territory Monitor starting up")
    log.info(f"Poll interval: every {POLL_INTERVAL_SECONDS // 60} minutes")
    log.info(f"Routing: score {URGENT_THRESHOLD}–10 → #urgent  |  {WATCHLIST_MIN}–{URGENT_THRESHOLD - 1} → #watch-list")
    log.info("=" * 60)

    if not validate_env():
        sys.exit(1)

    cycle = 0
    while True:
        cycle += 1
        log.info(f"─── Cycle {cycle} ───────────────────────────────────────")
        try:
            stats = run_cycle()
            log.info(f"Cycle {cycle} complete: {stats['candidates']} candidate(s), {stats['alerted']} alert(s) sent")
        except Exception as e:
            # Log but don't crash — Railway will keep running
            log.error(f"Unhandled error in cycle {cycle}: {e}", exc_info=True)

        try:
            maybe_send_heartbeat()
        except Exception as e:
            log.warning(f"Heartbeat error: {e}")

        log.info(f"Sleeping {POLL_INTERVAL_SECONDS // 60} minutes…\n")
        try:
            time.sleep(POLL_INTERVAL_SECONDS)
        except SystemExit:
            log.info("Exiting cleanly")
            return


if __name__ == "__main__":
    main()
