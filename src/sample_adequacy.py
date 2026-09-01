"""Ask whether each slice has enough briefs to give a steady answer.

The question this answers is not "what is the number" but "would the number have
come out roughly the same with a different set of briefs of the same size". If a
slice's value swings wildly depending on which half of its briefs you look at,
that slice is undersampled and its result should not be quoted.

Method. For each slice, repeatedly split its briefs into two random halves and
compute the metrics on each half. Doing this many times with different splits
gives a spread rather than one arbitrary comparison. A slice whose halves agree
closely is adequately sampled at its current size. A slice whose halves disagree
needs more briefs before its number means anything.

This is deliberately cheap: it reuses data already collected and makes no API
calls, so the decision about whether to add briefs can be made from evidence
rather than from judgment.

Usage:  python src/sample_adequacy.py [--splits 200] [--dimension script]
"""

import argparse
import json
import random
import statistics
from collections import Counter

from config import DATA_DIR, PROJECT_ROOT
from metrics import DIMENSIONS, gini, hhi, top_share

SEED = 20260901


def load_rows():
    rows = []
    with open(DATA_DIR / "resolved.jsonl") as handle:
        for line in handle:
            row = json.loads(line)
            row["identity"] = (row["family"] if row["bucket"] == "google_fonts"
                               else row["original_string"])
            row.update(row["brief_tags"])
            rows.append(row)
    return rows


def metrics_for(rows):
    """The handful of figures most likely to be quoted."""
    if not rows:
        return None
    all_counts = Counter(r["identity"] for r in rows)
    gf_counts = Counter(r["family"] for r in rows if r["bucket"] == "google_fonts")
    out = sum(1 for r in rows if r["bucket"] == "known_non_google")
    return {
        "unique_families_gf": len(gf_counts),
        "top5_share_all": top_share(list(all_counts.values()), 5),
        "hhi_all": hhi(list(all_counts.values())),
        "gini_observed_gf": gini(list(gf_counts.values())),
        "out_of_catalog_share": round(out / len(rows), 4),
    }


def half_split_spread(rows, splits, rng):
    """Mean absolute gap between halves, per metric, over many random splits."""
    briefs = sorted({r["brief_id"] for r in rows})
    if len(briefs) < 4:
        return None, len(briefs)
    by_brief = {}
    for row in rows:
        by_brief.setdefault(row["brief_id"], []).append(row)

    gaps = {}
    for _ in range(splits):
        shuffled = briefs[:]
        rng.shuffle(shuffled)
        midpoint = len(shuffled) // 2
        left = [r for b in shuffled[:midpoint] for r in by_brief[b]]
        right = [r for b in shuffled[midpoint:] for r in by_brief[b]]
        a, b = metrics_for(left), metrics_for(right)
        if not a or not b:
            continue
        for key in a:
            if a[key] is None or b[key] is None:
                continue
            gaps.setdefault(key, []).append(abs(a[key] - b[key]))
    return ({k: (round(statistics.mean(v), 4), round(max(v), 4))
             for k, v in gaps.items()}, len(briefs))


def verdict(gap, whole, key):
    """Is the half-to-half gap small relative to the value being measured?

    The threshold is a rule of thumb, not a test. A gap under a tenth of the
    value means the two halves broadly agree. Over a quarter means the number
    is being driven by which briefs happened to be included.
    """
    if whole in (None, 0) or gap is None:
        return "?"
    ratio = gap / abs(whole)
    if key == "unique_families_gf":
        return "steady" if ratio < 0.15 else "wobbly" if ratio < 0.35 else "UNRELIABLE"
    return "steady" if ratio < 0.10 else "wobbly" if ratio < 0.25 else "UNRELIABLE"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", type=int, default=200)
    parser.add_argument("--dimension", default=None,
                        help="limit to one dimension, e.g. script")
    parser.add_argument("--model", default=None,
                        help="limit to one model. Use this when models have "
                             "unequal brief coverage, since mixing them makes "
                             "the spread reflect coverage rather than sampling.")
    args = parser.parse_args()

    rows = load_rows()
    if args.model:
        rows = [r for r in rows if r["model_key"] == args.model]
        print(f"restricted to model: {args.model}")
    rng = random.Random(SEED)
    briefs_in_run = len({r["brief_id"] for r in rows})
    available = len(json.load(open(PROJECT_ROOT / "briefs.json"))["briefs"])
    print(f"briefs in data: {briefs_in_run} of {available}")
    print(f"random half-splits per slice: {args.splits}\n")
    print("Each cell is the average gap between two random halves of the same")
    print("slice. Small means the slice would give the same answer with a")
    print("different set of briefs that size. Large means it would not.\n")

    dimensions = [args.dimension] if args.dimension else DIMENSIONS
    keys = ["unique_families_gf", "top5_share_all", "hhi_all",
            "gini_observed_gf", "out_of_catalog_share"]

    for dimension in dimensions:
        print(f"=== {dimension} ===")
        header = f"  {'slice':<20}{'briefs':>7}  "
        header += "".join(f"{k.replace('_all','').replace('_gf',''):>22}" for k in keys)
        print(header)
        for value in sorted({r[dimension] for r in rows}):
            subset = [r for r in rows if r[dimension] == value]
            spread, n_briefs = half_split_spread(subset, args.splits, rng)
            whole = metrics_for(subset)
            if spread is None:
                print(f"  {value:<20}{n_briefs:>7}   too few briefs to split")
                continue
            line = f"  {value:<20}{n_briefs:>7}  "
            for key in keys:
                mean_gap = spread.get(key, (None, None))[0]
                mark = verdict(mean_gap, whole.get(key), key)
                line += f"{str(mean_gap):>10} {mark:<11}"
            print(line)
        print()

    print("Reading this: 'steady' means the two halves agree closely enough that")
    print("more briefs would not change the answer. 'wobbly' means treat the")
    print("number as approximate. 'UNRELIABLE' means the slice is too small and")
    print("the figure should not be quoted without more briefs.")


if __name__ == "__main__":
    main()
