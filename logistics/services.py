# deliveries/services.py

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
    Call Google Directions API with waypoint optimization.

    Returns:
        waypoint_order (list[int])   # order of input waypoints
        legs (list[dict])            # travel legs between points
    """
    waypoint_str = None
    if waypoints:
        waypoint_str = "optimize:true|" + "|".join(waypoints)

    params = {
        "origin": origin,
        "destination": destination,
        "waypoints": waypoint_str,
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    params = {k: v for k, v in params.items() if v}

    response = requests.get(GOOGLE_DIRECTIONS_URL, params=params, timeout=20)
    if response.status_code != 200:
        raise RuntimeError("Failed to contact Google Directions API")

    data = response.json()
    if data.get("status") != "OK":
        raise RuntimeError(f"Google Directions error: {data.get('status')}")

    route = data["routes"][0]
    return route.get("waypoint_order", []), route["legs"]


# -------------------------------------------------
# MAIN ROUTE PLANNER (HUMAN DISPATCHER LOGIC)
# -------------------------------------------------
def plan_run_sequence(run):
    """
    HUMAN DISPATCHER LOGIC

    Selected Supplier (start)
        OR
    Depot (fallback)

            ↓

    Optimized SUPPLIERS + CUSTOMERS

            ↓

    Depot (end)
    """

    print("\n==== ROUTE PLANNING START ====")
    print("RUN ID:", run.id)

    print("ROUTE ORIGIN:", run.start_location_label or run.depot_label)

    if not run.has_depot_geo:
        return False, "Depot coordinates are missing."

    # -------------------------------------------------
    # Collect ALL routable stops (suppliers + customers)
    # -------------------------------------------------
    stops = list(
        run.stops.filter(
            stop_type="CUSTOMER",
            lat__isnull=False,
            lng__isnull=False,
        )
    )

    if not stops:
        return False, "No routable stops found."

    # ---------------------------------------------
    # Route origin
    # ---------------------------------------------
    if run.start_lat is not None and run.start_lng is not None:
        origin_point = f"{run.start_lat},{run.start_lng}"
    else:
        origin_point = f"{run.depot_lat},{run.depot_lng}"

    destination_point = f"{run.depot_lat},{run.depot_lng}"

    waypoint_coords = [f"{s.lat},{s.lng}" for s in stops]

    # -------------------------------------------------
    # Call Google ONCE (single optimization)
    # -------------------------------------------------
    try:
        waypoint_order, legs = _call_google(
            origin=origin_point,
            destination=destination_point,
            waypoints=waypoint_coords,
        )
    except Exception as exc:
        print("❌ ROUTING ERROR:", exc)
        return False, str(exc)

    # Sanity check (VERY important)
    expected_legs = len(stops) + 1
    if len(legs) != expected_legs:
        return False, (
            f"Leg mismatch: expected {expected_legs}, got {len(legs)}"
        )

    # -------------------------------------------------
    # Ensure RETURN stop exists (logical, not geographic)
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
    # Persist routing
    # -------------------------------------------------
    with transaction.atomic():

        # Reset previous routing safely
        run.stops.update(
            sequence=None,
            distance_km=None,
            drive_min=None,
            eta=None,
        )

        # Apply Google ordering
        ordered_stops = [stops[i] for i in waypoint_order]

        current_eta = None
        sequence = 1

        # -------------------------------------------------
        # LEG → STOP MAPPING (THIS FIXES THE BUG)
        #
        # legs[0] → origin → stop 1
        # legs[1] → stop 1 → stop 2
        # ...
        # legs[N] → last stop → depot
        
        # ...
        
        # -------------------------------------------------

        # ---- NON-RETURN STOPS
        for idx, stop in enumerate(ordered_stops):
            leg = legs[idx]  # 🔑 CORRECT mapping

            distance_km = Decimal(leg["distance"]["value"]) / Decimal("1000")
            drive_min = int(leg["duration"]["value"] / 60)

            if current_eta is None:
                base_time = run.start_time
                current_eta = now().replace(
                    hour=base_time.hour if base_time else now().hour,
                    minute=base_time.minute if base_time else now().minute,
                    second=0,
                    microsecond=0,
                )

            current_eta += timedelta(minutes=drive_min)

            stop.sequence = sequence
            stop.distance_km = distance_km
            stop.drive_min = drive_min
            stop.eta = current_eta

            stop.save(update_fields=[
                "sequence",
                "distance_km",
                "drive_min",
                "eta",
                "updated_at",
            ])

            print(
                f"SEQ {sequence} | {stop.stop_type} | "
                f"{distance_km} km / {drive_min} min"
            )

            sequence += 1

        # ---- FINAL LEG → RETURN STOP
        final_leg = legs[len(ordered_stops)]

        distance_km = Decimal(final_leg["distance"]["value"]) / Decimal("1000")
        drive_min = int(final_leg["duration"]["value"] / 60)

        current_eta += timedelta(minutes=drive_min)

        return_stop.sequence = sequence
        return_stop.distance_km = distance_km
        return_stop.drive_min = drive_min
        return_stop.eta = current_eta

        return_stop.save(update_fields=[
            "sequence",
            "distance_km",
            "drive_min",
            "eta",
            "updated_at",
        ])

        print(
            f"SEQ {sequence} | RETURN | "
            f"{distance_km} km / {drive_min} min"
        )

        run.recalc_aggregates(save=True)

    print("==== ROUTE PLANNING COMPLETE ====\n")
    return True, "Route optimized successfully."
