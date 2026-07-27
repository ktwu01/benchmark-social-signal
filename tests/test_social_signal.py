import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

MODULE_PATH = Path(__file__).parents[1] / "src" / "social_signal.py"
SPEC = importlib.util.spec_from_file_location("social_signal", MODULE_PATH)
assert SPEC and SPEC.loader
social_signal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(social_signal)


def config():
    return json.loads(Path("config.json").read_text(encoding="utf-8"))["hacker_news"]


def fixture_fetcher(_url, _params):
    return json.loads(Path("tests/fixtures/hn.json").read_text(encoding="utf-8"))


def test_public_collector_emits_attention_observation():
    observations, health = social_signal.collect_hacker_news(
        config(),
        datetime(2026, 7, 27, 12, tzinfo=UTC),
        fetcher=fixture_fetcher,
    )

    assert health == {
        "source": "Hacker News",
        "ok": True,
        "item_count": 1,
        "error": None,
    }
    assert len(observations) == 1
    observation = observations[0]
    assert observation["id"] == "hacker-news:12345"
    assert observation["url"] == "https://news.ycombinator.com/item?id=12345"
    assert observation["primary_artifact_url"] == "https://example.org/benchmark"
    assert observation["categories"] == ["benchmark", "evaluation"]
    assert observation["metrics"] == {
        "comments": 12.0,
        "points": 43.0,
        "submissions": 2.0,
    }
    assert observation["supporting_observations"] == [
        {
            "source_id": "12346",
            "url": "https://news.ycombinator.com/item?id=12346",
            "published_at": "2026-07-27T09:00:00+00:00",
            "metrics": {"points": 1.0, "comments": 0.0},
            "primary_artifact_url": "https://mirror.example.org/benchmark",
        }
    ]
    assert any("not scientific-quality evidence" in reason for reason in observation["rationale"])
    assert any("Clustered 2 public submissions" in reason for reason in observation["rationale"])


def test_title_normalization_is_exact_but_punctuation_insensitive():
    assert social_signal.normalized_title(
        "DeepSWE – Best Benchmark?"
    ) == social_signal.normalized_title("DeepSWE: Best Benchmark!")


def test_empty_result_is_healthy():
    observations, health = social_signal.collect_hacker_news(
        config(),
        datetime(2026, 7, 27, 12, tzinfo=UTC),
        fetcher=lambda _url, _params: {"hits": []},
    )

    assert observations == []
    assert health["ok"] is True
    assert health["item_count"] == 0


def test_failure_does_not_look_like_empty_success():
    def fail(_url, _params):
        raise TimeoutError("fixture timeout")

    observations, health = social_signal.collect_hacker_news(
        config(),
        datetime(2026, 7, 27, 12, tzinfo=UTC),
        fetcher=fail,
    )

    assert observations == []
    assert health["ok"] is False
    assert "TimeoutError" in health["error"]


def test_checked_in_feed_matches_public_contract():
    schema = json.loads(
        Path("schema/public-observation-feed.schema.json").read_text(encoding="utf-8")
    )
    feed = json.loads(Path("feed.json").read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(feed)
