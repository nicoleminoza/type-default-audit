"""Ask each configured model to recommend five typefaces for each brief.

Every call is appended to data/responses.jsonl as one line holding the raw
provider response alongside the parsed result. The file is append-only and keyed,
so a crash costs only the calls in flight: rerunning skips work already recorded.

The prompt does not mention Google Fonts. That is deliberate. Step 4 needs a
bucket counting recommendations that fall outside the catalog, and constraining
the prompt to Google Fonts would empty that bucket and destroy the out-of-catalog
rate. Models are asked what they would actually recommend, and the catalog serves
as the reference corpus rather than as a constraint.

Nothing is ever silently dropped. Every call resolves to a recorded outcome, and
failures are counted rather than discarded, because failures are unlikely to be
distributed evenly across briefs and dropping them would make concentration look
tighter than it is.

Usage:
  python src/run_recommendations.py --models anthropic --limit 20
  python src/run_recommendations.py --models anthropic,gemini --samples 3
  python src/run_recommendations.py --list-models
"""

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import providers
from config import DATA_DIR, PROJECT_ROOT

# Changing the prompt changes the instrument. The version is part of every
# record's key so responses gathered under different wording never pool silently.
PROMPT_VERSION = "v1"

PROMPT_TEMPLATE = """Brief:
{brief}

Recommend exactly five typefaces for this brief.

Respond with only a JSON object in this exact shape and nothing else:
{{"recommendations": [{{"font": "...", "reason": "..."}}]}}

Each reason should be one sentence."""

# Pinned model identifiers. Dated where the provider offers a dated id, because
# an alias that drifts makes a rerun incomparable and no provenance record can
# detect it after the fact.
MODELS = {
    "anthropic": {
        "provider": "anthropic",
        "model_id": "claude-opus-4-5-20251101",
        "tier": "flagship",
        "pinning": "fully dated",
    },
    "openai": {
        "provider": "openai",
        "model_id": "gpt-5.5-2026-04-23",
        "tier": "flagship",
        "pinning": "fully dated",
    },
    "gemini": {
        "provider": "gemini",
        "model_id": "gemini-3.1-pro-preview",
        "tier": "pro",
        "pinning": "id undated, version string 3.1-pro-preview-01-2026 recorded per call",
    },
    # Fallback for the Gemini leg if Pro billing stays off. Not tier-matched to
    # the other two, so results from it must be labelled as Flash rather than
    # quietly pooled with flagship numbers.
    "gemini_flash": {
        "provider": "gemini",
        "model_id": "gemini-3.6-flash",
        "tier": "flash, NOT tier-matched to the others",
        "pinning": "id undated, version string 3.6-flash-07-2026",
    },
}

RESPONSES_PATH = DATA_DIR / "responses.jsonl"

REFUSAL_MARKERS = ("i can't", "i cannot", "i'm unable", "i am unable",
                   "as an ai", "i won't", "i will not")

_write_lock = threading.Lock()


def brief_fingerprint(text):
    """Short hash of the brief text, used in the record key.

    Without this, editing a brief would leave its old responses looking valid
    and a rerun would skip them, so results would silently mix answers to two
    different questions. Changing a brief now invalidates exactly that brief's
    responses and nothing else.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def record_key(brief_id, model_key, sample_index, fingerprint):
    return f"{PROMPT_VERSION}|{model_key}|{brief_id}|{fingerprint}|{sample_index}"


def load_completed_keys(path):
    """Keys already recorded, so a rerun resumes instead of repeating work."""
    if not path.exists():
        return set()
    keys = set()
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(json.loads(line)["key"])
            except (json.JSONDecodeError, KeyError):
                # A truncated final line is the normal shape of a crash. Skip it
                # rather than refusing to start, and let the call be redone.
                continue
    return keys


def extract_json(text):
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or fences despite instructions. Stripping fences
    and taking the outermost braces recovers most of those without being so
    permissive that genuinely broken output looks fine.
    """
    if not text:
        return None
    cleaned = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(),
                     flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None


def parse_response(text):
    """Return (outcome, recommendations). Never raises, never guesses a font."""
    document = extract_json(text)
    if document is None:
        lowered = (text or "").lower()
        if any(marker in lowered for marker in REFUSAL_MARKERS):
            return "possible_refusal", []
        return "malformed_json", []

    items = document.get("recommendations")
    if not isinstance(items, list):
        return "malformed_json", []

    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        font = item.get("font")
        if isinstance(font, str) and font.strip():
            parsed.append({"font": font.strip(),
                           "reason": str(item.get("reason", "")).strip()})

    if not parsed:
        return "malformed_json", []
    if len(parsed) != 5:
        return "wrong_count", parsed
    return "ok", parsed


def run_one(task, provider, path):
    brief, model_key, sample_index = task
    fingerprint = brief_fingerprint(brief["text"])
    key = record_key(brief["id"], model_key, sample_index, fingerprint)
    prompt = PROMPT_TEMPLATE.format(brief=brief["text"])

    started = time.time()
    record = {
        "key": key,
        "brief_id": brief["id"],
        "model_key": model_key,
        "provider": MODELS[model_key]["provider"],
        "model_id": MODELS[model_key]["model_id"],
        "sample_index": sample_index,
        "prompt_version": PROMPT_VERSION,
        "brief_fingerprint": fingerprint,
        "brief_text": brief["text"],
        "prompt": prompt,
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "brief_tags": {k: brief[k] for k in
                       ("domain", "tone", "medium", "script", "specificity")},
    }

    try:
        result = provider.complete(prompt)
        outcome, parsed = parse_response(result["text"])
        record.update({
            "outcome": outcome,
            "text": result["text"],
            "raw": result["raw"],
            "usage": result["usage"],
            "sent_parameters": result["sent_parameters"],
            "parsed": parsed,
            "error": None,
        })
    except providers.ProviderError as err:
        record.update({"outcome": "api_error", "text": None, "raw": None,
                       "usage": {}, "sent_parameters": {}, "parsed": [],
                       "error": str(err)[:600]})
    except Exception as err:  # noqa: BLE001 - a crash here must not lose the batch
        record.update({"outcome": "api_error", "text": None, "raw": None,
                       "usage": {}, "sent_parameters": {}, "parsed": [],
                       "error": f"{type(err).__name__}: {err}"[:600]})

    record["latency_seconds"] = round(time.time() - started, 2)

    with _write_lock:
        with open(path, "a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record["outcome"]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default="anthropic",
                        help="comma-separated keys from --list-models")
    parser.add_argument("--limit", type=int, default=None,
                        help="use only the first N briefs, for a pilot run")
    parser.add_argument("--samples", type=int, default=3,
                        help="samples per brief per model, for the stability measure")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be called without calling anything")
    args = parser.parse_args()

    if args.list_models:
        for key, spec in MODELS.items():
            print(f"  {key:<15} {spec['model_id']:<32} {spec['tier']}")
            print(f"  {'':<15} pinning: {spec['pinning']}")
        return

    briefs = json.load(open(PROJECT_ROOT / "briefs.json"))["briefs"]
    if args.limit:
        briefs = briefs[:args.limit]

    model_keys = [m.strip() for m in args.models.split(",") if m.strip()]
    for key in model_keys:
        if key not in MODELS:
            raise SystemExit(f"Unknown model key {key}. Try --list-models.")

    built = {}
    for key in model_keys:
        spec = MODELS[key]
        provider = providers.build(spec["provider"], spec["model_id"])
        if not provider.available():
            raise SystemExit(f"{key} needs {provider.key_env} in .env")
        built[key] = provider

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    done = load_completed_keys(RESPONSES_PATH)

    tasks = [
        (brief, key, sample)
        for brief in briefs
        for key in model_keys
        for sample in range(1, args.samples + 1)
        if record_key(brief["id"], key, sample,
                      brief_fingerprint(brief["text"])) not in done
    ]
    total = len(briefs) * len(model_keys) * args.samples

    print(f"briefs: {len(briefs)}   models: {len(model_keys)}   samples: {args.samples}")
    print(f"calls needed: {total}   already recorded: {total - len(tasks)}   "
          f"to run now: {len(tasks)}")
    if args.dry_run:
        print("dry run, nothing called")
        return
    if not tasks:
        print("nothing to do")
        return

    counts = Counter()
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, task, built[task[1]], RESPONSES_PATH)
                   for task in tasks]
        for index, future in enumerate(futures, start=1):
            counts[future.result()] += 1
            if index % 10 == 0 or index == len(futures):
                elapsed = time.time() - started
                print(f"  {index}/{len(futures)}  {elapsed:.0f}s  "
                      + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())),
                      flush=True)

    print(f"\nwrote {RESPONSES_PATH}")
    for outcome, count in sorted(counts.items()):
        print(f"  {outcome:<18} {count}")
    if counts["ok"] != len(tasks):
        print("\nNon-ok outcomes are recorded, not discarded. Review them before "
              "trusting any concentration number computed from this run.")


if __name__ == "__main__":
    main()
