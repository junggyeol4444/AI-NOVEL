"""Reference document parsers; source texts remain local and transient."""

from .episode_splitter import Episode, SplitEpisodes, split_episodes
from .import_pipeline import ImportResult, import_reference_file
from .basic_statistics import (
    TextStatistics, EpisodeStatistics, ReferenceStatistics, measure_text, measure_reference,
)
from .dialogue_statistics import (
    DialogueCounts, EpisodeDialogue, ReferenceDialogue,
    measure_dialogue_text, measure_dialogue_reference,
)
from .episode_structure import (
    CueCounts, SectionMetrics, EpisodeStructure, ReferenceStructure,
    analyze_structure_text, analyze_reference_structure,
)
from .event_timing import (
    MAX_EVENT_MARKERS, EventCuePosition, EpisodeEventTiming, ReferenceEventTiming,
    analyze_event_timing_text, analyze_reference_event_timing,
)
from .event_pacing import (
    GapMetrics, EpisodePacing, ReferencePacing,
    analyze_pacing_text, analyze_reference_pacing,
)
from .cliffhanger_analysis import (
    LEXICAL_TYPES, PUNCTUATION_TYPES, TYPE_PRIORITY, LexicalSignals,
    EpisodeCliffhanger, ReferenceCliffhangers,
    analyze_cliffhanger_text, analyze_reference_cliffhangers,
)
from .relationship_changes import (
    MAX_PAIR_OBSERVATIONS, MAX_PAIR_DISTANCE, PairEvidence, EpisodeRelationships,
    PairSummary, RelationshipChange, ReferenceRelationships,
    analyze_relationship_text, analyze_reference_relationships,
)
from .docx_parser import parse_docx_bytes, parse_docx_file
from .pdf_parser import ParsedPdfReference, parse_pdf_bytes, parse_pdf_file
from .plaintext_parser import (
    ParsedBlock,
    ParsedReference,
    ReferenceParseError,
    parse_reference_file,
    parse_text,
)

__all__ = [
    "MAX_PAIR_OBSERVATIONS", "MAX_PAIR_DISTANCE", "PairEvidence", "EpisodeRelationships",
    "PairSummary", "RelationshipChange", "ReferenceRelationships",
    "analyze_relationship_text", "analyze_reference_relationships",
    "LEXICAL_TYPES", "PUNCTUATION_TYPES", "TYPE_PRIORITY",
    "LexicalSignals", "EpisodeCliffhanger", "ReferenceCliffhangers",
    "analyze_cliffhanger_text", "analyze_reference_cliffhangers",
    "GapMetrics", "EpisodePacing", "ReferencePacing",
    "analyze_pacing_text", "analyze_reference_pacing",
    "MAX_EVENT_MARKERS", "EventCuePosition", "EpisodeEventTiming", "ReferenceEventTiming",
    "analyze_event_timing_text", "analyze_reference_event_timing",
    "CueCounts", "SectionMetrics", "EpisodeStructure", "ReferenceStructure",
    "analyze_structure_text", "analyze_reference_structure",
    "ImportResult", "import_reference_file",
    "DialogueCounts", "EpisodeDialogue", "ReferenceDialogue",
    "measure_dialogue_text", "measure_dialogue_reference",
    "TextStatistics",
    "EpisodeStatistics",
    "ReferenceStatistics",
    "measure_text",
    "measure_reference",
    "Episode",
    "SplitEpisodes",
    "split_episodes",
    "ParsedBlock",
    "ParsedReference",
    "ReferenceParseError",
    "parse_reference_file",
    "parse_text",
    "parse_docx_bytes",
    "parse_docx_file",
    "ParsedPdfReference",
    "parse_pdf_bytes",
    "parse_pdf_file",
]

# Stage 26: deterministic character prominence and explicit role-hint candidates.
from .character_roles import (
    CharacterSpec, CharacterRoleCandidate, EpisodeCharacterRoles, ReferenceCharacterRoles,
    analyze_character_text, analyze_reference_character_roles,
)
__all__ += [
    "CharacterSpec", "CharacterRoleCandidate", "EpisodeCharacterRoles", "ReferenceCharacterRoles",
    "analyze_character_text", "analyze_reference_character_roles",
]

# Stage 28: fixed-vocabulary foreshadow/affect cues (no actual plot inference).
from .foreshadow_emotion import (
    MAX_ANALYZED_TEXT_CHARS, MAX_FORESHADOW_EMOTION_CUES, CueTotals,
    EmotionWindow, EpisodeForeshadowEmotion, ReferenceForeshadowEmotion,
    analyze_foreshadow_emotion_text, analyze_reference_foreshadow_emotion,
)
__all__ += [
    "MAX_ANALYZED_TEXT_CHARS", "MAX_FORESHADOW_EMOTION_CUES", "CueTotals",
    "EmotionWindow", "EpisodeForeshadowEmotion", "ReferenceForeshadowEmotion",
    "analyze_foreshadow_emotion_text", "analyze_reference_foreshadow_emotion",
]

# Stage 29: deterministic writing-style statistics, without source quotations.
from .style_statistics import (
    MAX_STYLE_TEXT_CHARS, MAX_STYLE_TOKENS, LengthSummary, PunctuationCounts, ScriptCounts,
    StyleMetrics, EpisodeStyle, ReferenceStyle, analyze_style_text, analyze_reference_style,
)
__all__ += [
    "MAX_STYLE_TEXT_CHARS", "MAX_STYLE_TOKENS", "LengthSummary", "PunctuationCounts",
    "ScriptCounts", "StyleMetrics", "EpisodeStyle", "ReferenceStyle",
    "analyze_style_text", "analyze_reference_style",
]

# Stage 30: aggregate-only, offline Reference Profile
from .reference_profile import (
    PROFILE_SCHEMA_VERSION, EpisodeProfile, ReferenceProfile,
    build_reference_profile, render_reference_profile, validate_profile,
)
from .profile_pipeline import ProfileImportResult, import_reference_profile
__all__.extend([
    "PROFILE_SCHEMA_VERSION", "EpisodeProfile", "ReferenceProfile",
    "build_reference_profile", "render_reference_profile", "validate_profile",
    "ProfileImportResult", "import_reference_profile",
])

# Stage 31: completely offline, text-free multi-reference profile integration.
from .profile_collection import (
    MAX_COLLECTION_REFERENCES, CURVE_BINS, WEIGHTING_MODES, MetricSpread,
    CurveSegment, ProfileCollection, combine_reference_profiles,
    combine_saved_profiles, render_profile_collection,
)
__all__.extend([
    "MAX_COLLECTION_REFERENCES", "CURVE_BINS", "WEIGHTING_MODES", "MetricSpread",
    "CurveSegment", "ProfileCollection", "combine_reference_profiles",
    "combine_saved_profiles", "render_profile_collection",
])

# Stage 32: offline, human-tagged Genre Pattern statistics.
from .genre_patterns import (
    GENRE_NAMES, GENRE_PATTERN_VERSION, GenreFeature, GenrePattern,
    validate_genre, build_genre_pattern, render_genre_pattern,
)
__all__ += [
    "GENRE_NAMES", "GENRE_PATTERN_VERSION", "GenreFeature", "GenrePattern",
    "validate_genre", "build_genre_pattern", "render_genre_pattern",
]



# Stage 36: local, aggregate-only relevance search across saved genre patterns.
__all__ += [
    "RelatedPatternError", "MetricDifference", "RelatedPattern", "RelatedPatternResults",
    "RelatedPatternSearch", "render_related_patterns",
]

# Lazy stage-36 exports prevent a database <-> references package import cycle.
def __getattr__(name: str):
    if name in {"RelatedPatternError", "MetricDifference", "RelatedPattern",
                "RelatedPatternResults", "RelatedPatternSearch", "render_related_patterns"}:
        from . import related_pattern_search
        return getattr(related_pattern_search, name)
    raise AttributeError(name)

# Stage 38: offline and fail-closed non-copy guard for transient source text.
from .copy_protection import (
    REVIEW_MATCH_UNITS, BLOCK_MATCH_UNITS, CopyProtectionError,
    CopyMatchEvidence, CopyProtectionReport, analyze_copy_protection,
    require_copy_safe_draft, render_copy_protection,
)
__all__ += [
    "REVIEW_MATCH_UNITS", "BLOCK_MATCH_UNITS", "CopyProtectionError",
    "CopyMatchEvidence", "CopyProtectionReport", "analyze_copy_protection",
    "require_copy_safe_draft", "render_copy_protection",
]

# Stage 39: offline paragraph-level lexical similarity baseline.
from .similarity_baseline import (
    SHINGLE_UNITS, MIN_PARAGRAPH_UNITS, SimilarityCheckError,
    ParagraphSimilarityEvidence, SimilarityBaselineReport,
    analyze_similarity_baseline, require_similarity_safe_draft,
    render_similarity_baseline,
)
__all__ += [
    "SHINGLE_UNITS", "MIN_PARAGRAPH_UNITS", "SimilarityCheckError",
    "ParagraphSimilarityEvidence", "SimilarityBaselineReport",
    "analyze_similarity_baseline", "require_similarity_safe_draft",
    "render_similarity_baseline",
]
