import math
from routes.models import FuelStation
import polyline

def distance_between_points(point_a, point_b):
    """Return straight-line distance between two coordinates in miles.

    Coordinates must be in (longitude, latitude) order.
    """
    longitude_a, latitude_a = map(math.radians, point_a)
    longitude_b, latitude_b = map(math.radians, point_b)

    latitude_difference = latitude_b - latitude_a
    longitude_difference = longitude_b - longitude_a

    a = (
        math.sin(latitude_difference / 2) ** 2
        + math.cos(latitude_a)
        * math.cos(latitude_b)
        * math.sin(longitude_difference / 2) ** 2
    )

    earth_radius_miles = 3958.8
    return 2 * earth_radius_miles * math.asin(math.sqrt(min(1, a)))


def decode_route(route_result):
    """Return route points in (longitude, latitude) order."""
    encoded_geometry = route_result["routes"][0]["geometry"]

    return polyline.decode(encoded_geometry, geojson=True)

def distances_along_route(points):
    """Return the accumulated distance in miles at each route point."""
    distances = [0.0]

    for index in range(1, len(points)):
        segment_distance = distance_between_points(
            points[index - 1],
            points[index],
        )

        distances.append(distances[-1] + segment_distance)

    return distances

def closest_point_on_segment(station, segment_start, segment_end):
    """Find the point on a route segment closest to a station.

    All coordinates are (longitude, latitude).
    Returns (closest_point, fraction).
    """
    station_lon, station_lat = station
    start_lon, start_lat = segment_start
    end_lon, end_lat = segment_end

    # Approximate longitude and latitude as a flat surface locally.
    latitude_scale = math.cos(math.radians(station_lat))

    segment_x = (end_lon - start_lon) * latitude_scale
    segment_y = end_lat - start_lat

    station_x = (station_lon - start_lon) * latitude_scale
    station_y = station_lat - start_lat

    segment_length_squared = segment_x**2 + segment_y**2

    if segment_length_squared == 0:
        return segment_start, 0.0

    fraction = (
        station_x * segment_x + station_y * segment_y
    ) / segment_length_squared

    # Keep the closest point within the segment's endpoints.
    fraction = max(0.0, min(1.0, fraction))

    closest_point = (
        start_lon + fraction * (end_lon - start_lon),
        start_lat + fraction * (end_lat - start_lat),
    )

    return closest_point, fraction


def find_station_position(station, points, distances, *, segment_indices=None):
    """Return the station's distance from and position along the route.

    Both distances are in miles. Coordinates use (longitude, latitude).
    """
    if len(points) < 2 or len(distances) != len(points):
        raise ValueError("The route must contain at least two points.")

    closest_distance = float("inf")
    distance_along_route = 0.0

    if segment_indices is None:
        segment_indices = range(len(points) - 1)

    for index in segment_indices:
        closest_point, fraction = closest_point_on_segment(
            station,
            points[index],
            points[index + 1],
        )

        distance_from_route = distance_between_points(
            station,
            closest_point,
        )

        if distance_from_route < closest_distance:
            closest_distance = distance_from_route

            segment_distance = distances[index + 1] - distances[index]
            distance_along_route = (
                distances[index] + fraction * segment_distance
            )

    return closest_distance, distance_along_route

def get_candidate_stations(points, max_distance_miles=5):
    """Return stations in a rectangle around the route."""
    if not points:
        raise ValueError("The route has no points.")

    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]

    # One degree of latitude is approximately 69 miles.
    latitude_margin = max_distance_miles / 69

    # Longitude degrees get narrower farther from the equator.
    furthest_latitude = max(abs(lat) for lat in latitudes) + latitude_margin
    longitude_margin = max_distance_miles / (
        69 * math.cos(math.radians(furthest_latitude))
    )

    return FuelStation.objects.filter(
        latitude__gte=min(latitudes) - latitude_margin,
        latitude__lte=max(latitudes) + latitude_margin,
        longitude__gte=min(longitudes) - longitude_margin,
        longitude__lte=max(longitudes) + longitude_margin,
    )


def _route_segment_blocks(points, block_size=32):
    """Precompute bounds for consecutive groups of route segments.

    Every segment belongs to a block, including the segment crossing a block
    boundary. Bounds include both endpoints, so they also contain every point
    that closest_point_on_segment can return.
    """
    blocks = []
    for start in range(0, len(points) - 1, block_size):
        stop = min(start + block_size, len(points) - 1)
        longitudes, latitudes = zip(*points[start:stop + 1])
        blocks.append((start, stop, min(longitudes), max(longitudes),
                       min(latitudes), max(latitudes)))
    return blocks


def _nearby_segment_indices(station, blocks, max_distance_miles):
    """Skip blocks outside a conservative bounding box of the search circle.

    Remaining segments still use the original distance calculation. Keep their
    route order so equally close positions resolve to the same first segment.
    """
    longitude, latitude = station
    angular_radius = max_distance_miles / 3958.8
    latitude_margin = math.degrees(angular_radius) + 1e-9
    if abs(latitude) + latitude_margin >= 90:
        longitude_margin = 180
    else:
        longitude_margin = math.degrees(math.asin(min(
            1.0, math.sin(angular_radius) / math.cos(math.radians(latitude)),
        ))) + 1e-9
    min_lon, max_lon = longitude - longitude_margin, longitude + longitude_margin
    if min_lon < -180 or max_lon > 180:
        # Keep all longitudes when the search crosses the antimeridian.
        min_lon, max_lon = -180, 180
    min_lat, max_lat = latitude - latitude_margin, latitude + latitude_margin
    for start, stop, west, east, south, north in blocks:
        if east < min_lon or west > max_lon or north < min_lat or south > max_lat:
            continue
        yield from range(start, stop)


def get_stations_along_route(points, max_distance_miles=5):
    if len(points) < 2:
        raise ValueError("The route must contain at least two points.")
    if not math.isfinite(max_distance_miles) or max_distance_miles < 0:
        raise ValueError("The station distance limit must be finite and non-negative.")
    distances = distances_along_route(points)
    candidates = get_candidate_stations(points, max_distance_miles)
    blocks = _route_segment_blocks(points)
    positions = {}
    results = []

    for station in candidates:
        coordinates = (station.longitude, station.latitude)
        if coordinates not in positions:
            positions[coordinates] = find_station_position(
                coordinates, points, distances,
                segment_indices=_nearby_segment_indices(
                    coordinates, blocks, max_distance_miles,
                ),
            )
        distance_from, distance_along = positions[coordinates]

        if distance_from <= max_distance_miles:
            results.append({
                "station": station,
                "distance_from_route": distance_from,
                "distance_along_route": distance_along,
            })

    return sorted(results, key=lambda item: item["distance_along_route"])
