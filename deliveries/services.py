# deliveries/services.py
from django.db.models import Q
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
    Plan the delivery run in this order:

        Driver address
            ↓
        Selected starting supplier
            ↓
        Nearest customer
            ↓
        Nearest remaining customer
            ↓
        ...
            ↓
        Driver address

    The driver's saved coordinates are the route origin and destination.
    The selected supplier's coordinates come from Supplier.delivery_lat
    and Supplier.delivery_lng.
    """

    print("\n==== ROUTE PLANNING START ====")
    print("RUN:", run.id)

    # -------------------------------------------------
    # 1. DRIVER ADDRESS = ORIGIN AND DESTINATION
    # -------------------------------------------------
    if run.start_lat is None or run.start_lng is None:
        return False, (
            "Driver route coordinates are missing. "
            "Check the selected driver's profile."
        )

    origin_point = f"{run.start_lat},{run.start_lng}"
    destination_point = origin_point

    # -------------------------------------------------
    # 2. SELECTED STARTING SUPPLIER
    # -------------------------------------------------
    supplier = getattr(run, "start_supplier", None)

    if supplier is None:
        return False, "Please select a starting supplier before generating the route."

    supplier_lat = getattr(supplier, "delivery_lat", None)
    supplier_lng = getattr(supplier, "delivery_lng", None)

    if supplier_lat is None or supplier_lng is None:
        return False, (
            f"{supplier.name} is selected as the starting supplier, "
            "but its delivery latitude or longitude is missing."
        )

    # Create or update the physical supplier stop from the selected
    # supplier's current address and saved GPS coordinates.
    supplier_address_parts = [
        getattr(supplier, "address_line1", ""),
        getattr(supplier, "address_line2", ""),
        getattr(supplier, "city", ""),
        getattr(supplier, "province", ""),
        getattr(supplier, "postal_code", ""),
        getattr(supplier, "country", ""),
    ]
    supplier_address_parts = [
        str(part).strip()
        for part in supplier_address_parts
        if part and str(part).strip()
    ]
    supplier_address = ", ".join(supplier_address_parts)

    supplier_stop, _ = DeliveryStop.objects.get_or_create(
        run=run,
        stop_type="SUPPLIER",
        supplier=supplier,
        order__isnull=True,
        defaults={
            "status": "assigned",
            "customer_name": supplier.name,
            "address_line1": supplier.address_line1 or supplier.name,
            "address_line2": supplier.address_line2 or "",
            "city": supplier.city or "",
            "province": supplier.province or "",
            "postal_code": supplier.postal_code or "",
            "country": supplier.country or "South Africa",
            "lat": supplier_lat,
            "lng": supplier_lng,
            "service_min": 0,
        },
    )

    # Refresh the stop snapshot so a previously-created legacy stop
    # uses the selected supplier's current coordinates and address.
    supplier_stop.customer_name = supplier.name
    supplier_stop.address_line1 = supplier.address_line1 or supplier.name
    supplier_stop.address_line2 = supplier.address_line2 or ""
    supplier_stop.city = supplier.city or ""
    supplier_stop.province = supplier.province or ""
    supplier_stop.postal_code = supplier.postal_code or ""
    supplier_stop.country = supplier.country or "South Africa"
    supplier_stop.lat = supplier_lat
    supplier_stop.lng = supplier_lng
    supplier_stop.save(update_fields=[
        "customer_name",
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "country",
        "lat",
        "lng",
        "updated_at",
    ])

    supplier_point = f"{supplier_lat},{supplier_lng}"

    # -------------------------------------------------
    # 3. CUSTOMER STOPS WITH VALID COORDINATES
    # -------------------------------------------------
    remaining = list(
        run.stops.filter(
            stop_type="CUSTOMER",
            lat__isnull=False,
            lng__isnull=False,
        ).order_by("id")
    )

    # Do not silently create a route that skips customers with no GPS.
    customers_without_geo = run.stops.filter(
        stop_type="CUSTOMER"
    ).filter(
        Q(lat__isnull=True) | Q(lng__isnull=True)
    ).count()

    if customers_without_geo:
        return False, (
            f"{customers_without_geo} customer stop(s) are missing GPS coordinates. "
            "Update those delivery addresses before generating the route."
        )

    if not remaining:
        return False, (
            "No customer stops with coordinates. "
            "Check the delivery addresses and GPS coordinates."
        )

    # -------------------------------------------------
    # 4. ORDER CUSTOMERS BY NEAREST NEIGHBOUR FROM SUPPLIER
    # -------------------------------------------------
    current_lat = float(supplier_lat)
    current_lng = float(supplier_lng)
    ordered_stops = []

    while remaining:
        nxt = _nearest(current_lat, current_lng, remaining)
        ordered_stops.append(nxt)
        remaining.remove(nxt)
        current_lat = float(nxt.lat)
        current_lng = float(nxt.lng)

    print("ROUTE ORIGIN = DRIVER:", origin_point)
    print("FIRST PHYSICAL STOP = SUPPLIER:", supplier.name, supplier_point)
    print("CUSTOMER DISPATCH ORDER:")
    for index, stop in enumerate(ordered_stops, start=1):
        print(index, "-", stop.customer_name)

    # -------------------------------------------------
    # 5. ASK GOOGLE FOR ROUTE LEGS
    #    Fixed waypoint order: supplier first, then customers.
    # -------------------------------------------------
    waypoint_coords = [supplier_point] + [
        f"{stop.lat},{stop.lng}" for stop in ordered_stops
    ]

    try:
        legs = _call_google(
            origin=origin_point,
            destination=destination_point,
            waypoints=waypoint_coords,
        )
    except Exception as exc:
        print("Google Directions error:", exc)
        return False, str(exc)

    expected_legs = len(waypoint_coords) + 1
    if len(legs) != expected_legs:
        return False, (
            f"Expected {expected_legs} route legs, "
            f"but Google returned {len(legs)}."
        )

    # -------------------------------------------------
    # 6. CREATE / UPDATE RETURN STOP AT DRIVER ADDRESS
    # -------------------------------------------------
    return_stop, _ = DeliveryStop.objects.get_or_create(
        run=run,
        stop_type="RETURN",
        order__isnull=True,
        supplier__isnull=True,
        defaults={
            "status": "assigned",
            "customer_name": (
                run.start_location_label
                or (run.driver.get_full_name() if run.driver else "")
                or "Driver address"
            ),
            "address_line1": run.start_location_label or "Driver address",
            "lat": run.start_lat,
            "lng": run.start_lng,
            "service_min": 0,
        },
    )

    return_stop.customer_name = (
        run.start_location_label
        or (run.driver.get_full_name() if run.driver else "")
        or "Driver address"
    )
    return_stop.address_line1 = run.start_location_label or "Driver address"
    return_stop.lat = run.start_lat
    return_stop.lng = run.start_lng

    # -------------------------------------------------
    # 7. SAVE SEQUENCES AND TIMINGS
    # -------------------------------------------------
    route_stops = [supplier_stop] + ordered_stops

    with transaction.atomic():
        run.stops.update(
            sequence=None,
            distance_km=None,
            drive_min=None,
            eta=None,
        )

        # Reapply return stop's driver-address snapshot after clearing
        # route sequence/timing fields.
        return_stop.sequence = None
        return_stop.distance_km = None
        return_stop.drive_min = None
        return_stop.eta = None
        return_stop.save(update_fields=[
            "customer_name",
            "address_line1",
            "lat",
            "lng",
            "sequence",
            "distance_km",
            "drive_min",
            "eta",
            "updated_at",
        ])

        base = run.start_time
        current_eta = now().replace(
            hour=base.hour if base else now().hour,
            minute=base.minute if base else now().minute,
            second=0,
            microsecond=0,
        )

        for index, stop in enumerate(route_stops):
            leg = legs[index]
            distance_km = Decimal(leg["distance"]["value"]) / Decimal("1000")
            drive_min = int(leg["duration"]["value"] / 60)
            current_eta += timedelta(minutes=drive_min)

            stop.sequence = index + 1
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
                f"SEQ {stop.sequence} | "
                f"{stop.customer_name} | {distance_km} km"
            )

        # Last leg is from the final customer (or supplier if there
        # are no customers) back to the driver's address.
        last_leg = legs[-1]
        return_distance_km = (
            Decimal(last_leg["distance"]["value"]) / Decimal("1000")
        )
        return_drive_min = int(last_leg["duration"]["value"] / 60)
        current_eta += timedelta(minutes=return_drive_min)

        return_stop.sequence = len(route_stops) + 1
        return_stop.distance_km = return_distance_km
        return_stop.drive_min = return_drive_min
        return_stop.eta = current_eta
        return_stop.save(update_fields=[
            "sequence",
            "distance_km",
            "drive_min",
            "eta",
            "updated_at",
        ])

        run.recalc_aggregates(save=True)

    print("==== ROUTE COMPLETE ====\n")
    return True, "Route planned successfully: driver → supplier → customers → driver."
