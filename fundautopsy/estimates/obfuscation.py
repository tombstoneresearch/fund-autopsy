"""Fund filing obfuscation scoring.

Inspired by deHaan, Hafzalla, Xue, and Zhang (2021) "Obfuscation in
Mutual Funds" which demonstrated that high-fee funds deliberately
increase narrative complexity to obscure costs from investors.

This module scores fund filings on readability and structural complexity
to detect intentional obfuscation. It does not require external NLP
libraries — all metrics are computed from raw text using standard
readability formulas.

Scoring dimensions:
  1. Readability (Flesch-Kincaid, Gunning Fog) — lower = harder to read
  2. Document length — longer filings correlate with higher fees
  3. Fee table complexity — nested tables, footnotes, cross-references
  4. Disclosure fragmentation — how spread out cost info is across pages
  5. Passive voice density — deliberate distancing from fee disclosures

Academic references:
  - deHaan et al. (2021) "Obfuscation in Mutual Funds" (JAR)
  - Li (2008) "Annual Report Readability, Earnings, and Stock Returns" (JAE)
  - Loughran & McDonald (2014) "Measuring Readability in Financial Disclosures" (JF)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ObfuscationScore:
    """Obfuscation assessment for a fund's filings."""

    # Overall score: 0 (crystal clear) to 100 (maximum obfuscation)
    overall_score: float = 0.0
    grade: str = ""  # A (clear) through F (obfuscated)

    # Component scores (each 0-100)
    readability_score: float = 0.0
    length_score: float = 0.0
    complexity_score: float = 0.0
    fragmentation_score: float = 0.0
    passive_voice_score: float = 0.0

    # Raw metrics
    flesch_kincaid_grade: float = 0.0
    gunning_fog_index: float = 0.0
    word_count: int = 0
    sentence_count: int = 0
    avg_sentence_length: float = 0.0
    avg_word_syllables: float = 0.0
    passive_voice_pct: float = 0.0
    footnote_count: int = 0
    cross_reference_count: int = 0
    fee_table_nesting_depth: int = 0

    methodology: str = ""


# ── Text analysis utilities ──────────────────────────────────────────────────

def _count_syllables(word: str) -> int:
    """Estimate syllable count using the vowel-group method."""
    word = word.lower().strip()
    if not word:
        return 0
    if len(word) <= 3:
        return 1

    # Count vowel groups
    vowels: str = "aeiouy"
    count: int = 0
    prev_vowel: bool = False
    for char in word:
        is_vowel: bool = char in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel

    # Adjustments
    if word.endswith("e") and count > 1:
        count -= 1
    if word.endswith("le") and len(word) > 2 and word[-3] not in vowels:
        count += 1
    if count == 0:
        count = 1

    return count


def _is_complex_word(word: str) -> bool:
    """A word is 'complex' for Gunning Fog if it has 3+ syllables."""
    return _count_syllables(word) >= 3


def _detect_passive_voice(sentence: str) -> bool:
    """Heuristic detection of passive voice constructions."""
    # Be verb followed by past participle or -ing form
    # Common patterns:
    #  - "was bought", "were disclosed", "is reported"
    #  - "is being managed", "are being tracked"
    #  - "was managed", "are tracked"
    passive_patterns = [
        # Standard forms: be + past participle (regular and irregular)
        r'\b(?:is|are|was|were|been|be)\s+(?:\w+ed|bought|sold|made|put|set|held|taken|given|sent|shown)\b',
        # Present participle forms
        r'\b(?:is|are|was|were|been|being|be)\s+being\s+\w+',
        # Negative forms
        r'\b(?:is|are|was|were)\s+not\s+(?:\w+ed|bought|sold|made|put|set|held|taken|given|sent|shown)\b',
    ]
    for pattern in passive_patterns:
        if re.search(pattern, sentence, re.IGNORECASE):
            return True
    return False


# ── Readability formulas ─────────────────────────────────────────────────────

def _flesch_kincaid_grade(
    total_words: int, total_sentences: int, total_syllables: int
) -> float:
    """Flesch-Kincaid Grade Level.

    Higher = harder to read. Financial filings typically score 14-20.
    """
    if total_sentences == 0 or total_words == 0:
        return 0.0
    result: float = (
        0.39 * (total_words / total_sentences) +
        11.8 * (total_syllables / total_words) -
        15.59
    )
    return result


def _gunning_fog(
    total_words: int, total_sentences: int, complex_words: int
) -> float:
    """Gunning Fog Index.

    Higher = harder to read. Typical financial docs: 16-22.
    """
    if total_sentences == 0 or total_words == 0:
        return 0.0
    result: float = 0.4 * (
        (total_words / total_sentences) +
        100 * (complex_words / total_words)
    )
    return result


# ── Scoring functions ────────────────────────────────────────────────────────

def _score_readability(fk_grade: float, fog: float) -> float:
    """Convert readability metrics to 0-100 obfuscation score.

    Baseline: A clear fund prospectus scores ~12 FK grade.
    Obfuscated filings score 18+.
    """
    avg: float = (fk_grade + fog) / 2
    # Map: 10 -> 0, 14 -> 25, 18 -> 75, 22+ -> 100
    score: float = max(0, min(100, (avg - 10) * 8.33))
    return round(score, 1)


def _score_length(word_count: int) -> float:
    """Score based on document length.

    deHaan et al. found that longer filings correlate with higher fees.
    A typical 497K is 2,000-5,000 words. SAIs can be 50,000+.
    """
    # Map: <3000 -> 0, 5000 -> 20, 15000 -> 50, 30000+ -> 100
    if word_count < 3000:
        return 0.0
    score: float = min(100, (word_count - 3000) / 270)
    return round(score, 1)


def _score_complexity(
    footnote_count: int,
    cross_ref_count: int,
    nesting_depth: int,
) -> float:
    """Score structural complexity of fee disclosures."""
    # Each dimension contributes up to ~33 points
    footnote_score: float = min(33, footnote_count * 3.3)
    xref_score: float = min(33, cross_ref_count * 5.5)
    nesting_score: float = min(34, nesting_depth * 11)
    return round(footnote_score + xref_score + nesting_score, 1)


def _score_passive_voice(passive_pct: float) -> float:
    """Score passive voice usage.

    Academic writing averages ~15%. Obfuscated financial disclosures
    often exceed 30%.
    """
    # Map: <10% -> 0, 15% -> 20, 25% -> 60, 35%+ -> 100
    score: float = max(0, min(100, (passive_pct - 10) * 4))
    return round(score, 1)


def _assign_grade(score: float) -> str:
    """Convert overall score to letter grade."""
    if score < 20:
        return "A"
    elif score < 35:
        return "B"
    elif score < 50:
        return "C"
    elif score < 70:
        return "D"
    else:
        return "F"


# ── Main scoring function ───────────────────────────────────────────────────

def score_obfuscation(
    text: str,
    html: str | None = None,
) -> ObfuscationScore:
    """Score a fund filing's obfuscation level.

    Args:
        text: Clean text content of the filing (HTML stripped).
        html: Optional raw HTML for structural analysis (footnotes, tables).

    Returns:
        ObfuscationScore with component and overall scores.
    """
    result = ObfuscationScore()

    if not text or len(text) < 20:
        result.methodology = "Insufficient text for analysis."
        return result

    # Tokenize
    sentences: list[str] = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip() and len(s.strip()) > 10]
    words: list[str] = [w for w in re.findall(r'\b[a-zA-Z]+\b', text) if len(w) > 1]

    if not sentences or not words:
        return result

    result.word_count = len(words)
    result.sentence_count = len(sentences)
    result.avg_sentence_length = len(words) / len(sentences)

    # Syllable analysis
    total_syllables: int = sum(_count_syllables(w) for w in words)
    complex_words: int = sum(1 for w in words if _is_complex_word(w))
    result.avg_word_syllables = total_syllables / len(words) if words else 0

    # Readability
    result.flesch_kincaid_grade = round(
        _flesch_kincaid_grade(len(words), len(sentences), total_syllables), 1
    )
    result.gunning_fog_index = round(
        _gunning_fog(len(words), len(sentences), complex_words), 1
    )
    result.readability_score = _score_readability(
        result.flesch_kincaid_grade, result.gunning_fog_index
    )

    # Length
    result.length_score = _score_length(len(words))

    # Passive voice
    passive_count: int = sum(1 for s in sentences if _detect_passive_voice(s))
    result.passive_voice_pct = round(passive_count / len(sentences) * 100, 1)
    result.passive_voice_score = _score_passive_voice(result.passive_voice_pct)

    # Structural complexity (from HTML if available)
    if html:
        result.footnote_count = len(re.findall(
            r'(?i)(?:\(\d+\)|\*{1,3}|†|‡)\s*(?:see|refer|as\s+described)',
            html
        ))
        result.cross_reference_count = len(re.findall(
            r'(?i)(?:see\s+"|refer\s+to\s+"|as\s+(?:described|discussed)\s+(?:in|under))',
            html
        ))
        # Table nesting depth
        nesting: int = 0
        depth: int = 0
        for m in re.finditer(r'</?table[^>]*>', html, re.IGNORECASE):
            if m.group().startswith('</'):
                depth -= 1
            else:
                depth += 1
                nesting = max(nesting, depth)
        result.fee_table_nesting_depth = nesting

    result.complexity_score = _score_complexity(
        result.footnote_count,
        result.cross_reference_count,
        result.fee_table_nesting_depth,
    )

    # Fragmentation (how far apart fee-related terms are in the document)
    fee_mentions: list[int] = [m.start() for m in re.finditer(
        r'(?i)(?:expense|fee|commission|cost|charge)', text
    )]
    if len(fee_mentions) > 2:
        spread: int = fee_mentions[-1] - fee_mentions[0]
        doc_len: int = len(text)
        fragmentation_ratio: float = spread / doc_len if doc_len > 0 else 0
        result.fragmentation_score = round(min(100, fragmentation_ratio * 120), 1)

    # Overall score: weighted average
    result.overall_score = round(
        result.readability_score * 0.30 +
        result.length_score * 0.15 +
        result.complexity_score * 0.20 +
        result.fragmentation_score * 0.15 +
        result.passive_voice_score * 0.20,
        1
    )

    result.grade = _assign_grade(result.overall_score)

    result.methodology = (
        f"Obfuscation score based on Flesch-Kincaid ({result.flesch_kincaid_grade}), "
        f"Gunning Fog ({result.gunning_fog_index}), document length ({result.word_count} words), "
        f"structural complexity ({result.footnote_count} footnotes, "
        f"{result.cross_reference_count} cross-references), "
        f"and passive voice ({result.passive_voice_pct:.0f}%). "
        f"Inspired by deHaan et al. (2021) 'Obfuscation in Mutual Funds.'"
    )

    return result
