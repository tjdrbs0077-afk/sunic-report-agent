"""⑥ 동향 인사이트 — 정렬과 지식맵 연동 회귀 테스트.

실제로 났던 두 결함을 고정한다.
  1. '정확순'을 눌러도 오늘 기사만 나옴 (점수가 RSS 순위를 따라가 동점 → 시간 tie-break)
  2. 오른쪽 지식맵과 기사 목록이 서로 연결되지 않음 (양방향 색인 없음)
"""
import unittest
from datetime import datetime, timedelta, timezone

from app.services import news
from app.services.news import (_published_at, _window_query, balanced_pool,
                               build_graph, relevance_score, rescore,
                               sort_articles, spread_by_day)
from app.routers.news import _with_sort


def _aged(title: str, days: float, score: float) -> dict:
    """며칠 전 기사 한 건을 만든다."""
    when = datetime.now(timezone.utc) - timedelta(days=days)
    return {"title": title, "score": score,
            "published_at": when.isoformat(timespec="seconds").replace("+00:00", "Z")}


class NewsSortingTests(unittest.TestCase):
    def test_rss_date_is_exposed_as_sortable_utc_time(self):
        self.assertEqual(
            _published_at("Sun, 09 Aug 2026 12:30:00 +0900"),
            "2026-08-09T03:30:00Z",
        )

    def test_articles_can_be_sorted_by_accuracy_or_latest(self):
        items = [
            {"title": "정확한 과거 기사", "score": 0.95, "published_at": "2026-08-01T00:00:00Z"},
            {"title": "최신 기사", "score": 0.70, "published_at": "2026-08-09T00:00:00Z"},
            {"title": "날짜 없는 기사", "score": 0.90, "published_at": ""},
        ]
        self.assertEqual(sort_articles(items, "accuracy")[0]["title"], "정확한 과거 기사")
        self.assertEqual(sort_articles(items, "latest")[0]["title"], "최신 기사")
        self.assertEqual(sort_articles(items, "latest")[-1]["title"], "날짜 없는 기사")

    def test_latest_sort_supports_legacy_relative_dates(self):
        items = [
            {"title": "과거 캐시", "score": 0.99, "date": "07/24"},
            {"title": "오늘 기사", "score": 0.70, "date": "오늘"},
            {"title": "날짜 없음", "score": 1.0, "date": ""},
        ]
        self.assertEqual(
            [item["title"] for item in sort_articles(items, "latest")],
            ["오늘 기사", "과거 캐시", "날짜 없음"],
        )

    def test_accuracy_prefers_query_match_over_feed_rank(self):
        matching = relevance_score(
            "자율제조 AI 플랫폼 구축 본격화", "제조 현장 자동화", "자율제조", 15, 20
        )
        unrelated = relevance_score(
            "오늘의 주요 경제 소식", "증시와 환율 동향", "자율제조", 0, 20
        )
        self.assertGreater(matching, unrelated)
        self.assertGreaterEqual(matching, 0.7)

    def test_feed_rank_does_not_change_the_score(self):
        """RSS 순위가 점수에 섞이면 정확순이 최신순의 복사본이 된다."""
        first = relevance_score("자율제조 운영체계 표준화", "표준화 착수", "자율제조 운영체계", 0, 40)
        last = relevance_score("자율제조 운영체계 표준화", "표준화 착수", "자율제조 운영체계", 39, 40)
        self.assertEqual(first, last)

    def test_accuracy_separates_articles_that_share_keyword_coverage(self):
        """제목이 검색어로 채워진 기사가, 검색어를 스쳐 지나간 기사보다 앞서야 한다."""
        focused = relevance_score("자율제조 운영체계 구축", "", "자율제조 운영체계")
        passing = relevance_score(
            "글로벌 경기 둔화 속 수출 반등 신호…업계는 자율제조 운영체계 도입 검토",
            "", "자율제조 운영체계",
        )
        self.assertGreater(focused, passing)

    def test_accuracy_tie_break_is_not_recency(self):
        """동점이어도 발행 시각이 순위를 결정하면 안 된다 (오늘 기사 쏠림의 원인)."""
        items = [
            {"title": "오늘 올라온 기사", "score": 0.8, "published_at": "2026-08-10T00:00:00Z",
             "matched_keywords": ["자율제조"]},
            {"title": "지난달 기사", "score": 0.8, "published_at": "2026-07-01T00:00:00Z",
             "matched_keywords": ["자율제조", "운영체계"]},
        ]
        self.assertEqual(sort_articles(items, "accuracy")[0]["title"], "지난달 기사")

    def test_multi_keyword_articles_score_higher(self):
        one = rescore({"title": "포스코 자율제조 확대", "summary": "", "matched_keywords": ["자율제조"]})
        both = rescore({"title": "포스코 자율제조 운영체계 확대", "summary": "",
                        "matched_keywords": ["자율제조", "운영체계"]})
        self.assertGreater(both, one)

    def test_balanced_pool_keeps_recent_articles_for_the_latest_tab(self):
        """정확순 기준으로만 잘라 캐시에 담으면 최신순 탭이 볼 기사가 없어진다."""
        items = [
            {"title": f"정확도 높은 과거 기사 {i}", "score": 0.9 - i * 0.01,
             "published_at": "2026-07-0{}T00:00:00Z".format(i % 9 + 1)}
            for i in range(20)
        ] + [
            {"title": "오늘 올라온 낮은 점수 기사", "score": 0.2,
             "published_at": "2026-08-10T00:00:00Z"},
        ]
        pool = balanced_pool(items, 6)
        self.assertEqual(len(pool), 6)
        self.assertIn("오늘 올라온 낮은 점수 기사", [item["title"] for item in pool])


class NewsLookbackTests(unittest.TestCase):
    """정확순이 최근 한 달을 훑는지 — '오늘 기사만 나온다'의 재발 방지."""

    def test_windows_cover_a_month(self):
        self.assertGreaterEqual(news.LOOKBACK_DAYS, 30)
        self.assertGreaterEqual(max(since for since, _ in news.SEARCH_WINDOWS),
                                news.LOOKBACK_DAYS)

    def test_recent_window_uses_when_so_today_is_not_excluded(self):
        """before:오늘 은 오늘 기사를 빼 버린다 — 최근 창은 when: 을 써야 한다."""
        self.assertIn("when:7d", _window_query("자율제조", 7, 0))

    def test_older_window_pins_an_explicit_date_range(self):
        query = _window_query("자율제조", 30, 14)
        self.assertRegex(query, r"after:\d{4}-\d{2}-\d{2} before:\d{4}-\d{2}-\d{2}")

    def test_pool_keeps_older_articles_even_when_scores_tie(self):
        """동점이면 정확순도 시각으로 갈린다 → 그냥 자르면 후보가 최근 며칠로 쪼그라든다."""
        items = ([_aged(f"최근 기사 {i}", i * 0.2, 0.8) for i in range(30)]
                 + [_aged(f"3주 전 기사 {i}", 20 + i * 0.2, 0.8) for i in range(30)])
        pool = balanced_pool(items, 24)
        oldest = max(news._age_days(item) for item in pool)
        self.assertGreater(oldest, 14, "2주보다 오래된 기사가 후보군에 하나도 남지 않았다")

    def test_accuracy_view_is_not_all_from_one_day(self):
        items = ([_aged(f"오늘 기사 {i}", 0.01 * i, 0.9) for i in range(12)]
                 + [_aged(f"열흘 전 기사 {i}", 10 + 0.01 * i, 0.88) for i in range(12)])
        shown = spread_by_day(sort_articles(items, "accuracy"), 12)
        days = {news._day_key(item) for item in shown}
        self.assertGreater(len(days), 1, "정확순 상위가 전부 같은 날짜다")

    def test_spread_keeps_the_highest_score_first(self):
        """날짜를 흩뿌리더라도 1위는 여전히 가장 정확한 기사여야 한다."""
        items = [_aged("압도적으로 정확한 기사", 25, 0.99)] + \
                [_aged(f"오늘 기사 {i}", 0.01 * i, 0.9) for i in range(12)]
        shown = spread_by_day(sort_articles(items, "accuracy"), 12)
        self.assertEqual(shown[0]["title"], "압도적으로 정확한 기사")

    def test_day_key_ignores_the_clock_in_display_dates(self):
        self.assertEqual(news._day_key({"date": "3일 전 09:00"}), "3일 전")
        self.assertEqual(news._day_key({"date": "오늘 14:30"}), "오늘")


SAMPLE_ARTICLES = [
    ("삼성전자, HBM4 양산 앞당긴다…엔비디아 공급 협상",
     "삼성전자가 고대역폭메모리 양산을 앞당긴다. AI 반도체 수요에 대응한다."),
    ("SK하이닉스·TSMC, AI 데이터센터용 반도체 동맹",
     "AI 데이터센터 시장을 겨냥해 파운드리 공정 기술을 공유한다."),
    ("포스코, 수소환원제철 실증 착수…탄소중립 앞당긴다",
     "포스코가 수소 기반 제철 공정 실증에 들어갔다."),
    ("산업통상자원부, 자율제조 확산에 2조 투입…스마트팩토리 1만곳",
     "제조 AI와 로봇을 결합한 자율제조 확산 계획. 디지털전환 지원도 늘린다."),
    ("두산에너빌리티, SMR 주기기 수주…원자력 수출 확대",
     "소형모듈원자로 주기기를 수주했다. 원전 수출 밸류체인이 넓어진다."),
    ("한국전력, 전력망 확충에 10조…데이터센터 수요 대응",
     "AI 데이터센터 전력 수요에 대응해 송배전 전력망을 확충한다."),
]


def _sample_items() -> list[dict]:
    return [{"title": title, "summary": summary, "matched_keywords": []}
            for title, summary in SAMPLE_ARTICLES]


class NewsExtractionTests(unittest.TestCase):
    """지식맵 재료 추출 — '지식맵이 빈약하다'의 원인이던 부분."""

    def test_tech_terms_come_from_the_article_not_just_the_search_word(self):
        techs = news.extract_techs("삼성전자, HBM4 양산…AI 반도체 수요 급증", limit=5)
        self.assertIn("HBM", techs)
        self.assertIn("반도체", techs)

    def test_unknown_tech_terms_are_picked_up_by_suffix(self):
        techs = news.extract_techs("정부, 차세대소재 산업 육성책 발표", limit=5)
        self.assertTrue(any("소재" in term for term in techs))

    def test_summary_is_searched_too_not_only_the_title(self):
        orgs = news.extract_orgs("친환경 전환 가속", limit=4)
        self.assertEqual(orgs, [])
        both = news.extract_orgs("친환경 전환 가속 포스코가 실증에 들어갔다", limit=4)
        self.assertIn("포스코", both)

    def test_tech_terms_are_not_mistaken_for_organisations(self):
        """'수소환원제철' 은 접미사 '제철' 때문에 기관으로 잡히던 말이다."""
        self.assertNotIn("수소환원제철",
                         news.extract_orgs("포스코, 수소환원제철 실증 착수", limit=4))

    def test_parent_and_subsidiary_names_do_not_split_into_two_nodes(self):
        orgs = news.extract_orgs("두산에너빌리티, SMR 주기기 수주", limit=4)
        self.assertIn("두산에너빌리티", orgs)
        self.assertNotIn("두산", orgs)

    def test_english_acronyms_match_when_a_korean_particle_follows(self):
        r"""파이썬 `\b` 는 한글도 낱말 문자로 봐서 'AI가' 의 AI 를 놓친다."""
        self.assertIn("AI", news.extract_techs("AI가 산업 지형을 바꾼다", limit=5))
        self.assertIn("ESG", news.extract_techs("ESG는 이제 필수다", limit=5))
        self.assertIn("KT", news.extract_orgs("KT가 데이터센터를 늘린다", limit=4))

    def test_versioned_acronyms_are_recognised(self):
        self.assertIn("HBM", news.extract_techs("HBM4 양산 경쟁", limit=5))


class NewsGraphRichnessTests(unittest.TestCase):
    def test_graph_is_richer_than_the_search_keywords(self):
        """예전에는 기술 노드 = 검색어뿐이라 노드가 서너 개에 그쳤다."""
        graph = news.build_graph(_sample_items(), "1팀_AI데이터센터")
        techs = [n for n in graph["nodes"] if n["type"] == "tech"]
        orgs = [n for n in graph["nodes"] if n["type"] == "company"]
        self.assertGreaterEqual(len(techs), 8)
        self.assertGreaterEqual(len(orgs), 5)
        self.assertGreater(len(graph["links"]), len(graph["nodes"]) // 2)

    def test_co_occurrence_edges_need_two_articles(self):
        """한 기사에서 우연히 겹친 것만으로 선을 긋지 않는다."""
        graph = news.build_graph(_sample_items(), "1팀")
        for link in graph["links"]:
            if link["relation_type"] == "co_occurrence":
                self.assertGreaterEqual(link["weight"], 2)

    def test_no_node_is_left_floating(self):
        graph = news.build_graph(_sample_items(), "1팀")
        linked = {end for link in graph["links"] for end in (link["source"], link["target"])}
        for node in graph["nodes"]:
            if node["id"] != "us":
                self.assertIn(node["id"], linked, f"{node['id']} 노드가 어디에도 연결되지 않았다")

    def test_report_keywords_stay_in_the_map_even_if_rare(self):
        items = _sample_items()
        items[0]["matched_keywords"] = ["희귀검색어"]
        graph = news.build_graph(items, "1팀", max_techs=3)
        self.assertIn("t:희귀검색어", {node["id"] for node in graph["nodes"]})

    def test_graph_uses_the_top_ten_articles(self):
        self.assertEqual(news.GRAPH_ARTICLES, 10)


class NewsGraphLinkTests(unittest.TestCase):
    def test_graph_center_uses_the_exact_search_keyword(self):
        keyword = "AI 데이터센터 전력 인프라 동향"
        result = {
            "items": [{
                "title": "AI 데이터센터 전력 수요 확대",
                "keyword": keyword,
                "matched_keywords": [keyword],
            }]
        }

        response = _with_sort(result, "accuracy", 10, keyword)
        center = next(node for node in response["graph"]["nodes"] if node["id"] == "us")

        self.assertEqual(response["graph_keyword"], keyword)
        self.assertEqual(center["label"], keyword)
        self.assertNotIn("검색", center["label"])

    def test_direct_search_articles_create_a_linked_graph(self):
        graph = build_graph([
            {
                "title": "포스코, 자율제조 AI 플랫폼 확대",
                "keyword": "자율제조",
                "matched_keywords": ["자율제조"],
            }
        ], "자율제조")
        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertIn("us", node_ids)
        self.assertIn("t:자율제조", node_ids)
        self.assertTrue(any(link["source"] == "us" and link["target"] == "t:자율제조"
                            for link in graph["links"]))

    def test_articles_and_nodes_index_each_other(self):
        """기사 → 노드, 노드 → 기사 양쪽 색인이 있어야 화면에서 서로 하이라이트된다."""
        items = [
            {"title": "삼성전자, 자율제조 라인 확대", "matched_keywords": ["자율제조"]},
            {"title": "환율 급등에 수출기업 비상", "matched_keywords": []},
            {"title": "포스코, 자율제조 운영체계 도입", "matched_keywords": ["자율제조"]},
        ]
        graph = build_graph(items, "스마트제조")

        self.assertIn("t:자율제조", items[0]["node_ids"])
        self.assertIn("c:삼성전자", items[0]["node_ids"])
        self.assertEqual(items[1]["node_ids"], [])

        tech = [n for n in graph["nodes"] if n["id"] == "t:자율제조"][0]
        self.assertEqual(tech["articles_idx"], [0, 2])

    def test_article_node_ids_never_point_at_dropped_nodes(self):
        """상위 노드 수 제한에 걸려 잘린 기업은 기사 색인에서도 빠져야 한다."""
        items = [{"title": f"{name}, 자율제조 도입", "matched_keywords": ["자율제조"]}
                 for name in ("삼성전자", "SK하이닉스", "LG전자", "현대자동차", "포스코")]
        graph = build_graph(items, "스마트제조", max_orgs=2)
        live = {node["id"] for node in graph["nodes"]}
        for item in items:
            for node_id in item["node_ids"]:
                self.assertIn(node_id, live)


if __name__ == "__main__":
    unittest.main()
