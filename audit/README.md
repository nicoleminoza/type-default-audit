# audit

This directory holds the small artifacts the study's conclusions rest on. It
is tracked in git, unlike `data/`, which is ignored.

The split is deliberate. `data/` holds things that are large and
regenerable: the cached Google Fonts catalog, the raw API response bodies,
and later the raw model responses for every brief and sample. Those can be
refetched or rerun, and committing megabytes of them would make the history
unusable. This directory holds things that are small, that a human is
expected to read, and whose changes over time are themselves evidence.

Files that will land here as the phases complete:

- `normalization_decisions.csv`, written by step 4. Every model-returned font
  string, the catalog family it was matched to, the method that produced the
  match, and the bucket it fell into. This is the file the methodology
  commits to being reviewable line by line, because normalization is where
  results get quietly corrupted.
- `metrics.csv`, written by step 5, holding the concentration measures per
  model and pooled, and the same measures sliced by every brief dimension.
- `summary.json`, written by step 6, holding the headline figures together
  with the catalog provenance they were computed against.

Version history matters here for a specific reason. If a matching rule
changes, the diff on `normalization_decisions.csv` shows exactly which
strings were reclassified, which is the only practical way to tell an
improvement from a regression. A results file with no history cannot support
that claim.

The honest cost of this arrangement is that every rerun produces a diff, even
when nothing meaningful changed, because sampling from a model is not
deterministic. That noise is tolerable. The alternative, which is untracked
results, means the mapping you reviewed and the mapping the numbers came from
can silently diverge with nothing to show it.

Being tracked does not make these files correct. The normalization CSV is
worth what the review of it is worth, and nothing here should be cited until
someone has actually read it.
