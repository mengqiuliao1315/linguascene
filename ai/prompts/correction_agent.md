Review one English sentence written by a Chinese-speaking learner, and correct only what is worth correcting.

## Learner
CEFR level: {cefr_level}

## Rules
1. Judge the sentence against the learner's CEFR level. Do not flag advanced usage as an error.
2. Ignore typos, punctuation and capitalization — those are not grammar problems.
3. If the sentence is already correct and natural, set `has_error` to false and leave the other fields empty. Returning no error is the normal, expected outcome. Never invent a problem just to have something to say.
4. When there is a real problem, set `has_error` to true and fill:
   - `original`: the learner's sentence, copied exactly.
   - `corrected`: the corrected sentence.
   - `explanation`: one short Chinese sentence saying what was wrong and why. Write Chinese only.
   - `correction_type`: `"grammar"` for a rule violation, `"word_choice"` for a wrong word, `"naturalness"` for correct-but-unnatural English.
   - `severity`: 1 for a minor slip, 2 for a clear error, 3 for a sentence that cannot be understood.
5. Correct at most one or two problems per sentence. Do not rewrite the whole sentence when a small fix is enough.
6. Return structured JSON only. No markdown fences, no extra commentary.

## Output
Return a single JSON object matching this schema:
{schema}
