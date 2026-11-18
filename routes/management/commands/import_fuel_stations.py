import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routes.models import FuelStation


class Command(BaseCommand):
    help = "Import fuel stations and their approximate coordinates"

    def handle(self, *args, **options):
        path = settings.BASE_DIR / "data" / "fuel_stations_coordinates_unverified.csv"

        if not Path(path).is_file():
            raise CommandError(f"File not found: {path}")

        stations = []

        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                stations.append(
                    FuelStation(
                        opis_id=int(row["OPIS Truckstop ID"]),
                        name=row["Truckstop Name"],
                        address=row["Address"],
                        city=row["City"],
                        state=row["State"],
                        price_per_gallon=Decimal(row["Retail Price"]),
                        latitude=float(row["latitude"]) if row["latitude"].strip() else None,
                        longitude=float(row["longitude"]) if row["longitude"].strip() else None,
                    )
                )

        with transaction.atomic():
            FuelStation.objects.bulk_create(
                stations,
                batch_size=500,
                update_conflicts=True,
                unique_fields=["opis_id"],
                update_fields=[
                    "name",
                    "address",
                    "city",
                    "state",
                    "price_per_gallon",
                    "latitude",
                    "longitude",
                ],
            )

        self.stdout.write(
            self.style.SUCCESS(f"Imported or updated {len(stations)} stations.")
        )