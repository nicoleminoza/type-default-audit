# What each number means

A plain reading of every metric in `metrics.csv` and `summary.json`, with the
pilot figures used as worked examples. The pilot covers 20 of the 210 briefs, so
treat every number here as an illustration of the measure rather than as a
result.

## The starting material

Each model was shown a design brief and asked for five typefaces. Each brief was
asked three separate times of each model, so that we could see how much the
answers move. In the pilot that produced 917 recommendations, and every one of
them was sorted into one of three groups: it named a font in the Google Fonts
catalog, it named a licensed font that is not in the catalog such as Minion Pro,
or it could not be resolved at all.

## Coverage, meaning how much of the catalog gets used

The catalog held 1,955 families on the run date. Across all 917 pilot
recommendations the models named 78 distinct catalog families, which is 4.0
percent. Imagine a menu with 1,955 dishes where the diners only ever order 78 of
them.

Coverage is bounded by how many recommendations you collect. Twenty briefs
cannot touch much of a large catalog no matter how varied the models are, so the
4.0 percent figure is mostly a statement about sample size. It will rise with the
full run, and that rise will not mean the models became more adventurous. This is
the number most likely to be misquoted.

## Share taken by the most popular choices

Line up all 917 recommendations and ask what fraction went to just the five most
recommended fonts. The answer is 22.9 percent. The ten most popular take 33.9
percent, and the twenty-five most popular take 52.0 percent. So a quarter of all
advice given pointed at five fonts, and half of it pointed at twenty-five.

This measure needs no statistical background to read, which makes it the most
useful one for a general audience.

## Herfindahl-Hirschman index, or how bunched up the answers are

The HHI compresses the whole distribution into one number between 0 and 1. It is
borrowed from competition regulators, who use it to judge whether a market is
dominated by a few firms. Near 0 means recommendations are spread thinly across
many fonts. Near 1 means everything went to one font.

The raw value is hard to feel. Dividing 1 by it gives something much more
intuitive, sometimes called the effective number of choices. It answers: if the
recommendations had been spread perfectly evenly, how many fonts would that have
taken to produce this much concentration?

| group | HHI | effective number of choices | fonts actually named |
|---|---:|---:|---:|
| pooled | 0.0178 | 56 | 78 |
| Anthropic | 0.0218 | 46 | 42 |
| Gemini | 0.0173 | 58 | 50 |
| OpenAI | 0.0262 | 38 | 46 |

Read the OpenAI row as: across a catalog of 1,955 families, its recommendations
behaved like a menu of roughly 38 options.

## Gini, or how unevenly the attention is shared

The Gini coefficient is the same measure economists use for income inequality. 0
means everyone gets an identical share. 1 means one recipient takes everything.

It appears twice in the output because there are two honest ways to count, and
they answer different questions.

`gini_observed_gf` is 0.60 in the pilot. It looks only at the 78 fonts that were
recommended at least once and asks how evenly the attention was shared among
them. Some were named dozens of times and many were named once, which is what a
0.60 describes. This is the version that changes meaningfully between slices, so
it is the one to use when comparing conditions.

`gini_against_catalog` is 0.98. It counts every catalog family, including the
roughly 1,877 that were never mentioned, each entering as a zero. That is the
literal answer to "how concentrated are recommendations against everything
available", and it is the more honest framing of the study's actual question. Its
weakness is that it will sit near 0.98 in every condition, so it cannot
distinguish between them. Quote it once to establish the scale, then use the
other one for comparisons.

## Share falling outside the catalog

36.0 percent of pilot recommendations named a font that is not in Google Fonts at
all, mostly licensed faces from commercial foundries. This is not an error rate.
The models were never told to restrict themselves to Google Fonts, deliberately,
because knowing how often they reach for licensed type is part of the finding.

## Stability, or whether asking again changes the answer

Each brief was put to each model three times. Stability asks how much those three
answers overlap.

The headline figure is 0.49, calculated as the average overlap between each pair
of answer sets. A more direct way to say the same thing: of the five fonts
recommended, an average of 2.5 appeared in all three attempts. So roughly half
the advice is stable and half moves between askings.

This is only meaningful because the models were sampled at their default
randomness rather than being pinned to their most likely answer. Had they been
pinned, the three attempts would have been near copies and this number would have
described the API rather than the model.

## Why some metrics appear twice, once for everything and once for Google only

Roughly a third of recommendations name licensed fonts. If concentration were
measured only over the Google Fonts hits, that third would vanish from the
analysis, and the study would be describing how models choose among Google fonts
rather than how they give font advice.

So the concentration measures are computed twice. The columns ending `_all` treat
a licensed face like Graphik as its own option, which measures how narrow the
advice is overall. The columns ending `_gf` cover only recommendations that
landed in the catalog. Neither is wrong, but quoting one without saying which is
misleading.

## Why the Greek slice uses a different denominator

Only 118 of the 1,955 catalog families support Greek. A brief that asks for Greek
text can therefore only ever draw on those 118.

Scored against the whole catalog, the Greek slice shows 1.2 percent coverage,
which reads as extreme narrowness. Scored against the 118 families actually
eligible, it shows 20.3 percent. The second is the true figure. The first would
have blamed the models for a shortage in the catalog. Every script slice uses its
own eligible count for this reason.

## Why most rows in metrics.csv should not be read yet

The file holds 116 rows because every dimension is crossed with every model. At
pilot size only 4 of them clear the bar: the pooled row and one per model.

The reason is arithmetic. Twenty briefs spread across ten domains leaves two
briefs per domain. A concentration figure built on two briefs mostly reflects
which two briefs happened to be included. Every row carries a `reliable` column
and a brief count, and anything below fifteen briefs is marked `NO, n too small`.

After the full 210-brief run each domain will hold 21 briefs and each script 42,
at which point the slices become the actual finding.

## How much the judgment calls move the results

Some recommendations required interpretation. "Source Sans Pro" is a name Google
retired, and the same typeface is in the catalog today as "Source Sans 3". Those
decisions are all recorded in `normalization_decisions.csv` and were reviewed.

To show how much they matter, every metric is also computed with all of them
reversed. Doing so moves the out-of-catalog share from 36.0 to 38.3 percent, and
moves HHI from 0.0178 to 0.0170 and the unique family count from 78 to 75.

The useful conclusion is that the judgment calls matter for the out-of-catalog
figure and are close to irrelevant for the concentration figures. So the
concentration finding does not depend on a reader accepting those calls, while
the out-of-catalog number should always be quoted with that range attached.
