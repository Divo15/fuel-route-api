from rest_framework.decorators import api_view
from rest_framework.response import Response
import requests
from rest_framework import status
from .serializers import RouteRequestSerializer
from .services import get_route_by_names
from .trip_planner import build_fuel_plan
from .route_geometry import decode_route
from django.shortcuts import render


def route_map(request):
    response = render(request, "routes/map.html")
    # Tile providers require a Referer; share only this page's origin.
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response



@api_view(["GET"])
def health_check(request):
    return Response({"status": "ok"})



@api_view(["POST"])
def plan_route(request):
    serializer = RouteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        result = get_route_by_names(
            serializer.validated_data["start"],
            serializer.validated_data["finish"],
        )
    except ValueError:
        return Response(
            {"error": "A location could not be resolved. Check your input."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except requests.Timeout:
        return Response(
            {"error": "The location or routing service timed out."},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except (requests.RequestException, RuntimeError):
        return Response(
            {"error": "The location or routing service is unavailable."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        total_distance, fuel_plan = build_fuel_plan(result)
    except (KeyError, IndexError, TypeError, ValueError):
        return Response(
            {"error": "The routing service returned invalid route geometry."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({
        **result,
        "route_geojson": {"type": "LineString", "coordinates": decode_route(result)},
        "total_distance_miles": total_distance,
        "fuel_plan": fuel_plan,
    })
    
