"""TF-IDF 슬라이드 검색 — _ref/report_ai_prototype/app.py의 retrieve 부분 이식."""
from __future__ import annotations

from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MIN_SCORE = 0.025


def slide_document(slide: dict[str, Any]) -> str:
    parts = [slide.get("page_title", ""), slide.get("summary", "")]
    parts.extend(item.get("text", "") for item in slide.get("body", []))
    for key in ("table1", "table2"):
        table = slide.get(key)
        if table:
            parts.extend(table.get("headers", []))
            for row in table.get("rows", []):
                parts.extend(row)
    return " ".join(str(x) for x in parts if x)


def retrieve(payload: dict[str, Any], question: str, top_k: int = 3) -> list[tuple[dict[str, Any], float]]:
    slides = payload["slides"]
    docs = [slide_document(s) for s in slides]
    if not docs:
        return []
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(docs + [question])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    order = scores.argsort()[::-1][: min(top_k, len(slides))]
    return [(slides[int(i)], float(scores[int(i)])) for i in order]
