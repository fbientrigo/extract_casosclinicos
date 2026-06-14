from __future__ import annotations

import json
from pathlib import Path

from scanbook.build_index import build_index
from scanbook.local_llm import (
    OllamaClient,
    answer_question,
    build_messages,
    format_answer,
)


def _build_index(tmp_path: Path) -> Path:
    rows = [
        {"case_id": "112", "title": "Anemia ferropriva", "text": "paciente con anemia ferropenica y fatiga", "page_start": 12},
        {"case_id": "201", "title": "Leucemia aguda", "text": "paciente con leucemia mieloide aguda", "page_start": 40},
    ]
    input_jsonl = tmp_path / "cases.jsonl"
    input_jsonl.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    index_dir = tmp_path / "index"
    build_index(input_jsonl=input_jsonl, output_dir=index_dir, vector_store="lexical")
    return index_dir


class FakeClient:
    """Stand-in for OllamaClient so tests never need a running server."""

    def __init__(self) -> None:
        self.model = "fake-model"
        self.last_messages: list[dict[str, str]] | None = None

    def chat(self, messages, temperature: float = 0.2) -> str:
        self.last_messages = messages
        return "Respuesta basada en el contexto [caso 112]."


def test_answer_question_grounds_on_retrieved_context(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    fake = FakeClient()
    result = answer_question(
        index_dir=index_dir,
        question="anemia ferropenica",
        top_k=2,
        client=fake,
    )
    assert result["grounded"] is True
    assert result["answer"]
    assert result["sources"], "should report retrieved sources"
    # The retrieved context must have been passed to the model.
    user_msg = fake.last_messages[-1]["content"]
    assert "CONTEXTO" in user_msg
    assert "anemia" in user_msg.lower()
    # Top hit for this query should be the ferropenia case.
    assert result["sources"][0]["chunk_id"] == "112"


def test_answer_question_no_hits_is_honest(tmp_path: Path) -> None:
    index_dir = _build_index(tmp_path)
    fake = FakeClient()
    result = answer_question(
        index_dir=index_dir,
        question="zxqwv términos que no existen",
        top_k=2,
        client=fake,
    )
    assert result["grounded"] is False
    assert result["sources"] == []
    # Must not call the model when there is nothing to ground on.
    assert fake.last_messages is None


def test_build_messages_respects_context_budget(tmp_path: Path) -> None:
    hits = [
        {"chunk_id": "1", "title": "Caso largo", "text": "x" * 5000},
        {"chunk_id": "2", "title": "Otro", "text": "y" * 5000},
    ]
    messages = build_messages("pregunta", hits, max_context_chars=1000)
    context = messages[-1]["content"]
    # The first snippet is truncated to the budget and the second is dropped.
    assert context.count("x") == 1000
    assert "y" * 50 not in context


def test_format_answer_includes_sources_and_disclaimer() -> None:
    result = {
        "answer": "Una respuesta.",
        "sources": [{"label": "caso 112 · Anemia ferropriva"}],
    }
    text = format_answer(result)
    assert "caso 112" in text
    assert "educativo" in text.lower()


def test_client_is_available_false_when_unreachable() -> None:
    # Unroutable host/port so this is fast and offline-safe.
    client = OllamaClient(host="http://127.0.0.1:1", timeout=0.2)
    assert client.is_available() is False
