import incognito_sql


def test_package_exposes_version() -> None:
    assert incognito_sql.__version__ == "0.0.0"
