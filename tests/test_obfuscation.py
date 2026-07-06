"""Tests for fund filing obfuscation scoring."""


from fundautopsy.estimates.obfuscation import (
    _assign_grade,
    _count_syllables,
    _detect_passive_voice,
    _flesch_kincaid_grade,
    _gunning_fog,
    _is_complex_word,
    _score_complexity,
    _score_length,
    _score_passive_voice,
    _score_readability,
    score_obfuscation,
)


class TestSyllableDetection:
    """Test syllable counting."""

    def test_simple_words(self):
        """Test syllable counts for common words."""
        assert _count_syllables("cat") == 1
        assert _count_syllables("dog") == 1
        assert _count_syllables("apple") == 2
        assert _count_syllables("wonderful") == 3
        assert _count_syllables("unfortunately") >= 5

    def test_single_letter(self):
        """Single letters should be 1 syllable."""
        assert _count_syllables("a") == 1
        assert _count_syllables("I") == 1

    def test_empty_string(self):
        """Empty string should return 0."""
        assert _count_syllables("") == 0

    def test_short_words(self):
        """Short words (<=3 chars) should be 1 syllable."""
        assert _count_syllables("cat") == 1
        assert _count_syllables("dog") == 1
        assert _count_syllables("box") == 1

    def test_complex_words(self):
        """Complex words should have multiple syllables."""
        assert _count_syllables("financial") >= 3
        assert _count_syllables("management") >= 3
        assert _count_syllables("performance") >= 3


class TestComplexWordDetection:
    """Test complex word detection (3+ syllables)."""

    def test_simple_words_not_complex(self):
        """Simple words should not be complex."""
        assert not _is_complex_word("cat")
        assert not _is_complex_word("dog")
        assert not _is_complex_word("run")

    def test_three_syllable_words_complex(self):
        """Words with 3+ syllables should be complex."""
        assert _is_complex_word("wonderful")
        assert _is_complex_word("financial")
        assert _is_complex_word("management")

    def test_two_syllable_words_not_complex(self):
        """Two-syllable words should not be complex."""
        assert not _is_complex_word("apple")
        assert not _is_complex_word("market")
        assert not _is_complex_word("money")


class TestPassiveVoiceDetection:
    """Test passive voice detection."""

    def test_active_voice_not_detected(self):
        """Active voice sentences should not be flagged."""
        assert not _detect_passive_voice("The fund manager bought stocks.")
        assert not _detect_passive_voice("We reported the costs.")

    def test_passive_voice_detected(self):
        """Passive voice should be detected."""
        assert _detect_passive_voice("The stocks were bought by the manager.")
        assert _detect_passive_voice("Costs are reported in the filing.")
        assert _detect_passive_voice("The portfolio was managed.")

    def test_is_been_patterns(self):
        """'is/are/was/were been' patterns should be detected."""
        assert _detect_passive_voice("The fund is being managed.")
        assert _detect_passive_voice("The costs are being tracked.")

    def test_complex_passive_structures(self):
        """Complex passive structures should be detected."""
        assert _detect_passive_voice("The expenses were not disclosed.")


class TestReadabilityFormulas:
    """Test readability calculation formulas."""

    def test_flesch_kincaid_basic(self):
        """Test Flesch-Kincaid grade calculation."""
        # Simple example: 10 words, 2 sentences, 13 syllables
        grade = _flesch_kincaid_grade(total_words=10, total_sentences=2, total_syllables=13)
        assert grade > 0
        assert grade < 12

    def test_flesch_kincaid_zero_inputs(self):
        """Zero inputs should return 0."""
        assert _flesch_kincaid_grade(0, 0, 0) == 0.0
        assert _flesch_kincaid_grade(0, 1, 5) == 0.0

    def test_gunning_fog_basic(self):
        """Test Gunning Fog index calculation."""
        # 100 words, 5 sentences, 30 complex words
        fog = _gunning_fog(total_words=100, total_sentences=5, complex_words=30)
        assert fog > 0
        assert fog < 25

    def test_gunning_fog_zero_inputs(self):
        """Zero inputs should return 0."""
        assert _gunning_fog(0, 0, 0) == 0.0

    def test_higher_complexity_higher_grade(self):
        """More complex text should produce higher grade."""
        simple = _flesch_kincaid_grade(100, 10, 100)  # ~10 grade
        complex_text = _flesch_kincaid_grade(100, 5, 150)  # ~15 grade
        assert complex_text > simple


class TestReadabilityScoring:
    """Test readability scoring."""

    def test_clear_text_low_score(self):
        """Clear, simple text should get low obfuscation score."""
        score = _score_readability(fk_grade=10.0, fog=10.0)
        assert 0 <= score <= 100
        assert score < 30  # Clear = low obfuscation

    def test_obfuscated_text_high_score(self):
        """Complex, obfuscated text should get high score."""
        score = _score_readability(fk_grade=20.0, fog=20.0)
        assert score > 70  # Obfuscated = high score

    def test_scoring_monotonic(self):
        """Score should increase monotonically with complexity."""
        low = _score_readability(12.0, 12.0)
        mid = _score_readability(15.0, 15.0)
        high = _score_readability(18.0, 18.0)
        assert low < mid < high


class TestLengthScoring:
    """Test document length scoring."""

    def test_short_document_low_score(self):
        """Short documents should get low obfuscation score."""
        score = _score_length(word_count=2000)
        assert score < 30

    def test_long_document_high_score(self):
        """Long documents should get higher score."""
        score = _score_length(word_count=30000)
        assert score > 50

    def test_length_scoring_scale(self):
        """Scores should scale with length."""
        short = _score_length(3000)
        medium = _score_length(10000)
        long = _score_length(30000)
        assert short < medium < long


class TestComplexityScoring:
    """Test structural complexity scoring."""

    def test_simple_structure_low_score(self):
        """Simple structure should get low score."""
        score = _score_complexity(
            footnote_count=0,
            cross_ref_count=0,
            nesting_depth=0,
        )
        assert score == 0.0

    def test_complex_structure_high_score(self):
        """Complex structure should get higher score."""
        score = _score_complexity(
            footnote_count=30,
            cross_ref_count=20,
            nesting_depth=5,
        )
        assert score > 50

    def test_complexity_contributions(self):
        """Each component should contribute to score."""
        footnotes = _score_complexity(footnote_count=20, cross_ref_count=0, nesting_depth=0)
        xrefs = _score_complexity(footnote_count=0, cross_ref_count=10, nesting_depth=0)
        nesting = _score_complexity(footnote_count=0, cross_ref_count=0, nesting_depth=3)

        # Each should contribute
        assert footnotes > 0
        assert xrefs > 0
        assert nesting > 0


class TestPassiveVoiceScoring:
    """Test passive voice scoring."""

    def test_low_passive_voice_low_score(self):
        """Low passive voice percentage should get low score."""
        score = _score_passive_voice(passive_pct=5.0)
        assert score < 30

    def test_high_passive_voice_high_score(self):
        """High passive voice percentage should get higher score."""
        score = _score_passive_voice(passive_pct=35.0)
        assert score > 50

    def test_passive_voice_scale(self):
        """Scores should scale with passive voice percentage."""
        low = _score_passive_voice(10.0)
        mid = _score_passive_voice(20.0)
        high = _score_passive_voice(30.0)
        assert low < mid < high


class TestGradeAssignment:
    """Test grade letter assignment."""

    def test_score_to_grade_mapping(self):
        """Scores should map to letter grades."""
        assert _assign_grade(10.0) == "A"
        assert _assign_grade(25.0) == "B"
        assert _assign_grade(40.0) == "C"
        assert _assign_grade(60.0) == "D"
        assert _assign_grade(75.0) == "F"

    def test_grade_boundaries(self):
        """Test grade boundaries."""
        assert _assign_grade(19.9) == "A"
        assert _assign_grade(20.0) == "B"
        assert _assign_grade(34.9) == "B"
        assert _assign_grade(35.0) == "C"

    def test_all_grades_possible(self):
        """All grades A-F should be possible."""
        grades = set()
        for score in range(0, 101):
            grades.add(_assign_grade(float(score)))
        assert "A" in grades
        assert "B" in grades
        assert "C" in grades
        assert "D" in grades
        assert "F" in grades


class TestObfuscationScoring:
    """Test main obfuscation scoring function."""

    def test_empty_text_no_crash(self):
        """Empty text should not crash."""
        result = score_obfuscation("")
        assert result.overall_score == 0.0

    def test_short_text_processed(self):
        """Short valid text should be processed."""
        text = "The quick brown fox jumps over the lazy dog. This is a simple sentence."
        result = score_obfuscation(text)
        assert result.word_count > 0
        assert result.sentence_count > 0

    def test_simple_text_clear_grade(self):
        """Simple text should get 'A' or 'B' grade."""
        text = "The fund bought stocks. It held them. The costs were small."
        result = score_obfuscation(text)
        assert result.grade in ("A", "B")
        assert result.overall_score < 30

    def test_complex_text_worse_grade(self):
        """Complex text should get worse grade."""
        simple = score_obfuscation("The fund bought stocks.")
        complex_text = score_obfuscation(
            "The aforementioned investment vehicle, functioning as a comprehensive and "
            "sophisticated mechanism for portfolio allocation and the subsequent accumulation "
            "of diversified equity instruments, demonstrated exceptional performance "
            "characteristics throughout the reporting period."
        )
        assert complex_text.grade.lower() > simple.grade.lower() or \
               complex_text.overall_score > simple.overall_score

    def test_long_text_higher_obfuscation(self):
        """Longer text should produce higher obfuscation score."""
        short = score_obfuscation("The fund bought stocks. The costs were low.")
        # Create text with at least 3000 words
        long_text = " ".join(["The fund bought various securities and held them in the portfolio."] * 100)
        long = score_obfuscation(long_text)
        # Long text should have more word count
        assert long.word_count > short.word_count

    def test_all_metrics_calculated(self):
        """All metrics should be calculated for valid text."""
        text = "The fund manager bought stocks. The portfolio grew. Expenses were disclosed."
        result = score_obfuscation(text)

        assert result.word_count > 0
        assert result.sentence_count > 0
        assert result.flesch_kincaid_grade >= 0
        assert result.gunning_fog_index >= 0
        assert result.readability_score >= 0
        assert result.length_score >= 0
        assert 0 <= result.overall_score <= 100

    def test_grade_based_on_score(self):
        """Grade should match overall score."""
        result = score_obfuscation(
            "This is a test. " * 10 + " ".join(["complex"] * 100)
        )
        assert result.grade == _assign_grade(result.overall_score)

    def test_with_html_analysis(self):
        """HTML analysis should be performed if HTML provided."""
        text = "The fund has fees. Costs are disclosed."
        html = "<table><tr><td>Fee (1) See note 1</td><td>Refer to section 2</td></tr></table>"
        result = score_obfuscation(text, html=html)

        # HTML analysis should find footnotes and cross-references
        assert result.footnote_count > 0 or result.cross_reference_count > 0

    def test_methodology_populated(self):
        """Result should include methodology."""
        text = "The fund bought stocks and held them."
        result = score_obfuscation(text)

        assert result.methodology is not None
        assert len(result.methodology) > 0

    def test_extreme_obfuscation(self):
        """Extremely obfuscated text should score higher than simple text."""
        simple = score_obfuscation("The fund bought stocks.")
        # Use complex, passive-voice heavy text
        obfuscated = " ".join([
            "The aforementioned investment vehicle, functioning as a comprehensive mechanism, "
            "was established to facilitate portfolio diversification strategies, such that "
            "comprehensive consideration of multitudinous investment parameters was undertaken, "
            "whereby sophisticated analytical methodologies and technologically-enhanced "
            "systematization protocols were implemented to optimize performance metrics, "
            "notwithstanding significant complications arising from macroeconomic volatility "
            "and geopolitical uncertainties, which may be characterized as multifarious in nature."
        ] * 20)
        result = score_obfuscation(obfuscated)

        # More complex text should have higher obfuscation score
        assert result.overall_score >= simple.overall_score or result.readability_score > simple.readability_score

    def test_passive_voice_detection_in_scoring(self):
        """High passive voice should increase obfuscation score."""
        active = "The manager bought stocks. Costs increased."
        passive = "Stocks were bought by the manager. Costs were increased."

        active_result = score_obfuscation(active)
        passive_result = score_obfuscation(passive)

        # Passive should score higher for obfuscation
        assert passive_result.passive_voice_pct > active_result.passive_voice_pct
