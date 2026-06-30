# Provenance Guard — Planning Document

> Written before implementation, per project requirements.

---

## Problem Statement

Creative platforms face a growing attribution problem: AI-generated content submitted as original human work. Provenance Guard is a backend classification system that analyzes submitted text, scores confidence in an AI-vs-human attribution, surfaces a plain-language transparency label, and gives creators a fair path to appeal misclassifications.

---

## Detection Signals

### Signal 1: LLM Semantic Classification (Groq)

**What it measures:** Whether the text reads as AI-generated based on semantic and stylistic coherence — phrasing patterns, topic transitions, hedging language, and overall register. An LLM is well-positioned to recognize other LLMs' outputs because they share training data and generation patterns.

**Output format:** A float score from 0.0 to 1.0, where 1.0 = high confidence AI-generated, 0.0 = high confidence human-written. The model is prompted to return a structured JSON response with a `score` and a `reasoning` field.

**Why it differs between human and AI writing:** AI-generated text tends to overuse transition phrases ("Furthermore," "It is important to note"), hedging ("it is worth considering"), and balanced-paragraph structures. Human writing is messier — it wanders, uses colloquialisms, and reflects individual voice. The LLM captures this holistically.

**Blind spots:** Highly edited AI text that a human has rewritten substantially. Formal academic human writing that happens to use AI-like phrasing. Non-native English speakers whose writing is more grammatically regular than typical native speakers. The LLM may also be biased toward English writing conventions.

---

### Signal 2: Stylometric Heuristics

**What it measures:** Statistical structural properties of the text that differ between human and AI writing. AI text is statistically more uniform than human text. Three metrics:

1. **Sentence length variance** — AI text has low variance in sentence length (consistently medium-length sentences). Human writing swings between short punchy sentences and long sprawling ones.
2. **Type-token ratio (TTR)** — vocabulary diversity: unique words / total words. AI text scores higher (more varied vocabulary) on longer texts; human informal writing often repeats words naturally.
3. **Punctuation density** — exclamation points, em-dashes, ellipses per sentence. Human writers use these far more than AI, which defaults to periods and commas.

**Output format:** A float score from 0.0 to 1.0, where 1.0 = strong AI stylometric signature, 0.0 = strong human stylometric signature.

**Why it differs:** AI models optimize for readability and completeness, producing text with consistent pacing. Human writing reflects cognitive rhythm — short when making a quick point, long when working through an idea.

**Blind spots:** Short texts (under ~100 words) produce unreliable variance measurements. Poetry has unusual sentence structure that may score unpredictably. Writers who have been trained to write consistently (journalists, lawyers) may score falsely high on AI likelihood.

---

## Confidence Scoring and Uncertainty Representation

### Combining the signals

Both signals produce a 0.0–1.0 score where higher = more likely AI. I combine them with a **weighted average** that favors the LLM signal slightly, since it captures semantic context that stylometrics can't:

```
combined = (0.60 × llm_score) + (0.40 × stylo_score)
```

The LLM weight is higher because it is the more reliable signal for creative text specifically. Stylometrics matter more for prose than for poetry, so for texts under 100 words, the stylo weight is reduced to 0.20 and the LLM weight raised to 0.80.

### What scores mean

| Score range | Interpretation | Label tier |
|---|---|---|
| 0.00 – 0.35 | Likely human-written | Human (high confidence) |
| 0.36 – 0.64 | Uncertain — could be either | Uncertain |
| 0.65 – 1.00 | Likely AI-generated | AI (high confidence) |

A score of 0.60 means: the system sees some AI-like signals but not enough to call it confidently. It should produce an "Uncertain" label — not a positive AI attribution. This asymmetry is intentional: false positives (calling a human's work AI) are worse than false negatives on a creative platform.

### False-positive asymmetry

The thresholds are deliberately conservative. A 65% threshold to reach the "Likely AI" label means the system needs meaningful agreement from both signals before making a definitive call. The uncertain band (36–64%) is intentionally wide.

---

## Transparency Label Design

Three variants, written as they will appear in the API response and any UI:

**High-confidence AI (score ≥ 0.65):**
```
⚠️ AI-Generated Content Likely
Our analysis found strong signals that this content was generated with AI assistance.
This label is based on automated analysis and may not be perfect.
If you created this content yourself, you can submit an appeal.
Confidence: [XX]%
```

**Uncertain (score 0.36–0.64):**
```
🔍 Attribution Uncertain
Our analysis found mixed signals — this content could be human-written or AI-assisted.
We don't have enough confidence to make a definitive call.
If you created this content yourself, no action is needed.
Confidence: [XX]%
```

**High-confidence human (score ≤ 0.35):**
```
✅ Appears Human-Written
Our analysis found strong signals that this content was written by a person.
This label is based on automated analysis and may not be perfect.
Confidence: [XX]%
```

---

## Appeals Workflow

**Who can appeal:** Any creator who submitted content (identified by `creator_id`). No authentication beyond `creator_id` for this implementation.

**What they provide:**
- `content_id` — the ID returned at submission time
- `creator_reasoning` — a plain-text explanation of why they believe the classification is wrong

**What happens on appeal:**
1. The system looks up the original submission record by `content_id`
2. The record's `status` field is updated from `"classified"` to `"under_review"`
3. An appeal entry is appended to the audit log with: original classification, confidence score, creator reasoning, and appeal timestamp
4. A human reviewer sees the original text (if stored), both signal scores, and the creator's reasoning
5. The API returns a confirmation with the new status

**What is not implemented:** Automated re-classification, reviewer authentication, or resolution workflow. Appeals are queued for human review only.

---

## Anticipated Edge Cases

1. **Formal human writing (academic, legal):** An economist or lawyer writing in a careful, structured register will trigger high sentence-length consistency and hedged phrasing — both AI markers. The LLM signal may also flag formal prose as AI-like. These writers are the most likely false-positive victims. The wide uncertain band (36–64%) is the primary mitigation.

2. **Short creative texts (haiku, tweets, flash fiction under 50 words):** Stylometric heuristics become statistically unreliable at short lengths — you can't compute meaningful sentence length variance from 3 sentences. The system reduces the stylometric weight for short texts, but the LLM signal alone is also less reliable without enough text to assess. These will almost always land in the uncertain band.

3. **Non-native English speakers:** Writers whose first language isn't English often produce more grammatically regular prose — fewer contractions, more formal phrasing, less idiomatic variation. Both signals may read this as AI-like. The appeal path is especially important for this group.

4. **Lightly edited AI output:** A creator who generates a draft with AI and then edits it substantially occupies genuine gray territory — it's neither fully AI nor fully human. The uncertain band is the correct outcome for this case, not a definitive label either way.

---

## Architecture

### Submission Flow

```
POST /submit
  │
  ├─── [Validate input] ──── missing fields → 400 error
  │         │
  │    raw text + creator_id
  │         │
  ├─── [Signal 1: LLM] ─────── Groq API call → llm_score (0.0–1.0)
  │         │
  ├─── [Signal 2: Stylometrics] ── pure Python → stylo_score (0.0–1.0)
  │         │
  ├─── [Confidence Scorer] ─── weighted average → combined_score (0.0–1.0)
  │         │
  ├─── [Label Generator] ──── score → label text (one of 3 variants)
  │         │
  ├─── [Audit Logger] ──────── write structured entry → audit log (JSONL)
  │         │
  └─── [Response] ──────────── content_id, attribution, confidence, label → caller
```

### Appeal Flow

```
POST /appeal
  │
  ├─── [Validate input] ──── content_id + creator_reasoning required
  │         │
  ├─── [Lookup record] ─────── find original entry by content_id
  │         │
  ├─── [Update status] ─────── "classified" → "under_review"
  │         │
  ├─── [Audit Logger] ──────── append appeal entry to audit log
  │         │
  └─── [Response] ──────────── confirmation + new status → caller
```

### Supporting Endpoints

```
GET /log  →  return last N audit log entries as JSON
GET /health  →  sanity check
```

---

## AI Tool Plan

### M3 — Submission endpoint + LLM signal
- **Provide to AI:** Detection signals section + architecture diagram
- **Ask for:** Flask app skeleton with POST /submit stub + `llm_signal()` function that calls Groq and returns a 0–1 score
- **Verify:** Call `llm_signal()` directly on 2–3 test inputs; confirm scores are in [0,1] and vary; confirm Flask route accepts JSON and returns `content_id`

### M4 — Stylometric signal + confidence scoring
- **Provide to AI:** Detection signals section + uncertainty representation section + architecture diagram
- **Ask for:** `stylo_signal()` function computing sentence variance + TTR + punctuation density, and `combine_scores()` function implementing the weighted average with short-text adjustment
- **Verify:** Run all 4 test inputs from the spec; confirm clearly-AI text scores ≥ 0.65 and clearly-human text scores ≤ 0.35; print both individual scores to confirm they diverge appropriately

### M5 — Production layer
- **Provide to AI:** Label variants section + appeals workflow section + architecture diagram
- **Ask for:** `generate_label()` function mapping score to label text + POST /appeal endpoint
- **Verify:** Test all three label variants are reachable with scores 0.20, 0.50, 0.80; test appeal endpoint updates status and appears in GET /log with `under_review` status

---

## Stretch Features (if pursued)

- [ ] Ensemble detection (3rd signal: punctuation/emoji pattern analysis)
- [ ] Provenance certificate (verified human badge)
- [ ] Analytics dashboard
- [ ] Multi-modal support

> Update this section before implementing any stretch feature.
