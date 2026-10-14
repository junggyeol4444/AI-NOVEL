"""Run 120 tiny synthetic scenes through the actual local subprocess provider.
This does not establish writing quality, 120 full chapters, or publication readiness.
"""
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from ai_novel_factory.local_models import SceneDraftRequest, LocalExecutableProvider, draft_scene

def main():
    model_dir = sys.argv[1]
    provider = LocalExecutableProvider(str(Path(sys.executable).resolve()),
              arguments=(str(Path(__file__).with_name("ci_real_model.py").resolve()),
                         "--child", model_dir),
              timeout_seconds=120, explicitly_allowed=True)
    durations = []
    digest = hashlib.sha256()
    for episode in range(1,121):
        request = SceneDraftRequest(project_id="synthetic-original-stress",
            episode_number=episode, scene_number=1,
            novel_bible="An original invented world. No source fiction.",
            scene_goal=f"Find original clue {episode} inside a fictional observatory",
            scene_conflict="An invented mysterious door is stuck",
            scene_location="fictional mountain observatory",
            characters=("invented explorer",))
        start = perf_counter()
        result = draft_scene(request, provider)
        duration = perf_counter()-start
        assert result.episode_number == episode
        assert result.status == "DRAFT_REQUIRES_USER_APPROVAL"
        assert result.persisted is False and result.draft.strip()
        durations.append(duration)
        digest.update((str(episode)+"\n"+result.draft+"\n").encode("utf-8"))
        if episode % 20 == 0:
            print("Real local scene stress completed", episode, "of 120",flush=True)
    report = {"synthetic_mini_scenes": 120, "successful": 120,
        "real_cpu_model_used": True, "user_content_used": False,
        "mean_elapsed_seconds": round(statistics.mean(durations),3),
        "max_elapsed_seconds": round(max(durations),3),
        "result_sha256": digest.hexdigest(),
        "full_novel_quality_validated": False,
        "published": False}
    dest=Path("build/ci/real_model_stress.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps(report,sort_keys=True))
if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("local model directory required")
    main()
