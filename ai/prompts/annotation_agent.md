Scan one sentence from a reading passage and suggest which parts the learner should highlight.

## Sentence
{sentence}

## Learner
CEFR level: {cefr_level}

## Rules
1. Suggest **0 to {max_suggestions}** spans worth highlighting. Fewer is better than padding. An empty list is a valid answer for a plain sentence.
2. `text` MUST be copied **character for character** from the sentence above. Do not paraphrase, do not fix typos, do not change case or punctuation. A span that is not an exact substring will be discarded.
3. Each span should be a word or a short phrase (2-5 words). Never return the whole sentence.
4. `color` must be one of:
   - `blue` — a vocabulary item likely above the learner's level
   - `green` — a collocation or sentence pattern worth imitating in writing
   - `amber` — a grammar structure worth noticing
5. `reason`: one short Chinese sentence telling the learner why this is worth marking. Write Chinese only.
6. Prefer spans that are genuinely useful at this learner's CEFR level. Skip basic function words (the, of, is) and anything a learner at this level certainly knows.
7. Return structured JSON only. No markdown fences, no extra commentary.

## Output
Return a single JSON object matching this schema:
{schema}
