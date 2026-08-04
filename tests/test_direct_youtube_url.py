from app.service_queue import _direct_youtube_url


def test_standard_youtube_watch_url_is_direct_source():
    url = "https://www.youtube.com/watch?v=TAYZX0xJrjc"
    assert _direct_youtube_url(url) == url


def test_short_and_mobile_youtube_urls_are_supported():
    short = "https://youtu.be/TAYZX0xJrjc"
    mobile = "https://m.youtube.com/watch?v=TAYZX0xJrjc"
    assert _direct_youtube_url(short) == short
    assert _direct_youtube_url(mobile) == mobile


def test_plain_search_text_and_other_domains_are_not_direct_sources():
    assert _direct_youtube_url("Will Tura - Viva El Amor") is None
    assert _direct_youtube_url("https://example.com/watch?v=TAYZX0xJrjc") is None
