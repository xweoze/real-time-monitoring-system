import unittest
from pathlib import Path

from disaster_rag import DisasterKnowledgeBase, tokenize


ROOT = Path(__file__).resolve().parents[1]


class DisasterKnowledgeBaseTest(unittest.TestCase):
    def setUp(self):
        self.knowledge = DisasterKnowledgeBase(ROOT / "disaster_docs")

    def test_korean_tokens_are_extracted(self):
        self.assertIn("침수된", tokenize("침수된 도로 접근 금지"))

    def test_search_prioritizes_relevant_document(self):
        results = self.knowledge.search("침수된 지하차도 대피", 3)
        self.assertTrue(results)
        self.assertEqual(results[0]["documentTitle"], "호우·침수 국민행동요령")

    def test_answer_contains_sources_and_notice(self):
        answer = self.knowledge.answer("화재 연기 속 대피 방법")
        self.assertTrue(answer["grounded"])
        self.assertTrue(answer["answer"])
        self.assertTrue(answer["sources"][0]["url"].startswith("https://"))
        self.assertIn("119", answer["notice"])

    def test_unrelated_query_returns_no_grounded_answer(self):
        answer = self.knowledge.answer("양자컴퓨터 반도체")
        self.assertFalse(answer["grounded"])
        self.assertEqual(answer["sources"], [])


if __name__ == "__main__":
    unittest.main()
