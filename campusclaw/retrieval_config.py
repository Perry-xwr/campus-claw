"""Read retrieval provider settings without exposing secrets to the browser."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalConfig:
    qdrant_url: str
    collection: str
    embedding_base_url: str
    embedding_model: str
    embedding_api_key: str
    chat_base_url: str
    chat_model: str
    chat_api_key: str
    tutor_stub: bool = False

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        get = os.environ.get
        return cls(
            qdrant_url=get("QDRANT_URL", "http://127.0.0.1:6333").strip(),
            collection=get("QDRANT_COLLECTION", "campusclaw_chunks").strip(),
            embedding_base_url=get("EMBEDDING_BASE_URL", "").strip(),
            embedding_model=get("EMBEDDING_MODEL", "").strip(),
            embedding_api_key=get("EMBEDDING_API_KEY", "").strip(),
            chat_base_url=get("CHAT_BASE_URL", "").strip(),
            chat_model=get("CHAT_MODEL", "").strip(),
            chat_api_key=get("CHAT_API_KEY", "").strip(),
            tutor_stub=get("CAMPUSCLAW_TUTOR_STUB", "") == "1",
        )

    @property
    def embedding_ready(self) -> bool:
        return all((self.embedding_base_url, self.embedding_model, self.embedding_api_key))

    @property
    def chat_ready(self) -> bool:
        return all((self.chat_base_url, self.chat_model, self.chat_api_key))
