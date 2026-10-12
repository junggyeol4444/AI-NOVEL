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
