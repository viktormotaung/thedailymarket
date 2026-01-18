# deliveries/services.py

import requests
from decimal import Decimal
from django.conf import settings
from django.utils.timezone import now
from django.db import transaction
from datetime import timedelta

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def plan_run_sequence(run):
    print("\n==== ROUTE PLANNING START ====")
    print("RUN ID:", run.id)
    print("STATUS:", run.status)

    if not run.has_depot_geo:
        print("❌ Depot geo missing")
        return False, "Depot coordinates are missing."

    stops = list(
        run.stops
        .filter(lat__isnull=False, lng__isnull=False)
        .order_by("sequence", "id")
    )

    print("STOPS FOUND:", len(stops))

    if not stops:
        print("❌ No stops with coordinates")
        return False, "No delivery stops with coordinates."

    origin = f"{run.depot_lat},{run.depot_lng}"
    destination = f"{stops[-1].lat},{stops[-1].lng}"

    waypoints = [f"{s.lat},{s.lng}" for s in stops[:-1]]

    print("ORIGIN:", origin)
    print("DESTINATION:", destination)
    print("WAYPOINTS:", waypoints)

    params = {
        "origin": origin,
        "destination": destination,
        "waypoints": "|".join(waypoints) if waypoints else None,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    params = {k: v for k, v in params.items() if v}

    response = requests.get(GOOGLE_DIRECTIONS_URL, params=params, timeout=20)

    print("GOOGLE STATUS CODE:", response.status_code)

    if response.status_code != 200:
        return False, "Failed to contact Google Directions API."

    data = response.json()
    print("GOOGLE RESPONSE STATUS:", data.get("status"))

    if data.get("status") != "OK":
        print("❌ GOOGLE ERROR:", data)
        return False, f"Google Directions error: {data.get('status')}"

    legs = data["routes"][0]["legs"]
    print("LEGS RETURNED:", len(legs))

    with transaction.atomic():
        current_eta = None

        for stop, leg in zip(stops, legs):
            distance_km = Decimal(leg["distance"]["value"]) / Decimal("1000")
            drive_min = int(leg["duration"]["value"] / 60)

            print(
                f"STOP {stop.sequence} → "
                f"{distance_km} km / {drive_min} min"
            )

            stop.distance_km = distance_km
            stop.drive_min = drive_min

            if current_eta is None:
                base_time = run.start_time
                if base_time:
                    current_eta = now().replace(
                        hour=base_time.hour,
                        minute=base_time.minute,
                        second=0,
                        microsecond=0,
                    )
                else:
                    current_eta = now()

            current_eta += timedelta(minutes=drive_min)
            stop.eta = current_eta

            stop.save(update_fields=[
                "distance_km",
                "drive_min",
                "eta",
                "updated_at",
            ])

            print("ETA:", stop.eta)

        run.recalc_aggregates(save=True)

        print("TOTAL DISTANCE:", run.total_distance_km)
        print("TOTAL DRIVE MIN:", run.total_drive_min)

    print("==== ROUTE PLANNING COMPLETE ====\n")
    return True, "Route successfully generated."
