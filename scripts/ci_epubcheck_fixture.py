"""Create an independent synthetic EPUB3 fixture using the current branch generator."""
from pathlib import Path
from ai_novel_factory.epub3 import Chapter, create_epub, verify_epub
from ai_novel_factory.publication_metadata import MetadataDraft

output = Path("build/ci")
output.mkdir(parents=True, exist_ok=True)
meta = MetadataDraft("synthetic-ci-story", "새벽과 별의 여행", "합성 예시 작가",
                     "테스트용 완전 창작 세계관", "판타지", ("여행", "별"), "0")
result = create_epub(meta, [Chapter("제1화 새로운 길", "달빛 아래 새로운 문이 열렸다."),
                            Chapter("제2화 귀환", "여행자는 자기 선택을 기억했다.")], output)
assert verify_epub(result.path, expected_chapters=2).valid
print("Synthetic EPUB3 generated; SHA-256:", result.sha256)
