"""Small source-grounded disaster document retriever."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


class DisasterKnowledgeBase:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.documents = self._load_documents()
        self.document_frequency = Counter()
        for document in self.documents:
            self.document_frequency.update(set(document["tokens"]))

    def _load_documents(self) -> list[dict]:
        documents = []
        if not self.directory.exists():
            return documents
        for path in sorted(self.directory.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            metadata, content = self._parse_document(raw)
            for index, section in enumerate(re.split(r"\n(?=## )", content)):
                section = section.strip()
                if not section:
                    continue
                title_match = re.match(r"##\s+(.+)", section)
                section_title = (
                    title_match.group(1).strip()
                    if title_match
                    else metadata.get("title", path.stem)
                )
                documents.append(
                    {
                        "id": f"{path.stem}:{index}",
                        "title": section_title,
                        "documentTitle": metadata.get("title", path.stem),
                        "source": metadata.get("source", ""),
                        "sourceUrl": metadata.get("source_url", ""),
                        "updatedAt": metadata.get("updated_at", ""),
                        "content": section,
                        "tokens": tokenize(
                            f"{metadata.get('title', '')} {section_title} {section}"
                        ),
                    }
                )
        return documents

    @staticmethod
    def _parse_document(raw: str) -> tuple[dict, str]:
        if not raw.startswith("---\n"):
            return {}, raw
        _, header, content = raw.split("---\n", 2)
        metadata = {}
        for line in header.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        return metadata, content

    def search(self, query: str, limit: int = 5) -> list[dict]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        query_counts = Counter(query_tokens)
        total_documents = max(1, len(self.documents))
        results = []
        for document in self.documents:
            document_counts = Counter(document["tokens"])
            score = 0.0
            for token, query_count in query_counts.items():
                term_count = document_counts[token]
                if not term_count:
                    continue
                inverse_frequency = math.log(
                    (total_documents + 1)
                    / (self.document_frequency[token] + 1)
                ) + 1
                score += (1 + math.log(term_count)) * inverse_frequency * query_count
            if score:
                results.append(
                    {
                        key: value
                        for key, value in document.items()
                        if key != "tokens"
                    }
                    | {"score": round(score, 4)}
                )
        results.sort(key=lambda item: (-item["score"], item["title"]))
        return results[: max(1, min(10, int(limit)))]

    def answer(self, query: str, limit: int = 3) -> dict:
        matches = self.search(query, limit)
        return {
            "query": query,
            "answer": "\n\n".join(
                self._summary(match["content"]) for match in matches
            ),
            "sources": [
                {
                    "title": match["documentTitle"],
                    "section": match["title"],
                    "source": match["source"],
                    "url": match["sourceUrl"],
                    "updatedAt": match["updatedAt"],
                    "score": match["score"],
                }
                for match in matches
            ],
            "grounded": bool(matches),
            "notice": (
                "검색된 공식 문서 내용을 요약 없이 발췌한 결과입니다. "
                "긴급 상황에서는 119와 지자체 안내를 우선하세요."
            ),
        }

    @staticmethod
    def _summary(content: str) -> str:
        lines = [
            line.strip().lstrip("- ").strip()
            for line in content.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        return "\n".join(lines[:6])[:1200]
