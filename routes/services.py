import requests
from django.conf import settings

#this function takes set of two places as inputs then return the distance and duration.
def get_driving_route(start, finish):
    """Coordinates must be [longitude, latitude]."""
    response = requests.post(
        "https://api.heigit.org/openrouteservice/v2/directions/driving-car",
        headers={
            "Authorization": settings.ORS_API_KEY,
            "Accept": "application/json",
        },
        json={"coordinates": [start, finish]},
        timeout=(5, 30),
    )
    response.raise_for_status()
    return response.json()

# this funtion get the coordinates of a location from heigit.
def geocode_location(location):
    """Convert a US location name into a matched label and coordinates."""
    response = requests.get(
        "https://api.heigit.org/pelias/v1/search",
        params={
            "api_key": settings.ORS_API_KEY,
            "text": location,
            "boundary.country": "USA",
            "size": 1,
        },
        timeout=(5, 30),
    )

    if not response.ok:
        raise RuntimeError(
            f"Geocoding service returned HTTP {response.status_code}"
        )

    features = response.json().get("features", [])

    if not features:
        raise ValueError(f"No US location found for: {location}")



    return features[0]["geometry"]["coordinates"]


def get_route_by_names(start_name, finish_name):
    """Route between names or validated coordinate pairs; geocode names only."""
    start_coordinates = (
        geocode_location(start_name) if isinstance(start_name, str) else start_name
    )
    finish_coordinates = (
        geocode_location(finish_name) if isinstance(finish_name, str) else finish_name
    )

    return get_driving_route(
        start_coordinates,
        finish_coordinates,
    )
