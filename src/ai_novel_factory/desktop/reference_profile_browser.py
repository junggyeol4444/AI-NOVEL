"""Stage 30 offline profile browser for the existing PySide6 reference page.

No server, background sync, GitHub, or external API. File imports happen only
when the user explicitly presses the Analyze button.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ai_novel_factory.database import CatalogError, ReferenceCatalog
from ai_novel_factory.database.reference_profiles import ProfileStorageError, ReferenceProfileStore
from ai_novel_factory.references.plaintext_parser import ReferenceParseError
from ai_novel_factory.references.profile_pipeline import import_reference_profile
from ai_novel_factory.references.reference_profile import render_reference_profile
from ai_novel_factory.references.profile_collection import (
    combine_saved_profiles, render_profile_collection,
)
from .reference_selection import ReferenceFileSelection
from ai_novel_factory.database.genre_patterns import GenrePatternStore, GenreStorageError
from ai_novel_factory.database.pattern_strengths import (PatternStrengthStore, PatternStrengthStorageError)
from ai_novel_factory.references.pattern_strength import (PatternStrengthError, preview_strengths, render_strength_preview)
from ai_novel_factory.database.element_selections import (ElementSelectionStore, ElementSelectionStorageError)
from ai_novel_factory.references.element_selection import (
    FEATURE_KEYS, FEATURE_LABELS, ElementSelectionError, render_element_selection,
)
from ai_novel_factory.references.genre_patterns import GENRE_NAMES, render_genre_pattern
from ai_novel_factory.references.pattern_library import (
    PatternLibraryError, ReferencePatternLibrary, render_library_page, render_library_comparison,
)

from ai_novel_factory.references.related_pattern_search import (
    RelatedPatternSearch, RelatedPatternError, render_related_patterns,
)
from ai_novel_factory.database.pattern_usage import (PatternUsageStore, PatternUsageError, render_usage_record)


def default_local_catalog_path() -> Path:
    """PC-local per-user data only; never a URL or network share by default."""
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "AI Novel Factory" / "references.sqlite3"
    root = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "ai-novel-factory" / "references.sqlite3"


class ReferenceProfileBrowser(QWidget):
    def __init__(self, selection: ReferenceFileSelection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selection = selection
        self._ids: list[str] = []
        self._pattern_keys: list[tuple[str, str]] = []
        self._usage_ids: list[str] = []
        layout = QVBoxLayout(self)
        notice = QLabel("참고작 분석 프로필 · 이 PC의 SQLite 파일에 통계만 저장됩니다. 자동 업로드 없음")
        notice.setWordWrap(True)
        notice.setTextFormat(Qt.PlainText)
        layout.addWidget(notice)
        buttons = QHBoxLayout()
        self.analyze_button = QPushButton("선택한 파일 분석·저장")
        self.analyze_button.setObjectName("analyzeReferenceProfileButton")
        self.compare_button = QPushButton("선택한 작품들 통합 비교")
        self.compare_button.setObjectName("compareReferenceProfilesButton")
        self.refresh_button = QPushButton("저장된 프로필 새로고침")
        self.refresh_button.setObjectName("refreshReferenceProfilesButton")
        buttons.addWidget(self.analyze_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.compare_button)
        layout.addLayout(buttons)
        genre_row = QHBoxLayout()
        self.genre_selector = QComboBox()
        self.genre_selector.setObjectName("referenceGenreSelector")
        for slug, name in GENRE_NAMES.items():
            self.genre_selector.addItem(name, slug)
        self.genre_assign_button = QPushButton("선택한 작품에 장르 지정")
        self.genre_assign_button.setObjectName("assignReferenceGenreButton")
        self.genre_build_button = QPushButton("이 장르 패턴 구축")
        self.genre_build_button.setObjectName("buildGenrePatternButton")
        self.genre_show_button = QPushButton("저장된 장르 패턴 보기")
        self.genre_show_button.setObjectName("showGenrePatternButton")
        genre_row.addWidget(self.genre_selector)
        genre_row.addWidget(self.genre_assign_button)
        genre_row.addWidget(self.genre_build_button)
        genre_row.addWidget(self.genre_show_button)
        layout.addLayout(genre_row)
        # Stage 34: explicit user-set per-work numeric influence, local only.
        strength_controls = QHBoxLayout()
        self.strength_spinner = QSpinBox()
        self.strength_spinner.setObjectName("referencePatternStrengthSpinner")
        self.strength_spinner.setRange(0, 100)
        self.strength_spinner.setValue(50)
        self.strength_save_button = QPushButton("선택한 참고작 강도 저장")
        self.strength_save_button.setObjectName("saveReferencePatternStrengthButton")
        self.strength_preview_button = QPushButton("현재 장르 강도 미리보기")
        self.strength_preview_button.setObjectName("previewReferencePatternStrengthButton")
        strength_controls.addWidget(QLabel("패턴 강도(0~100)"))
        strength_controls.addWidget(self.strength_spinner)
        strength_controls.addWidget(self.strength_save_button)
        strength_controls.addWidget(self.strength_preview_button)
        layout.addLayout(strength_controls)
        # Stage 35: opt-in selection of descriptive metrics, never source text.
        layout.addWidget(QLabel("참고할 통계 요소 선택 (1~6개, 사용자 직접 선택)"))
        element_controls = QHBoxLayout()
        self.elements_save_button = QPushButton("참고 요소 저장")
        self.elements_save_button.setObjectName("saveReferenceElementsButton")
        self.elements_show_button = QPushButton("저장한 요소 보기")
        self.elements_show_button.setObjectName("showReferenceElementsButton")
        self.elements_delete_button = QPushButton("요소 선택 초기화")
        self.elements_delete_button.setObjectName("deleteReferenceElementsButton")
        element_controls.addWidget(self.elements_save_button)
        element_controls.addWidget(self.elements_show_button)
        element_controls.addWidget(self.elements_delete_button)
        layout.addLayout(element_controls)
        self.element_list = QListWidget()
        self.element_list.setObjectName("referenceElementSelectionList")
        self.element_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.element_list.setMaximumHeight(110)
        for key in FEATURE_KEYS:
            self.element_list.addItem(f"{FEATURE_LABELS[key]} ({key})")
        layout.addWidget(self.element_list)
        self.related_search_button = QPushButton("선택 요소로 관련 패턴 검색")
        self.related_search_button.setObjectName("searchRelatedReferencePatternsButton")
        self.related_search_button.setToolTip("해당 장르의 저장된 요소 선택을 이용해 로컬 패턴의 통계 근접도 비교")
        layout.addWidget(self.related_search_button)
        # Stage 37: explicit, local-only journal (never triggered by merely searching).
        usage_buttons = QHBoxLayout()
        self.usage_record_button = QPushButton("선택 장르/패턴 사용 기록")
        self.usage_record_button.setObjectName("recordReferencePatternUsageButton")
        self.usage_refresh_button = QPushButton("패턴 사용 이력 보기")
        self.usage_refresh_button.setObjectName("listReferencePatternUsageButton")
        self.usage_delete_button = QPushButton("선택한 사용 기록 삭제")
        self.usage_delete_button.setObjectName("deleteReferencePatternUsageButton")
        for widget in (self.usage_record_button, self.usage_refresh_button, self.usage_delete_button):
            usage_buttons.addWidget(widget)
        layout.addLayout(usage_buttons)
        self.usage_list = QListWidget()
        self.usage_list.setObjectName("referencePatternUsageList")
        self.usage_list.setMaximumHeight(90)
        layout.addWidget(self.usage_list)
        # Stage 33: browsing reads only previously saved, text-free recipes.
        library_label = QLabel("Reference Pattern Library · 저장된 장르 패턴 검색·비교 (로컬 DB)")
        library_label.setTextFormat(Qt.PlainText)
        layout.addWidget(library_label)
        library_controls = QHBoxLayout()
        self.pattern_search = QLineEdit()
        self.pattern_search.setObjectName("patternLibrarySearchInput")
        self.pattern_search.setPlaceholderText("장르 이름 또는 가중치 검색")
        self.pattern_refresh_button = QPushButton("패턴 검색")
        self.pattern_refresh_button.setObjectName("patternLibrarySearchButton")
        self.pattern_detail_button = QPushButton("패턴 상세")
        self.pattern_detail_button.setObjectName("patternLibraryDetailButton")
        self.pattern_compare_button = QPushButton("패턴 비교")
        self.pattern_compare_button.setObjectName("patternLibraryCompareButton")
        for widget in (self.pattern_search, self.pattern_refresh_button,
                       self.pattern_detail_button, self.pattern_compare_button):
            library_controls.addWidget(widget)
        layout.addLayout(library_controls)
        self.pattern_list = QListWidget()
        self.pattern_list.setObjectName("patternLibraryList")
        self.pattern_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.pattern_list.setMaximumHeight(130)
        layout.addWidget(self.pattern_list)
        self.profiles = QListWidget()
        self.profiles.setObjectName("savedReferenceProfilesList")
        self.profiles.setSelectionMode(QAbstractItemView.MultiSelection)
        self.profiles.setToolTip("통합 비교할 참고작을 2개 이상 선택하세요. 최대 50개까지 비교됩니다.")
        self.profiles.setMaximumHeight(130)
        self.report = QPlainTextEdit()
        self.report.setObjectName("referenceProfileReport")
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("저장된 참고작 프로필을 선택하면 통계 보고서가 표시됩니다.")
        layout.addWidget(self.profiles)
        layout.addWidget(self.report)
        self.analyze_button.clicked.connect(self._analyze_selected)
        self.refresh_button.clicked.connect(self.refresh)
        self.compare_button.clicked.connect(self._compare_selected)
        self.genre_assign_button.clicked.connect(self._assign_selected_genre)
        self.genre_build_button.clicked.connect(self._build_selected_genre)
        self.genre_show_button.clicked.connect(self._show_selected_genre)
        self.profiles.currentRowChanged.connect(self._show_profile)
        self.strength_save_button.clicked.connect(self._save_selected_strength)
        self.strength_preview_button.clicked.connect(self._preview_genre_strengths)
        self.pattern_refresh_button.clicked.connect(self._refresh_library)
        self.pattern_detail_button.clicked.connect(self._show_library_pattern)
        self.pattern_compare_button.clicked.connect(self._compare_library_patterns)
        self.pattern_search.returnPressed.connect(self._refresh_library)
        self.elements_save_button.clicked.connect(self._save_selected_elements)
        self.elements_show_button.clicked.connect(self._show_selected_elements)
        self.elements_delete_button.clicked.connect(self._delete_selected_elements)
        self.related_search_button.clicked.connect(self._search_related_patterns)
        self.usage_record_button.clicked.connect(self._record_usage)
        self.usage_refresh_button.clicked.connect(self._refresh_usage)
        self.usage_delete_button.clicked.connect(self._delete_usage)
        # Constructor does not touch the filesystem or send a network request.

    def _catalog_path(self) -> Path:
        path = default_local_catalog_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def refresh(self) -> None:
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                rows = ReferenceProfileStore(catalog).list(limit=200)
            self._ids = [row.reference_id for row in rows]
            self.profiles.blockSignals(True)
            self.profiles.clear()
            self.profiles.addItems([f"{row.file_name} · {row.episode_count}화" for row in rows])
            self.profiles.blockSignals(False)
            self.report.setPlainText(f"저장된 참고작 프로필 {len(rows)}개 (최근 200개 표시)")
        except (CatalogError, ProfileStorageError, OSError):
            self.report.setPlainText("로컬 프로필 목록을 불러오지 못했습니다.")

    def _show_profile(self, row: int) -> None:
        if not 0 <= row < len(self._ids):
            return
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                profile = ReferenceProfileStore(catalog).get(self._ids[row])
                strength = PatternStrengthStore(catalog).get(self._ids[row])
            self.strength_spinner.setValue(strength)
            self.report.setPlainText(render_reference_profile(profile, episode_limit=50)
                                     + f"\n참고 패턴 강도 설정: {strength}/100 (통계적 영향, 원문 복제 금지)")
        except (CatalogError, ProfileStorageError, PatternStrengthStorageError, ReferenceParseError, OSError):
            self.report.setPlainText("선택한 로컬 프로필을 불러올 수 없습니다.")

    def _save_selected_strength(self) -> None:
        indices = sorted(index.row() for index in self.profiles.selectedIndexes())
        if len(indices) != 1 or not 0 <= indices[0] < len(self._ids):
            self.report.setPlainText("강도를 변경할 참고작 한 개를 선택하세요.")
            return
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                PatternStrengthStore(catalog).set(self._ids[indices[0]], self.strength_spinner.value())
            self.report.setPlainText(f"강도 {self.strength_spinner.value()} 저장 완료. "
                                     "선택한 참고작의 통계적 비중 미리보기에만 적용됩니다.")
        except (CatalogError, ProfileStorageError, PatternStrengthStorageError, OSError):
            self.report.setPlainText("패턴 강도를 저장하지 못했습니다.")

    def _preview_genre_strengths(self) -> None:
        genre = self.genre_selector.currentData()
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                strengths = PatternStrengthStore(catalog)
                result = preview_strengths(GenrePatternStore(catalog), strengths, genre)
            self.report.setPlainText(render_strength_preview(result))
        except (CatalogError, ProfileStorageError, GenreStorageError,
                PatternStrengthStorageError, PatternStrengthError, ReferenceParseError, OSError):
            self.report.setPlainText("장르 패턴이 없거나 변경됐습니다. 먼저 장르 패턴을 구축하세요.")

    def _analyze_selected(self) -> None:
        if not self.selection.selected_paths:
            self.report.setPlainText("먼저 위에서 참고소설 파일을 선택하세요.")
            return
        # Explicit user action only. Keep file paths out of UI error reports.
        completed = 0
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                for path in self.selection.selected_paths:
                    import_reference_profile(path, catalog=catalog)
                    completed += 1
        except (CatalogError, ProfileStorageError, ReferenceParseError, OSError):
            self.report.setPlainText(f"{completed}개 저장 후 중단. 실패한 파일의 형식이나 크기를 확인하세요.")
            return
        self.refresh()
        self.report.setPlainText(f"참고작 {completed}개의 분석 프로필을 로컬 DB에 저장했습니다. 목록을 선택해 보세요.")

    def _compare_selected(self) -> None:
        indices = sorted(index.row() for index in self.profiles.selectedIndexes())
        if not 2 <= len(indices) <= 50:
            self.report.setPlainText("통합 분석할 참고작 프로필을 2~50개 선택하세요.")
            return
        try:
            ids = [self._ids[i] for i in indices]
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = combine_saved_profiles(ReferenceProfileStore(catalog), ids)
            self.report.setPlainText(render_profile_collection(result))
        except (IndexError, CatalogError, ProfileStorageError, ReferenceParseError, OSError):
            self.report.setPlainText("선택한 로컬 프로필을 통합 분석하지 못했습니다.")

    def _assign_selected_genre(self) -> None:
        indices = sorted(index.row() for index in self.profiles.selectedIndexes())
        if not indices:
            self.report.setPlainText("장르를 지정할 참고작 프로필을 먼저 선택하세요.")
            return
        if not all(0 <= i < len(self._ids) for i in indices):
            self.report.setPlainText("목록을 새로고침한 뒤 다시 선택하세요.")
            return
        genre = self.genre_selector.currentData()
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                storage = GenrePatternStore(catalog)
                for i in indices:
                    storage.assign(self._ids[i], genre)
            self.report.setPlainText(f"참고작 {len(indices)}개에 '{GENRE_NAMES[genre]}' 장르를 지정했습니다. "
                                     "기존 저장 패턴은 다시 구축해야 할 수 있습니다.")
        except (CatalogError, ProfileStorageError, GenreStorageError, OSError):
            self.report.setPlainText("선택한 참고작의 장르를 지정하지 못했습니다.")

    def _build_selected_genre(self) -> None:
        genre = self.genre_selector.currentData()
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = GenrePatternStore(catalog).build(genre)
            self.report.setPlainText(render_genre_pattern(result))
        except (CatalogError, ProfileStorageError, GenreStorageError, ReferenceParseError, OSError):
            self.report.setPlainText("장르 패턴을 구축하려면 해당 장르에 정상 프로필 2~50개가 필요합니다.")

    def _show_selected_genre(self) -> None:
        genre = self.genre_selector.currentData()
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = GenrePatternStore(catalog).get(genre)
            self.report.setPlainText(render_genre_pattern(result))
        except (CatalogError, ProfileStorageError, GenreStorageError, ReferenceParseError, OSError):
            self.report.setPlainText("저장된 장르 패턴을 표시하지 못했습니다. 변경이 있다면 다시 구축하세요.")

    def _refresh_library(self) -> None:
        """Explicit button operation, no server or automatic background sync."""
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                library = ReferencePatternLibrary(GenrePatternStore(catalog))
                page = library.search(query=self.pattern_search.text(), limit=100)
            self._pattern_keys = [(entry.genre, entry.weighting) for entry in page.entries]
            self.pattern_list.clear()
            for entry in page.entries:
                status = "최신" if entry.current else "재구축 필요"
                self.pattern_list.addItem(
                    f"{GENRE_NAMES[entry.genre]} · {entry.weighting} · {entry.reference_count}작품 · {status}")
            self.report.setPlainText(render_library_page(page))
        except (CatalogError, GenreStorageError, PatternLibraryError, OSError):
            self._pattern_keys = []
            self.pattern_list.clear()
            self.report.setPlainText("로컬 패턴 라이브러리를 검색하지 못했습니다.")

    def _show_library_pattern(self) -> None:
        indexes = [item.row() for item in self.pattern_list.selectedIndexes()]
        if len(indexes) != 1 or not 0 <= indexes[0] < len(self._pattern_keys):
            self.report.setPlainText("상세 정보를 볼 패턴 한 개를 선택하세요.")
            return
        genre, weighting = self._pattern_keys[indexes[0]]
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                pattern = ReferencePatternLibrary(GenrePatternStore(catalog)).get(
                    genre, weighting=weighting)
            self.report.setPlainText(render_genre_pattern(pattern))
        except (CatalogError, GenreStorageError, PatternLibraryError, ReferenceParseError, OSError):
            self.report.setPlainText("패턴 구성이 변경됐거나 자료가 손상됐습니다. 다시 구축하세요.")

    def _compare_library_patterns(self) -> None:
        indexes = sorted(i.row() for i in self.pattern_list.selectedIndexes())
        if not 2 <= len(indexes) <= 12 or not all(0 <= i < len(self._pattern_keys) for i in indexes):
            self.report.setPlainText("서로 다른 장르 패턴 2~12개를 선택하세요.")
            return
        keys = [self._pattern_keys[i] for i in indexes]
        if len({weighting for _, weighting in keys}) != 1:
            self.report.setPlainText("같은 가중치(equal 또는 characters)의 패턴만 비교하세요.")
            return
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = ReferencePatternLibrary(GenrePatternStore(catalog)).compare(
                    [genre for genre, _ in keys], weighting=keys[0][1])
            self.report.setPlainText(render_library_comparison(result))
        except (CatalogError, GenreStorageError, PatternLibraryError, ReferenceParseError, OSError):
            self.report.setPlainText("패턴 비교에 실패했습니다. 최신 구성으로 다시 구축하세요.")

    def _save_selected_elements(self) -> None:
        keys = [FEATURE_KEYS[i.row()] for i in self.element_list.selectedIndexes()
                if 0 <= i.row() < len(FEATURE_KEYS)]
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = ElementSelectionStore(catalog).save(self.genre_selector.currentData(), keys)
            self.report.setPlainText(render_element_selection(result))
        except (CatalogError, ElementSelectionStorageError, ElementSelectionError, OSError):
            self.report.setPlainText("통계 요소를 선택하고 장르 패턴·참고작 강도를 확인하세요.")

    def _show_selected_elements(self) -> None:
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = ElementSelectionStore(catalog).get(self.genre_selector.currentData())
            self.element_list.blockSignals(True)
            self.element_list.clearSelection()
            for position, key in enumerate(FEATURE_KEYS):
                self.element_list.item(position).setSelected(key in result.selected_keys)
            self.element_list.blockSignals(False)
            self.report.setPlainText(render_element_selection(result))
        except (CatalogError, ElementSelectionStorageError, ElementSelectionError, OSError):
            self.report.setPlainText("저장한 요소가 없거나 장르 구성이 변경됐습니다. 다시 선택하세요.")

    def _delete_selected_elements(self) -> None:
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                removed = ElementSelectionStore(catalog).delete(self.genre_selector.currentData())
            self.report.setPlainText("통계 요소 선택만 삭제했습니다." if removed else "저장된 요소 선택이 없습니다.")
        except (CatalogError, ElementSelectionStorageError, OSError):
            self.report.setPlainText("요소 선택을 초기화하지 못했습니다.")

    def _search_related_patterns(self) -> None:
        """User-triggered offline search; never sends anything to a service."""
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                result = RelatedPatternSearch(catalog).search(self.genre_selector.currentData())
            self.report.setPlainText(render_related_patterns(result))
        except (CatalogError, ProfileStorageError, GenreStorageError,
                PatternStrengthStorageError, ElementSelectionStorageError,
                RelatedPatternError, OSError):
            self.report.setPlainText("장르의 참고 요소 선택을 저장하고 패턴의 최신 상태와 강도를 확인하세요.")

    def _record_usage(self) -> None:
        """Only button press appends a record; selecting or searching never does."""
        source = self.genre_selector.currentData()
        indices = [item.row() for item in self.pattern_list.selectedIndexes()]
        target = None
        weighting = "equal"
        if len(indices) > 1:
            self.report.setPlainText("사용 기록을 남길 패턴은 최대 한 개만 선택하세요.")
            return
        if indices:
            if not 0 <= indices[0] < len(self._pattern_keys):
                self.report.setPlainText("패턴 목록을 새로고침하세요.")
                return
            target, weighting = self._pattern_keys[indices[0]]
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                record = PatternUsageStore(catalog).record(
                    source, pattern_genre=target, weighting=weighting)
            self._refresh_usage()
            self.report.setPlainText(render_usage_record(record))
        except (CatalogError, PatternUsageError, OSError):
            self.report.setPlainText("저장된 요소 선택, 장르 패턴, 참고작 강도를 확인하세요. 사용 기록을 추가하지 않았습니다.")

    def _refresh_usage(self) -> None:
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                values = PatternUsageStore(catalog).list(limit=100)
            self._usage_ids = [row.usage_id for row in values]
            self.usage_list.clear()
            for row in values:
                status = "최신" if row.current else "재검토 필요"
                self.usage_list.addItem(
                    f"{row.created_at[:16]} · {GENRE_NAMES[row.source_genre]} → "
                    f"{GENRE_NAMES[row.pattern_genre]} · {status}")
            self.report.setPlainText(f"로컬 패턴 사용 기록 {len(values)}개 표시 (최근 100건)")
        except (CatalogError, PatternUsageError, OSError):
            self._usage_ids = []
            self.usage_list.clear()
            self.report.setPlainText("패턴 사용 이력을 읽지 못했습니다.")

    def _delete_usage(self) -> None:
        indices = [item.row() for item in self.usage_list.selectedIndexes()]
        if len(indices) != 1 or not 0 <= indices[0] < len(self._usage_ids):
            self.report.setPlainText("삭제할 사용 기록 한 건을 선택하세요.")
            return
        try:
            with ReferenceCatalog(self._catalog_path()) as catalog:
                removed = PatternUsageStore(catalog).delete(self._usage_ids[indices[0]])
            self._refresh_usage()
            self.report.setPlainText("선택한 패턴 사용 기록만 삭제했습니다." if removed else "기록을 찾지 못했습니다.")
        except (CatalogError, PatternUsageError, OSError):
            self.report.setPlainText("패턴 사용 기록을 삭제하지 못했습니다.")
