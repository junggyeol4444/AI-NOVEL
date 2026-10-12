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
    if any(edge.get("from") == "desktop" and edge.get("to") != "api" for edge in connections):
        problems.append("Desktop must not bypass API boundary")
    if any(edge.get("from") == "reference_analyzer" and edge.get("to") == "writer" for edge in connections):
        problems.append("Reference raw material must not flow directly to writer")
    if not REQUIRED_CONTROLS.issubset(set(contract.get("nonnegotiable_controls", []))):
        problems.append("Required copyright/safety/approval control missing")
    deployment = contract.get("deployment", {})
    for key in ("api_host", "postgresql_host", "redis_host", "worker_host"):
        if deployment.get(key) != "UNDECIDED_APPROVAL_REQUIRED":
            problems.append(f"Deployment location prematurely decided: {key}")
    if deployment.get("remote_repository") != "NOT_CONNECTED":
        problems.append("Remote repository connection is not verified")
    return problems

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    errors = validate_contract(load_contract(root / "docs/architecture_decisions.json"))
    if errors:
        print("FAIL: " + "; ".join(errors))
        raise SystemExit(1)
    print("PASS: stage-3 architecture contract validation")