import importlib

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")


REMOVED_LEGACY_MODULES = [
    "app.services.chat_service",
    "app.services.data_import_service",
    "app.services.agent_tools",
    "app.services.agent_orchestrator",
    "app.services.llm_service",
    "app.services.answer_polisher",
    "app.services.response_renderer",
    "app.services.eav_service",
    "app.services.product_attribute_sync_service",
    "app.services.knowledge_pipeline",
    "app.services.task_service",
    "app.services.ticket_service",
    "app.services.rag_service",
    "app.services.magento_service",
]

CANONICAL_CASES = [
    ("app.services.chat.service", ["ChatService"]),
    ("app.services.imports.service", ["DataImportService", "data_import_service"]),
    ("app.services.chat.agentic.tool_registry", ["AgentToolRegistry"]),
    ("app.services.chat.agentic.orchestrator", ["AgentOrchestrator"]),
    ("app.services.ai.llm_service", ["LLMService", "llm_service"]),
    ("app.services.ai.answer_polisher", ["answer_polisher"]),
    ("app.services.ai.response_renderer", ["ResponseRenderer"]),
    ("app.services.catalog.attributes_service", ["EAVService", "eav_service"]),
    (
        "app.services.catalog.attribute_sync_service",
        ["ProductAttributeSyncService", "product_attribute_sync_service"],
    ),
    ("app.services.knowledge.pipeline", ["KnowledgePipeline"]),
    ("app.services.tasks.service", ["TaskService", "task_service"]),
    ("app.services.tickets.service", ["TicketService"]),
    ("app.services.legacy.rag_service_deprecated", ["RAGService", "rag_service"]),
    ("app.services.legacy.magento_service_deprecated", ["MagentoService"]),
]


@pytest.mark.parametrize("module_path", REMOVED_LEGACY_MODULES)
def test_legacy_wrapper_module_is_removed(module_path: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_path)


@pytest.mark.parametrize("module_path,expected_symbols", CANONICAL_CASES)
def test_canonical_module_exposes_expected_symbols(
    module_path: str,
    expected_symbols: list[str],
) -> None:
    module = importlib.import_module(module_path)
    for symbol in expected_symbols:
        assert hasattr(module, symbol), f"Missing symbol {symbol} on {module_path}"
