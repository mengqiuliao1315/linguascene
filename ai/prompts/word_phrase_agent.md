Explain a word or a phrase the learner highlighted while reading, and suggest a short study note.

## Highlighted text
{text}

## Sentence it came from
{sentence}

## Learner
CEFR level: {cefr_level}

## Rules
1. `kind`: `word` when the highlighted text is a single word, `phrase` when it is two or more words.
2. `lemma`: for a single word, its dictionary base form. For "studies" write "study"; for "went" write "go". For a phrase, repeat the phrase as written.
3. `text`: the highlighted text exactly as it appears in the sentence.
4. `meaning`: a short Chinese gloss of what it means in this sentence. Write Chinese only.
5. `part_of_speech`: for a single word, an abbreviated tag such as `n.`, `v.`, `adj.`, `adv.`. Leave empty for a phrase.
6. `note`: a concise Chinese study note the learner can keep — usage, collocation, or a trap worth remembering. One or two sentences. Write Chinese only.
7. `example`: one short English sentence using the word or phrase naturally, at the learner's level. Leave empty if you cannot produce a good one.
8. Judge the meaning from the sentence above. Never invent a meaning the word does not have.
9. Return structured JSON only. No markdown fences, no extra commentary.

## Output
Return a single JSON object matching this schema:
{schema}
