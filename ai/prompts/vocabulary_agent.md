Explain one English word or phrase a learner highlighted while reading.

## Highlighted text
{word}

## Sentence it came from
{context}

## Learner
CEFR level: {cefr_level}

## Rules
1. `word`: the dictionary base form (lemma) of the highlighted text. For "studies" write "study"; for "went" write "go"; for "degraded" write "degrade". For a phrase, repeat it as written.
2. `pronunciation`: IPA of the base form, wrapped in slashes, for example `/dɪˈɡreɪd/`.
3. `part_of_speech`: the part of speech of the highlighted text AS USED in the sentence. If "degraded" works as an adjective here, write `adj.` even though the lemma "degrade" is a verb. Use an abbreviated tag such as `n.`, `v.`, `adj.`, `adv.`
4. `senses`: 1-3 entries covering the parts of speech this word family commonly has, the sense of the highlighted form first. Each entry has `part_of_speech` (abbreviated tag), `meaning` (short Chinese gloss), and `example` (one short natural English sentence using that sense, at or slightly above the learner's level). Cover different parts of speech when they exist — for "degraded" give both the `v.` sense and the `adj.` sense.
5. `core_meanings`: 1-3 common Chinese meanings of the base form, most frequent first. Write Chinese only.
6. `meaning_in_context`: in Chinese, one or two sentences explaining what the highlighted text means right here. Always fill it when a sentence is given.
7. `collocations`: 2-4 common fixed phrases built with this word.
8. `example_sentences`: 2 English sentences using the base form, at or slightly above the learner's level.
9. `related_words`: 2-4 near-synonyms or word-family members, each with a short Chinese note.
10. Judge the meaning from the sentence above, and never invent a meaning the word does not have.
11. Return structured JSON only. No markdown fences, no extra commentary.

## Output
Return a single JSON object matching this schema:
{schema}