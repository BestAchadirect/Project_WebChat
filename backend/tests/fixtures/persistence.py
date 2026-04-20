from typing import Any


class NoopSavepoint:
    async def __aenter__(self) -> "NoopSavepoint":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class PersistenceDB:
    def __init__(self, *, assert_on_rollback: bool = False) -> None:
        self.added: list[Any] = []
        self.executed: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self._assert_on_rollback = assert_on_rollback

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> None:
        self.executed.append(statement)
        return None

    async def flush(self) -> None:
        return None

    def begin_nested(self) -> NoopSavepoint:
        return NoopSavepoint()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        if self._assert_on_rollback:
            raise AssertionError("rollback should not be called")
        self.rolled_back = True


class RuntimeDB:
    async def execute(self, *args: Any, **kwargs: Any) -> None:
        return None


class ConversationStateQueryResult:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def first(self) -> tuple[Any]:
        return (self._payload,)


class ConversationStateDB:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def execute(self, *args: Any, **kwargs: Any) -> ConversationStateQueryResult:
        return ConversationStateQueryResult(self._payload)
