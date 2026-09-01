"""Assign dimension tags to 210 briefs with exactly balanced marginals.

The construction is deliberately dull. Each dimension is expanded into a list
of exactly 210 tags, balanced by repetition, then shuffled independently with a
fixed seed and zipped together. Balanced marginals are therefore guaranteed by
construction rather than hoped for, and the fixed seed makes the assignment
reproducible.

Balanced marginals are the property step 5 needs, because it slices by one
dimension at a time. Balance on every pair of dimensions simultaneously is not
achievable at this size, so a short hill-climbing pass evens the pairs out as
far as it can and the script then reports the counts it actually achieved
instead of claiming a balance it does not have. The pass only ever swaps two
values inside one column, which cannot change a marginal.

Usage:  python src/build_brief_grid.py
"""

import json
import random
from collections import Counter

from config import DATA_DIR, PROJECT_ROOT

TOTAL = 210
SEED = 20260831

DIMENSIONS = {
    "domain": ["fintech", "healthcare", "editorial", "gaming", "luxury_retail",
               "public_sector", "nonprofit", "developer_tools", "food", "education"],
    "tone": ["authoritative", "playful", "warm", "technical", "elegant", "brutal"],
    "medium": ["website", "mobile_ui", "print_editorial", "packaging",
               "presentation", "long_form_reading"],
    "script": ["latin_only", "plus_cyrillic", "plus_greek", "plus_vietnamese",
               "cjk_adjacent"],
    "specificity": ["vague", "moderate", "highly_specific"],
}

# Eligible family counts measured from the catalog, not recalled. These are the
# denominators step 5 must use for script-sliced coverage, because a brief that
# demands Greek cannot draw on families that have no Greek.
SCRIPT_ELIGIBILITY = {
    "latin_only": ["latin"],
    "plus_cyrillic": ["latin", "cyrillic"],
    "plus_greek": ["latin", "greek"],
    "plus_vietnamese": ["latin", "vietnamese"],
    "cjk_adjacent": ["latin", "__cjk_any__"],
}


def balanced_column(values, total):
    """Repeat values so each appears equally often, exactly total items long."""
    if total % len(values) != 0:
        raise ValueError(f"{total} does not divide evenly by {len(values)} values")
    return values * (total // len(values))


def build_assignment(total=TOTAL, seed=SEED):
    rng = random.Random(seed)
    columns = {}
    for name, values in DIMENSIONS.items():
        column = balanced_column(values, total)
        rng.shuffle(column)
        columns[name] = column
    return [
        {"id": f"b{i + 1:03d}", **{name: columns[name][i] for name in DIMENSIONS}}
        for i in range(total)
    ]


def pairwise_cost(rows):
    """Sum of squared deviation from an even spread, across every pair.

    Lower is flatter. The value is not meaningful on its own, only in
    comparison with itself before and after the balancing pass.
    """
    names = list(DIMENSIONS)
    cost = 0
    for a_index, a in enumerate(names):
        for b in names[a_index + 1:]:
            cells = Counter((r[a], r[b]) for r in rows)
            expected = len(rows) / (len(DIMENSIONS[a]) * len(DIMENSIONS[b]))
            for combo_a in DIMENSIONS[a]:
                for combo_b in DIMENSIONS[b]:
                    cost += (cells.get((combo_a, combo_b), 0) - expected) ** 2
    return cost


def balance_pairs(rows, seed=SEED, rounds=40000):
    """Even out pairwise occupancy by swapping values within a single column.

    Marginals are untouched because a swap moves a value from one row to
    another without changing how many times it appears.
    """
    rng = random.Random(seed + 1)
    names = list(DIMENSIONS)
    cost = pairwise_cost(rows)
    for _ in range(rounds):
        name = rng.choice(names)
        i, j = rng.randrange(len(rows)), rng.randrange(len(rows))
        if rows[i][name] == rows[j][name]:
            continue
        rows[i][name], rows[j][name] = rows[j][name], rows[i][name]
        new_cost = pairwise_cost(rows)
        if new_cost <= cost:
            cost = new_cost
        else:
            rows[i][name], rows[j][name] = rows[j][name], rows[i][name]
    return rows


def report(rows):
    print(f"{len(rows)} briefs\n")
    print("Marginals, which are exact by construction:")
    for name in DIMENSIONS:
        counts = Counter(r[name] for r in rows)
        spread = f"{min(counts.values())} to {max(counts.values())}"
        print(f"  {name:<12} {len(counts)} values, {spread} each")

    print("\nPairwise cell occupancy, which is not guaranteed:")
    names = list(DIMENSIONS)
    for a_index, a in enumerate(names):
        for b in names[a_index + 1:]:
            cells = Counter((r[a], r[b]) for r in rows)
            possible = len(DIMENSIONS[a]) * len(DIMENSIONS[b])
            empty = possible - len(cells)
            print(f"  {a} x {b:<14} {len(cells)}/{possible} cells filled, "
                  f"{empty} empty, counts {min(cells.values())} to {max(cells.values())}")


def main():
    rows = build_assignment()
    before = pairwise_cost(rows)
    rows = balance_pairs(rows)
    after = pairwise_cost(rows)
    print(f"pairwise imbalance cost: {before:.1f} before balancing, {after:.1f} after\n")
    report(rows)
    out = DATA_DIR / "brief_grid.json"
    out.write_text(json.dumps(
        {"seed": SEED, "total": TOTAL, "dimensions": DIMENSIONS, "rows": rows},
        indent=2))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
