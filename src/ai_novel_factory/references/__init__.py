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
