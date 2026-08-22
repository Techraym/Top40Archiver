from app.providers import youtube
from app.providers.base import ProviderConfig


def test_collaboration_query_variants_cover_full_lead_and_slash_credits():
    variants = youtube._query_variants({
        "artist": "Justen De Wildt / Justen De Wildt x Outsiders",
        "title": "Cheerio / Cheerio - Remix",
        "custom_search_query": None,
    })

    folded = [item.casefold() for item in variants]
    assert folded[0].startswith("justen de wildt / justen de wildt x outsiders")
    assert any("outsiders" in item and "cheerio" in item for item in folded)
    assert any(item.startswith("justen de wildt cheerio") for item in folded)
    assert len(variants) <= 6


def test_ft_and_x_artist_metadata_generate_individual_artist_queries():
    anotr = [x.casefold() for x in youtube._query_variants({"artist": "Anotr ft 54 Ultra", "title": "Talk To You"})]
    shakira = [x.casefold() for x in youtube._query_variants({"artist": "Shakira x Burna Boy", "title": "Dai Dai"})]

    assert any(x.startswith("anotr talk to you") for x in anotr)
    assert any(x.startswith("54 ultra talk to you") for x in anotr)
    assert any(x.startswith("shakira dai dai") for x in shakira)
    assert any(x.startswith("burna boy dai dai") for x in shakira)


def test_provider_interleaves_results_from_multiple_queries(monkeypatch):
    calls = []

    def fake_ytdlp(target, **kwargs):
        calls.append(target)
        index = len(calls)
        return {
            "entries": [
                {
                    "id": f"id-{index}-{n}",
                    "url": f"https://www.youtube.com/watch?v=id{index}{n}",
                    "webpage_url": f"https://www.youtube.com/watch?v=id{index}{n}",
                    "title": f"Candidate {index}-{n}",
                    "duration": 180 + n,
                    "uploader": "Artist",
                }
                for n in range(3)
            ]
        }

    monkeypatch.setattr(youtube, "run_ytdlp_json", fake_ytdlp)
    provider = youtube.YouTubeProvider(ProviderConfig(
        name="youtube",
        enabled=True,
        priority=1,
        max_concurrent=1,
        requests_per_minute=3,
        min_delay_seconds=20,
        error_backoff_seconds=120,
    ))

    result = provider.search(
        {"artist": "Shakira x Burna Boy", "title": "Dai Dai"},
        limit=6,
    )

    assert len(calls) >= 3
    assert len(result) == 6
    # First result from each query should get a chance before second-row results.
    assert result[0].title == "Candidate 1-0"
    assert result[1].title == "Candidate 2-0"
    assert result[2].title == "Candidate 3-0"


def test_direct_youtube_download_uses_mweb_client():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "app/providers/youtube.py").read_text(encoding="utf-8")

    assert "youtube:player_client=mweb" in source
    assert "ytdlp_download_original" in source
    assert "extra_args=self.EXTRACTOR_ARGS" in source
