"""Shared rejection of recognizable default artwork URLs."""
from urllib.parse import unquote, urlsplit


def is_placeholder_url(url: str) -> bool:
    path = unquote(urlsplit(str(url or '').strip()).path).lower()
    parts = path.strip('/').split('/')
    name = parts[-1].rsplit('.', 1)[0]
    return ('placeholder' in parts or 'placeholders' in parts
            or name in {'placeholder', 'no-cover', 'no_cover', 'nocover',
                        'no-image', 'no_image', 'noimage', 'default-cover'}
            or ('generic' in parts and name in {'title-small', 'title', 'title-large'}))
