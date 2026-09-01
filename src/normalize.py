"""Resolve model-returned font strings to Google Fonts families.

Normalization is where results get quietly corrupted, so this module is built to
be read rather than trusted. Every distinct string that any model returned gets
one row in audit/normalization_decisions.csv recording what it was matched to,
by which rule, and whether that rule involved judgment. Nothing is dropped.

Three buckets, as the study requires:

  google_fonts      resolved to a family in the catalog
  known_non_google  a real typeface that is not in Google Fonts
  unresolved        could not be resolved, or could not be confirmed to exist

A name only enters known_non_google when it is a typeface I can positively
identify. Anything unconfirmed stays unresolved, because that bucket then holds
both genuinely obscure faces and any names a model may have invented, and
collapsing those together would hide the more interesting of the two.

Rules run in descending order of confidence and the first hit wins. Exact
matching runs before every heuristic, which is what makes the later rules safe:
Archivo Black is matched as itself long before any weight-stripping rule could
turn it into Archivo.

Usage:  python src/normalize.py
"""

import csv
import json
import re
from collections import Counter
from difflib import SequenceMatcher

from config import DATA_DIR, PROJECT_ROOT

AUDIT_DIR = PROJECT_ROOT / "audit"

# Fuzzy matching is the single most dangerous rule here, so the cutoff is set
# high and every fuzzy hit is flagged for review in the CSV rather than being
# quietly accepted. Lower this only after reading what it already accepts.
FUZZY_CUTOFF = 0.92

# Families Google renamed. The typeface is in the catalog under a new name, and
# the model named it correctly for an earlier era.
RENAMED_FAMILIES = {
    "Source Sans Pro": "Source Sans 3",
    "Source Serif Pro": "Source Serif 4",
    "Big Shoulders Display": "Big Shoulders",
    "Saira Stencil One": "Saira Stencil",
}

# The same typeface released under two vendors' names. Source Han and Noto CJK
# are the same joint Adobe and Google project with different branding.
KNOWN_ALIASES = {
    "Source Han Sans JP": "Noto Sans JP",
    "Source Han Serif JP": "Noto Serif JP",
    "Source Han Sans": "Noto Sans JP",
    "Source Han Serif": "Noto Serif JP",
    "Noto Sans CJK JP": "Noto Sans JP",
    "Noto Serif CJK JP": "Noto Serif JP",
    "Noto Sans CJK": "Noto Sans JP",
    "Noto Serif CJK": "Noto Serif JP",
}

# Script names that are subsets of a family rather than families of their own.
# "Noto Serif Greek" is Noto Serif with Greek coverage, not a separate release.
SCRIPT_QUALIFIERS = ("Greek", "Vietnamese", "Cyrillic", "Latin", "Thai",
                     "Arabic", "Hebrew", "Devanagari")
WIDTH_WORDS = ("Condensed", "Cond", "Expanded", "Extended", "Wide", "Narrow",
               "Compressed")

WEIGHT_WORDS = ("Thin", "ExtraLight", "Light", "Regular", "Medium", "SemiBold",
                "Bold", "ExtraBold", "Black", "Heavy")

# Typefaces I can positively identify as real and not in Google Fonts. Names I
# cannot confirm are deliberately absent and fall through to unresolved.
KNOWN_NON_GOOGLE = {
    # Adobe
    "Minion Pro": "Adobe", "Minion 3": "Adobe", "Arno Pro": "Adobe",
    "Adobe Caslon Pro": "Adobe", "Adobe Garamond Pro": "Adobe",
    "Garamond Premier Pro": "Adobe", "Acumin Pro": "Adobe",
    "Acumin Pro Condensed": "Adobe", "Adobe Text Pro": "Adobe",
    "Kozuka Gothic": "Adobe", "Kozuka Gothic Pro": "Adobe",
    # Monotype, Linotype, Berthold
    "Helvetica": "Monotype", "Helvetica Neue": "Monotype",
    "Helvetica Now": "Monotype", "Helvetica Now World": "Monotype",
    "Univers": "Monotype", "Univers Next": "Monotype", "Sabon": "Monotype",
    "Sabon Next": "Monotype", "Optima": "Monotype", "Palatino": "Monotype",
    "Plantin": "Monotype", "Bembo": "Monotype", "Bembo Book": "Monotype",
    "Frutiger": "Monotype",
    "Neue Frutiger World": "Monotype", "Trade Gothic Next": "Monotype",
    "DIN Next": "Monotype", "DIN Next LT Pro": "Monotype", "Avenir": "Monotype",
    "Avenir Next": "Monotype", "Avenir Next World": "Monotype",
    "Akzidenz-Grotesk": "Berthold", "Arial": "Monotype",
    "Impact": "Monotype", "Neue Haas Grotesk": "Monotype",
    "Neue Haas Unica": "Monotype", "FF Meta": "Monotype",
    # Hoefler and Co
    "Gotham": "Hoefler & Co", "Knockout": "Hoefler & Co",
    "Whitney": "Hoefler & Co", "Mercury Text": "Hoefler & Co",
    "Tungsten": "Hoefler & Co", "Hoefler Text": "Hoefler & Co",
    "Obviously": "Hoefler & Co",
    # Commercial Type
    "Graphik": "Commercial Type", "Lyon Text": "Commercial Type",
    "Canela": "Commercial Type", "Atlas Grotesk": "Commercial Type",
    "Druk": "Commercial Type", "Druk Wide": "Commercial Type",
    "Druk Cyr": "Commercial Type",
    # Klim
    "Founders Grotesk": "Klim", "Tiempos Text": "Klim", "Pitch": "Klim",
    # Grilli Type
    "GT America": "Grilli Type", "GT Walsheim": "Grilli Type",
    "GT Flexa": "Grilli Type", "GT Pressura": "Grilli Type",
    "GT Maru": "Grilli Type",
    # Dinamo, Colophon, other contemporary foundries
    "ABC Diatype": "Dinamo", "ABC Favorit": "Dinamo", "ABC Whyte": "Dinamo",
    "ABC Ginto": "Dinamo", "ABC Arizona": "Dinamo", "Favorit": "Dinamo",
    "Ginto": "Dinamo", "Mabry": "Colophon", "Trim": "Colophon",
    "Monument Extended": "Pangram Pangram", "Monument Grotesk": "Pangram Pangram",
    "Neue Machina": "Pangram Pangram", "Agrandir": "Pangram Pangram",
    "Right Grotesk": "Pangram Pangram",
    "Akkurat": "Lineto", "Suisse Int'l": "Swiss Typefaces",
    "Euclid Flex": "Swiss Typefaces", "Degular": "OH no Type",
    "Sharp Grotesk": "Sharp Type", "Roc Grotesk": "Sharp Type",
    "Roobert": "Displaay", "Aeonik Pro": "CoType", "Stapel": "Fontwerk",
    "Calluna": "exljbris", "Iowan Old Style": "Bitstream",
    "Miller Text": "Font Bureau", "Freight Text Pro": "Darden Studio",
    "Averta": "Intelligent Foundry", "Filson Pro": "Mostardesign",
    # Typotheque, Rosetta, Parachute
    "Fedra Sans": "Typotheque", "Fedra Serif": "Typotheque",
    "Greta Sans": "Typotheque", "Skolar": "Rosetta",
    "PF DIN Text Pro": "Parachute", "PF Centro Sans Pro": "Parachute",
    "PF Regal Text": "Parachute", "PF Handbook Pro": "Parachute",
    # Cyrillic-focused foundries
    "Pragmatica": "ParaType", "Soyuz Grotesk": "type.today",
    "Kazimir Text": "CSTM Fonts", "TT Firs Neue": "TypeType",
    # System and platform fonts
    "SF Pro": "Apple", "Segoe UI": "Microsoft", "Aptos": "Microsoft",
    # Japanese foundries
    "Hiragino Mincho ProN": "Screen", "Hiragino Kaku Gothic ProN": "Screen",
    "Yu Mincho": "Jiyukobo", "Yu Gothic": "Jiyukobo",
    "A-OTF Ryumin Pr6N": "Morisawa", "A-OTF Gothic MB101": "Morisawa",
    "A-OTF Midashi Go MB31": "Morisawa", "Tsukushi A Mincho": "Fontworks",
    "FOT-Matisse Pro": "Fontworks", "Axis Std": "Type Project",
    "TP Mincho": "Type Project", "Tazugane Gothic": "Morisawa",
    "DNP Shuei Mincho Pr6N": "DNP", "Kurokane": "Fontworks",
    # Other identifiable
    "Gentium": "SIL", "FiraGO": "bBox", "DIN Pro": "FontFont",
    "DIN 2014": "ParaType", "NB International": "Neubau",
    "Reforma Grotesk": "Letterhead",
    # Added after reviewing the pilot's unresolved bucket. Each of these I can
    # positively identify; names I still cannot confirm are left out on purpose.
    "Bandera Pro": "ParaType", "Molot": "Letterhead", "Apoc": "Pangram Pangram",
    "Authentic Sans": "Authentic", "Akira Expanded": "Bourbon",
    "Bebas Kai": "Dharma Type", "Suisse Int'l Mono": "Swiss Typefaces",
    "PF DIN Text Condensed": "Parachute", "PF DIN Text Cond": "Parachute",
    "Hakusyu Gyosho": "Hakusyu", "Shuei ShogoMincho": "DNP",
    "Source Han Sans": "Adobe", "Source Han Serif": "Adobe",
}

# Historical typeface names that do not identify a specific released family.
# A model saying "Garamond" or "Caslon" is naming a tradition, not a font you
# can license, so these are recorded distinctly rather than forced into a match.
# Bembo and Sabon are deliberately absent: those are specific twentieth-century
# releases with clear ownership, not open traditions with many interpretations.
GENERIC_HISTORICAL = {"Garamond", "Caslon", "Bodoni", "Baskerville", "Didot",
                      "Clarendon", "Futura", "Times"}

SPLIT_PATTERN = re.compile(r"\s*[+/]\s*|\s+\+\s+")


def simplify(name):
    """Casefold and flatten punctuation so curly and straight quotes agree."""
    return re.sub(r"[^a-z0-9]+", "", name.lower().replace("\u2019", "'"))


# Lookups are keyed on the simplified form so a curly apostrophe or a lowercase
# DIN cannot cause a miss. Both of those happened in the pilot.
RENAMED_SIMPLE = {simplify(k): v for k, v in RENAMED_FAMILIES.items()}
ALIAS_SIMPLE = {simplify(k): v for k, v in KNOWN_ALIASES.items()}
NON_GOOGLE_SIMPLE = {simplify(k): v for k, v in KNOWN_NON_GOOGLE.items()}


def load_records():
    """Latest record per key, matching the runner's dedupe rule."""
    path = DATA_DIR / "responses.jsonl"
    latest = {}
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            latest[record["key"]] = record
    return list(latest.values())


def split_pairing(raw):
    """Split a field naming two families into its parts.

    Models return things like "Roboto + Roboto Mono" in a single font field.
    Both are genuine recommendations, so both are counted, and the source string
    is preserved on each part so the split is visible in the audit file.
    """
    if not SPLIT_PATTERN.search(raw):
        return [raw]
    parts = [p.strip() for p in SPLIT_PATTERN.split(raw) if p.strip()]
    return parts if len(parts) > 1 else [raw]


def resolve(name, families, simple_index, depth=0):
    """Return (bucket, matched_family, method, score, needs_review).

    Rules run in descending order of confidence and the first hit wins. When a
    trailing weight, width or script word is stripped, the base is passed back
    through the whole cascade rather than only being checked against the
    catalog, because "Source Han Sans JP Heavy" needs the alias table after the
    weight comes off, not before.
    """
    if name in families:
        return "google_fonts", name, "exact", 1.0, False

    simple = simplify(name)
    if simple in simple_index:
        return "google_fonts", simple_index[simple], "punctuation_or_case", 1.0, False

    if simple in RENAMED_SIMPLE:
        return "google_fonts", RENAMED_SIMPLE[simple], "renamed_family", 1.0, True

    if simple in ALIAS_SIMPLE:
        return "google_fonts", ALIAS_SIMPLE[simple], "known_alias", 1.0, True

    if name in GENERIC_HISTORICAL:
        return ("unresolved", "", "generic_historical_name", 1.0, True)

    if simple in NON_GOOGLE_SIMPLE:
        foundry = NON_GOOGLE_SIMPLE[simple]
        return "known_non_google", "", f"known_non_google:{foundry}", 1.0, False

    # Strip one trailing qualifier and re-run the whole cascade on the base.
    if depth < 3:
        parts = name.split()
        if len(parts) > 1 and parts[-1] in WEIGHT_WORDS + WIDTH_WORDS + SCRIPT_QUALIFIERS:
            kind = ("weight" if parts[-1] in WEIGHT_WORDS
                    else "width" if parts[-1] in WIDTH_WORDS else "script")
            base = " ".join(parts[:-1])
            bucket, family, method, score, review = resolve(
                base, families, simple_index, depth + 1)
            if bucket != "unresolved":
                return (bucket, family, f"{kind}_suffix_stripped>{method}",
                        score, review or kind == "script")
        # Foundry prefixes such as "Dinamo ABC Arizona".
        if len(parts) > 2:
            base = " ".join(parts[1:])
            bucket, family, method, score, review = resolve(
                base, families, simple_index, depth + 1)
            if bucket != "unresolved":
                return (bucket, family, f"foundry_prefix_dropped>{method}",
                        score, True)

    # A known non-Google face carrying extra style words is still that face.
    for known_simple, foundry in NON_GOOGLE_SIMPLE.items():
        if simple.startswith(known_simple) and len(simple) > len(known_simple):
            return ("known_non_google", "",
                    f"known_non_google_variant:{foundry}", 1.0, False)

    best, best_score = None, 0.0
    for family in families:
        score = SequenceMatcher(None, simple, simplify(family)).ratio()
        if score > best_score:
            best, best_score = family, score
    if best_score >= FUZZY_CUTOFF:
        return "google_fonts", best, "fuzzy", round(best_score, 3), True

    return ("unresolved", "", "unresolved", round(best_score, 3), True)


def main():
    catalog = json.load(open(DATA_DIR / "catalog.json"))
    families = {item["family"] for item in catalog["items"]}
    simple_index = {simplify(f): f for f in families}

    records = load_records()
    occurrences = Counter()
    pairing_source = {}
    for record in records:
        for item in record.get("parsed", []):
            raw = item["font"]
            parts = split_pairing(raw)
            for part in parts:
                occurrences[part] += 1
                if len(parts) > 1:
                    pairing_source.setdefault(part, set()).add(raw)

    decisions = {}
    for name in occurrences:
        decisions[name] = resolve(name, families, simple_index)

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = AUDIT_DIR / "normalization_decisions.csv"
    with open(csv_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["original_string", "occurrences", "bucket",
                         "matched_family", "method", "score", "needs_review",
                         "split_from"])
        for name in sorted(occurrences, key=lambda n: (-occurrences[n], n)):
            bucket, family, method, score, review = decisions[name]
            writer.writerow([name, occurrences[name], bucket, family, method,
                             score, "yes" if review else "no",
                             "; ".join(sorted(pairing_source.get(name, [])))])

    resolved_path = DATA_DIR / "resolved.jsonl"
    total = 0
    with open(resolved_path, "w") as handle:
        for record in records:
            for item in record.get("parsed", []):
                for part in split_pairing(item["font"]):
                    bucket, family, method, score, review = decisions[part]
                    handle.write(json.dumps({
                        "brief_id": record["brief_id"],
                        "model_key": record["model_key"],
                        "sample_index": record["sample_index"],
                        "brief_tags": record["brief_tags"],
                        "original_string": part,
                        "raw_field": item["font"],
                        "bucket": bucket,
                        "family": family,
                        "method": method,
                        "needs_review": review,
                    }, ensure_ascii=False) + "\n")
                    total += 1

    buckets = Counter(decisions[n][0] for n in occurrences)
    weighted = Counter()
    for name, count in occurrences.items():
        weighted[decisions[name][0]] += count
    methods = Counter()
    for name, count in occurrences.items():
        methods[decisions[name][2].split(":")[0]] += count

    print(f"records read:            {len(records)}")
    print(f"recommendations after splitting pairings: {total}")
    print(f"distinct strings:        {len(occurrences)}\n")
    print("By bucket, counted as recommendations:")
    for bucket, count in weighted.most_common():
        print(f"  {bucket:<20} {count:>5}  {count/total:>6.1%}")
    print("\nBy bucket, counted as distinct strings:")
    for bucket, count in buckets.most_common():
        print(f"  {bucket:<20} {count:>5}")
    print("\nBy method, counted as recommendations:")
    for method, count in methods.most_common():
        print(f"  {method:<28} {count:>5}")
    review = sum(c for n, c in occurrences.items() if decisions[n][4])
    print(f"\nflagged needs_review:    {review} recommendations across "
          f"{sum(1 for n in occurrences if decisions[n][4])} strings")
    print(f"\nwrote {csv_path}")
    print(f"wrote {resolved_path}")


if __name__ == "__main__":
    main()
