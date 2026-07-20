from app.services.geocoding import geocode


def test_geocode_demo_dict_before_tmap(monkeypatch):
    from app.services import geocoding

    monkeypatch.setattr(geocoding.settings, "tmap_app_key", "fake-key")

    def fail_poi(*args, **kwargs):
        raise AssertionError("POI should not be called for demo dict names")

    monkeypatch.setattr(geocoding, "search_poi", fail_poi)

    hit = geocode("필수학학원")
    assert hit is not None
    assert hit.source == "DEMO_DICT"
    assert hit.label == "필수학학원"
