# =============================================================================
# YOUR TERRITORY CONFIGURATION
# This is the only file you need to edit.
# After changing anything here, Railway will automatically redeploy
# within a minute or two — no other steps needed.
# =============================================================================


# ---------------------------------------------------------------------------
# POLLING INTERVAL
# How many seconds to wait between feed checks.
# 300 = 5 minutes (recommended — matches RSS feed update cadence).
# Lower than 300 gives no meaningful speed benefit since the feeds
# themselves don't update faster than every 5 minutes.
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECONDS = 300


# ---------------------------------------------------------------------------
# DISCORD CHANNEL ROUTING
#
# Scores 8–10  → #urgent      (act today)
# Scores 6–7   → #watch-list  (review when convenient)
# Below 6      → suppressed
# ---------------------------------------------------------------------------

URGENT_THRESHOLD = 8
WATCHLIST_MIN    = 6


# ---------------------------------------------------------------------------
# GEOGRAPHY
# ---------------------------------------------------------------------------

TERRITORY_US_STATES = [
    "Alaska", "Arizona", "California", "Colorado", "Hawaii",
    "Idaho", "Kansas", "Minnesota", "Montana", "Nebraska",
    "Nevada", "New Mexico", "North Dakota", "Oklahoma", "Oregon",
    "South Dakota", "Utah", "Washington", "Wyoming",
]

TERRITORY_US_ABBREVIATIONS = [
    "AK", "AZ", "CA", "CO", "HI", "ID", "KS", "MN", "MT",
    "NE", "NV", "NM", "ND", "OK", "OR", "SD", "UT", "WA", "WY",
]

TERRITORY_US_CITIES = [
    # California
    "Los Angeles", "San Francisco", "San Diego", "Sacramento",
    "Fresno", "Oakland", "San Jose", "Long Beach", "Bakersfield",
    # Washington
    "Seattle", "Spokane", "Tacoma", "Bellevue", "Redmond", "Kirkland",
    # Arizona
    "Phoenix", "Tucson", "Scottsdale", "Mesa", "Tempe", "Chandler", "Gilbert",
    # Colorado
    "Denver", "Boulder", "Colorado Springs", "Fort Collins", "Aurora",
    # Oregon
    "Portland", "Eugene", "Salem", "Bend",
    # Nevada
    "Las Vegas", "Reno", "Henderson",
    # Utah
    "Salt Lake City", "Provo", "Ogden", "St. George",
    # New Mexico
    "Albuquerque", "Santa Fe", "Las Cruces",
    # Oklahoma
    "Oklahoma City", "Tulsa",
    # Minnesota
    "Minneapolis", "Saint Paul", "Bloomington", "Rochester",
    # Nebraska
    "Omaha", "Lincoln",
    # Idaho
    "Boise", "Meridian", "Nampa", "Idaho Falls",
    # Montana
    "Billings", "Missoula", "Great Falls", "Bozeman",
    # Alaska
    "Anchorage", "Fairbanks", "Juneau",
    # Hawaii
    "Honolulu", "Hilo", "Kailua",
    # Kansas
    "Wichita", "Overland Park", "Kansas City",
    # South Dakota
    "Sioux Falls", "Rapid City",
    # North Dakota
    "Bismarck", "Fargo", "Grand Forks",
    # Wyoming
    "Cheyenne", "Casper",
]

TERRITORY_CANADA = [
    "British Columbia", "Northwest Territories", "Saskatchewan", "Yukon",
    "BC", "NT", "SK", "YT",
    "Vancouver", "Victoria", "Kelowna", "Surrey", "Burnaby",
    "Richmond", "Abbotsford", "Kamloops", "Prince George",
    "Saskatoon", "Regina", "Prince Albert", "Moose Jaw",
    "Whitehorse", "Watson Lake",
    "Yellowknife", "Hay River",
]


# ---------------------------------------------------------------------------
# INDUSTRY KEYWORDS
# A release must mention at least ONE of these to pass the filter.
# ---------------------------------------------------------------------------

INDUSTRY_KEYWORDS = [
    # Food & Beverage
    "food", "beverage", "drink", "snack", "grocery", "bakery", "dairy",
    "meat", "poultry", "seafood", "frozen food", "packaged food",
    "food manufacturing", "food distribution", "food processing",
    "food and beverage", "food & beverage", "food service",
    "craft beer", "brewery", "winery", "spirits", "distillery",
    # Consumer Goods / CPG
    "consumer goods", "consumer products", "cpg", "fmcg",
    "personal care", "beauty", "cosmetics", "health and wellness",
    "supplement", "nutritional", "household goods", "cleaning products",
    "pet products", "pet food", "baby products",
    # Manufacturing & Industrial
    "manufacturing", "industrial", "fabrication", "production",
    "factory", "plant", "assembly", "contract manufacturing",
    "precision manufacturing", "metal fabrication", "plastics",
    "electronics manufacturing", "oem", "machine shop",
    "sheet metal", "casting", "forging",
    # Building Materials
    "building materials", "construction materials", "lumber",
    "flooring", "roofing", "siding", "windows", "doors",
    "hardware", "paint", "coatings", "fasteners", "plumbing",
    "hvac", "insulation", "drywall", "concrete", "masonry",
    "millwork", "cabinetry", "tile", "stone", "countertop",
    # Retail / E-commerce / Distribution / Wholesale
    "retail", "e-commerce", "ecommerce", "direct-to-consumer",
    "dtc", "omnichannel", "wholesale", "distribution", "distributor",
    "supply chain", "fulfillment", "warehousing", "specialty retail",
]


# ---------------------------------------------------------------------------
# BUYING TRIGGER KEYWORDS
# A release must mention at least ONE of these to pass the filter.
# ---------------------------------------------------------------------------

TRIGGER_KEYWORDS = {
    "acquisition": [
        "acquires", "acquired", "acquisition", "merger", "merges with",
        "merging with", "combined with", "takeover", "purchase of",
        "bought by", "buying", "transaction", "deal closed",
    ],
    "funding": [
        "funding", "investment", "raises", "raised", "series a", "series b",
        "series c", "series d", "venture capital", "private equity",
        "growth capital", "recapitalization", "ipo", "goes public",
        "growth investment", "strategic investment",
    ],
    "expansion": [
        "expands", "expansion", "new location", "new facility",
        "new warehouse", "new office", "new plant", "new distribution center",
        "opens in", "entering", "new market", "new region",
        "new headquarters", "relocates", "relocation", "new operations",
        "new manufacturing", "groundbreaking", "grand opening",
    ],
    "executive_change": [
        "appoints", "names new", "new cfo", "new controller",
        "chief financial officer", "new vp finance", "new director of finance",
        "new chief executive", "new ceo", "joins as", "promoted to",
        "named president", "leadership change", "new leadership",
    ],
    "contract": [
        "contract award", "awarded contract", "wins contract",
        "major contract", "government contract", "partnership agreement",
        "strategic partnership", "distribution agreement", "supply agreement",
        "multi-year agreement", "exclusive agreement", "preferred supplier",
    ],
    "product_launch": [
        "product launch", "new product line", "launches", "introduces",
        "unveils", "new brand", "new channel", "new platform",
        "ecommerce launch", "direct to consumer", "new offering",
        "entering market", "first-ever",
    ],
}

TRIGGER_LABELS = {
    "acquisition":      "Acquisition / Merger",
    "funding":          "Funding / Investment",
    "expansion":        "Expansion / New Location",
    "executive_change": "Executive Change",
    "contract":         "Contract / Partnership",
    "product_launch":   "Product / Channel Launch",
}

TRIGGER_COLORS = {
    "acquisition":      0xE24B4A,
    "funding":          0xEF9F27,
    "expansion":        0x1D9E75,
    "executive_change": 0x7F77DD,
    "contract":         0x378ADD,
    "product_launch":   0xD85A30,
}


# ---------------------------------------------------------------------------
# ENTERPRISE EXCLUSION
# ---------------------------------------------------------------------------

ENTERPRISE_EXCLUSION_KEYWORDS = [
    "fortune 500", "fortune 100", "fortune 50",
    "$1 billion", "$2 billion", "$5 billion", "$10 billion",
    "billion-dollar",
]


# ---------------------------------------------------------------------------
# RSS FEEDS
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    "https://www.prnewswire.com/rss/news-releases-list.rss",
    "https://www.globenewswire.com/RssFeed/country/United+States",
    "https://www.globenewswire.com/RssFeed/country/Canada",
    "https://www.accesswire.com/newsroom/rss",
    # BusinessWire removed — blocks automated requests from cloud IPs (403)
]


# ---------------------------------------------------------------------------
# LOOKBACK WINDOW
# How far back (in minutes) to check for new releases each cycle.
# At 5-minute polling we look back 8 minutes — a small overlap buffer
# to catch anything published right at the boundary of the last run.
# Deduplication in monitor.py prevents double-alerting on overlaps.
# ---------------------------------------------------------------------------

LOOKBACK_MINUTES = 8


# ---------------------------------------------------------------------------
# HEARTBEAT
# The daily check-in fires once per day in the 15:00–15:06 UTC window
# (8:00–8:06 AM Pacific). It goes to your #watch-list channel.
# ---------------------------------------------------------------------------

HEARTBEAT_HOUR_UTC   = 15   # 8 AM Pacific / 11 AM Eastern
HEARTBEAT_MINUTE_UTC = 0
