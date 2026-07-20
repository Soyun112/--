from app.services import tmap_quota


def test_cached_api_call_uses_cache_without_second_fetch(monkeypatch):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(tmap_quota.settings, "tmap_daily_limit_route", 1000)
    monkeypatch.setattr(tmap_quota.settings, "tmap_daily_reserve_route", 0)
    monkeypatch.setattr(tmap_quota.settings, "tmap_cache_ttl_route_s", 3600)

    first = tmap_quota.cached_api_call(
        cache_key="test:route:1",
        category="route",
        ttl_seconds=3600,
        fetch=fetch,
    )
    second = tmap_quota.cached_api_call(
        cache_key="test:route:1",
        category="route",
        ttl_seconds=3600,
        fetch=fetch,
    )

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert calls["n"] == 1
    assert tmap_quota.usage_snapshot()["route"] == 1


def test_can_use_respects_reserve(monkeypatch):
    monkeypatch.setattr(tmap_quota.settings, "tmap_daily_limit_route", 100)
    monkeypatch.setattr(tmap_quota.settings, "tmap_daily_reserve_route", 10)
    tmap_quota._counts["route"] = 90
    assert tmap_quota.can_use("route") is False
    tmap_quota._counts["route"] = 89
    assert tmap_quota.can_use("route") is True
