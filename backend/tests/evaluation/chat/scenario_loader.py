from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "chat"


def scenario_fixture_path(name: str | Path) -> Path:
    path = FIXTURE_DIR / str(name)
    if not path.exists():
        raise ValueError(f"scenario fixture does not exist: {path}")
    return path


def load_scenarios(name: str | Path) -> list[dict[str, Any]]:
    path = scenario_fixture_path(name)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError(f"scenario fixture must contain a list: {path}")

    return [_validate_scenario(item, path=path, index=index) for index, item in enumerate(payload, start=1)]


def _validate_scenario(raw: Any, *, path: Path, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"scenario #{index} in {path} must be a mapping")

    scenario = dict(raw)
    scenario_id = str(scenario.get("id") or "").strip()
    if not scenario_id:
        raise ValueError(f"scenario #{index} in {path} is missing id")

    messages = scenario.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"scenario {scenario_id!r} in {path} must contain a non-empty messages list")

    validated_messages: list[dict[str, str]] = []
    for message_index, raw_message in enumerate(messages, start=1):
        if not isinstance(raw_message, dict):
            raise ValueError(
                f"scenario {scenario_id!r} in {path} has invalid message #{message_index}: must be a mapping"
            )
        role = str(raw_message.get("role") or "").strip()
        content = str(raw_message.get("content") or "").strip()
        if not role:
            raise ValueError(f"scenario {scenario_id!r} in {path} message #{message_index} is missing role")
        if not content:
            raise ValueError(f"scenario {scenario_id!r} in {path} message #{message_index} is missing content")
        validated_messages.append({"role": role, "content": content})

    expected = scenario.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(f"scenario {scenario_id!r} in {path} is missing expected")

    normalized_expected = dict(expected)
    workflow = str(normalized_expected.get("workflow") or "").strip().lower()
    if workflow == "clarification":
        normalized_expected.pop("workflow", None)
        normalized_expected.setdefault("internal_workflow", "clarify")

    validated = {
        "id": scenario_id,
        "messages": validated_messages,
        "expected": normalized_expected,
    }
    description = str(scenario.get("description") or "").strip()
    if description:
        validated["description"] = description
    return validated
