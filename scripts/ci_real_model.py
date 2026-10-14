"""Exercise genuine CPU language model weights via ANF local-executable IPC."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

def child(model_dir: str):
    from transformers import AutoTokenizer, AutoModelForCausalLM
    import torch
    torch.set_num_threads(2)
    payload = json.loads(sys.stdin.read())
    assert payload["protocol"] == "anf-local-scene-v1"
    req = payload["request"]
    prompt = (f"Write one original short scene in a fantasy adventure. "
              f"Location: {req['scene_location']}. "
              f"Goal: {req['scene_goal']}. "
              f"Conflict: {req['scene_conflict']}. "
              "Do not quote another work. Scene:\n")
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True)
    inputs = tok(prompt, return_tensors="pt")
    with torch.no_grad():
        ids = model.generate(**inputs, max_new_tokens=45, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    result = tok.decode(ids[0][inputs["input_ids"].shape[-1]:],
                        skip_special_tokens=True).strip()
    assert result, "empty local model output"
    print(json.dumps({"protocol": "anf-local-scene-v1", "draft": result}, ensure_ascii=False))

def parent(model_dir: str):
    from ai_novel_factory.local_models import SceneDraftRequest, LocalExecutableProvider, draft_scene
    provider = LocalExecutableProvider(Path(sys.executable).resolve(),
                arguments=(str(Path(__file__).resolve()), "--child", model_dir),
                timeout_seconds=120, explicitly_allowed=True)
    request = SceneDraftRequest(project_id="synthetic-ci-work", episode_number=1,
                scene_number=1, novel_bible="Original fictional universe only.",
                scene_goal="Find a lantern before dawn",
                scene_conflict="Fog blocks the old bridge",
                scene_location="an invented mountain pass", characters=("a traveler",))
    result = draft_scene(request, provider)
    assert result.draft.strip() and result.status == "DRAFT_REQUIRES_USER_APPROVAL"
    assert result.persisted is False and result.provider == "local-executable-v1"
    record = {"real_cpu_language_model_used": True, "hosted_api_used": False,
              "local_ipc_roundtrip": "PASS", "scene_char_count": len(result.draft),
              "draft_sha256": hashlib.sha256(result.draft.encode("utf8")).hexdigest(),
              "publication_executed": False, "source": "synthetic_only",
              "quality_or_long_form_certified": False}
    path = Path("build/ci/real_cpu_model.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print(json.dumps(record,sort_keys=True))

if __name__ == "__main__":
    if len(sys.argv) != 3: raise SystemExit("mode/model dir required")
    if sys.argv[1] == "--child": child(sys.argv[2])
    elif sys.argv[1] == "--run": parent(sys.argv[2])
    else: raise SystemExit("unknown mode")
