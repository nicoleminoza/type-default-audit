"""Fetch the Google Fonts catalog from the Web Fonts Developer API.

Writes three files into data/:

  catalog_raw_alpha.json       untouched response body, sort=alpha
  catalog_raw_popularity.json  untouched response body, sort=popularity
  catalog_raw_vf.json          untouched response body, capability=VF
  catalog.json                 provenance wrapper plus items, enriched

The provenance block records when the fetch happened, what was called, how many
families came back and a SHA-256 of the exact bytes returned. The point is that
the family count quoted in any writeup can be traced to a specific response
rather than recalled from memory.

The catalog is fetched three times.

Twice for ordering, because the API exposes no popularity score, only an
ordering. Rank is therefore the only available form of that signal, and the
analysis needs it to ask whether models track catalog popularity.

Once more with capability=VF, purely to learn which families carry variable
axes. The default response omits the axes field entirely, so counting axes
without this request yields a silent zero rather than an answer. The VF
response is not used as the canonical source because it replaces the static
file list with variable files, and phase two needs the static TTFs.

Usage:  python src/fetch_catalog.py
"""

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from config import DATA_DIR, require

API = "https://www.googleapis.com/webfonts/v1/webfonts"
TIMEOUT_SECONDS = 60


def fetch(sort, api_key, capability=None):
    """Call the API once and return (raw_bytes, redacted_url).

    Failures exit loudly. A partial or substituted catalog would corrupt every
    downstream coverage number, so there is deliberately no fallback source.
    """
    suffix = f"&capability={capability}" if capability else ""
    url = f"{API}?key={api_key}&sort={sort}{suffix}"
    redacted = f"{API}?key=REDACTED&sort={sort}{suffix}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            return response.read(), redacted
    except urllib.error.HTTPError as err:
        raise SystemExit(f"{redacted} failed with HTTP {err.code}: {err.reason}")
    except urllib.error.URLError as err:
        raise SystemExit(f"{redacted} failed: {err.reason}")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def build_popularity_rank(popularity_items):
    """Map family name to 1-based rank in the popularity-sorted response."""
    return {item["family"]: i + 1 for i, item in enumerate(popularity_items)}


def summarize(items):
    """Counts the brief set in step 2 needs, computed rather than assumed.

    variable_font_families is only meaningful because axes were sourced from a
    capability=VF request. The default response has no axes field, so counting
    it there would report zero for every family regardless of the truth.
    """
    categories = {}
    subsets = {}
    variable = 0
    for item in items:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
        for subset in item.get("subsets", []):
            subsets[subset] = subsets.get(subset, 0) + 1
        if item.get("axes"):
            variable += 1
    return {
        "by_category": dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        "by_subset": dict(sorted(subsets.items(), key=lambda kv: -kv[1])),
        "variable_font_families": variable,
    }


def main():
    api_key = require("GOOGLE_FONTS_API_KEY")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fetched_at = datetime.now(timezone.utc)

    alpha_raw, alpha_url = fetch("alpha", api_key)
    popularity_raw, popularity_url = fetch("popularity", api_key)
    vf_raw, vf_url = fetch("alpha", api_key, capability="VF")

    (DATA_DIR / "catalog_raw_alpha.json").write_bytes(alpha_raw)
    (DATA_DIR / "catalog_raw_popularity.json").write_bytes(popularity_raw)
    (DATA_DIR / "catalog_raw_vf.json").write_bytes(vf_raw)

    alpha_items = json.loads(alpha_raw)["items"]
    popularity_items = json.loads(popularity_raw)["items"]
    vf_items = json.loads(vf_raw)["items"]

    # Do not assume the two responses agree. If they do not, say so rather than
    # quietly producing families with a missing rank.
    alpha_families = {item["family"] for item in alpha_items}
    popularity_families = {item["family"] for item in popularity_items}
    only_alpha = sorted(alpha_families - popularity_families)
    only_popularity = sorted(popularity_families - alpha_families)

    rank = build_popularity_rank(popularity_items)

    # Axes and variable files come from the VF response. The canonical "files"
    # map stays as the default response returned it, because that is where the
    # static TTFs phase two needs actually live.
    axes_by_family = {item["family"]: item.get("axes", []) for item in vf_items}
    vf_files_by_family = {item["family"]: item.get("files", {}) for item in vf_items}

    items = []
    for item in alpha_items:
        enriched = dict(item)
        enriched["popularity_rank"] = rank.get(item["family"])
        enriched["axes"] = axes_by_family.get(item["family"], [])
        enriched["vf_files"] = vf_files_by_family.get(item["family"], {})
        items.append(enriched)

    catalog = {
        "provenance": {
            "source": "Google Fonts Web Fonts Developer API",
            "endpoint_alpha": alpha_url,
            "endpoint_popularity": popularity_url,
            "endpoint_vf": vf_url,
            "fetched_at_utc": fetched_at.isoformat(),
            "fetched_on": fetched_at.date().isoformat(),
            "family_count": len(alpha_items),
            "family_count_popularity_response": len(popularity_items),
            "families_only_in_alpha": only_alpha,
            "families_only_in_popularity": only_popularity,
            "sha256_alpha_response": sha256(alpha_raw),
            "sha256_popularity_response": sha256(popularity_raw),
            "sha256_vf_response": sha256(vf_raw),
            "fetched_on_local": datetime.now().astimezone().date().isoformat(),
            "note": (
                "family_count is the exact number of items returned by the "
                "alpha-sorted response on fetched_on. It is the denominator for "
                "catalog coverage. Do not quote any other number."
            ),
        },
        "summary": summarize(items),
        "items": items,
    }

    out = DATA_DIR / "catalog.json"
    out.write_text(json.dumps(catalog, indent=2, ensure_ascii=False))

    print(f"Google Fonts families returned: {catalog['provenance']['family_count']}")
    print(f"Fetched on (UTC):               {catalog['provenance']['fetched_on']}")
    print(f"SHA-256 (alpha response):       {catalog['provenance']['sha256_alpha_response']}")
    if only_alpha or only_popularity:
        print(f"WARNING: responses disagree. alpha-only={only_alpha} popularity-only={only_popularity}")
    else:
        print("Both sort orders returned the same family set.")
    print(f"Written to:                     {out}")
    print()
    print("By category:")
    for name, count in catalog["summary"]["by_category"].items():
        print(f"  {name:<12} {count}")
    print(f"Variable-font families:         {catalog['summary']['variable_font_families']}"
          "  (axes sourced from capability=VF)")
    print()
    print("Subset coverage for the script dimension in step 2:")
    for subset in ("latin", "latin-ext", "cyrillic", "greek", "vietnamese",
                   "japanese", "korean", "chinese-simplified"):
        print(f"  {subset:<20} {catalog['summary']['by_subset'].get(subset, 0)}")


if __name__ == "__main__":
    main()
