from decimal import Decimal


def find_next_cheaper_station(stations, current_index):
    """
    Find the first cheaper station reachable on a full tank.

    Stations must be ordered by distance along the route.
    """
    current = stations[current_index]
    max_range = 500

    for station in stations[current_index + 1:]:
        distance_between = station["distance"] - current["distance"]

        if distance_between > max_range:
            break

        if station["price"] < current["price"]:
            return station

    return None


def fuel_to_buy(distance_miles, fuel_in_tank):
    """Gallons needed to reach a location along the route."""
    distance_miles = Decimal(str(distance_miles))
    fuel_in_tank = Decimal(str(fuel_in_tank))

    miles_per_gallon = Decimal("10")
    tank_capacity = Decimal("50")

    if distance_miles < 0:
        raise ValueError("Distance cannot be negative.")

    if not Decimal("0") <= fuel_in_tank <= tank_capacity:
        raise ValueError("Fuel in tank must be between 0 and 50 gallons.")

    fuel_needed = distance_miles / miles_per_gallon

    if fuel_needed > tank_capacity:
        raise ValueError("The location is beyond the vehicle's range.")

    return max(Decimal("0"), fuel_needed - fuel_in_tank)




def fuel_purchase_cost(gallons, price_per_gallon):
    """Calculate the cost of a fuel purchase in dollars."""
    gallons = Decimal(str(gallons))
    price_per_gallon = Decimal(str(price_per_gallon))

    return gallons * price_per_gallon


def plan_purchase(stations, current_index, fuel_in_tank, destination_distance):
    """Decide how much fuel to buy at the current station."""
    current = stations[current_index]
    distance_to_destination = destination_distance - current["distance"]

    if distance_to_destination < 0:
        raise ValueError("The station is beyond the destination.")

    cheaper = find_next_cheaper_station(stations, current_index)

    if cheaper and cheaper["distance"] < destination_distance:
        # Buy enough to reach the first cheaper station.
        target_distance = cheaper["distance"] - current["distance"]
    else:
        # Fill the tank, or buy only enough to finish if closer.
        target_distance = min(500, distance_to_destination)

    gallons = fuel_to_buy(target_distance, fuel_in_tank)
    cost = fuel_purchase_cost(gallons, current["price"])

    return {
        "station": current["name"],
        "station_id": current.get("station_id"),
        "gallons": gallons,
        "cost": cost,
    }


def plan_fuel_stops(stations, destination_distance):
    """
    Plan fuel purchases using stations ordered by route distance.

    Assume the vehicle arrives at the first station with an empty tank.
    """
    destination = Decimal(str(destination_distance))

    # Work with stations before the destination, in route order.
    stations = sorted(
        [
            {
                **station,
                "distance": Decimal(str(station["distance"])),
            }
            for station in stations
            if Decimal(str(station["distance"])) < destination
        ],
        key=lambda station: station["distance"],
    )

    if not stations:
        raise ValueError("No usable fuel stations found along the route.")

    if stations[0]["distance"] > 500:
        raise ValueError("The first station is beyond the vehicle's range.")

    fuel_in_tank = Decimal("0")
    total_cost = Decimal("0")
    purchases = []

    for index, station in enumerate(stations):
        purchase = plan_purchase(
            stations,
            index,
            fuel_in_tank,
            destination,
        )

        gallons = Decimal(str(purchase["gallons"]))
        fuel_in_tank += gallons

        if gallons > 0:
            purchases.append(purchase)
            total_cost += purchase["cost"]

        if index + 1 < len(stations):
            next_distance = stations[index + 1]["distance"]
        else:
            next_distance = destination

        miles_to_next = next_distance - station["distance"]
        fuel_needed = miles_to_next / Decimal("10")

        if fuel_needed > fuel_in_tank:
            raise ValueError(
                "The vehicle cannot reach the next station or destination."
            )

        fuel_in_tank -= fuel_needed

    return {
        "purchases": purchases,
        "total_cost": total_cost,
    }



