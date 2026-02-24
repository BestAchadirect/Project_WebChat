import pytest

pytest.importorskip("sqlalchemy")

from app.services.imports.service import data_import_service


def test_private_helper_surfaces_remain_available_for_scripts() -> None:
    attributes = {
        "jewelry_type": "Labret",
        "material": "Titanium G23",
        "gauge": "16g",
        "threading": "internal",
        "color": "silver",
    }

    keywords = data_import_service._build_search_keywords(
        display_name="Threadless Labret",
        sku="LAB-001",
        legacy_skus=["OLD-LAB-001"],
        attributes=attributes,
        keyword_columns=["jewelry_type", "material", "gauge"],
    )
    assert "threadless labret" in keywords
    assert "lab 001" not in keywords
    assert "labret" in keywords

    search_text = data_import_service._build_search_text(
        display_name="Threadless Labret",
        sku="LAB-001",
        object_id="1001",
        description="Implant grade titanium",
        legacy_skus=["OLD-LAB-001"],
        synonyms=["implant grade"],
        attributes=attributes,
        attribute_columns=["material", "gauge"],
    )
    assert "threadless" in search_text
    assert "lab 001" in search_text
    assert "implant grade" in search_text

    chunks = data_import_service._chunk_text("abcdefghij", chunk_size=4, overlap=1)
    assert chunks == ["abcd", "defg", "ghij", "j"]

    assert (
        data_import_service._hash_text("abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
