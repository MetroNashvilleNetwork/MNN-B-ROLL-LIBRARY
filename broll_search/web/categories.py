"""Subject/topic categories for the footage gallery.

Real stock-footage sites lead with subjects ("Nature", "Business", …). Our
files have no explicit category, but the descriptive filenames are keyword-rich,
so we define each category as a set of keywords and match clips whose indexed
``keywords`` contain any of them (an OR full-text query).

The list below was derived from the actual keyword distribution of the MNN
library (corporate/meetings, water-treatment, cherry blossoms, courthouse,
healthcare, commercial kitchen, aerial/drone, …). It's just data — add, rename,
or reorder freely; categories with zero matches are hidden automatically.
"""

from __future__ import annotations

import re

# key, label, and the keywords that define the subject. Order = display order.
CATEGORIES: list[dict] = [
    {"key": "corporate",  "label": "Corporate & Meetings",
     "keywords": ["corporate", "meeting", "office", "conference", "documents",
                  "paper", "boardroom", "presentation", "business"]},
    {"key": "water",      "label": "Water & Utilities",
     "keywords": ["water", "treatment", "plant", "solar", "utility", "pipe",
                  "tank", "infrastructure", "power"]},
    {"key": "courts",     "label": "Courts & Civic",
     "keywords": ["courthouse", "court", "judge", "lawyer", "courtroom", "legal",
                  "funeral", "government", "council", "civic"]},
    {"key": "healthcare", "label": "Healthcare",
     "keywords": ["doctor", "patient", "hospital", "medical", "clinic", "nurse",
                  "health", "care"]},
    {"key": "kitchen",    "label": "Commercial Kitchen",
     "keywords": ["kitchen", "commercial", "equipment", "oven", "bakery", "food",
                  "commissary", "cooking", "cooker", "mixer", "kettle", "appliance",
                  "blodgett", "vollrath", "cleveland", "groen", "hobart"]},
    {"key": "nature",     "label": "Nature & Seasons",
     "keywords": ["cherry", "blossom", "blossoms", "tree", "trees", "flower",
                  "flowers", "sky", "park", "garden", "nature", "river", "leaves",
                  "eagle", "bird", "flying", "shore", "cumberland"]},
    {"key": "weather",    "label": "Weather & Sky",
     "keywords": ["storm", "rain", "clouds", "cloud", "winter", "snow",
                  "timelapse", "weather", "fog", "lightning", "sunset", "sunrise"]},
    {"key": "aerial",     "label": "Aerial & Drone",
     "keywords": ["dji", "drone", "aerial", "skyline", "overhead", "birdseye"]},
    {"key": "education",  "label": "Education & Schools",
     "keywords": ["teacher", "student", "students", "classroom", "school",
                  "learning", "education", "lesson", "blackboard", "study"]},
    {"key": "people",     "label": "People",
     "keywords": ["woman", "man", "people", "person", "hands", "crowd", "worker",
                  "staff", "child", "children", "family", "senior", "daughter",
                  "mother", "smartphone"]},
    {"key": "finance",    "label": "Banking & Finance",
     "keywords": ["bank", "banker", "investment", "checklist", "finance",
                  "notepad", "employee", "money"]},
    {"key": "city",       "label": "City & Buildings",
     "keywords": ["building", "buildings", "downtown", "street", "storefront",
                  "sign", "city", "skyline", "exterior", "ave", "avenue",
                  "commerce", "alley", "intersection", "traffic", "bridge",
                  "capital", "capitol", "square", "lamp", "march"]},
    {"key": "architecture", "label": "Architecture & Interiors",
     "keywords": ["ceiling", "window", "windows", "arcade", "walkthrough", "fan",
                  "fans", "mural", "interior", "wall", "pillar", "glass",
                  "hallway", "columns", "stairs", "studio", "gear"]},
]

# Pseudo-category key for clips that match no real category (catch-all row).
UNCATEGORIZED_KEY = "_more"
UNCATEGORIZED_LABEL = "More B-Roll"

_BY_KEY = {c["key"]: c for c in CATEGORIES}


def get_category(key: str) -> dict | None:
    return _BY_KEY.get(key)


def _safe_terms(keywords: list[str]) -> list[str]:
    out = []
    for kw in keywords:
        safe = "".join(ch for ch in kw if ch.isalnum())
        if safe:
            out.append(safe)
    return out


def category_fts(key: str) -> str:
    """OR full-text expression for a category, e.g. 'kitchen* OR oven* OR ...'."""
    cat = _BY_KEY.get(key)
    if not cat:
        return ""
    terms = _safe_terms(cat["keywords"])
    return " OR ".join(f"{t}*" for t in terms)


def all_categories_fts() -> str:
    """OR expression spanning EVERY category's keywords — used to find the clips
    that belong to no category (the 'More B-Roll' catch-all)."""
    terms: list[str] = []
    for c in CATEGORIES:
        terms.extend(_safe_terms(c["keywords"]))
    # De-dup while preserving order.
    seen: set[str] = set()
    uniq = [t for t in terms if not (t in seen or seen.add(t))]
    return " OR ".join(f"{t}*" for t in uniq)


def combine_fts(user_query: str, category_key: str = "") -> str:
    """Build a combined FTS5 MATCH expression from an optional free-text query
    (AND of its words) and an optional category (OR of its keywords)."""
    parts: list[str] = []
    q = (user_query or "").strip()
    if q:
        words = []
        for tok in re.split(r"\s+", q.replace('"', " ").replace("-", " ")):
            safe = "".join(ch for ch in tok if ch.isalnum())
            if safe:
                words.append(f"{safe}*")
        if words:
            parts.append("(" + " AND ".join(words) + ")")
    cat_expr = category_fts(category_key) if category_key else ""
    if cat_expr:
        parts.append("(" + cat_expr + ")")
    return " AND ".join(parts)
