"""Rules that turn raw postings into Data Nerd jobs: which titles count as data
engineering, which region a location is in, the seniority level, and which
skills a posting asks for. Kept separate from the fetchers so it's easy to test.
"""

from __future__ import annotations

import html
import re

# ---------------------------------------------------------------- titles

_INCLUDE = [
    r"\bdata\b.{0,30}\b(engineer|engineering|developer|architect)",
    r"\b(engineer|developer)\b.{0,25}\bdata\b",
    r"\banalytics engineer",
    r"\b(etl|elt)\b",
    r"\bbig data\b",
    r"\bdata ?ops\b",
    r"\bdata (platform|pipelines?|warehous\w*|infrastructure|integration|lake\w*)\b",
    r"\b(dbt|snowflake|databricks|spark|pyspark|kafka|airflow)\b.{0,20}\b(engineer|developer)",
]
_EXCLUDE = [
    r"data scien", r"machine learning engineer", r"\bml engineer", r"\bai engineer", r"analyst", r"data cent(er|re)",
    r"data entry", r"privacy", r"protection", r"security", r"governance officer", r"recruit",
    r"sales", r"account (executive|manager)", r"solutions? (engineer|architect)", r"support",
    r"marketing", r"customer success", r"technician", r"electrical", r"mechanical", r"hardware",
    r"data annotat", r"labell?ing", r"quality assurance", r"\bqa\b", r"test engineer", r"embedded",
    r"\bfirmware\b", r"\bios\b", r"android", r"front ?end", r"mobile", r"product manag", r"program manag",
    r"project manag", r"full[ -]?stack", r"mlops", r"technical solutions", r"deployment engineer",
    r"forward deployed", r"value engineer", r"learning (&|and) development", r"solutions? specialist",
    r"pre-?sales", r"robotics", r"field engineer",
]
_INCLUDE_RE = re.compile("|".join(_INCLUDE), re.I)
_EXCLUDE_RE = re.compile("|".join(_EXCLUDE), re.I)


def is_data_engineering(title: str) -> bool:
    return bool(_INCLUDE_RE.search(title)) and not _EXCLUDE_RE.search(title)


# ---------------------------------------------------------------- regions

REGIONS = ("na", "eu", "in")

_NA = [
    "united states", "usa", "u.s.", "us-", "america", "canada", "new york", "nyc", "san francisco",
    "bay area", "seattle", "austin", "boston", "chicago", "los angeles", "denver", "atlanta",
    "toronto", "vancouver", "montreal", "ottawa", "calgary", "waterloo", "washington", "dallas",
    "houston", "miami", "philadelphia", "pittsburgh", "portland", "salt lake", "phoenix",
    "san diego", "san jose", "palo alto", "mountain view", "menlo park", "sunnyvale", "raleigh",
    "charlotte", "minneapolis", "detroit", "nashville", "columbus", "st. louis", "kansas city",
    "jersey city", "brooklyn", "remote - us", "remote us", "north america",
    "california", "texas", "florida", "illinois", "massachusetts", "colorado", "georgia",
    "virginia", "ontario", "quebec", "british columbia", "alberta", "oregon", "arizona",
    "north carolina", "pennsylvania", "michigan", "ohio", "minnesota", "utah", "tennessee",
]
_NA_STATE = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
    r"NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|ON|QC|BC|AB)\b"
)
_EU = [
    "europe", "emea", "united kingdom", "uk", "england", "scotland", "wales", "london", "manchester",
    "edinburgh", "cambridge, uk", "bristol", "leeds", "ireland", "dublin", "cork", "germany",
    "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart",
    "düsseldorf", "netherlands", "amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague",
    "france", "paris", "lyon", "spain", "madrid", "barcelona", "valencia", "portugal", "lisbon",
    "porto", "italy", "milan", "rome", "poland", "warsaw", "krakow", "kraków", "wroclaw", "wrocław",
    "gdansk", "sweden", "stockholm", "gothenburg", "denmark", "copenhagen", "norway", "oslo",
    "finland", "helsinki", "switzerland", "zurich", "zürich", "geneva", "basel", "lausanne",
    "austria", "vienna", "belgium", "brussels", "antwerp", "czech", "prague", "brno", "romania",
    "bucharest", "cluj", "hungary", "budapest", "greece", "athens", "estonia", "tallinn",
    "lithuania", "vilnius", "latvia", "riga", "luxembourg", "serbia", "belgrade", "croatia",
    "zagreb", "bulgaria", "sofia", "slovakia", "bratislava", "slovenia", "ljubljana",
]
_IN = [
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "chennai", "mumbai", "gurgaon",
    "gurugram", "noida", "delhi", "kolkata", "ahmedabad", "kochi", "trivandrum", "thiruvananthapuram",
    "coimbatore", "jaipur", "indore", "chandigarh", "mohali", "vadodara", "nagpur", "bhubaneswar",
]
_NA_CODE = re.compile(r"\b(US|USA|U\.S\.|CAN)\b")

# Countries outside the three regions. A remote role limited to one of these
# isn't open to our users, so it doesn't count as "remote worldwide".
_OTHER = [
    "brazil", "são paulo", "sao paulo", "mexico", "argentina", "colombia", "chile", "peru",
    "latam", "latin america", "australia", "sydney", "melbourne", "new zealand", "singapore",
    "japan", "tokyo", "korea", "seoul", "china", "hong kong", "taiwan", "taipei", "philippines",
    "manila", "vietnam", "indonesia", "jakarta", "malaysia", "kuala lumpur", "thailand", "bangkok",
    "uae", "dubai", "abu dhabi", "saudi", "riyadh", "qatar", "israel", "tel aviv", "turkey",
    "istanbul", "egypt", "cairo", "nigeria", "lagos", "kenya", "nairobi", "south africa",
    "cape town", "johannesburg", "pakistan", "bangladesh", "sri lanka", "apac", "asia",
]

_REMOTE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed|worldwide|global)\b", re.I)


def _has_any(text: str, words: list[str]) -> bool:
    for w in words:
        if len(w) <= 3:
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text):
                return True
        elif w in text:
            return True
    return False


def classify_location(location: str, *, remote_hint: bool = False, country_codes: list[str] | None = None):
    """Return (regions, remote) for a free-text location."""
    text = (location or "").lower()
    regions: list[str] = []
    codes = {c.upper() for c in (country_codes or []) if c}
    if (_has_any(text, _NA) or _NA_STATE.search(location or "") or _NA_CODE.search(location or "")
            or codes & {"US", "USA", "CA", "CAN"}):
        regions.append("na")
    if _has_any(text, _EU) or codes & _EU_CODES:
        regions.append("eu")
    if _has_any(text, _IN) or codes & {"IN", "IND"}:
        regions.append("in")
    remote = remote_hint or bool(_REMOTE.search(text))
    return regions, remote


def names_other_country(location: str) -> bool:
    return _has_any((location or "").lower(), _OTHER)


_EU_CODES = {
    "GB", "UK", "IE", "DE", "NL", "FR", "ES", "PT", "IT", "PL", "SE", "DK", "NO", "FI", "CH", "AT",
    "BE", "CZ", "RO", "HU", "GR", "EE", "LT", "LV", "LU", "RS", "HR", "BG", "SK", "SI",
    "GBR", "IRL", "DEU", "NLD", "FRA", "ESP", "PRT", "ITA", "POL", "SWE", "DNK", "NOR", "FIN", "CHE",
    "AUT", "BEL", "CZE", "ROU", "HUN",
}

# ---------------------------------------------------------------- level

def level_of(title: str) -> str:
    t = title.lower()
    if re.search(r"\b(intern|internship|trainee|apprentice|working student|werkstudent|stage|stagiaire|"
                 r"alternance|alternant|praktikum|praktikant|stagiair)\b", t):
        return "intern"
    if re.search(r"\b(head|director|vp|vice president|manager)\b", t):
        return "manager"
    if re.search(r"\b(staff|principal|lead|architect|distinguished)\b", t):
        return "lead"
    if re.search(r"\b(senior|sr\.?|iii|iv)\b", t):
        return "senior"
    if re.search(r"\b(junior|jr\.?|entry|graduate|grad|associate|new grad|i)\b", t):
        return "junior"
    return "mid"


_YEARS_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)\s*\+?\s*(?:-|to|–)?\s*(?:\d{1,2}\s*)?\+?\s*years?", re.I)


def min_years(text: str) -> int | None:
    years = [int(m.group(1)) for m in _YEARS_RE.finditer(text or "")]
    years = [y for y in years if 0 < y <= 15]
    return min(years) if years else None


# ---------------------------------------------------------------- skills

# Skill id → regex. Ids that match an interview track id (sql, pyspark, dbt,
# modeling, git, python, snowflake, databricks, aws, azure, gcp, airflow,
# kafka) power "Prep for this job" in the app.
SKILLS: dict[str, str] = {
    "sql": r"\bsql\b|t-sql|pl/sql|postgres|mysql",
    "python": r"\bpython\b",
    "pyspark": r"\b(py)?spark\b",
    "scala": r"\bscala\b",
    "java": r"\bjava\b(?!script)",
    "dbt": r"\bdbt\b",
    "airflow": r"\bairflow\b|\bmwaa\b|cloud composer",
    "kafka": r"\bkafka\b|confluent",
    "flink": r"\bflink\b",
    "snowflake": r"\bsnowflake\b",
    "databricks": r"\bdatabricks\b|delta lake|unity catalog",
    "bigquery": r"\bbigquery\b|\bbig query\b",
    "redshift": r"\bredshift\b",
    "aws": r"\baws\b|amazon web services|\bs3\b|\bglue\b|\bemr\b|kinesis|athena|lambda",
    "azure": r"\bazure\b|data factory|\badf\b|synapse|fabric",
    "gcp": r"\bgcp\b|google cloud|bigquery|dataflow|dataproc|pub/sub",
    "iceberg": r"\biceberg\b|\bhudi\b",
    "terraform": r"\bterraform\b|infrastructure as code",
    "kubernetes": r"\bkubernetes\b|\bk8s\b|\bdocker\b",
    "git": r"\bgit\b|github|gitlab|ci/cd",
    "modeling": r"data model(l)?ing|dimensional model|star schema|kimball|data vault",
    "streaming": r"\bstreaming\b|real-time|real time",
}
_SKILL_RES = {k: re.compile(v, re.I) for k, v in SKILLS.items()}


def skills_in(text: str) -> list[str]:
    return [k for k, rx in _SKILL_RES.items() if rx.search(text or "")]


# ---------------------------------------------------------------- text

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def plain_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)  # Greenhouse double-escapes its HTML
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", html.unescape(text)).strip()


def summary(text: str, limit: int = 220) -> str:
    """A short teaser only; the full posting stays on the employer's site."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.-") + "…"
