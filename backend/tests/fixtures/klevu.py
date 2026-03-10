from __future__ import annotations

from typing import Any
from uuid import UUID


class NoopSavepoint:
    async def __aenter__(self) -> "NoopSavepoint":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class ProcessRowsDB:
    def begin_nested(self) -> NoopSavepoint:
        return NoopSavepoint()


class ScalarOneOrNoneResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class ScalarsCollection:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class ScalarsResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> ScalarsCollection:
        return ScalarsCollection(self._values)


class FakeSingleRunDB:
    def __init__(self, run: Any) -> None:
        self.run = run
        self.commit_calls = 0
        self.refresh_calls = 0

    async def execute(self, _stmt: Any) -> ScalarOneOrNoneResult:
        return ScalarOneOrNoneResult(self.run)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, _obj: Any) -> None:
        self.refresh_calls += 1


class FakeActiveRunsDB:
    def __init__(self, runs: list[Any]) -> None:
        self.runs = runs
        self.commit_calls = 0
        self.refresh_calls = 0

    async def execute(self, _stmt: Any) -> ScalarsResult:
        return ScalarsResult(self.runs)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, _obj: Any) -> None:
        self.refresh_calls += 1


class FakeQueueCreateDB:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commit_calls = 0
        self.refresh_calls = 0
        self._next_id = UUID("00000000-0000-0000-0000-0000000000B1")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, obj: Any) -> None:
        self.refresh_calls += 1
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
