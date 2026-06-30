"""
signals.py — Two independent detection signals for Provenance Guard.

Signal 1: LLM Semantic Classification (Groq)
  Asks the model to score whether the text reads as AI-generated.
  Output: (score: float 0–1, reasoning: str)

Signal 2: Stylometric Heuristics
  Computes sentence length variance, type-token ratio, and punctuation
  density. Pure Python, no external libraries.
  Output: (score: float 0–1, detail: dict)
"""

import os
import re
import json
import math
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
LLM_MODEL = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Signal 1: LLM Semantic Classification
# ---------------------------------------------------------------------------

_LLM_SYSTEM = """You are an expert at distinguishing AI-generated text from human-written text.
Analyze the provided text and assess how likely it is to be AI-generated.

Consider:
- Overuse of transition phrases ("Furthermore," "It is important to note," "Additionally")
- Hedging and balanced phrasing typical of AI ("while X has benefits, it also has drawbacks")
- Uniform sentence rhythm and length
- Generic, non-specific content with no personal voice
- Absence of colloquialisms, typos, or idiosyncratic phrasing
- Overly comprehensive coverage of a topic (AI tends to cover all angles)

Human writing tends to be: messier, more specific, more personal, with irregular rhythm,
genuine opinions, and natural vocabulary variation.

Respond ONLY with valid JSON in this exact format (no other text):
{
  "score": <float between 0.0 and 1.0, where 1.0 = definitely AI, 0.0 = definitely human>,
  "reasoning": "<one concise sentence explaining the key signal>"
}"""


def llm_signal(text: str) -> tuple[float, str]:
    """
    Call Groq LLM to assess whether text is AI-generated.
    Returns (score: float 0–1, reasoning: str).
    On failure, returns (0.5, "LLM signal unavailable") to avoid skewing results.
    """
    try:
        response = _client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": f"Analyze this text:\n\n{text}"},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)
        score = float(parsed.get("score", 0.5))
        score = max(0.0, min(1.0, score))  # clamp
        reasoning = str(parsed.get("reasoning", ""))
        return score, reasoning

    except Exception as e:
        return 0.5, f"LLM signal error: {type(e).__name__}"


# ---------------------------------------------------------------------------
# Signal 2: Stylometric Heuristics
# ---------------------------------------------------------------------------

def _sentence_length_variance(sentences: list[str]) -> float:
    """
    Normalized sentence length variance.
    AI text: low variance (consistently medium sentences).
    Human text: high variance (short punchy + long sprawling).
    Returns a score 0–1 where 1 = AI-like (low variance).
    """
    if len(sentences) < 2:
        return 0.5  # can't measure with 1 sentence

    lengths = [len(s.split()) for s in sentences if s.strip()]
    if not lengths:
        return 0.5

    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    std_dev = math.sqrt(variance)

    # High std_dev = human-like. Normalize: std_dev of ~8 words = very human.
    # Score: 1 = low variance (AI), 0 = high variance (human)
    normalized = max(0.0, 1.0 - (std_dev / 10.0))
    return round(min(1.0, normalized), 4)


def _type_token_ratio(words: list[str]) -> float:
    """
    Vocabulary diversity: unique_words / total_words.
    Higher TTR = more diverse vocabulary.
    AI text on longer passages tends to have moderate-high TTR (varied but not personal).
    Human informal text has lower TTR (repeats common words).
    Human formal/academic text has high TTR too — this signal is weaker for formal writing.

    We use a windowed TTR (MATTR) to reduce length bias.
    Returns score 0–1 where higher = more AI-like (0.65+ TTR range).
    """
    if len(words) < 10:
        return 0.5

    window_size = min(50, len(words))
    ttrs = []
    for i in range(0, len(words) - window_size + 1, window_size // 2 or 1):
        window = words[i:i + window_size]
        if window:
            ttr = len(set(w.lower() for w in window)) / len(window)
            ttrs.append(ttr)

    if not ttrs:
        return 0.5

    avg_ttr = sum(ttrs) / len(ttrs)

    # TTR: very casual human ~0.45-0.55, formal human ~0.65-0.75, AI ~0.60-0.72
    # This signal is weaker — we map it to a mild AI indicator above 0.60
    # Score: 0 = low TTR (casual human), 1 = high TTR (could be AI or formal human)
    score = max(0.0, min(1.0, (avg_ttr - 0.40) / 0.40))
    return round(score, 4)


def _punctuation_score(text: str, sentences: list[str]) -> float:
    """
    Human writers use more expressive punctuation: !, ?, ..., —, em-dash.
    AI tends to stick to periods and commas.
    Returns score 0–1 where 1 = AI-like (low expressive punctuation).
    """
    expressive = len(re.findall(r'[!?]|\.{2,}|—|–', text))
    n_sentences = max(1, len(sentences))
    rate = expressive / n_sentences

    # High rate = human. Score: 1 = few expressive marks (AI), 0 = many (human)
    score = max(0.0, 1.0 - min(rate / 2.0, 1.0))
    return round(score, 4)


def stylo_signal(text: str) -> tuple[float, dict]:
    """
    Compute stylometric heuristics.
    Returns (score: float 0–1, detail: dict with individual sub-scores).
    Higher score = more AI-like stylometric profile.
    """
    # Tokenize
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s for s in sentences if s.strip()]
    words = re.findall(r"\b\w+\b", text)

    if len(words) < 10:
        # Too short to measure reliably
        return 0.5, {"note": "text too short for reliable stylometric analysis", "word_count": len(words)}

    sl_var = _sentence_length_variance(sentences)
    ttr = _type_token_ratio(words)
    punct = _punctuation_score(text, sentences)

    # Weighted combination of three sub-signals
    # Sentence variance is most reliable, TTR least reliable
    combined = (0.45 * sl_var) + (0.25 * ttr) + (0.30 * punct)
    combined = round(max(0.0, min(1.0, combined)), 4)

    detail = {
        "sentence_length_variance_score": sl_var,
        "type_token_ratio_score": ttr,
        "punctuation_score": punct,
        "word_count": len(words),
        "sentence_count": len(sentences),
    }

    return combined, detail
