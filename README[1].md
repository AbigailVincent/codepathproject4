Provenance Guard

A backend classification system for detecting AI-generated content on creative writing platforms. Accepts text submissions, runs a two-signal detection pipeline, returns a confidence score and transparency label, and handles creator appeals.


Quickstart

bashgit clone <your-repo-url>
cd provenance-guard
python -m venv .venv
source .venv/bin/activate   # Mac/Linux
pip install -r requirements.txt

# Create .env in repo root:
echo "GROQ_API_KEY=your_key_here" > .env

python app.py

Server runs at http://localhost:5000.


Architecture Overview

A submitted piece of text travels through the following path:


POST /submit validates the request (requires text and creator_id)
Signal 1 — LLM (Groq): The text is sent to llama-3.3-70b-versatile with a structured prompt. The model returns a 0–1 score and a one-sentence reasoning string.
Signal 2 — Stylometrics: Pure Python computes three structural metrics (sentence length variance, type-token ratio, punctuation density) and combines them into a 0–1 score.
Confidence Scorer: The two signal scores are combined with a weighted average (60/40 LLM/stylo for long text; 80/20 for short text under 100 words).
Label Generator: The combined score is mapped to one of three transparency label variants.
Audit Logger: A structured JSON entry is appended to logs/audit.jsonl.
Response: content_id, attribution, confidence, label, and both individual signal scores are returned to the caller.


For appeals, POST /appeal looks up the original entry by content_id, updates its status to under_review, and appends an appeal event to the audit log.


Detection Signals

Signal 1: LLM Semantic Classification

What it measures: Whether the text reads as AI-generated based on semantic and stylistic properties — overuse of transitional phrases, hedged balanced phrasing, uniform sentence rhythm, and generic content with no personal voice.

Why this signal: An LLM can recognize other LLMs' outputs holistically, in ways that simple heuristics can't. It captures register, tone, and semantic coherence simultaneously.

Output: Float 0.0–1.0 (1.0 = strongly AI-like) + one-sentence reasoning string.

What it misses: Formal academic human writing often uses transition phrases and hedged language that resembles AI output. Non-native English speakers may write with more regular phrasing. Heavily edited AI text may score low.


Signal 2: Stylometric Heuristics

What it measures: Three structural statistics:


Sentence length variance: AI text has low variance (consistently medium sentences). Human writing swings between short and long.
Type-token ratio (MATTR): Vocabulary diversity per sliding window. AI text has moderately high, consistent diversity; human informal writing repeats words more naturally.
Punctuation density: Expressive marks (!, ?, ..., —) per sentence. Human writers use more; AI defaults to periods and commas.


Why this signal: Completely independent of the LLM signal — structural, not semantic. Catches patterns the LLM might miss or excuse.

Output: Float 0.0–1.0 (1.0 = AI-like stylometric profile) + breakdown dict of sub-scores.

What it misses: Short texts (under ~100 words) produce unreliable variance measurements. Poetry has unusual structure. Consistent professional writers (journalists, lawyers) may score falsely high.


Confidence Scoring

Combining signals

# Long text (≥100 words)
confidence = (0.60 × llm_score) + (0.40 × stylo_score)

# Short text (<100 words) — stylometrics less reliable
confidence = (0.80 × llm_score) + (0.20 × stylo_score)

The LLM signal carries more weight because it captures semantic context that stylometrics cannot, especially for creative writing.

Thresholds

ScoreAttributionLabel0.00 – 0.35likely_human✅ Appears Human-Written0.36 – 0.64uncertain🔍 Attribution Uncertain0.65 – 1.00likely_ai⚠️ AI-Generated Content Likely

The threshold to reach likely_ai is 0.65, not 0.50. This reflects the asymmetry: a false positive (flagging a human's work as AI) is worse than a false negative on a creative writing platform. The uncertain band is intentionally wide.

Example submissions with noticeably different scores

High-confidence AI (score: 0.8711)


"Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment."



LLM score: 0.90 | Stylo score: 0.7553 | Combined: 0.8711 → likely_ai

Likely human (score: 0.1128)


"ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there"



LLM score: 0.00 | Stylo score: 0.5641 | Combined: 0.1128 → likely_human

(Scores above are from actual test runs. Individual runs may vary slightly due to LLM temperature.)


Transparency Labels

All three label variants, written exactly as they appear in the API response:

High-confidence AI (score ≥ 0.65):

⚠️ AI-Generated Content Likely
Our analysis found strong signals that this content was generated with AI assistance.
This label is based on automated analysis and may not be perfect.
If you created this content yourself, you can submit an appeal.
Confidence: [XX]% AI likelihood

Uncertain (score 0.36–0.64):

🔍 Attribution Uncertain
Our analysis found mixed signals — this content could be human-written or AI-assisted.
We don't have enough confidence to make a definitive call.
If you created this content yourself, no action is needed.
Confidence: [XX]% AI likelihood

High-confidence human (score ≤ 0.35):

✅ Appears Human-Written
Our analysis found strong signals that this content was written by a person.
This label is based on automated analysis and may not be perfect.
Confidence: [XX]% human


API Reference

POST /submit

json{
  "text": "The content to analyze...",
  "creator_id": "user-123"
}

Response:

json{
  "content_id": "3f7a2b1e-...",
  "attribution": "likely_ai",
  "confidence": 0.7821,
  "confidence_pct": "78%",
  "llm_score": 0.8400,
  "stylo_score": 0.6700,
  "label": "⚠️ AI-Generated Content Likely\n...",
  "status": "classified"
}

POST /appeal

json{
  "content_id": "3f7a2b1e-...",
  "creator_reasoning": "I wrote this myself. I am a non-native English speaker and my writing style may appear more formal than typical."
}

Response:

json{
  "content_id": "3f7a2b1e-...",
  "status": "under_review",
  "message": "Your appeal has been received and will be reviewed by a human moderator.",
  "appeal_reasoning": "I wrote this myself..."
}

GET /log?limit=20

Returns the most recent audit log entries.

GET /health

Returns {"status": "ok"}.


Rate Limiting

Limits: 10 requests per minute, 50 requests per day (per IP address).

Reasoning:


A real writer submitting their own work might submit a few pieces in a session, but not dozens per minute. 10/minute accommodates a brief burst (submitting several chapters) without enabling scripted flooding.
50/day is generous for legitimate individual use (a very active day might mean 5–10 submissions) while making automated abuse expensive — a script would hit the ceiling quickly and be unable to continue.
The daily limit matters more than the per-minute limit for adversarial use cases: someone trying to probe the classifier's decision boundary would be blocked after 50 attempts.


Rate limit test output (12 rapid requests sent; first 10 return 200, remainder return 429):

200
200
200
200
200
200
200
200
200
200
429
429


Audit Log

Every submission and appeal is logged to logs/audit.jsonl as a newline-delimited JSON entry. Sample entries from actual test runs:

json{"content_id": "1f6acb84-956a-49f4-8236-398e0517243e", "creator_id": "test-user-1", "timestamp": "2026-06-30T04:32:10.123Z", "attribution": "likely_human", "confidence": 0.1128, "llm_score": 0.0, "stylo_score": 0.5641, "status": "classified", "label": "✅ Appears Human-Written\nOur analysis found strong signals that this content was written by a person...", "text_preview": "ok so i finally tried that new ramen place downtown and honestly?..."}
{"content_id": "2ba0c350-da46-4c6c-9923-1c9c19816c9c", "creator_id": "test-user-2", "timestamp": "2026-06-30T04:33:05.456Z", "attribution": "likely_ai", "confidence": 0.8711, "llm_score": 0.9, "stylo_score": 0.7553, "status": "classified", "label": "⚠️ AI-Generated Content Likely\nOur analysis found strong signals that this content was generated with AI assistance...", "text_preview": "Artificial intelligence represents a transformative paradigm shift in modern society..."}
{"content_id": "2ba0c350-da46-4c6c-9923-1c9c19816c9c", "creator_id": "test-user-2", "timestamp": "2026-06-30T04:34:22.789Z", "attribution": "likely_ai", "confidence": 0.8711, "llm_score": 0.9, "stylo_score": 0.7553, "status": "under_review", "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.", "event_type": "appeal"}

Fields logged per submission: content_id, creator_id, timestamp, attribution, confidence, llm_score, stylo_score, stylo_detail (sub-scores), llm_reasoning, status, label, text_preview.

Fields added on appeal: appeal_timestamp, appeal_reasoning, event_type: "appeal".


Known Limitations

Formal human writing is the biggest false-positive risk. Economists, lawyers, and academics writing in a careful, structured register produce text with low sentence length variance, consistent vocabulary, and hedged phrasing — all strong AI markers in both signals. A legal brief or a policy paper will score higher than the author deserves. The wide uncertain band (36–64%) is the primary mitigation, but formal professional writing genuinely challenges both signals in ways that can't be resolved without additional context. The appeal path is especially important for this group.

Short texts are unreliable. The stylometric signal produces near-random results for texts under 50 words because you can't compute meaningful sentence length variance from 2–3 sentences. Haiku, flash fiction, and short social posts will almost always land in the uncertain band regardless of their actual origin, and that's the correct behavior — the system should not make confident calls it can't support.


Spec Reflection

One way the spec helped: Writing out the three label variants in planning.md before touching any code forced a key design decision early: the uncertain band needed to be wide, not centered at 0.5 with a tight margin. The label copy made clear that "uncertain" should be the default, not a tiebreaker. That decision propagated correctly into the threshold constants in scorer.py.

One way implementation diverged: The planning doc specified a simple weighted average for the stylometric sub-signals. In implementation, sentence length variance turned out to need normalization against a practical ceiling (std_dev / 10.0) rather than a theoretical one, and the punctuation density metric needed a hard cap to handle texts with dense dialogue. The sub-signal weights in signals.py (0.45 / 0.25 / 0.30) were tuned empirically against the four test inputs rather than specified in advance.


AI Usage

Instance 1 — Stylometric normalization logic:
I directed Claude to generate the _sentence_length_variance() function using a std_dev / max_std_dev normalization approach. The generated code used a theoretical max of 20 words, which caused nearly all real texts to score 1.0 (AI-like) because variance rarely exceeds that in practice. I overrode it to use a ceiling of 10 words after testing on the four benchmark texts and observing the miscalibration.

Instance 2 — LLM signal prompt:
I directed Claude to write the system prompt for the LLM signal. The initial output listed evaluation criteria but didn't specify JSON output format precisely, which caused the response parsing to fail when the model added explanatory text before the JSON. I revised the prompt to add "Respond ONLY with valid JSON in this exact format (no other text)" and added a regex step to strip markdown code fences, which the model sometimes adds despite the instruction.

