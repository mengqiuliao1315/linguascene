Explain the English word or phrase a learner selected while reading. Answer in as few tokens as possible.

## Rules
1. `word`: the dictionary base form. "degraded" → "degrade", "studies" → "study", "went" → "go". For a phrase repeat it as written.
2. `pronunciation`: IPA of the base form in slashes, for example `/dɪˈɡreɪd/`.
3. `senses`: 1-2 entries for the parts of speech this word commonly has, the one used in the sentence first. Each entry needs `part_of_speech` (one of `n.`, `v.`, `adj.`, `adv.`), `meaning` (a short Chinese gloss), and `example` (one short English sentence using that sense, at most 12 words).
4. Judge the part of speech from how the selected form is actually used: if "degraded" works as an adjective in this sentence, its sense must be `adj.` even though the base form is a verb.
5. `meaning_in_context`: one short Chinese sentence telling what the selected text means right here.
6. Never invent a meaning the word does not have. Keep every string short — no explanations, no extra keys.

## Output schema (JSON)
{schema}

## Input
Selected text: {word}
Sentence it came from: {context}
Learner CEFR level: {cefr_level}

## Answer
Return a single JSON object matching the schema above. No markdown fences, no extra commentary.