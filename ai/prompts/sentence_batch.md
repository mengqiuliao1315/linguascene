Analyze {count} English sentences for a Chinese-speaking learner.

## Sentences
{sentences}

## Learner
CEFR level: {cefr_level}

## Rules
For EACH sentence, produce one analysis object with exactly these fields:

1. `sentence`: copy the original sentence exactly, character for character.
2. `chinese_meaning`: a natural Chinese translation of that sentence. Write Chinese only, never English.
3. `main_clause`: the subject-verb-object skeleton of that sentence, in English.
4. `structure`: one short Chinese sentence describing how that sentence is built — clause type, key patterns.
5. `vocabulary`: 2-5 key words the learner should know, for THAT sentence. Use the base form (lemma) for `word`. Write `meaning` in Chinese. `example` may copy the original sentence.
6. `collocations`: fixed phrases or idioms that actually appear in THAT sentence. Write `meaning` in Chinese. Leave the list empty when there are none — do not force a match.
7. `grammar_points`: grammar worth noticing in THAT sentence. Write `explanation` in Chinese. Leave the list empty when there is nothing notable.
8. `natural_alternative`: a more idiomatic English version of the same idea. Leave it empty when the original is already natural.
9. Explain at the learner's CEFR level.
10. Return structured JSON only. No markdown fences, no extra commentary.

## Output
Return a single JSON object matching this schema. The `sentences` array MUST contain exactly {count} items, in the SAME order as the input above.

{schema}
