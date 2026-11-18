from decimal import Decimal
from unittest.mock import patch

import polyline
import requests
from rest_framework.test import APITestCase
from django.test import SimpleTestCase

from .models import FuelStation


class RouteMatchingAccuracyTests(SimpleTestCase):
    def assert_matches_full_scan(self, points, stations, limits):
        from .route_geometry import (
            _route_segment_blocks, _nearby_segment_indices,
            distances_along_route, find_station_position,
        )
        distances = distances_along_route(points)
        blocks = _route_segment_blocks(points)
        for station in stations:
            expected = find_station_position(station, points, distances)
            for limit in limits:
                with self.subTest(station=station, limit=limit):
                    actual = find_station_position(
                        station, points, distances,
                        segment_indices=_nearby_segment_indices(station, blocks, limit),
                    )
                    if expected[0] <= limit:
                        self.assertEqual(actual, expected)
                    else:
                        self.assertGreater(actual[0], limit)

    def test_curves_repeated_points_and_block_boundaries_match_full_scan(self):
        import math
        import random

        rng = random.Random(71)
        points = [(-118 + i * .003, 34 + .02 * math.sin(i / 6)) for i in range(130)]
        points.insert(32, points[31])
        points += list(reversed(points[20:50]))
        stations = [points[0], points[31], points[32], points[64], points[-1]]
        stations += [(rng.uniform(-118.2, -117.4), rng.uniform(33.9, 34.1)) for _ in range(45)]
        self.assert_matches_full_scan(points, stations, [0, 3, 5, 20])

    def test_long_segment_middle_is_kept_at_high_latitude(self):
        self.assert_matches_full_scan(
            [(-155, 70), (-145, 70)],
            [(-150, 70), (-150, 70.05), (-150, 70.08), (-155.1, 70)],
            [0, 3, 5],
        )

    def test_five_mile_boundary_is_not_lost_by_bounding_boxes(self):
        import math

        latitude_margin = math.degrees(5 / 3958.8)
        self.assert_matches_full_scan(
            [(-118, 34), (-114, 34)],
            [(-116, 34 + latitude_margin * scale) for scale in (.999999, 1, 1.000001)],
            [5],
        )


class PlanRouteTests(APITestCase):
    def setUp(self):
        self.route = {
            "routes": [{
                "geometry": polyline.encode([(-118, 34), (-114, 34)], geojson=True),
                "summary": {"distance": 370000, "duration": 15000},
            }],
            "metadata": {"service": "routing"},
        }
        self.provider = patch("routes.views.get_route_by_names", return_value=self.route)
        self.get_route = self.provider.start()
        self.addCleanup(self.provider.stop)

    def station(self, longitude, price="4.00", name="Test station", latitude=34):
        return FuelStation.objects.create(
            opis_id=FuelStation.objects.count() + 1,
            name=name, address="Test address", city="Test city", state="CA",
            price_per_gallon=Decimal(price), latitude=latitude, longitude=longitude,
        )

    def request_plan(self):
        return self.client.post(
            "/api/plan/", {"start": "Los Angeles", "finish": "Test destination"},
            format="json",
        )

    def test_starting_fuel_estimate_is_included_in_trip_cost(self):
        station = self.station(-116)
        response = self.request_plan()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        plan = body["fuel_plan"]
        self.assertEqual(body["routes"], self.route["routes"])
        self.assertEqual(body["metadata"], self.route["metadata"])
        self.assertEqual(body["route_geojson"], {
            "type": "LineString", "coordinates": [[-118, 34], [-114, 34]],
        })
        self.assertEqual(plan["status"], "estimated")
        self.assertTrue(plan["fuel_pricing_complete"])
        self.assertEqual(plan["unpriced_distance_miles"], 0)
        first_distance = plan["distance_before_first_station_miles"]
        self.assertGreater(first_distance, 0)
        self.assertEqual(plan["estimated_distance_miles"], first_distance)
        self.assertEqual(plan["assumptions"]["starting_fuel_price_per_gallon"], "3.30")
        self.assertAlmostEqual(
            plan["priced_distance_miles"] + plan["unpriced_distance_miles"],
            body["total_distance_miles"],
        )
        self.assertEqual(plan["stops"][0]["station_id"], station.pk)
        self.assertEqual(plan["stops"][0]["longitude"], -116)
        expected_cost = (body["total_distance_miles"] - first_distance) / 10 * 4
        starting_cost = first_distance / 10 * 3.30
        self.assertAlmostEqual(float(plan["cost_before_first_station"]), starting_cost, places=2)
        self.assertEqual(
            Decimal(plan["total_trip_cost"]),
            Decimal(plan["cost_before_first_station"]) + Decimal(plan["cost_from_first_station"]),
        )
        self.assertAlmostEqual(float(plan["cost_from_first_station"]), expected_cost, places=2)
        self.get_route.assert_called_once_with("Los Angeles", "Test destination")

    def test_complete_pricing_and_duplicate_names_preserve_station_identity(self):
        start = self.station(-118, price="4.00")
        later = self.station(-116, price="3.00")
        plan = self.request_plan().json()["fuel_plan"]
        self.assertEqual(plan["status"], "complete")
        self.assertTrue(plan["fuel_pricing_complete"])
        self.assertEqual(plan["unpriced_distance_miles"], 0)
        self.assertEqual(plan["total_trip_cost"], plan["cost_from_first_station"])
        self.assertEqual(plan["cost_before_first_station"], "0.00")
        self.assertEqual([stop["station_id"] for stop in plan["stops"]], [start.pk, later.pk])
        self.assertEqual([stop["longitude"] for stop in plan["stops"]], [-118, -116])

    def test_recorded_jean_to_vegas_subtotal_is_10_93(self):
        rows = [
            ("Terrible Herbst", "3.45900000", 238.6868334833846),
            ("Mortons", "3.39900000", 269.906740731266),
            ("Maverik", "3.35566666", 270.23253022779517),
        ]
        nearby = [
            {
                "station": self.station(-116, price=price, name=name),
                "distance_along_route": distance,
                "distance_from_route": 0.25,
            }
            for name, price, distance in rows
        ]
        with (
            patch("routes.trip_planner.get_stations_along_route", return_value=nearby),
            patch("routes.trip_planner.distances_along_route", return_value=[0, 270.30571096158803]),
        ):
            plan = self.request_plan().json()["fuel_plan"]
        self.assertEqual(plan["cost_from_first_station"], "10.93")
        self.assertEqual(plan["status"], "estimated")
        self.assertGreater(Decimal(plan["total_trip_cost"]), Decimal("10.93"))
        self.assertAlmostEqual(plan["estimated_distance_miles"], 238.6868334833846)
        self.assertEqual(plan["unpriced_distance_miles"], 0)
        self.assertEqual(len(plan["stops"]), 3)

    def test_no_station_returns_route_without_misleading_zero_cost(self):
        response = self.request_plan()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        plan = body["fuel_plan"]
        self.assertEqual(plan["status"], "unavailable")
        self.assertIsNone(plan["total_trip_cost"])
        self.assertIsNone(plan["cost_from_first_station"])
        self.assertEqual(plan["unpriced_distance_miles"], body["total_distance_miles"])
        self.assertEqual(plan["stops"], [])

    def test_station_between_three_and_five_miles_is_included(self):
        station = self.station(-116, latitude=34.06)
        plan = self.request_plan().json()["fuel_plan"]
        self.assertEqual(plan["assumptions"]["max_distance_from_route_miles"], 5)
        self.assertEqual(plan["stops"][0]["station_id"], station.pk)
        self.assertGreater(plan["stops"][0]["distance_from_route_miles"], 3)
        self.assertLess(plan["stops"][0]["distance_from_route_miles"], 5)

    def test_station_more_than_five_miles_away_is_excluded(self):
        self.station(-116, latitude=34.08)
        self.assertEqual(self.request_plan().json()["fuel_plan"]["status"], "unavailable")

    def test_gap_beyond_tank_range_is_unavailable(self):
        self.route["routes"][0]["geometry"] = polyline.encode(
            [(-118, 34), (-104, 34)], geojson=True,
        )
        self.station(-118)
        response = self.request_plan()
        self.assertEqual(response.status_code, 200)
        plan = response.json()["fuel_plan"]
        self.assertEqual(plan["status"], "unavailable")
        self.assertIn("cannot reach", plan["error"])
        self.assertIsNone(plan["total_trip_cost"])
        self.assertEqual(plan["stops"], [])

    def test_estimated_price_does_not_make_distant_first_station_reachable(self):
        self.route["routes"][0]["geometry"] = polyline.encode(
            [(-118, 34), (-104, 34)], geojson=True,
        )
        self.station(-106)
        plan = self.request_plan().json()["fuel_plan"]
        self.assertEqual(plan["status"], "unavailable")
        self.assertIn("beyond the vehicle's range", plan["error"])
        self.assertFalse(plan["fuel_pricing_complete"])
        self.assertIsNone(plan["total_trip_cost"])

    def test_invalid_route_geometry_returns_502(self):
        for geometry in ("", "?", polyline.encode([(0, 0)], geojson=True)):
            with self.subTest(geometry=geometry):
                self.route["routes"][0]["geometry"] = geometry
                self.assertEqual(self.request_plan().status_code, 502)

    def test_existing_input_and_provider_errors(self):
        self.assertEqual(self.client.post("/api/plan/", {}, format="json").status_code, 400)
        self.get_route.assert_not_called()
        for error, expected_status in (
            (ValueError("No result"), 400),
            (requests.Timeout(), 504),
            (requests.ConnectionError(), 502),
        ):
            with self.subTest(error=type(error).__name__):
                self.get_route.side_effect = error
                self.assertEqual(self.request_plan().status_code, expected_status)

    def test_map_page_loads_without_calling_routing_service(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "routes/map.html")
        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertContains(response, 'id="route-form"')
        self.assertContains(response, 'id="map"')
        self.assertContains(response, '/api/plan/')
        self.get_route.assert_not_called()

class CoordinateInputTests(APITestCase):
    def setUp(self):
        self.start = [-118.2437, 34.0522]
        self.finish = [-115.1398, 36.1699]
        self.get_patch = patch("routes.services.requests.get")
        self.post_patch = patch("routes.services.requests.post")
        self.external_get = self.get_patch.start()
        self.external_post = self.post_patch.start()
        self.addCleanup(self.get_patch.stop)
        self.addCleanup(self.post_patch.stop)
        self.external_post.return_value.json.return_value = {
            "routes": [{"geometry": polyline.encode([self.start, self.finish], geojson=True)}],
        }

    def request_plan(self, start, finish):
        return self.client.post("/api/plan/", {"start": start, "finish": finish}, format="json")

    def test_coordinate_request_makes_one_routing_call_without_geocoding(self):
        response = self.request_plan(self.start, self.finish)
        self.assertEqual(response.status_code, 200)
        self.external_get.assert_not_called()
        self.external_post.assert_called_once()
        self.assertEqual(self.external_post.call_args.kwargs["json"], {
            "coordinates": [self.start, self.finish],
        })

    def test_city_names_still_make_two_geocodes_and_one_routing_call(self):
        from unittest.mock import Mock

        self.external_get.side_effect = [
            Mock(ok=True, json=lambda: {"features": [{"geometry": {"coordinates": self.start}}]}),
            Mock(ok=True, json=lambda: {"features": [{"geometry": {"coordinates": self.finish}}]}),
        ]
        response = self.request_plan("Los Angeles, CA", "Las Vegas, NV")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.external_get.call_count, 2)
        self.external_post.assert_called_once()
        self.assertEqual(self.external_post.call_args.kwargs["json"]["coordinates"], [self.start, self.finish])

    def test_mixed_inputs_only_geocode_the_name(self):
        self.external_get.return_value.ok = True
        self.external_get.return_value.json.return_value = {
            "features": [{"geometry": {"coordinates": self.finish}}],
        }
        response = self.request_plan(self.start, "Las Vegas, NV")
        self.assertEqual(response.status_code, 200)
        self.external_get.assert_called_once()
        self.assertEqual(self.external_get.call_args.kwargs["params"]["text"], "Las Vegas, NV")
        self.external_post.assert_called_once()

    def test_invalid_coordinates_rejected_before_any_external_calls(self):
        for invalid in ([], [1], [1, 2, 3], [181, 34], [-118, 91],
                        [-181, 34], [-118, -91], [True, 34], [None, 34],
                        ["NaN", 34], ["Infinity", 34], ["bad", 34],
                        {"latitude": 34, "longitude": -118}, 42, "   ", None):
            for field in ("start", "finish"):
                with self.subTest(value=invalid, field=field):
                    inputs = {"start": self.start, "finish": self.finish, field: invalid}
                    response = self.request_plan(**inputs)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json())
        self.external_get.assert_not_called()
        self.external_post.assert_not_called()

