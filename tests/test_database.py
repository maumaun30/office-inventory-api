import pytest

from app.database import normalize_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///./inventory.db", "sqlite:///./inventory.db"),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected
