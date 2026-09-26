Analyze this English reading material and turn it into a study aid for a Chinese-speaking learner.

## Material
Learner's CEFR level: {cefr_level}

{content}

## Rules
1. `summary`: one or two sentences in Chinese, capturing the main idea. Write Chinese only.
2. `level`: the CEFR level of this material, judged from its vocabulary and sentence length.
3. `keywords`: 6-10 words a learner at this level would not know or would find useful. Use the base form (lemma) for each `word`. Write `meaning` in Chinese. `example` must be a sentence copied from the material above.
4. `phrases`: fixed collocations and idioms that actually appear in the text. Write `meaning` in Chinese. Leave the list empty when there are none — do not force a match.
5. `grammar_points`: sentence patterns worth learning from this text. Write `explanation` in Chinese.
6. `reading_questions`: 3 comprehension questions in English.
7. `speaking_questions`: 2 discussion questions in English.
8. `writing_task`: one writing prompt in English.
9. Only use vocabulary and structures that actually appear in the material. Do not invent content.
10. Return structured JSON only. No markdown fences, no extra commentary.

## Output
Return a single JSON object matching this schema:
{schema}
