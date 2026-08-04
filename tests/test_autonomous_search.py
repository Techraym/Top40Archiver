from app.downloader import _candidate_score, _unique_queries


def test_autonomous_queries_start_broad_and_include_canonical_metadata():
    queries = _unique_queries(
        "Original Artist",
        "Song Title (Radio Edit)",
        "Original Artist - Song Title official audio",
        "Canonical Artist",
        "Canonical Song",
    )

    assert queries[0] == "Canonical Artist - Canonical Song"
    assert "Canonical Artist - Canonical Song official audio" in queries
    assert "Original Artist - Song Title (Radio Edit)" in queries
    assert "Original Artist - Song Title" in queries
    assert len(queries) <= 20
    assert len({query.casefold() for query in queries}) == len(queries)


def test_official_audio_suffix_is_not_the_primary_search():
    queries = _unique_queries(
        "Will Tura",
        "Viva El Amor",
        "Will Tura - Viva El Amor official audio",
        None,
        None,
    )

    assert queries[0] == "Will Tura - Viva El Amor"
    assert "Will Tura - Viva El Amor official audio" in queries
    assert queries.index("Will Tura - Viva El Amor") < queries.index(
        "Will Tura - Viva El Amor official audio"
    )


def test_compound_historical_credits_are_searched_as_matching_pairs():
    queries = _unique_queries(
        "Duo Acropolis / Trio Hellenique / Mikis Theodorakis",
        "Zorba Le Grec / La Danse De Zorba / Sirtaki",
        "",
        None,
        None,
    )

    assert queries[0] == "Duo Acropolis - Zorba Le Grec"
    assert "Trio Hellenique - La Danse De Zorba" in queries
    assert "Mikis Theodorakis - Sirtaki" in queries


def test_conductor_credit_gets_a_broader_artist_variant():
    queries = _unique_queries(
        "Bob Smit en het Duke City Sextet o.l.v. Jan Blaaser",
        "Ik Heb Me Weer Vergist",
        "",
        None,
        None,
    )

    assert (
        "Bob Smit en het Duke City Sextet - Ik Heb Me Weer Vergist"
        in queries
    )


def test_single_internal_slash_in_artist_name_is_not_split():
    queries = _unique_queries(
        "AC/DC",
        "T.N.T.",
        "",
        None,
        None,
    )

    assert queries[0] == "AC/DC - T.N.T."


def test_candidate_score_rewards_exact_official_audio_and_duration():
    candidate = {
        "title": "Artist Name - Hit Title (Official Audio)",
        "channel": "Artist Name - Topic",
        "duration": 183,
    }

    score = _candidate_score("Artist Name", "Hit Title", candidate, 181_000)
    assert score >= 0.80


def test_candidate_score_penalizes_unrequested_live_version():
    normal = {
        "title": "Artist Name - Hit Title",
        "channel": "Artist Name - Topic",
        "duration": 183,
    }
    live = {
        "title": "Artist Name - Hit Title Live",
        "channel": "Random Channel",
        "duration": 245,
    }

    assert _candidate_score("Artist Name", "Hit Title", normal, 181_000) > _candidate_score(
        "Artist Name", "Hit Title", live, 181_000
    )
