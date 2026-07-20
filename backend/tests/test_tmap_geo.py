from app.services.tmap_geo import match_coords_to_roads


def test_match_coords_to_roads_returns_more_points(monkeypatch):
    from app.services import tmap_geo

    sparse = [(37.5012, 127.0499), (37.4989686, 127.0525688)]
    dense = [
        (37.5012, 127.0499),
        (37.5009, 127.0503),
        (37.5004, 127.0510),
        (37.4995, 127.0520),
        (37.4989686, 127.0525688),
    ]

    monkeypatch.setattr(tmap_geo.settings, "tmap_road_match_enabled", True)

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "resultData": {
                    "matchedPoints": [
                        {"matchedLocation": {"latitude": lat, "longitude": lng}}
                        for lat, lng in dense
                    ]
                }
            }

    monkeypatch.setattr(tmap_geo.requests, "post", lambda *args, **kwargs: FakeResp())

    result = match_coords_to_roads(sparse)
    assert len(result) > len(sparse)
