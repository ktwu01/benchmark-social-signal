# Benchmark Social Signal

A small, public-only attention feed for
[Benchmark Radar](https://github.com/ktwu01/benchmark-radar).

The collector currently scans public Hacker News stories for benchmark, evaluation,
dataset, and data-quality terms. It publishes normalized observations to
[`feed.json`](feed.json), which Benchmark Radar loads into its Explorer as
**attention signals**.

## Boundaries

- Public, anonymous endpoints only
- No cookies, browser profiles, logged-in sessions, or private posts
- No LinkedIn or X scraping
- No claim that popularity equals scientific quality
- No repository secrets required
- Source text is exported as data, never as executable HTML

The main radar keeps primary artifacts and scientific evidence separate. A social
observation can help discover a work, but it does not increase that work's quality score.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python src/social_signal.py
```

The scheduled workflow refreshes `feed.json` once per day. Failed collection stops the
update instead of replacing the last healthy feed with an empty result.

## Feed contract

The feed implements schema version 1 from
[`schema/public-observation-feed.schema.json`](schema/public-observation-feed.schema.json).
Each observation retains its public source, timestamps, attention metrics, matching
rationale, and primary artifact link when the submitted story has one.

## License

MIT
