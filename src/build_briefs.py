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
import re
import sys
from collections import Counter
from datetime import datetime, timezone

from config import DATA_DIR, PROJECT_ROOT

# Words that should appear in a brief tagged with each non-Latin script need.
# Latin-only briefs are unconstrained, so they are not checked.
# A brief tagged with a non-Latin script must state that the TEXT is in that
# language. Naming a nationality is not enough: "a Vietnamese chilli sauce"
# describes cuisine, and a model reading it will reasonably recommend Latin-only
# display faces. That exact case was caught in the pilot, where none of the seven
# fonts returned for b001 supported Vietnamese. A tag the text does not carry
# puts a dead brief in the slice, which is worse than no tag at all.
SCRIPT_LANGUAGES = {
    "plus_cyrillic": ["Russian", "Ukrainian", "Serbian", "Bulgarian"],
    "plus_greek": ["Greek"],
    "plus_vietnamese": ["Vietnamese"],
    "cjk_adjacent": ["Japanese", "Korean", "Chinese"],
}

# Script-specific terms that only appear when real script support is being asked
# for, independent of how the language is named.
SCRIPT_TERMS = {
    "plus_cyrillic": [r"Cyrillic"],
    "plus_greek": [r"polytonic", r"tonos"],
    "cjk_adjacent": [r"Noto", r"kanji", r"Mincho", r"Gothic face"],
}

# Phrasings that state the text is in the language, rather than merely naming a
# nationality. {l} is substituted with each candidate language name.
LANGUAGE_PHRASINGS = [
    r"in {l}\b", r"into {l}\b", r"{l} and English", r"English and {l}",
    r"{l} and Latin", r"Latin and {l}", r"{l}-language", r"{l}-speaking",
    r"{l} (text|titles?|titling|labels?|interface|headlines?|captions?|body|"
    r"descriptions?|strings?|diacritics|prose|quotations?|translation|"
    r"abstracts?|terminology)",
    r"render {l}", r"{l} (must|has to|needs|should|stacks|carries)",
    r"the {l}\b", r"set in {l}", r"published in {l}", r"written in {l}",
    r"labelled in {l}",
]


def states_script_requirement(text, script):
    """True when the brief actually asks for text in that script."""
    if script == "latin_only":
        return True
    for term in SCRIPT_TERMS.get(script, []):
        if re.search(term, text, re.I):
            return True
    for language in SCRIPT_LANGUAGES[script]:
        for phrasing in LANGUAGE_PHRASINGS:
            if re.search(phrasing.replace("{l}", language), text, re.I):
                return True
    return False


SPECIFICITY_ORDER = ["vague", "moderate", "highly_specific"]

# The brief set is balanced across script needs at 42 each, which gives every
# script slice equal precision. It is deliberately not representative of real
# design work, where Latin-only briefs dominate. Pooling all 210 briefs against
# the full catalog would therefore report catalog scarcity in Greek and Cyrillic
# as though it were model concentration.
#
# Step 5 corrects this by post-stratifying the pooled figure. The weights below
# are assumptions about the real-world mix, not measurements. Nobody here has
# data on the true distribution of design briefs, so step 5 must report the
# pooled figure under every scenario rather than picking one and calling it the
# answer. The placeholder values are marked to make that impossible to forget.
POOLING_SCENARIOS = {
    "as_sampled": {
        "status": "MEASURED, this is the actual composition of the brief set",
        "weights": {"latin_only": 0.20, "plus_cyrillic": 0.20, "plus_greek": 0.20,
                    "plus_vietnamese": 0.20, "cjk_adjacent": 0.20},
    },
    "latin_dominant": {
        "status": "PLACEHOLDER, UNVALIDATED ASSUMPTION, not measured from anything",
        "weights": {"latin_only": 0.70, "plus_cyrillic": 0.10, "plus_greek": 0.05,
                    "plus_vietnamese": 0.10, "cjk_adjacent": 0.05},
    },
    "latin_overwhelming": {
        "status": "PLACEHOLDER, UNVALIDATED ASSUMPTION, not measured from anything",
        "weights": {"latin_only": 0.90, "plus_cyrillic": 0.04, "plus_greek": 0.02,
                    "plus_vietnamese": 0.03, "cjk_adjacent": 0.01},
    },
}


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
        if not states_script_requirement(b["text"], b["script"]):
            problems.append(f"{b['id']} is tagged {b['script']} but never states that "
                            f"the text is in that language")
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
            "sampling_design": {
                "principle": (
                    "Balanced by construction, not representative. Every script "
                    "need carries 42 briefs so each slice has equal precision. "
                    "Real design work is overwhelmingly Latin only, so the pooled "
                    "figure must be post-stratified before it can be read as a "
                    "statement about typical practice."),
                "mean_eligible_families_per_brief": None,
                "decision": (
                    "Nicole chose on 2026-08-31 to keep the balanced design and "
                    "weight the pooled figure, rather than rebalancing the set "
                    "toward Latin or reporting Latin-only as the headline."),
            },
            "pooling_scenarios": POOLING_SCENARIOS,
            "confounds": [
                "Specificity is entangled with prompt length by construction. Any "
                "effect attributed to specificity is also an effect of token count.",
                "The briefs were written by Claude, which is one of the models under "
                "test. If this phrasing sits closer to one provider's training "
                "distribution than another's, that advantages a condition in a way "
                "balancing does not correct.",
                "Marginals are exact. Pairwise balance is approximate and was "
                "improved by hill climbing, not guaranteed.",
                "80 percent of briefs demand a non-Latin script, so the average "
                "brief can draw on 602 families rather than 1955. Any pooled "
                "figure computed against the full catalog without reweighting "
                "will overstate concentration.",
            ],
        },
        "dimensions": grid["dimensions"],
        "script_eligibility": script_eligibility(),
        "specificity_lengths": word_counts(briefs),
        "briefs": briefs,
    }

    document["provenance"]["sampling_design"]["mean_eligible_families_per_brief"] = round(
        sum(document["script_eligibility"][b["script"]] for b in briefs) / len(briefs), 1)

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

    mean_pool = document["provenance"]["sampling_design"]["mean_eligible_families_per_brief"]
    print(f"\nMean eligible pool per brief: {mean_pool} families, "
          f"{mean_pool / document['script_eligibility']['_catalog_family_count']:.0%} of the catalog.")
    print("Pooling scenarios recorded for step 5:")
    for name, scenario in POOLING_SCENARIOS.items():
        print(f"  {name:<20} {scenario['status']}")

    print("\nEligible families per script need, the denominators step 5 must use:")
    for key in SCRIPT_LANGUAGES:
        print(f"  {key:<16} {document['script_eligibility'][key]}")
    print(f"  {'latin_only':<16} {document['script_eligibility']['latin_only']}")


if __name__ == "__main__":
    main()
