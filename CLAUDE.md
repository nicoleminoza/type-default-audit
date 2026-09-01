# Project: type-default-audit

## What this is
An empirical study of how concentrated large language model font
recommendations are, measured against the full Google Fonts catalog. The
output is a distribution and a set of conditions that widen it, not an
opinion about which fonts are good.

## Who is building it
Nicole Miñoza, former Director of Product and Product Marketing for Adobe
Fonts. She has run evaluation and measurement work as a product leader but
has not personally built an eval harness, an MCP server, or a React app
before. She is building this to learn as well as to ship.

## How to work with her
Explain the reasoning before writing code, not after. When there is a real
choice to make, name the options and the tradeoff and let her pick rather
than choosing silently. Prefer boring, readable code over clever code. When
something is a genuine judgment call about methodology, stop and say so.
Never fabricate a result, a count, or a benchmark figure. If a number is not
yet measured, leave it as a placeholder that is obviously a placeholder.

## Methodological commitments, do not violate these
- The Google Fonts catalog is the only corpus. No licensed fonts.
- Report the exact family count returned by the API on the run date. Never
  approximate it from memory.
- Recommendations that fall outside the Google Fonts catalog are data, not
  errors. Bucket and count them separately.
- Normalization of model-returned font names to catalog entries is where
  results get quietly corrupted. Every normalization decision must be
  written to an auditable file that a human can review line by line.
- Concentration is what this measures. Recommendation quality is explicitly
  out of scope for phase one.
- Any comparison between conditions must hold the brief set and the sampling
  parameters identical, and must state its confounds plainly.

## Style for any prose this project generates
Connected prose in full sentences. No em dashes. No clipped fragments for
emphasis. Be direct about weaknesses.
