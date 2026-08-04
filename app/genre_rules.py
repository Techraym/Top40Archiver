from __future__ import annotations

import re
from typing import Optional

# Deze regels zijn gelijkgetrokken met Techraym/GenreSplitter.
# De output blijft bewust beperkt tot een voorspelbare set hoofdmappen.

GENRE_SIMPLIFY: dict[str, str] = {
    "alternative rock": "Alternative Rock",
    "progressive rock": "Progressive Rock",
    "stage and screen": "Soundtrack",
    "stage & screen": "Soundtrack",
    "drum and bass": "Drum & Bass",
    "hardcore punk": "Hardcore Punk",
    "classic rock": "Classic Rock",
    "thrash metal": "Thrash Metal",
    "black metal": "Black Metal",
    "death metal": "Death Metal",
    "drum & bass": "Drum & Bass",
    "funk / soul": "Soul",
    "gangsta rap": "Rap",
    "garage rock": "Garage Rock",
    "heavy metal": "Heavy Metal",
    "post-grunge": "Post-Grunge",
    "smooth jazz": "Jazz",
    "spoken word": "Spoken",
    "children's": "Children",
    "deep house": "House",
    "doom metal": "Doom Metal",
    "electronic": "Electronic",
    "electropop": "Electropop",
    "indie folk": "Folk",
    "indie rock": "Indie Rock",
    "soundtrack": "Soundtrack",
    "tech house": "House",
    "acid jazz": "Acid Jazz",
    "classical": "Classical",
    "dance pop": "Dance-Pop",
    "dance-pop": "Dance-Pop",
    "dutch pop": "Nederpop",
    "eurodance": "Electronic",
    "hard rock": "Hard Rock",
    "hardstyle": "Electronic",
    "metalcore": "Metalcore",
    "non-music": "Spoken",
    "orchestra": "Classical",
    "post punk": "Post-Punk",
    "post-punk": "Post-Punk",
    "post-rock": "Post-Rock",
    "prog rock": "Progressive Rock",
    "punk rock": "Punk-Rock",
    "punk-rock": "Punk-Rock",
    "synth pop": "Synthpop",
    "synth-pop": "Synthpop",
    "alt rock": "Alternative Rock",
    "hollands": "Nederpop",
    "nederpop": "Nederpop",
    "new wave": "New Wave",
    "nu metal": "Nu Metal",
    "pop punk": "Pop-Punk",
    "pop rock": "Pop-Rock",
    "pop-punk": "Pop-Punk",
    "pop-rock": "Pop-Rock",
    "schlager": "Pop",
    "ska punk": "Ska-Punk",
    "ska-punk": "Ska-Punk",
    "symphony": "Classical",
    "synthpop": "Synthpop",
    "teen pop": "Pop",
    "ambient": "Ambient",
    "country": "Country",
    "dubstep": "Electronic",
    "hip hop": "Hip-Hop",
    "hip-hop": "Hip-Hop",
    "grunge": "Grunge",
    "hiphop": "Hip-Hop",
    "reggae": "Reggae",
    "techno": "Techno",
    "trance": "Trance",
    "blues": "Blues",
    "disco": "Disco",
    "house": "House",
    "k-pop": "Pop",
    "latin": "Latin",
    "metal": "Metal",
    "opera": "Classical",
    "score": "Soundtrack",
    "world": "World",
    "folk": "Folk",
    "funk": "Funk",
    "jazz": "Jazz",
    "kpop": "Pop",
    "rock": "Rock",
    "soul": "Soul",
    "trap": "Trap",
    "dnb": "Drum & Bass",
    "dub": "Dub",
    "edm": "Electronic",
    "pop": "Pop",
    "r&b": "R&B",
    "rap": "Rap",
    "rnb": "R&B",
    "ska": "Ska",
    "piratenmuziek": "Piratenmuziek",
    "piraten hits": "Piratenmuziek",
    "piratenhits": "Piratenmuziek",
    "piratenzender": "Piratenmuziek",
    "piraten zender": "Piratenmuziek",
    "geheime zender": "Piratenmuziek",
}

PIRATEN_STRONG_KEYWORDS = {
    "piratenmuziek",
    "piratenhits",
    "piraten hits",
    "piraat",
    "piraten",
    "piratenzender",
    "geheime zender",
    "piratenmedley",
    "piraten medley",
}

PIRATEN_CONTEXT_KEYWORDS = {
    "nederlandstalig",
    "hollands",
    "volksmuziek",
    "levenslied",
    "smartlap",
    "schlager",
    "duitse schlager",
    "feest",
    "party",
    "polka",
}

PIRATEN_SEED_ARTISTS = {
    "jannes",
    "frans bauer",
    "henk wijngaard",
    "marianne weber",
    "stef ekkel",
    "koos alberts",
    "rene riva",
    "grad damen",
    "thomas berge",
    "dries roelvink",
    "monique smit",
    "rene schuurmans",
    "helemaal hollands",
    "albert west",
    "mooi wark",
    "frank van etten",
    "django wagner",
    "mart hoogkamer",
}

CHRISTMAS_KEYWORDS = (
    "christmas",
    "xmas",
    "merry christmas",
    "jingle bells",
    "we wish you",
    "noel",
    "noël",
    "kerst",
    "kerstmis",
    "navidad",
    "weihnachten",
    "natale",
    "white christmas",
    "silent night",
    "santa claus",
)


def _norm_text(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[\u2019\u2018\u201c\u201d]", "'", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def piratenmuziek_score(
    artist: str,
    title: str,
    raw_genre: Optional[str] = None,
) -> int:
    artist_norm = _norm_text(artist)
    text = f"{artist_norm} {_norm_text(title)} {_norm_text(raw_genre or '')}".strip()
    score = 0

    if any(keyword in text for keyword in PIRATEN_STRONG_KEYWORDS):
        score += 6
    if any(seed and seed in artist_norm for seed in PIRATEN_SEED_ARTISTS):
        score += 6
    if any(keyword in text for keyword in PIRATEN_CONTEXT_KEYWORDS):
        score += 2
    if ("schlager" in text or "volks" in text) and (
        "nederland" in text or "hollands" in text
    ):
        score += 1
    return score


def is_piratenmuziek(
    artist: str,
    title: str,
    raw_genre: Optional[str] = None,
    threshold: int = 6,
) -> bool:
    return piratenmuziek_score(artist, title, raw_genre) >= int(threshold)


def normalize_genre(value: str | None) -> str:
    """Pas exact dezelfde gesloten hoofdgenre-regels toe als GenreSplitter."""
    if not value:
        return "Other"

    normalized = str(value).strip().lower()
    if not normalized:
        return "Other"

    normalized = (
        normalized.replace("_", " ")
        .replace("/", " ")
        .replace("-", " ")
        .replace(".", " ")
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()

    special_cases = {
        "folk pop": "Pop",
        "pop punk": "Punk",
        "punk rock": "Punk",
        "alternative rock": "Alternative",
        "indie rock": "Indie",
        "k pop": "K-Pop",
        "kpop": "K-Pop",
        "hip hop": "Hip-Hop",
        "hiphop": "Hip-Hop",
        "indie pop": "Pop",
        "dutch indie": "Indie",
        "indie folk": "Folk",
        "singer songwriter": "Pop",
        "singer songwriters": "Pop",
    }
    if normalized in special_cases:
        return special_cases[normalized]

    if "metal" in normalized:
        return "Metal"
    if "hard rock" in normalized:
        return "Rock"

    tokens = [token for token in normalized.split(" ") if token]
    token_set = set(tokens)

    if "edm" in token_set:
        return "EDM"
    if "club" in token_set:
        return "Club"
    if "hardcore" in token_set:
        return "Hardcore"

    last = tokens[-1] if tokens else normalized
    if last == "trance" or last.endswith("trance"):
        return "Trance"
    if last == "house" or last.endswith("house"):
        return "House"

    suffix_map = (
        ("classical", "Classical"),
        ("country", "Country"),
        ("reggae", "Reggae"),
        ("latin", "Latin"),
        ("blues", "Blues"),
        ("jazz", "Jazz"),
        ("folk", "Folk"),
        ("punk", "Punk"),
        ("rock", "Rock"),
        ("dance", "Dance"),
        ("indie", "Indie"),
        ("alternative", "Alternative"),
        ("rap", "Rap"),
        ("pop", "Pop"),
    )
    for suffix, output in suffix_map:
        if last == suffix or last.endswith(suffix):
            return output

    return "Other"


def is_christmas_track(artist: str, title: str, genre: Optional[str]) -> bool:
    if genre and normalize_genre(genre) == "Christmas":
        return True
    text = f"{artist} {title}".lower()
    return any(keyword in text for keyword in CHRISTMAS_KEYWORDS)


def guess_genre_from_keywords(artist: str, title: str) -> Optional[str]:
    text = f"{artist} {title}".lower()
    if is_piratenmuziek(artist, title, raw_genre=text, threshold=6):
        return "Piratenmuziek"
    if any(keyword in text for keyword in CHRISTMAS_KEYWORDS):
        return "Christmas"
    for keyword, genre in GENRE_SIMPLIFY.items():
        if keyword in text:
            return genre
    return None


def final_genre(artist: str, title: str, raw_genre: str | None) -> str:
    genre = normalize_genre(raw_genre)
    if is_piratenmuziek(artist, title, raw_genre=raw_genre, threshold=6):
        genre = "Piratenmuziek"
    if is_christmas_track(artist, title, genre):
        genre = "Christmas"
    return genre


def artist_bucket(artist: str) -> str:
    value = str(artist or "").strip()
    if not value:
        return "!-?"
    first = value[0].upper()
    if first.isdigit():
        return "0-9"
    if "A" <= first <= "Z":
        return first
    return "!-?"
