"""
Rough area buckets for raw_postings.location — DISPLAY ONLY.

WHAT THIS IS NOT
This is not a gate, and nothing here may ever feed one. pipeline/prefilter.py
decides a posting's outcome; this module decides which heading a row is shown
under in the dashboard. A posting's first_pass_result, classification and every
qualified_opportunities field are identical whether or not this file exists.
Keeping the two apart is the point: the vocabulary below is tuned for "roughly
where is this", which is a far looser question than "is this candidate allowed
to work here", and it would be actively wrong as gate input.

WHY IT DOES NOT REUSE prefilter.ALLOWLIST_LOCATION_PHRASES
That list answers a different question. Its phrases ("must live in", "eligible
hiring locations", "residents of the following") detect that a RESTRICTION is
being expressed in description prose — they deliberately do not name a place,
which is exactly why prefilter can only route them to a human. The vocabulary
here has to name places and reads the structured `location` field, not prose.
Importing it would have coupled a display bucket to gate semantics while
supplying almost none of the terms actually needed. The matching STYLE is the
same though: lowercase the haystack once, then test a curated list of literal
phrases in priority order.

WHY CITIES AND NOT JUST COUNTRIES
Measured against the live corpus (13,882 non-duplicate postings, 2,333 distinct
non-empty location strings) before this list was written: bare city names with
no country attached are the single most common shape — "San Francisco" (1167),
"London" (283), "Berlin" (222), "Munich" (136), "Stockholm" (75), "Amsterdam"
(71), "Dublin" (52), "Paris" (51). A country-name-only vocabulary would have
dropped all of those into Other and made the bucket meaningless. The tail is
long (top 50 distinct values cover only 49.6% of rows), so cities carry real
weight rather than being a rounding error.

ORDER IS LOAD-BEARING
Rules are evaluated top to bottom and the FIRST match wins, so more specific
signals must precede broader ones:

  * Geography beats remoteness. "Remote US" / "United States (Remote)" /
    "Remote Canada" all carry a real country, so they bucket to that country;
    only a string with NO geographic signal at all ("Remote", "Anywhere in the
    World") becomes Remote/Unspecified. Checking remoteness first would have
    collapsed ~300 clearly-placed US rows into the unspecified bucket.
  * UK and Ireland are separated from the rest of Europe because the brief
    treats them separately, and Canada precedes the US because "Remote Canada"
    and "Toronto, Canada" would otherwise be at risk from US state matching.

SHORT TOKENS ARE WORD-BOUNDED, LONG ONES ARE NOT
"us", "uk", "ca", "ny" and the other two-letter codes are matched with a regex
word boundary; everything longer is a plain substring test. Without that,
"Belarus" and "Cyprus" would read as US, and "Fukuoka" as UK. Confirmed against
the corpus rather than assumed — those exact strings are present in it.

UNMATCHED TEXT IS NEVER GUESSED
A location string that matches nothing lands in Other, and a blank/NULL one in
Remote/Unspecified. Neither is inferred into a specific region: the whole value
of the Other bucket is as an honest measure of how much location text is not
cleanly parseable, so quietly forcing rows out of it would destroy the signal.
"""
import re

# Bucket display names. Exposed as constants so app.py never spells them as
# string literals — a typo there would silently create a phantom bucket that
# renders empty rather than failing.
US = "US"
CANADA = "Canada"
UK_IE = "UK & Ireland"
EUROPE = "Europe (non-UK)"
GCC = "GCC"
MIDEAST = "Middle East (non-GCC)"
APAC = "APAC"
LATAM = "LATAM"
REMOTE = "Remote/Unspecified"
OTHER = "Other"

# Display order for controls and charts: the regions this project's brief
# actually targets first (Ring 1 Europe/UK, Ring 2 GCC), then the rest, with the
# two catch-alls pinned last so they never sort into the middle of real regions.
BUCKET_ORDER = [UK_IE, EUROPE, GCC, MIDEAST, US, CANADA, APAC, LATAM, REMOTE, OTHER]

# Two-letter and other ambiguous tokens — matched with \b...\b. Kept separate
# from the substring lists purely because they need the stricter test.
_WORD_BOUNDED = {
    # DELIBERATELY EXCLUDED: "in" (Indiana), "or" (Oregon) and "co" (Colorado).
    # All three are ordinary English words, and a word boundary does not save
    # them — "Anywhere in the World" matched \bin\b and bucketed as US, which
    # silently inflated the US count by the 96 rows carrying that exact string
    # until a test caught it. Their states stay reachable through the full
    # names ("indiana"/"oregon"/"colorado") and city names ("indianapolis",
    # "portland", "denver") in the substring list below, so nothing is lost.
    US: [
        "us", "usa", "u.s.", "u.s.a.", "ny", "nyc", "ca", "sf", "tx", "wa",
        "ma", "il", "ga", "fl", "va", "nc", "pa", "az", "mn",
        "mi", "oh", "nj", "md", "dc", "ut", "tn", "mo", "wi",
    ],
    UK_IE: ["uk", "u.k."],
}

# Plain substring tests, evaluated in the order of BUCKET_RULES below.
_SUBSTRING = {
    GCC: [
        "united arab emirates", "uae", "dubai", "abu dhabi", "sharjah",
        "saudi arabia", "saudi", "riyadh", "jeddah", "dammam", "khobar",
        "qatar", "doha", "kuwait", "bahrain", "manama",
        "oman", "muscat",
    ],
    MIDEAST: [
        # Lebanon first: it is the candidate's own country, and burying Beirut
        # (55 postings) in Other would hide the most directly relevant rows on
        # the board.
        "lebanon", "beirut", "jordan", "amman", "israel", "tel aviv",
        "turkey", "türkiye", "istanbul", "ankara", "egypt", "cairo",
    ],
    UK_IE: [
        "united kingdom", "great britain", "england", "scotland", "wales",
        "northern ireland", "london", "manchester", "birmingham", "leeds",
        "glasgow", "edinburgh", "bristol", "cambridge", "oxford", "sheffield",
        "liverpool", "cardiff", "belfast", "brighton", "nottingham", "reading",
        "ireland", "dublin", "cork", "galway",
    ],
    CANADA: [
        "canada", "canadian", "toronto", "vancouver", "montreal", "montréal",
        "ottawa", "calgary", "edmonton", "winnipeg", "halifax", "waterloo",
        "mississauga", "quebec", "québec", "ontario", "british columbia",
        "alberta", "nova scotia",
    ],
    US: [
        "united states", "u.s. only", "san francisco", "new york", "boston",
        "seattle", "austin", "chicago", "los angeles", "denver", "atlanta",
        "washington", "d.c.", "san diego", "san jose", "palo alto",
        "mountain view", "menlo park", "sunnyvale", "santa clara", "oakland",
        "berkeley", "foster city", "redwood city", "cupertino", "bellevue",
        "portland", "philadelphia", "houston", "dallas", "phoenix", "miami",
        "orlando", "tampa", "charlotte", "raleigh", "durham", "nashville",
        "columbus", "detroit", "minneapolis", "salt lake city", "pittsburgh",
        "baltimore", "st. louis", "kansas city", "las vegas", "san antonio",
        # Full state names, listed out rather than sampled: "Sheridan,
        # Wyoming" (17 rows) was landing in Other purely because Wyoming was
        # missing, and a partial list makes that failure mode recur silently
        # for whichever state is omitted next. "georgia" is the one deliberate
        # omission — it is also a country, and "Tbilisi, Georgia" is in the
        # corpus, so it is matched only in its unambiguous "georgia, us" form.
        "california", "texas", "florida", "massachusetts", "illinois",
        "colorado", "virginia", "arizona", "georgia, us", "new jersey",
        "pennsylvania", "michigan", "maryland", "oregon", "utah",
        "wyoming", "montana", "idaho", "nevada", "new mexico", "oklahoma",
        "arkansas", "louisiana", "mississippi", "alabama", "south carolina",
        "north carolina", "kentucky", "iowa", "nebraska", "kansas",
        "west virginia", "delaware", "connecticut", "rhode island",
        "new hampshire", "vermont", "maine", "alaska", "hawaii",
        "north dakota", "south dakota", "wisconsin", "indiana", "ohio",
        "missouri", "minnesota", "tennessee", "washington state",
        "puerto rico",
    ],
    EUROPE: [
        "germany", "berlin", "munich", "münchen", "hamburg", "frankfurt",
        "cologne", "köln", "stuttgart", "düsseldorf", "dusseldorf", "leipzig",
        "hannover", "hanover", "heilbronn", "nuremberg", "nürnberg", "bremen",
        "dresden", "essen", "dortmund", "mannheim", "karlsruhe", "freiburg",
        "bonn", "münster", "muenster", "aachen", "augsburg", "bielefeld",
        "netherlands", "amsterdam", "rotterdam", "utrecht", "eindhoven",
        "the hague", "hague", "amersfoort", "groningen", "tilburg", "breda",
        "haarlem", "delft", "leiden", "nijmegen", "arnhem", "zwolle",
        "france", "paris", "lyon", "marseille", "toulouse", "bordeaux",
        "nantes", "lille",
        "spain", "madrid", "barcelona", "valencia", "seville", "malaga",
        "portugal", "lisbon", "lisboa", "porto",
        "italy", "milan", "milano", "rome", "roma", "turin", "bologna",
        "belgium", "brussels", "bruxelles", "antwerp", "ghent", "leuven",
        "switzerland", "zurich", "zürich", "geneva", "basel", "lausanne",
        "austria", "vienna", "wien", "graz",
        "sweden", "stockholm", "gothenburg", "göteborg", "goteborg", "malmö",
        "malmo", "uppsala",
        "denmark", "copenhagen", "københavn", "aarhus",
        "norway", "oslo", "bergen", "trondheim",
        "finland", "helsinki", "espoo", "tampere",
        "iceland", "reykjavik",
        "poland", "warsaw", "warszawa", "krakow", "kraków", "wroclaw",
        "wrocław", "gdansk", "poznan",
        "czech", "prague", "praha", "brno",
        "slovakia", "bratislava", "hungary", "budapest",
        "romania", "bucharest", "cluj", "bulgaria", "sofia",
        "greece", "athens", "thessaloniki",
        "ireland",  # also in UK_IE; harmless, UK_IE is evaluated first
        "estonia", "tallinn", "latvia", "riga", "lithuania", "vilnius",
        "slovenia", "ljubljana", "croatia", "zagreb", "serbia", "belgrade",
        "ukraine", "kyiv", "kiev", "lviv",
        "luxembourg", "malta", "cyprus", "nicosia",
        "europe", "european union",
    ],
    APAC: [
        "singapore", "japan", "tokyo", "osaka", "kyoto", "china", "beijing",
        "shanghai", "shenzhen", "guangzhou", "hong kong", "taiwan", "taipei",
        "korea", "seoul", "india", "bengaluru", "bangalore", "mumbai", "delhi",
        "gurgaon", "gurugram", "noida", "hyderabad", "chennai", "pune",
        "kolkata", "australia", "sydney", "melbourne", "brisbane", "perth",
        "canberra", "adelaide", "new zealand", "auckland", "wellington",
        "indonesia", "jakarta", "malaysia", "kuala lumpur", "philippines",
        "manila", "cebu", "thailand", "bangkok", "vietnam", "hanoi",
        "ho chi minh", "pakistan", "karachi", "lahore", "bangladesh", "dhaka",
        "sri lanka", "colombo", "apac",
        # Singapore's own board (connectors/mycareersfuture.py) reports planning
        # districts rather than the city name — "Islandwide", "D01 Marina,
        # Raffles Place...", "D12 Toa Payoh, Balestier, Serangoon". ~70 rows
        # were landing in Other for that reason alone, so the district
        # vocabulary is carried here rather than left as an unexplained gap.
        "islandwide", "raffles place", "pasir panjang", "toa payoh",
        "geylang", "clementi", "serangoon", "balestier", "eunos", "jurong",
        "tampines", "woodlands", "bedok", "yishun", "ang mo kio", "novena",
        "bukit", "queenstown, singapore", "marina bay", "orchard road",
        # Indian state names catch a long tail of smaller towns ("Vijayawada,
        # Andhra Pradesh") that no practical city list would reach.
        "andhra pradesh", "maharashtra", "karnataka", "tamil nadu", "gujarat",
        "rajasthan", "uttar pradesh", "kerala", "haryana", "west bengal",
        "telangana", "madhya pradesh", "uttarakhand", "odisha",
        # Central Asia is conventionally grouped under APAC by job boards; a
        # judgment call, flagged here because it is genuinely arguable.
        "kazakhstan", "astana", "almaty", "uzbekistan", "tashkent",
    ],
    LATAM: [
        "brazil", "brasil", "sao paulo", "são paulo", "rio de janeiro",
        "mexico", "méxico", "mexico city", "guadalajara", "monterrey",
        "argentina", "buenos aires", "chile", "santiago", "colombia",
        "bogota", "bogotá", "medellin", "medellín", "peru", "lima",
        "uruguay", "montevideo", "costa rica", "san jose, costa rica",
        "panama", "ecuador", "quito", "guatemala", "latam",
        "latin america", "south america",
    ],
}

# Only consulted when NOTHING above matched — see the module docstring on why
# geography has to win over remoteness.
_REMOTE_ONLY = [
    "remote", "anywhere", "worldwide", "world wide", "global", "distributed",
    "work from home", "wfh", "any location", "location independent",
    # Explicit "no location given" markers. These are unspecified by the
    # poster's own admission, which is exactly what this bucket means — quite
    # different from text we simply failed to recognise, which stays in Other.
    "n/a", "not specified", "unspecified", "various", "multiple locations",
]

# Evaluation order. GCC and the Middle East precede Europe so "Dubai" and
# "Istanbul" are not caught by a broader rule; UK & Ireland precedes Europe
# because "ireland" appears in both; Canada precedes the US so its cities are
# not exposed to US state-code matching.
BUCKET_RULES = [GCC, MIDEAST, UK_IE, CANADA, US, EUROPE, APAC, LATAM]

# Compiled once at import — bucket_for is called per row, and re-compiling a few
# dozen alternations on every call would show up on a 14k-row frame.
_BOUNDED_RE = {
    bucket: re.compile(r"\b(?:" + "|".join(re.escape(t) for t in tokens) + r")\b")
    for bucket, tokens in _WORD_BOUNDED.items()
}


def bucket_for(location):
    """
    Map one free-text location to a display bucket. Never raises, never returns
    None: an unusable value is Remote/Unspecified and an unrecognised one is
    Other, so every row lands somewhere and none are dropped from a grouped view.
    """
    if location is None:
        return REMOTE
    text_value = str(location).strip().lower()
    if not text_value:
        return REMOTE

    for bucket in BUCKET_RULES:
        for phrase in _SUBSTRING.get(bucket, []):
            if phrase in text_value:
                return bucket
        pattern = _BOUNDED_RE.get(bucket)
        if pattern is not None and pattern.search(text_value):
            return bucket

    if any(token in text_value for token in _REMOTE_ONLY):
        return REMOTE
    return OTHER


def add_area_column(df, source_column="location", target_column="area"):
    """
    Attach the bucket as a new column, leaving every existing column untouched.
    A frame with no location column gets the catch-all rather than a KeyError —
    the dashboard renders several different queries through this.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    if source_column not in out.columns:
        out[target_column] = REMOTE
        return out
    out[target_column] = out[source_column].apply(bucket_for)
    return out
