"""Real local CPU LLM -> local TXT draft -> EPUB3 end-to-end synthetic QA."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
from ai_novel_factory.publication_metadata import MetadataDraft
from ai_novel_factory.epub3 import Chapter, create_epub, verify_epub
from ai_novel_factory.episode_upload_files import (UploadEpisode, export_upload_drafts,
                                                    verify_upload_drafts)
from ai_novel_factory.local_models import (SceneDraftRequest, LocalExecutableProvider,
                                           draft_scene)

def generate(model_dir: str):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch.set_num_threads(2)
    payload=json.loads(sys.stdin.read())
    if payload["protocol"]!="anf-local-scene-v1": raise ValueError("unsafe request protocol")
    req=payload["request"]
    prompt=("Write a short original fantasy prose scene, no quotes from other works. "
            "Goal: "+req["scene_goal"]+". Conflict: "+req["scene_conflict"]
            +". Location: "+req["scene_location"]+". Story:\n")
    tokenizer=AutoTokenizer.from_pretrained(model_dir,local_files_only=True)
    model=AutoModelForCausalLM.from_pretrained(model_dir,local_files_only=True)
    v=tokenizer(prompt,return_tensors="pt")
    with torch.no_grad():
        tokens=model.generate(**v,max_new_tokens=65,do_sample=False,pad_token_id=tokenizer.eos_token_id)
    text=tokenizer.decode(tokens[0][v["input_ids"].shape[-1]:],skip_special_tokens=True).strip()
    if not text: raise ValueError("model returned no text")
    print(json.dumps({"protocol":"anf-local-scene-v1","draft":text},ensure_ascii=False))

def run(model_dir: str):
    if os.environ.get("HF_HUB_OFFLINE")!="1": raise RuntimeError("offline inference required")
    root=Path("build/ci")
    root.mkdir(parents=True,exist_ok=True)
    work=root/"synthetic"
    work.mkdir(mode=0o700,exist_ok=False)
    model=LocalExecutableProvider(str(Path(sys.executable).resolve()),
        arguments=(str(Path(__file__).resolve()),"--child",model_dir),
        timeout_seconds=120,explicitly_allowed=True)
    req=SceneDraftRequest(project_id="ci_synthetic_orig",
        episode_number=1,scene_number=1,novel_bible="Original made-up world.",
        scene_goal="find a lantern before the sunset",
        scene_conflict="a locked gate blocks a fictional road",
        scene_location="an invented mountain town",
        characters=("a traveler",))
    output=draft_scene(req,model)
    assert output.status=="DRAFT_REQUIRES_USER_APPROVAL"
    assert output.persisted is False and output.draft.strip()
    meta=MetadataDraft("ci_synthetic_orig","합성 CI 원고","가상 작가",
        "테스트 목적으로 생성한 비공개 가상 세계","판타지",("합성","테스트"),"0")
    chapter=Chapter("제1화 시험 장면",output.draft)
    epub=create_epub(meta,[chapter],work)
    assert epub.publication_approved is False
    valid=verify_epub(epub.path,expected_chapters=1,expected_sha256=epub.sha256)
    assert valid.valid
    drafts=export_upload_drafts(meta,[UploadEpisode(1,chapter.title,output.draft,"가상 작가의 말")],work)
    assert drafts.publication_approved is False
    verify=verify_upload_drafts(drafts.directory,expected_manifest_sha256=drafts.manifest_sha256)
    assert verify.valid and verify.episode_count==1
    report=dict(stage="CI_E2E",test_only=True,real_local_llm=True,offline_llm=True,
       output_sha256=hashlib.sha256(output.draft.encode("utf-8")).hexdigest(),
       generated_text_chars=len(output.draft),epub_valid=True,
       epub_sha256=epub.sha256,upload_txt_count=drafts.files_created,
       upload_drafts_verified=True,published=False,
       user_approval_granted=False,user_content_used=False,
       platform_api_called=False,quality_accepted=False)
    (root/"real_model_to_epub_txt.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True,ensure_ascii=False))

if __name__=="__main__":
    if len(sys.argv)!=3: raise SystemExit("expected --run or --child and local model directory")
    if sys.argv[1]=="--child":generate(sys.argv[2])
    elif sys.argv[1]=="--run":run(sys.argv[2])
    else:raise SystemExit("invalid mode")
