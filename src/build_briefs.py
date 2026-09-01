"""Assemble the brief set from the tag grid and the authored texts.

Writes briefs.json at the repo root. That file is tracked in git rather than
left in data/, because the briefs are a hand-authored input that cannot be
regenerated from a seed, and because any comparison between conditions has to
hold the brief set identical, which requires knowing exactly which set was used.

Validation here is deliberately suspicious. It checks that marginals are exact,
that no two briefs share text, and that a brief tagged as needing a non-Latin
script actually mentions that script in its wording. A tag the text does not
reflect is worse than no tag, because the slice would look populated while
measuring nothing.

briefs.json is the hand-editable artifact once written. This script refuses to
overwrite it unless --force is passed, because rebuilding after a hand edit
would silently discard that edit and no error would appear anywhere.

Usage:  python src/build_briefs.py [texts_dir] [--force]
"""

import glob
import json
import sys
from collections import Counter
from datetime import datetime, timezone

from config import DATA_DIR, PROJECT_ROOT

# Words that should appear in a brief tagged with each non-Latin script need.
# Latin-only briefs are unconstrained, so they are not checked.
SCRIPT_MARKERS = {
    "plus_cyrillic": ("russian", "ukrainian", "serbian", "bulgarian", "cyrillic"),
    "plus_greek": ("greek",),
    "plus_vietnamese": ("vietnamese",),
    "cjk_adjacent": ("japanese", "korean", "chinese", "kanji", "noto s", "mincho", "gothic"),
}

SPECIFICITY_ORDER = ["vague", "moderate", "highly_specific"]


def load_texts(texts_dir):
    texts = {}
    for path in sorted(glob.glob(f"{texts_dir}/batch*.json")):
        batch = json.load(open(path))
        overlap = set(batch) & set(texts)
        if overlap:
            raise SystemExit(f"{path} redefines briefs already authored: {sorted(overlap)}")
        texts.update(batch)
    return texts


def validate(briefs, dimensions):
    """Return a list of problems. An empty list means the set is usable."""
    problems = []

    if len(briefs) != 210:
        problems.append(f"expected 210 briefs, found {len(briefs)}")

    for name, values in dimensions.items():
        counts = Counter(b[name] for b in briefs)
        expected = len(briefs) // len(values)
        off = {v: counts.get(v, 0) for v in values if counts.get(v, 0) != expected}
        if off:
            problems.append(f"{name} marginals not flat, expected {expected} each, off: {off}")

    seen = {}
    for b in briefs:
        key = b["text"].strip().lower()
        if key in seen:
            problems.append(f"{b['id']} duplicates the text of {seen[key]}")
        seen[key] = b["id"]

    for b in briefs:
        markers = SCRIPT_MARKERS.get(b["script"])
        if markers and not any(m in b["text"].lower() for m in markers):
            problems.append(f"{b['id']} is tagged {b['script']} but the text never mentions it")
        if not b["text"].strip():
            problems.append(f"{b['id']} has empty text")

    return problems


def word_counts(briefs):
    """Mean words per specificity level, reported rather than asserted.

    Specificity is entangled with length by construction. Showing the numbers
    makes that confound visible instead of leaving it implied.
    """
    out = {}
    for level in SPECIFICITY_ORDER:
        lengths = [len(b["text"].split()) for b in briefs if b["specificity"] == level]
        out[level] = {
            "count": len(lengths),
            "mean_words": round(sum(lengths) / len(lengths), 1),
            "min_words": min(lengths),
            "max_words": max(lengths),
        }
    return out


def script_eligibility():
    """Eligible catalog families per script need, measured from the cached catalog."""
    catalog = json.load(open(DATA_DIR / "catalog.json"))
    items = catalog["items"]
    cjk = ("japanese", "korean", "chinese-simplified", "chinese-traditional", "chinese-hongkong")

    def count(extra=None, any_of=None):
        total = 0
        for item in items:
            subsets = item.get("subsets", [])
            if "latin" not in subsets:
                continue
            if extra and extra not in subsets:
                continue
            if any_of and not any(s in subsets for s in any_of):
                continue
            total += 1
        return total

    return {
        "latin_only": count(),
        "plus_cyrillic": count(extra="cyrillic"),
        "plus_greek": count(extra="greek"),
        "plus_vietnamese": count(extra="vietnamese"),
        "cjk_adjacent": count(any_of=cjk),
        "_catalog_family_count": catalog["provenance"]["family_count"],
        "_catalog_fetched_on": catalog["provenance"]["fetched_on"],
        "_note": ("Step 5 must use these as the denominator for script-sliced "
                  "coverage. Measuring a Greek-constrained slice against the full "
                  "catalog would report catalog scarcity as model concentration."),
    }


def main():
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    texts_dir = args[0] if args else str(PROJECT_ROOT / "src" / "brief_texts")

    out_path = PROJECT_ROOT / "briefs.json"
    if out_path.exists() and not force:
        raise SystemExit(
            f"{out_path} already exists and may contain hand edits. "
            "Pass --force to overwrite it.")

    grid = json.load(open(DATA_DIR / "brief_grid.json"))
    texts = load_texts(texts_dir)

    missing = sorted({r["id"] for r in grid["rows"]} - set(texts))
    if missing:
        raise SystemExit(f"No text authored for: {missing}")

    briefs = [{**row, "text": texts[row["id"]]} for row in grid["rows"]]
    problems = validate(briefs, grid["dimensions"])

    document = {
        "provenance": {
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "brief_count": len(briefs),
            "grid_seed": grid["seed"],
            "authored_by": "Claude (Opus 5), reviewed by Nicole Minoza",
            "confounds": [
                "Specificity is entangled with prompt length by construction. Any "
                "effect attributed to specificity is also an effect of token count.",
                "The briefs were written by Claude, which is one of the models under "
                "test. If this phrasing sits closer to one provider's training "
                "distribution than another's, that advantages a condition in a way "
                "balancing does not correct.",
                "Marginals are exact. Pairwise balance is approximate and was "
                "improved by hill climbing, not guaranteed.",
            ],
        },
        "dimensions": grid["dimensions"],
        "script_eligibility": script_eligibility(),
        "specificity_lengths": word_counts(briefs),
        "briefs": briefs,
    }

    out = out_path
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False))

    print(f"{len(briefs)} briefs written to {out}\n")
    if problems:
        print(f"VALIDATION FAILED, {len(problems)} problems:")
        for p in problems:
            print(f"  {p}")
    else:
        print("Validation passed: marginals exact, no duplicate texts, "
              "every non-Latin script tag reflected in its brief.")

    print("\nWords per brief by specificity, which is the length confound made visible:")
    for level, stats in document["specificity_lengths"].items():
        print(f"  {level:<16} n={stats['count']:<4} mean {stats['mean_words']:<6} "
              f"range {stats['min_words']} to {stats['max_words']}")

    print("\nEligible families per script need, the denominators step 5 must use:")
    for key in SCRIPT_MARKERS:
        print(f"  {key:<16} {document['script_eligibility'][key]}")
    print(f"  {'latin_only':<16} {document['script_eligibility']['latin_only']}")


if __name__ == "__main__":
    main()
