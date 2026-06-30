"""
scorer.py — Confidence scoring and transparency label generation.

Combines LLM and stylometric signals into a single calibrated confidence score,
then maps that score to one of three transparency label variants.

Thresholds (from planning.md):
  0.00 – 0.35 → likely_human    → "✅ Appears Human-Written"
  0.36 – 0.64 → uncertain       → "🔍 Attribution Uncertain"
  0.65 – 1.00 → likely_ai       → "⚠️ AI-Generated Content Likely"

Weighting:
  Standard (≥100 words): LLM 60%, Stylometrics 40%
  Short text (<100 words): LLM 80%, Stylometrics 20%
  (Stylometrics are unreliable on short texts)

False-positive asymmetry: the threshold to reach "likely_ai" is 0.65, not 0.50.
This means the uncertain band is intentionally wide — we'd rather be uncertain
than falsely flag a human writer's work.
"""


def combine_scores(llm_score: float, stylo_score: float, word_count: int) -> tuple[float, str]:
    """
    Combine LLM and stylometric scores into a single confidence score.

    Args:
        llm_score: 0–1, higher = more AI-like (from LLM signal)
        stylo_score: 0–1, higher = more AI-like (from stylometric signal)
        word_count: number of words in the submitted text

    Returns:
        (confidence: float 0–1, attribution: str)
        attribution is one of: "likely_ai", "uncertain", "likely_human"
    """
    if word_count < 100:
        llm_weight = 0.80
        stylo_weight = 0.20
    else:
        llm_weight = 0.60
        stylo_weight = 0.40

    confidence = (llm_weight * llm_score) + (stylo_weight * stylo_score)
    confidence = round(max(0.0, min(1.0, confidence)), 4)

    if confidence <= 0.35:
        attribution = "likely_human"
    elif confidence <= 0.64:
        attribution = "uncertain"
    else:
        attribution = "likely_ai"

    return confidence, attribution


def generate_label(confidence: float) -> str:
    """
    Map a confidence score to one of three transparency label variants.
    Returns the full label text as it would be shown to a reader.
    """
    pct = round(confidence * 100)

    if confidence <= 0.35:
        return (
            f"✅ Appears Human-Written\n"
            f"Our analysis found strong signals that this content was written by a person. "
            f"This label is based on automated analysis and may not be perfect.\n"
            f"Confidence: {pct}% human"
        )
    elif confidence <= 0.64:
        return (
            f"🔍 Attribution Uncertain\n"
            f"Our analysis found mixed signals — this content could be human-written or AI-assisted. "
            f"We don't have enough confidence to make a definitive call. "
            f"If you created this content yourself, no action is needed.\n"
            f"Confidence: {pct}% AI likelihood"
        )
    else:
        return (
            f"⚠️ AI-Generated Content Likely\n"
            f"Our analysis found strong signals that this content was generated with AI assistance. "
            f"This label is based on automated analysis and may not be perfect. "
            f"If you created this content yourself, you can submit an appeal.\n"
            f"Confidence: {pct}% AI likelihood"
        )
