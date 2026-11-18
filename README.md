# Fuel Route API

This API finds a US driving route and suggests fuel stops using the supplied price data. It returns the route, stops, gallons to buy and an estimated cost.

## Getting started

You'll need Python 3.14 and a HeiGIT/openrouteservice API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```text
ORS_API_KEY=your_key
```

Keep your key private. Then set up the database and start the server:

```bash
python manage.py migrate
python manage.py import_fuel_stations
python manage.py runserver
```

The import reads `data/fuel_stations_coordinates_unverified.csv` and updates stations by OPIS ID. Run the tests with:

```bash
python manage.py test routes
```

## Try the API

Send a `POST` request to `http://127.0.0.1:8000/api/plan/` with `Content-Type: application/json`:

```json
{
  "start": [-118.2437, 34.0522],
  "finish": [-115.1398, 36.1699]
}
```

Use `[longitude, latitude]` order, or US place names like `"Los Angeles, CA"`. Coordinates are range-checked, but not independently verified to be in the USA.

The response includes directions, `route_geojson`, distance in miles, and a `fuel_plan` with stops, costs and assumptions. If no fuel plan is possible, the route is still returned with HTTP 200, an explanation and a null total. `GET /api/health/` checks the app.

## How it works and why

- **Routing:** I use HeiGIT/openrouteservice. Coordinates need one routing call; place names need two additional geocoding calls. Station coordinates are saved locally to avoid a call per station. The `driving-car` profile ignores truck-specific restrictions.
- **Station data:** SQLite keeps 6,626 stations easy to search locally. For conflicting prices on one ID, I used the median of the distinct prices; it may not appear in the source. Some coordinates are approximate or city-level, and the dataset has gaps.
- **Finding stops:** A bounding rectangle and grouped route segments speed up the search; stations are sorted in travel order. The **5-mile straight-line limit** keeps stops nearby, but can exclude useful stations and isn't the driving detour.
- **Buying fuel:** A 50-gallon tank at 10 MPG gives a 500-mile range. The planner buys enough to reach the first cheaper reachable station; otherwise, it fills up or buys enough to finish. Prices use decimal arithmetic. The approach may suggest small purchases and doesn't guarantee the cheapest real-world trip.
- **Starting fuel:** The vehicle starts with enough to reach the first station and arrives empty. I include that fuel at **$3.30/gallon**, an estimate rather than a verified price.

Route distance comes from decoded geometry; detour fuel and time are excluded. Prices and locations aren't verified live. If a station gap exceeds the vehicle's range, the API reports that it can't make a plan.

The optional map at `/` uses Leaflet and OpenStreetMap tiles, so it needs an internet connection.
