# deliveries/services.py

import math
import requests
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.utils.timezone import now
from django.db import transaction

from deliveries.models import DeliveryStop

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


# -------------------------------------------------
# GOOGLE API HELPER
# -------------------------------------------------
def _call_google(origin, destination, waypoints):
    """
    Uses the EXACT waypoint order supplied.

    Returns:
        legs
    """

    waypoint_str = None

    if waypoints:
        waypoint_str = "|".join(waypoints)

    params = {
        "origin": origin,
        "destination": destination,
        "waypoints": waypoint_str,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    params = {
        k: v
        for k, v in params.items()
        if v
    }

    response = requests.get(
        GOOGLE_DIRECTIONS_URL,
        params=params,
        timeout=20,
    )

    if response.status_code != 200:
        raise RuntimeError("Failed to contact Google Directions API")

    data = response.json()

    if data.get("status") != "OK":
        raise RuntimeError(
            f"Google Directions error: {data.get('status')}"
        )

    return data["routes"][0]["legs"]


# -------------------------------------------------
# DISTANCE
# -------------------------------------------------
def _distance(a_lat, a_lng, b_lat, b_lng):
    """
    Haversine distance (km)
    """

    r = 6371

    lat1 = math.radians(float(a_lat))
    lon1 = math.radians(float(a_lng))

    lat2 = math.radians(float(b_lat))
    lon2 = math.radians(float(b_lng))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    aa = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(aa), math.sqrt(1 - aa))

    return r * c


# -------------------------------------------------
# NEAREST NEIGHBOUR
# -------------------------------------------------
def _nearest(current_lat, current_lng, remaining):

    best = None
    best_distance = None

    for stop in remaining:

        d = _distance(
            current_lat,
            current_lng,
            stop.lat,
            stop.lng,
        )

        if best is None or d < best_distance:
            best = stop
            best_distance = d

    return best


# -------------------------------------------------
# MAIN ROUTE PLANNER
# -------------------------------------------------
def plan_run_sequence(run):
    """
    HUMAN DISPATCHER LOGIC

    Supplier
        ↓
    Closest customer
        ↓
    Closest remaining customer
        ↓
    Closest remaining customer
        ↓
    ...
        ↓
    Last customer
        ↓
    Depot
    """

    print("\n==== ROUTE PLANNING START ====")
    print("RUN:", run.id)

    if not run.has_depot_geo:
        return False, "Depot coordinates missing."

    # -------------------------------------------------
    # Customer stops
    # -------------------------------------------------
    remaining = list(
        run.stops.filter(
            stop_type="CUSTOMER",
            lat__isnull=False,
            lng__isnull=False,
        )
    )

    if not remaining:
        return False, "No customer stops."

    # -------------------------------------------------
    # Origin
    # -------------------------------------------------
    if run.start_lat is not None and run.start_lng is not None:

        current_lat = float(run.start_lat)
        current_lng = float(run.start_lng)

        origin_point = f"{run.start_lat},{run.start_lng}"

        print("START = SUPPLIER")

    else:

        current_lat = float(run.depot_lat)
        current_lng = float(run.depot_lng)

        origin_point = f"{run.depot_lat},{run.depot_lng}"

        print("START = DEPOT")

    destination_point = f"{run.depot_lat},{run.depot_lng}"

    # -------------------------------------------------
    # HUMAN DISPATCH ORDER
    # -------------------------------------------------
    ordered_stops = []

    while remaining:

        nxt = _nearest(
            current_lat,
            current_lng,
            remaining,
        )

        ordered_stops.append(nxt)

        remaining.remove(nxt)

        current_lat = float(nxt.lat)
        current_lng = float(nxt.lng)

    print("\nDISPATCH ORDER")

    for i, s in enumerate(ordered_stops, start=1):
        print(i, "-", s.customer_name)

    # -------------------------------------------------
    # Ask Google ONLY for timing
    # -------------------------------------------------
    waypoint_coords = [
        f"{s.lat},{s.lng}"
        for s in ordered_stops
    ]

    try:

        legs = _call_google(
            origin=origin_point,
            destination=destination_point,
            waypoints=waypoint_coords,
        )

    except Exception as exc:

        print(exc)

        return False, str(exc)

    expected = len(ordered_stops) + 1

    if len(legs) != expected:

        return (
            False,
            f"Expected {expected} legs but Google returned {len(legs)}."
        )

    # -------------------------------------------------
    # Return stop
    # -------------------------------------------------
    return_stop, _ = DeliveryStop.objects.get_or_create(
        run=run,
        stop_type="RETURN",
        order__isnull=True,
        supplier__isnull=True,
        defaults={
            "status": "assigned",
            "customer_name": run.depot_label or "Depot",
            "address_line1": run.depot_label or "Depot",
            "lat": run.depot_lat,
            "lng": run.depot_lng,
            "service_min": 0,
        },
    )

    # -------------------------------------------------
    # Save
    # -------------------------------------------------
    with transaction.atomic():

        run.stops.update(
            sequence=None,
            distance_km=None,
            drive_min=None,
            eta=None,
        )

        sequence = 1

        current_eta = None

        for idx, stop in enumerate(ordered_stops):

            leg = legs[idx]

            distance_km = (
                Decimal(leg["distance"]["value"])
                / Decimal("1000")
            )

            drive_min = int(
                leg["duration"]["value"] / 60
            )

            if current_eta is None:

                base = run.start_time

                current_eta = now().replace(
                    hour=base.hour if base else now().hour,
                    minute=base.minute if base else now().minute,
                    second=0,
                    microsecond=0,
                )

            current_eta += timedelta(
                minutes=drive_min
            )

            stop.sequence = sequence
            stop.distance_km = distance_km
            stop.drive_min = drive_min
            stop.eta = current_eta

            stop.save(
                update_fields=[
                    "sequence",
                    "distance_km",
                    "drive_min",
                    "eta",
                    "updated_at",
                ]
            )

            print(
                f"SEQ {sequence} | "
                f"{stop.customer_name} | "
                f"{distance_km} km"
            )

            sequence += 1

        # -----------------------------
        # Return leg
        # -----------------------------
        last_leg = legs[-1]

        distance_km = (
            Decimal(last_leg["distance"]["value"])
            / Decimal("1000")
        )

        drive_min = int(
            last_leg["duration"]["value"] / 60
        )

        current_eta += timedelta(
            minutes=drive_min
        )

        return_stop.sequence = sequence
        return_stop.distance_km = distance_km
        return_stop.drive_min = drive_min
        return_stop.eta = current_eta

        return_stop.save(
            update_fields=[
                "sequence",
                "distance_km",
                "drive_min",
                "eta",
                "updated_at",
            ]
        )

        run.recalc_aggregates(save=True)

    print("==== ROUTE COMPLETE ====\n")

    return True, "Route planned successfully."