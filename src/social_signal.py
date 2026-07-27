from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import certifi

USER_AGENT = "benchmark-social-signal/0.1 (+https://github.com/ktwu01/benchmark-social-signal)"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(
        request,
        timeout=30,
        context=ssl.create_default_context(cafile=certifi.where()),
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def match_categories(title: str, taxonomy: dict[str, list[str]]) -> list[str]:
    haystack = title.lower()
    return sorted(
        category
        for category, terms in taxonomy.items()
        if any(term.lower() in haystack for term in terms)
    )


def normalized_title(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.casefold()))


def _attention_total(observation: dict[str, Any]) -> float:
    metrics = observation["metrics"]
    return float(metrics.get("points", 0)) + float(metrics.get("comments", 0))


def cluster_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for observation in observations:
        key = (observation["source"], normalized_title(observation["title"]))
        groups.setdefault(key, []).append(observation)

    clustered: list[dict[str, Any]] = []
    for group in groups.values():
        primary = max(
            group,
            key=lambda value: (
                _attention_total(value),
                value["published_at"],
                value["source_id"],
            ),
        )
        result = {
            **primary,
            "categories": sorted({category for value in group for category in value["categories"]}),
            "metrics": {
                "points": sum(float(value["metrics"].get("points", 0)) for value in group),
                "comments": sum(float(value["metrics"].get("comments", 0)) for value in group),
                "submissions": float(len(group)),
            },
            "rationale": sorted({reason for value in group for reason in value["rationale"]}),
        }
        supporting = sorted(
            (value for value in group if value["source_id"] != primary["source_id"]),
            key=lambda value: (value["published_at"], value["source_id"]),
            reverse=True,
        )
        if supporting:
            result["rationale"].append(
                f"Clustered {len(group)} public submissions with the same normalized title"
            )
            result["supporting_observations"] = [
                {
                    "source_id": value["source_id"],
                    "url": value["url"],
                    "published_at": value["published_at"],
                    "metrics": value["metrics"],
                    **(
                        {"primary_artifact_url": value["primary_artifact_url"]}
                        if value.get("primary_artifact_url")
                        else {}
                    ),
                }
                for value in supporting
            ]
        clustered.append(result)
    return sorted(
        clustered,
        key=lambda value: (value["published_at"], value["source_id"]),
        reverse=True,
    )


def collect_hacker_news(
    config: dict[str, Any],
    now: datetime,
    fetcher: Callable[[str, dict[str, Any]], dict[str, Any]] = fetch_json,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    since = now - timedelta(hours=int(config.get("lookback_hours", 72)))
    limit = min(int(config.get("items_per_query", 30)), 100)
    found: dict[str, dict[str, Any]] = {}
    try:
        for query in config["queries"]:
            payload = fetcher(
                HN_SEARCH_URL,
                {
                    "query": query,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{int(since.timestamp())}",
                    "hitsPerPage": limit,
                },
            )
            for hit in payload.get("hits", []):
                source_id = str(hit.get("objectID") or "")
                title = str(hit.get("title") or "").strip()
                created_at = hit.get("created_at")
                if not source_id or not title or not created_at:
                    continue
                published = parse_time(str(created_at))
                if published < since:
                    continue
                categories = match_categories(title, config["taxonomy"])
                if not categories:
                    continue
                discussion_url = f"https://news.ycombinator.com/item?id={source_id}"
                artifact_url = hit.get("url")
                rationale = [
                    f"Public Hacker News story matched query: {query}",
                    "Attention signal only; not scientific-quality evidence",
                ]
                observation = found.get(source_id)
                if observation:
                    observation["categories"] = sorted(
                        set(observation["categories"]) | set(categories)
                    )
                    observation["rationale"] = sorted(
                        set(observation["rationale"]) | set(rationale)
                    )
                    continue
                observation = {
                    "id": f"hacker-news:{source_id}",
                    "source": "Hacker News",
                    "source_id": source_id,
                    "title": title,
                    "url": discussion_url,
                    "published_at": published.isoformat(),
                    "discovered_at": now.astimezone(UTC).isoformat(),
                    "summary": (
                        f"Public Hacker News discussion linking to "
                        f"{urllib.parse.urlsplit(artifact_url).netloc}."
                        if isinstance(artifact_url, str)
                        and artifact_url.startswith(("https://", "http://"))
                        else "Public discussion submitted to Hacker News."
                    ),
                    "event_kind": "discussed",
                    "categories": categories,
                    "metrics": {
                        "points": float(hit.get("points") or 0),
                        "comments": float(hit.get("num_comments") or 0),
                    },
                    "rationale": rationale,
                }
                if isinstance(artifact_url, str) and artifact_url.startswith(
                    ("https://", "http://")
                ):
                    observation["primary_artifact_url"] = artifact_url
                found[source_id] = observation
    except Exception as error:
        return [], {
            "source": "Hacker News",
            "ok": False,
            "item_count": 0,
            "error": f"{type(error).__name__}: {error}",
        }
    observations = cluster_observations(list(found.values()))
    return observations, {
        "source": "Hacker News",
        "ok": True,
        "item_count": len(observations),
        "error": None,
    }


def build_feed(config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    observations, health = collect_hacker_news(config["hacker_news"], now)
    if not health["ok"]:
        raise RuntimeError(f"Required public source failed: {health['error']}")
    return {
        "schema_version": 1,
        "producer": "benchmark-social-signal",
        "generated_at": now.astimezone(UTC).isoformat(),
        "observations": observations,
        "health": [health],
    }


def write_feed(feed: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(feed, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public benchmark attention signals.")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, default=Path("feed.json"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    feed = build_feed(config)
    write_feed(feed, args.output)
    print(f"Wrote {len(feed['observations'])} public observations to {args.output}")


if __name__ == "__main__":
    main()
