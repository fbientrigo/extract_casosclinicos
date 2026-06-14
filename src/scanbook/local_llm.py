"""Optional, fully-local question answering over a built scanbook index.

This module is an *optional* alternative to handing batches off to a hosted
model (e.g. Gemini). It does retrieval-augmented generation (RAG) entirely on
the local machine:

  1. Retrieve the most relevant chunks from a local index (``scanbook query``).
  2. Ask a small local LLM, served by `Ollama <https://ollama.com>`_, to answer
     using *only* that retrieved context.

It is designed for modest hardware: the default model (``qwen2.5:3b``) is
multilingual (good Spanish) and runs in well under 5 GB of VRAM when quantized,
and also works CPU-only.

Nothing here is required for the core pipeline. The only dependency is the
Python standard library; the LLM itself runs in a separate Ollama process that
the user installs and starts on their own. If Ollama is not running, the
functions raise :class:`LocalLLMError` with actionable instructions.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from scanbook.query import query_index

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"

# A conservative ceiling so we never blow past a small model's context window
# (and so a few long clinical cases don't crowd everything else out).
DEFAULT_MAX_CONTEXT_CHARS = 6000

SYSTEM_PROMPT = (
    "Eres un asistente que responde preguntas sobre una colección local de "
    "casos clínicos, usando ÚNICAMENTE el contexto recuperado que se te entrega. "
    "Reglas estrictas:\n"
    "- Responde solo con información presente en el CONTEXTO. No uses conocimiento externo.\n"
    "- Si el contexto no contiene la respuesta, di claramente que no aparece en los casos disponibles.\n"
    "- No inventes valores de laboratorio, rangos de referencia, cifras, diagnósticos ni IDs de casos.\n"
    "- Cita los casos que uses por su identificador (p. ej. [caso 112] o el título mostrado).\n"
    "- Responde en español, de forma breve y concreta.\n"
    "- Este material es solo para fines educativos; no es consejo médico ni sirve para decisiones clínicas reales."
)


class LocalLLMError(RuntimeError):
    """Raised when the local LLM (Ollama) cannot be reached or used."""


class OllamaClient:
    """Tiny stdlib-only client for a local Ollama server."""

    def __init__(self, host: str | None = None, model: str = DEFAULT_MODEL, timeout: float = 120.0):
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.model = model
        self.timeout = timeout

    # -- low level ---------------------------------------------------------
    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.host}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LocalLLMError(self._unreachable_message()) from exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 or "not found" in body.lower():
                raise LocalLLMError(
                    f"El modelo '{self.model}' no está disponible en Ollama.\n"
                    f"Descárgalo con:\n    ollama pull {self.model}"
                ) from exc
            raise LocalLLMError(f"Ollama devolvió un error HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise LocalLLMError(self._unreachable_message()) from exc

    def _unreachable_message(self) -> str:
        return (
            f"No se pudo conectar a Ollama en {self.host}.\n"
            "Para usar el LLM local:\n"
            "  1. Instala Ollama desde https://ollama.com\n"
            "  2. Inicia el servidor (suele iniciarse solo; si no: 'ollama serve')\n"
            f"  3. Descarga el modelo: 'ollama pull {self.model}'\n"
            "También puedes apuntar a otro host con la variable OLLAMA_HOST."
        )

    # -- public ------------------------------------------------------------
    def is_available(self) -> bool:
        """Return True if the Ollama server responds."""
        try:
            self._get("/api/tags")
            return True
        except LocalLLMError:
            return False

    def list_models(self) -> list[str]:
        data = self._get("/api/tags")
        return [m.get("name", "") for m in data.get("models", [])]

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        data = self._post("/api/chat", payload)
        return str(data.get("message", {}).get("content", "")).strip()


def _hit_label(hit: dict[str, Any]) -> str:
    """Human-readable citation label for a retrieved chunk."""
    parts = []
    cid = hit.get("chunk_id")
    if cid:
        parts.append(f"caso {cid}")
    title = hit.get("title")
    if title:
        parts.append(str(title))
    ps, pe = hit.get("page_start"), hit.get("page_end")
    if ps is not None:
        parts.append(f"pág. {ps}" + (f"-{pe}" if pe not in (None, ps) else ""))
    return " · ".join(parts) if parts else "fragmento"


def build_messages(question: str, hits: list[dict[str, Any]], max_context_chars: int) -> list[dict[str, str]]:
    """Build the chat messages with the retrieved context block."""
    blocks: list[str] = []
    budget = max_context_chars
    for hit in hits:
        text = str(hit.get("text", "")).strip()
        if not text:
            continue
        snippet = text[: max(0, budget)]
        budget -= len(snippet)
        blocks.append(f"[{_hit_label(hit)}]\n{snippet}")
        if budget <= 0:
            break

    context = "\n\n---\n\n".join(blocks) if blocks else "(sin contexto recuperado)"
    user = (
        f"CONTEXTO (casos recuperados de la colección local):\n\n{context}\n\n"
        f"PREGUNTA: {question}\n\n"
        "Responde usando solo el CONTEXTO de arriba y cita los casos que uses."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def answer_question(
    index_dir: Path,
    question: str,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
    top_k: int = 5,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    temperature: float = 0.2,
    client: OllamaClient | None = None,
) -> dict[str, Any]:
    """Answer ``question`` from the local ``index_dir`` using a local LLM.

    Returns a dict with the answer, the model used, and the list of source
    chunks that were retrieved (for transparency / citation checking).

    A pre-built ``client`` may be injected (used by tests); otherwise an
    :class:`OllamaClient` is created from ``host``/``model``.
    """
    hits = query_index(index_dir=index_dir, question=question, top_k=top_k)
    sources = [
        {
            "chunk_id": h.get("chunk_id"),
            "title": h.get("title"),
            "page_start": h.get("page_start"),
            "page_end": h.get("page_end"),
            "score": h.get("score"),
            "label": _hit_label(h),
        }
        for h in hits
    ]

    if not hits:
        return {
            "question": question,
            "answer": (
                "No encontré casos relevantes en el índice local para esa pregunta. "
                "Prueba con otros términos o reconstruye el índice con 'scanbook build-index'."
            ),
            "model": model,
            "sources": [],
            "grounded": False,
        }

    cli = client or OllamaClient(host=host, model=model)
    messages = build_messages(question, hits, max_context_chars=max_context_chars)
    answer = cli.chat(messages, temperature=temperature)
    return {
        "question": question,
        "answer": answer,
        "model": getattr(cli, "model", model),
        "sources": sources,
        "grounded": True,
    }


def format_answer(result: dict[str, Any]) -> str:
    """Format an :func:`answer_question` result for terminal output."""
    lines = [result.get("answer", "").strip(), ""]
    sources = result.get("sources") or []
    if sources:
        lines.append("Fuentes (recuperadas del índice local):")
        for s in sources:
            lines.append(f"  - {s.get('label')}")
    lines.append("")
    lines.append("[Material educativo — no es consejo médico.]")
    return "\n".join(lines)
