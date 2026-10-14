"""Validate the stage-3 architecture contract using Python standard library."""
from __future__ import annotations
import json
from pathlib import Path

REQUIRED_COMPONENTS = {
    "desktop", "api", "orchestrator", "reference_analyzer", "planner",
    "writer", "quality", "memory", "queue", "publishing", "provider",
}
REQUIRED_CONTROLS = {
    "NO_REFERENCE_RAW_TEXT_TO_WRITER",
    "NOVEL_BIBLE_OVERRIDES_REFERENCE_PROFILE",
    "SIMILARITY_CHECK_BEFORE_EPISODE_FINALIZATION",
    "NO_PUBLICATION_WITHOUT_EXPLICIT_USER_APPROVAL",
    "NO_PAID_API_OR_INSTALL_WITHOUT_APPROVAL",
    "NO_CLAIM_OF_PC_OFF_LOCAL_BUILD",
    "SECRETS_NEVER_IN_SOURCE_OR_LOGS",
    "OFFLINE_CORE_FUNCTIONS", "NO_EXTERNAL_AI_API",
    "NO_GITHUB_RUNTIME_DEPENDENCY", "NO_REMOTE_DATABASE_OR_JOB_SERVER",
}

def load_contract(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def validate_contract(contract: dict) -> list[str]:
    """Return human-readable problems; an empty list means the spec is consistent."""
    problems: list[str] = []
    if contract.get("stage") != 3:
        problems.append("Stage must equal 3")
    components = contract.get("components", [])
    ids = [item.get("id") for item in components]
    if len(ids) != len(set(ids)):
        problems.append("Component identifiers must be unique")
    if set(ids) != REQUIRED_COMPONENTS:
        problems.append("Missing/unexpected components")
    connections = contract.get("connections", [])
    for edge in connections:
        if edge.get("from") not in ids or edge.get("to") not in ids:
            problems.append("Unknown connection endpoint")
    if any(edge.get("from") == "desktop" and edge.get("to") not in {"api", "orchestrator"}
           for edge in connections):
        problems.append("Desktop must not access storage/providers directly")
    if any(edge.get("from") == "reference_analyzer" and edge.get("to") == "writer" for edge in connections):
        problems.append("Reference raw material must not flow directly to writer")
    if not REQUIRED_CONTROLS.issubset(set(contract.get("nonnegotiable_controls", []))):
        problems.append("Required copyright/safety/approval control missing")
    deployment = contract.get("deployment", {})
    required_local = {
        "desktop": "USER_WINDOWS_PC",
        "api_host": "OPTIONAL_LOOPBACK_ONLY",
        "postgresql_host": "NOT_USED",
        "redis_host": "NOT_USED",
        "worker_host": "SAME_WINDOWS_PC_IN_PROCESS",
        "remote_repository": "NOT_USED_AT_RUNTIME",
        "offline_behavior": "NO_NETWORK_REQUIRED_FOR_CORE_FUNCTIONS",
        "pc_off_execution": "NOT_SUPPORTED",
        "runtime_network": "NO_EXTERNAL_NETWORK_DEPENDENCY",
        "ai_execution": "LOCAL_DEVICE_ONLY",
        "data_storage": "USER_PC_SQLITE",
    }
    for key, expected in required_local.items():
        if deployment.get(key) != expected:
            problems.append(f"Local-only deployment contract violated: {key}")
    for component in components:
        if component.get("zone") != "local":
            problems.append("All runtime components must remain on the local PC")
    if contract.get("stack", {}).get("model_provider") != "LOCAL_MODEL_ONLY_NOT_YET_IMPLEMENTED":
        problems.append("AI provider must be local-only")
    return problems

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    errors = validate_contract(load_contract(root / "docs/architecture_decisions.json"))
    if errors:
        print("FAIL: " + "; ".join(errors))
        raise SystemExit(1)
    print("PASS: stage-3 architecture contract validation")
