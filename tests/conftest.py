"""Historical HTTP tests exercise the retained legacy feature flag with their original fakes."""
import pytest


@pytest.fixture(autouse=True)
def legacy_http_contract(request, monkeypatch):
    if request.module.__name__ in {'test_main', 'test_door', 'test_kinds', 'test_trips'}:
        import main
        monkeypatch.setattr(main, 'CATALOG_ENABLED', False)
