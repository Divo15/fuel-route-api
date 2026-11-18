"""Connect route geometry and saved station prices to the fuel planner."""

import math
from decimal import Decimal, ROUND_HALF_UP

from .fuel_planner import plan_fuel_stops
from .route_geometry import (
    decode_route,
    distances_along_route,
    get_stations_along_route,
)

STARTING_FUEL_PRICE_PER_GALLON = Decimal("3.30")


def money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def build_fuel_plan(route_result):
    """Return route miles and complete, estimated, or unavailable pricing.

    Use decoded route miles consistently with station positions. The original
    provider response (including its distance/duration summary) is kept by the view.
    """
    points = decode_route(route_result)
    if len(points) < 2 or any(
        not (math.isfinite(lon) and math.isfinite(lat)
             and -180 <= lon <= 180 and -90 < lat < 90)
        for lon, lat in points
    ):
        raise ValueError("The route needs at least two valid coordinates.")

    total_distance = distances_along_route(points)[-1]
    plan = {
        "status": "unavailable",
        "fuel_pricing_complete": False,
        "currency": "USD",
        "total_trip_cost": None,
        "cost_before_first_station": None,
        "gallons_before_first_station": None,
        "cost_from_first_station": None,
        "estimated_distance_miles": 0.0,
        "priced_distance_miles": 0.0,
        "unpriced_distance_miles": total_distance,
        "distance_before_first_station_miles": None,
        "stops": [],
        "assumptions": {
            "range_miles": 500,
            "miles_per_gallon": 10,
            "tank_capacity_gallons": 50,
            "fuel_at_first_station_gallons": 0,
            "starting_fuel": "Enough to reach the first station with an empty tank.",
            "starting_fuel_price_per_gallon": str(STARTING_FUEL_PRICE_PER_GALLON),
            "starting_fuel_price_source": "user_selected_estimate",
            "max_distance_from_route_miles": 5,
            "distance_from_route_method": "straight_line",
            "detour_fuel_included": False,
        },
        "notes": [
            "Estimates use saved station coordinates and prices; locations may be approximate.",
            "Fuel used to drive between the route and stations is excluded.",
        ],
    }
    if total_distance == 0:
        plan.update(
            status="complete", fuel_pricing_complete=True,
            total_trip_cost="0.00", unpriced_distance_miles=0.0,
        )
        return total_distance, plan

    nearby = [
        item for item in get_stations_along_route(points, max_distance_miles=5)
        if item["distance_along_route"] < total_distance
    ]
    if not nearby:
        plan["error"] = "No usable fuel stations found within 5 miles of the route."
        return total_distance, plan

    first_distance = nearby[0]["distance_along_route"]
    plan["distance_before_first_station_miles"] = first_distance
    if first_distance > 0:
        plan["notes"].append(
            "Fuel before the first station is estimated at $3.30 per gallon. "
            "You start with enough fuel to reach that station and arrive empty."
        )

    planner_stations = [
        {
            "station_id": item["station"].pk,
            "name": item["station"].name,
            "price": item["station"].price_per_gallon,
            "distance": item["distance_along_route"],
        }
        for item in nearby
    ]
    try:
        purchases = plan_fuel_stops(planner_stations, total_distance)
    except ValueError as error:
        plan["error"] = str(error)
        return total_distance, plan

    by_id = {item["station"].pk: item for item in nearby}
    for purchase in purchases["purchases"]:
        item = by_id[purchase["station_id"]]
        station = item["station"]
        plan["stops"].append({
            "station_id": station.pk,
            "opis_id": station.opis_id,
            "name": station.name,
            "address": station.address,
            "city": station.city,
            "state": station.state,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "distance_along_route_miles": item["distance_along_route"],
            "distance_from_route_miles": item["distance_from_route"],
            "price_per_gallon": str(station.price_per_gallon),
            "gallons": float(purchase["gallons"]),
            "cost": money(purchase["cost"]),
        })

    starting_gallons = Decimal(str(first_distance)) / Decimal("10")
    starting_cost = starting_gallons * STARTING_FUEL_PRICE_PER_GALLON
    # Sum the displayed cent amounts so the cost breakdown matches the total.
    starting_cost_display = money(starting_cost)
    subtotal = money(purchases["total_cost"])
    plan.update(
        status="estimated" if first_distance > 0 else "complete",
        fuel_pricing_complete=True,
        total_trip_cost=money(Decimal(starting_cost_display) + Decimal(subtotal)),
        cost_before_first_station=starting_cost_display,
        gallons_before_first_station=float(starting_gallons),
        cost_from_first_station=subtotal,
        estimated_distance_miles=first_distance,
        priced_distance_miles=total_distance,
        unpriced_distance_miles=0.0,
    )
    return total_distance, plan
