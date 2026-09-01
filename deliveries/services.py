# deliveries/services.py

import requests
from decimal import Decimal
from django.conf import settings
from django.utils.timezone import now
from django.db import transaction
from datetime import timedelta
from deliveries.models import DeliveryStop
    

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def plan_run_sequence(run):
    """
    Build the delivery route in this order:

        DRIVER ADDRESS
            ↓
        SELECTED START SUPPLIER
            ↓
        OTHER SUPPLIERS
            ↓
        CUSTOMERS
            ↓
        DRIVER ADDRESS

    The driver address is both the origin and destination.

    Supplier order:
        - Selected start_supplier is always first.
        - Remaining suppliers are selected by nearest-neighbour distance.

    Customer order:
        - Start from the final supplier.
        - Select the nearest remaining customer.
        - Reserve the customer closest to the driver for the final customer stop.
        - Return to the driver.

    The final "RETURN" stop is a visible stop in the Delivery Stops
    table, but it is NOT sent to Google as a waypoint. The driver's
    coordinates are used as Google's final destination.
    """

    print("\n==== ROUTE PLANNING START ====")
    print("RUN ID:", run.id)
    print("STATUS:", run.status)

    # ============================================================
    # 1. DRIVER START / END LOCATION
    # ============================================================

    if not run.driver:
        print("❌ No driver assigned")
        return False, "No driver is assigned to this delivery run."

    try:
        driver_profile = run.driver.driver_profile
    except Exception:
        print("❌ Driver profile missing")
        return False, "Driver profile is missing."

    if (
        driver_profile.latitude is None
        or driver_profile.longitude is None
    ):
        print("❌ Driver coordinates missing")
        return False, "Driver coordinates are missing."

    driver_lat = float(driver_profile.latitude)
    driver_lng = float(driver_profile.longitude)

    print(
        "DRIVER START / END:",
        driver_lat,
        driver_lng,
    )

    # ============================================================
    # 2. CREATE / UPDATE RETURN-TO-DRIVER STOP
    #
    # This is a visible final stop.
    #
    # IMPORTANT:
    # It is NOT added to Google's waypoints.
    #
    # Google will instead use:
    #
    #     Origin      = Driver
    #     Waypoints   = Suppliers + Customers
    #     Destination = Driver
    #
    # The final Google leg will then be:
    #
    #     Last Customer → Driver
    #
    # That final leg will be saved against this RETURN stop.
    # ============================================================

    return_stop = (
        run.stops
        .filter(
            stop_type="RETURN"
        )
        .first()
    )

    # ------------------------------------------------------------
    # Build driver display name
    # ------------------------------------------------------------

    try:
        driver_name = run.driver.get_full_name()
    except Exception:
        driver_name = ""

    if not driver_name:
        driver_name = (
            getattr(
                run.driver,
                "username",
                ""
            )
            or "Driver"
        )

    # ------------------------------------------------------------
    # Driver address
    #
    # We use getattr so this does not break if a particular
    # address field is not present on DriverProfile.
    # ------------------------------------------------------------

    driver_address_line1 = (
        getattr(
            driver_profile,
            "address_line1",
            ""
        )
        or getattr(
            driver_profile,
            "address",
            ""
        )
        or ""
    )

    driver_address_line2 = (
        getattr(
            driver_profile,
            "address_line2",
            ""
        )
        or ""
    )

    driver_suburb = (
        getattr(
            driver_profile,
            "suburb",
            ""
        )
        or ""
    )

    driver_city = (
        getattr(
            driver_profile,
            "city",
            ""
        )
        or ""
    )

    driver_province = (
        getattr(
            driver_profile,
            "province",
            ""
        )
        or ""
    )

    driver_postal_code = (
        getattr(
            driver_profile,
            "postal_code",
            ""
        )
        or ""
    )

    driver_country = (
        getattr(
            driver_profile,
            "country",
            ""
        )
        or "South Africa"
    )

    # ------------------------------------------------------------
    # Create or update Return-to-Driver stop
    # ------------------------------------------------------------

    if return_stop is None:

        return_stop = DeliveryStop.objects.create(
            run=run,
            stop_type="RETURN",
            status="assigned",
            sequence=0,

            customer_name=driver_name,

            address_line1=driver_address_line1,
            address_line2=driver_address_line2,
            suburb=driver_suburb,
            city=driver_city,
            province=driver_province,
            postal_code=driver_postal_code,
            country=driver_country,

            lat=driver_lat,
            lng=driver_lng,

            service_min=0,
        )

        print(
            "CREATED RETURN-TO-DRIVER STOP:",
            driver_name,
        )

    else:

        # --------------------------------------------------------
        # Update the return stop in case the driver or driver's
        # address has changed.
        # --------------------------------------------------------

        return_stop.status = "assigned"

        return_stop.customer_name = driver_name

        return_stop.address_line1 = driver_address_line1
        return_stop.address_line2 = driver_address_line2
        return_stop.suburb = driver_suburb
        return_stop.city = driver_city
        return_stop.province = driver_province
        return_stop.postal_code = driver_postal_code
        return_stop.country = driver_country

        return_stop.lat = driver_lat
        return_stop.lng = driver_lng

        return_stop.service_min = 0

        return_stop.save(
            update_fields=[
                "status",
                "customer_name",
                "address_line1",
                "address_line2",
                "suburb",
                "city",
                "province",
                "postal_code",
                "country",
                "lat",
                "lng",
                "service_min",
                "updated_at",
            ]
        )

        print(
            "UPDATED RETURN-TO-DRIVER STOP:",
            driver_name,
        )

    # ============================================================
    # 3. LOAD SUPPLIER STOPS
    # ============================================================

    supplier_stops = list(
        run.stops
        .filter(
            stop_type="SUPPLIER",
            supplier__isnull=False,
            lat__isnull=False,
            lng__isnull=False,
        )
        .select_related("supplier")
    )

    # ============================================================
    # 4. LOAD CUSTOMER STOPS
    #
    # IMPORTANT:
    #
    # There should now be ONE CUSTOMER stop per physical client,
    # regardless of how many orders/items that client has.
    # ============================================================

    customer_stops = list(
        run.stops
        .filter(
            stop_type="CUSTOMER",
            lat__isnull=False,
            lng__isnull=False,
        )
    )

    print(
        "SUPPLIER STOPS:",
        len(supplier_stops),
    )

    print(
        "CUSTOMER STOPS:",
        len(customer_stops),
    )

    if not supplier_stops:
        return False, "No supplier stops with coordinates."

    if not customer_stops:
        return False, "No customer stops with coordinates."

    # ============================================================
    # 5. SIMPLE DISTANCE HELPER
    #
    # Used only to determine sequence.
    #
    # Google Directions calculates the actual driving distance
    # and travel time.
    # ============================================================

    from math import (
        radians,
        sin,
        cos,
        sqrt,
        atan2,
    )

    def straight_line_km(
        lat1,
        lng1,
        lat2,
        lng2,
    ):

        R = 6371.0

        dlat = radians(
            lat2 - lat1
        )

        dlng = radians(
            lng2 - lng1
        )

        a = (
            sin(dlat / 2) ** 2
            +
            cos(radians(lat1))
            * cos(radians(lat2))
            * sin(dlng / 2) ** 2
        )

        c = 2 * atan2(
            sqrt(a),
            sqrt(1 - a),
        )

        return R * c

    # ============================================================
    # 6. SUPPLIER SEQUENCE
    #
    # The selected start_supplier MUST be first.
    # ============================================================

    ordered_suppliers = []

    remaining_suppliers = supplier_stops.copy()

    start_supplier_id = run.start_supplier_id

    if start_supplier_id:

        selected_start = next(
            (
                stop
                for stop in remaining_suppliers
                if stop.supplier_id == start_supplier_id
            ),
            None,
        )

        if selected_start:

            ordered_suppliers.append(
                selected_start
            )

            remaining_suppliers.remove(
                selected_start
            )

            print(
                "SELECTED START SUPPLIER:",
                selected_start.supplier.name,
            )

        else:

            print(
                "⚠️ Selected start supplier was not "
                "found among the Picking Batch suppliers."
            )

    # ============================================================
    # 7. IF NO VALID START SUPPLIER
    #
    # Use the supplier closest to the driver's address.
    # ============================================================

    if not ordered_suppliers:

        if not remaining_suppliers:
            return False, "No suppliers available for routing."

        first_supplier = min(
            remaining_suppliers,
            key=lambda stop: straight_line_km(
                driver_lat,
                driver_lng,
                float(stop.lat),
                float(stop.lng),
            ),
        )

        ordered_suppliers.append(
            first_supplier
        )

        remaining_suppliers.remove(
            first_supplier
        )

        print(
            "AUTO START SUPPLIER:",
            first_supplier.supplier.name,
        )

    # ============================================================
    # 8. SEQUENCE REMAINING SUPPLIERS
    #
    # From the current supplier, select the nearest remaining
    # supplier.
    # ============================================================

    while remaining_suppliers:

        current_supplier = (
            ordered_suppliers[-1]
        )

        next_supplier = min(
            remaining_suppliers,
            key=lambda stop: straight_line_km(
                float(current_supplier.lat),
                float(current_supplier.lng),
                float(stop.lat),
                float(stop.lng),
            ),
        )

        ordered_suppliers.append(
            next_supplier
        )

        remaining_suppliers.remove(
            next_supplier
        )

        print(
            "NEXT SUPPLIER:",
            next_supplier.supplier.name,
        )

    # ============================================================
    # 9. CUSTOMER SEQUENCE
    #
    # We want the final customer to be the customer closest
    # to the driver's address.
    #
    # This means:
    #
    # Supplier(s)
    #      ↓
    # Customer
    #      ↓
    # Customer
    #      ↓
    # Customer closest to driver
    #      ↓
    # Driver
    # ============================================================

    ordered_customers = []

    remaining_customers = customer_stops.copy()

    # ------------------------------------------------------------
    # Reserve the customer closest to the driver for LAST.
    # ------------------------------------------------------------

    final_customer = min(
        remaining_customers,
        key=lambda stop: straight_line_km(
            driver_lat,
            driver_lng,
            float(stop.lat),
            float(stop.lng),
        ),
    )

    if len(remaining_customers) > 1:

        remaining_customers.remove(
            final_customer
        )

    # ------------------------------------------------------------
    # Start customer sequencing from the FINAL supplier.
    # ------------------------------------------------------------

    current_lat = float(
        ordered_suppliers[-1].lat
    )

    current_lng = float(
        ordered_suppliers[-1].lng
    )

    # ============================================================
    # 10. NEAREST-NEIGHBOUR CUSTOMER ROUTING
    # ============================================================

    while remaining_customers:

        next_customer = min(
            remaining_customers,
            key=lambda stop: straight_line_km(
                current_lat,
                current_lng,
                float(stop.lat),
                float(stop.lng),
            ),
        )

        ordered_customers.append(
            next_customer
        )

        remaining_customers.remove(
            next_customer
        )

        current_lat = float(
            next_customer.lat
        )

        current_lng = float(
            next_customer.lng
        )

    # ------------------------------------------------------------
    # Add the reserved final customer.
    # ------------------------------------------------------------

    if final_customer not in ordered_customers:

        ordered_customers.append(
            final_customer
        )

    # ============================================================
    # 11. FINAL PHYSICAL STOPS
    #
    # These are ONLY:
    #
    #     Suppliers
    #     +
    #     Customers
    #
    # The Return-to-Driver stop is handled separately because
    # it is the Google destination, not a waypoint.
    # ============================================================

    ordered_stops = (
        ordered_suppliers
        + ordered_customers
    )

    # ============================================================
    # 12. PRINT FINAL ROUTE
    # ============================================================

    print("\nFINAL ROUTE ORDER:")

    print(
        "START:",
        driver_name,
        "→",
        driver_lat,
        driver_lng,
    )

    for sequence, stop in enumerate(
        ordered_stops,
        start=1,
    ):

        if stop.stop_type == "SUPPLIER":

            print(
                sequence,
                "SUPPLIER:",
                stop.supplier.name,
            )

        elif stop.stop_type == "CUSTOMER":

            print(
                sequence,
                "CUSTOMER:",
                stop.customer_name,
            )

    print(
        len(ordered_stops) + 1,
        "RETURN TO DRIVER:",
        driver_name,
    )

    # ============================================================
    # 13. SAVE SEQUENCE NUMBERS
    #
    # Supplier/customer stops:
    #
    #     1
    #     2
    #     3
    #     ...
    #
    # Return-to-driver:
    #
    #     final sequence
    # ============================================================

    with transaction.atomic():

        for sequence, stop in enumerate(
            ordered_stops,
            start=1,
        ):

            stop.sequence = sequence

            stop.save(
                update_fields=[
                    "sequence",
                    "updated_at",
                ]
            )

        # --------------------------------------------------------
        # Return-to-driver is ALWAYS LAST.
        # --------------------------------------------------------

        return_stop.sequence = (
            len(ordered_stops) + 1
        )

        return_stop.save(
            update_fields=[
                "sequence",
                "updated_at",
            ]
        )

    # ============================================================
    # 14. GOOGLE ROUTE
    #
    # VERY IMPORTANT:
    #
    # ORIGIN:
    #     Driver address
    #
    # WAYPOINTS:
    #     Suppliers + Customers
    #
    # DESTINATION:
    #     SAME DRIVER ADDRESS
    #
    # The RETURN stop is NOT a waypoint.
    # ============================================================

    origin = (
        f"{driver_lat},{driver_lng}"
    )

    destination = (
        f"{driver_lat},{driver_lng}"
    )

    waypoints = [
        f"{float(stop.lat)},{float(stop.lng)}"
        for stop in ordered_stops
    ]

    print(
        "\nGOOGLE ORIGIN:",
        origin,
    )

    print(
        "GOOGLE WAYPOINTS:",
        waypoints,
    )

    print(
        "GOOGLE DESTINATION:",
        destination,
    )

    params = {
        "origin": origin,
        "destination": destination,
        "waypoints": "|".join(waypoints),
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    response = requests.get(
        GOOGLE_DIRECTIONS_URL,
        params=params,
        timeout=20,
    )

    print(
        "GOOGLE STATUS CODE:",
        response.status_code,
    )

    if response.status_code != 200:

        return False, (
            "Failed to contact Google Directions API."
        )

    data = response.json()

    print(
        "GOOGLE RESPONSE STATUS:",
        data.get("status"),
    )

    if data.get("status") != "OK":

        print(
            "❌ GOOGLE ERROR:",
            data,
        )

        return False, (
            f"Google Directions error: "
            f"{data.get('status')}"
        )

    route = data["routes"][0]

    legs = route["legs"]

    print(
        "LEGS RETURNED:",
        len(legs),
    )

    # ============================================================
    # EXPECTED GOOGLE LEG COUNT
    #
    # If we have:
    #
    # 1 supplier
    # 4 customers
    #
    # Google should return:
    #
    # Driver → Supplier       = Leg 1
    # Supplier → Customer 1   = Leg 2
    # Customer 1 → Customer 2 = Leg 3
    # Customer 2 → Customer 3 = Leg 4
    # Customer 3 → Customer 4 = Leg 5
    # Customer 4 → Driver     = Leg 6
    #
    # Therefore:
    #
    # len(legs) == len(ordered_stops) + 1
    # ============================================================

    expected_legs = (
        len(ordered_stops) + 1
    )

    if len(legs) != expected_legs:

        print(
            "❌ UNEXPECTED GOOGLE LEG COUNT"
        )

        print(
            "Expected:",
            expected_legs,
        )

        print(
            "Received:",
            len(legs),
        )

        return False, (
            "Google returned an unexpected number "
            "of route legs."
        )

    # ============================================================
    # 15. SAVE ROUTE DISTANCE / TIME / ETA
    # ============================================================

    with transaction.atomic():

        current_eta = None

        # --------------------------------------------------------
        # Supplier + customer stops receive the first N legs.
        # --------------------------------------------------------

        for stop, leg in zip(
            ordered_stops,
            legs[:-1],
        ):

            distance_km = (
                Decimal(
                    leg["distance"]["value"]
                )
                / Decimal("1000")
            )

            drive_min = int(
                leg["duration"]["value"] / 60
            )

            stop.distance_km = (
                distance_km
            )

            stop.drive_min = (
                drive_min
            )

            # ====================================================
            # ETA
            # ====================================================

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

            current_eta += timedelta(
                minutes=drive_min
            )

            stop.eta = current_eta

            stop.save(
                update_fields=[
                    "distance_km",
                    "drive_min",
                    "eta",
                    "updated_at",
                ]
            )

            print(
                f"STOP {stop.sequence}: "
                f"{stop.stop_type} → "
                f"{distance_km} km / "
                f"{drive_min} min"
            )

        # ========================================================
        # 16. FINAL LEG = LAST CUSTOMER → DRIVER
        #
        # Save this against the visible RETURN stop.
        # ========================================================

        final_leg = legs[-1]

        return_distance_km = (
            Decimal(
                final_leg["distance"]["value"]
            )
            / Decimal("1000")
        )

        return_drive_min = int(
            final_leg["duration"]["value"] / 60
        )

        return_stop.distance_km = (
            return_distance_km
        )

        return_stop.drive_min = (
            return_drive_min
        )

        # --------------------------------------------------------
        # Continue ETA from the last customer.
        # --------------------------------------------------------

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

        current_eta += timedelta(
            minutes=return_drive_min
        )

        return_stop.eta = current_eta

        return_stop.sequence = (
            len(ordered_stops) + 1
        )

        return_stop.save(
            update_fields=[
                "distance_km",
                "drive_min",
                "eta",
                "sequence",
                "updated_at",
            ]
        )

        print(
            f"STOP {return_stop.sequence}: "
            f"RETURN TO DRIVER → "
            f"{return_distance_km} km / "
            f"{return_drive_min} min"
        )

        # ========================================================
        # 17. RUN TOTALS
        # ========================================================

        run.recalc_aggregates(
            save=True
        )

    # ============================================================
    # 18. FINAL SUMMARY
    # ============================================================

    print(
        "TOTAL DISTANCE:",
        run.total_distance_km,
    )

    print(
        "TOTAL DRIVE MIN:",
        run.total_drive_min,
    )

    print(
        "==== ROUTE PLANNING COMPLETE ====\n"
    )

    return True, "Route successfully generated."