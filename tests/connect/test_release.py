"""Which installed version a client's entry may pin: only a published release."""

from importlib.metadata import PackageNotFoundError

import pytest

from incognito_sql.connect import release as module


class _Dist:
    def __init__(self, version: str, direct: str | None) -> None:
        self.version, self._direct = version, direct

    def read_text(self, name: str) -> str | None:
        return self._direct if name == "direct_url.json" else None


@pytest.mark.parametrize(
    ("version", "direct", "pinned"),
    [
        ("0.4.0", None, "0.4.0"),
        ("0.4.0", '{"url": "file:///x", "dir_info": {"editable": true}}', None),
        ("0.0.0", None, None),
        ("0.5.0.dev3", None, None),
        ("0.4.0+local", None, None),
        ("0.4.0", "[1, 2]", "0.4.0"),
        ("0.4.0", '"text"', "0.4.0"),
        ("0.4.0", '{"dir_info": []}', "0.4.0"),
        ("0.4.0", "not json", None),
    ],
)
def test_only_a_release_is_pinned(
    version: str, direct: str | None, pinned: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "distribution", lambda _: _Dist(version, direct))
    assert module.release() == pinned


def test_no_installation_is_no_release(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_: str) -> object:
        raise PackageNotFoundError

    monkeypatch.setattr(module, "distribution", missing)
    assert module.release() is None
