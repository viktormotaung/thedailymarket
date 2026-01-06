from decimal import Decimal
import re

from openpyxl import load_workbook
from django.db import transaction
from django.core.exceptions import ValidationError

from products.models import Category, Product, ProductPricing
from suppliers.models import Supplier


# ======================================================
# HELPERS
# ======================================================

def _vat_included(val):
    """
    Excel: Yes = VAT INCLUDED
           No  = VAT EXCLUDED
    """
    return str(val).strip().lower() in ("yes", "true", "1")


def _is_active(val):
    """
    Excel: Yes = Active
           No  = Inactive
    """
    return str(val).strip().lower() in ("yes", "true", "1")



def _dec(val):
    try:
        return Decimal(str(val)) if val not in (None, "") else Decimal("0")
    except Exception:
        return Decimal("0")


def generate_supplier_code(name: str) -> str:
    """
    Generates a unique supplier code from supplier name.
    Example: 'Jumbo Wholesale' → 'JUMBOWHOLE'
    """
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:10] or "SUPPLIER"
    code = base
    counter = 1

    while Supplier.objects.filter(code=code).exists():
        counter += 1
        code = f"{base[:7]}{counter}"

    return code


# ======================================================
# MAIN IMPORTER
# ======================================================

def import_products_from_excel(file):
    """
    EXPECTED EXCEL STRUCTURE

    Row 1: Group headers (Cost / Wholesale / Retail) → IGNORED
    Row 2: Actual column headers
    Row 3+: Data
    """

    # ======================================================
    # STEP 1 — LOAD FILE
    # ======================================================
    try:
        wb = load_workbook(file, data_only=True)
    except Exception as e:
        raise ValidationError(f"STEP 1 (File load): {e}")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    if len(rows) < 3:
        raise ValidationError("STEP 1: Excel must contain at least 3 rows")

    # ======================================================
    # STEP 2 — HEADER POSITIONS (FIXED)
    # ======================================================
    HEADER_ROW = 1   # Excel row 2
    DATA_START = 2   # Excel row 3+

    headers = rows[HEADER_ROW]
    if not headers:
        raise ValidationError("STEP 2: Header row is empty")

    COL = {
        "category": 0,
        "subcategory": 1,
        "product": 2,
        "product_no": 3,
        "description": 4,
        "supplier": 5,
        "uom": 6,
        "vat_included": 8,
        "cost_price": 9,
        "wholesale_margin": 12,
        "retail_margin": 15,
        "is_active": 18,
    }

    EXPECTED_HEADERS = {
        0: "Category",
        1: "Subcategory",
        2: "Product",
        3: "Product No.",
        5: "Supplier",
        6: "UOM",
        8: "Vat Included",
        9: "Price",
        12: "Profit (%)",
        15: "Profit (%)",
        18: "Is Active",
    }

    for idx, expected in EXPECTED_HEADERS.items():
        actual = str(headers[idx]).strip() if headers[idx] else ""
        if actual != expected:
            raise ValidationError(
                f"STEP 2: Expected '{expected}' in column {idx + 1}, found '{actual}'"
            )

    created = 0
    updated = 0

    # ======================================================
    # STEP 3 — PROCESS ROWS (PER-ROW TRANSACTION)
    # ======================================================

    for excel_row, row in enumerate(rows[DATA_START:], start=DATA_START + 1):

        if not row or not row[COL["product_no"]]:
            continue

        try:
            with transaction.atomic():

                # --------------------------------------------------
                # STEP 4 — READ DATA
                # --------------------------------------------------
                category_name = str(row[COL["category"]]).strip()
                subcategory_name = str(row[COL["subcategory"]]).strip()
                product_name = str(row[COL["product"]]).strip()
                product_no = int(row[COL["product_no"]])
                description = row[COL["description"]] or ""

                supplier_name = str(row[COL["supplier"]]).strip()
                if not supplier_name:
                    raise ValidationError("Supplier name is required")

                raw_uom = row[COL["uom"]]
                uom = str(raw_uom).strip().upper() if raw_uom else "EA"
                if uom not in {"EA", "KG", "L", "PK", "BOX"}:
                    raise ValidationError(f"Invalid UOM '{uom}'")

                vat_included = _vat_included(row[COL["vat_included"]])
                cost_price = _dec(row[COL["cost_price"]])
                wholesale_margin = _dec(row[COL["wholesale_margin"]])
                retail_margin = _dec(row[COL["retail_margin"]])
                is_active = _is_active(row[COL["is_active"]])

                # --------------------------------------------------
                # STEP 5 — CATEGORY
                # --------------------------------------------------
                parent_cat, _ = Category.objects.get_or_create(
                    name=category_name,
                    parent=None,
                )

                sub_cat, _ = Category.objects.get_or_create(
                    name=subcategory_name,
                    parent=parent_cat,
                )

                # --------------------------------------------------
                # STEP 6 — PRODUCT
                # --------------------------------------------------
                product, was_created = Product.objects.update_or_create(
                    product_no=product_no,
                    defaults={
                        "name": product_name,
                        "category": sub_cat,
                        "description": description,
                        "uom": uom,
                        "cost_price": cost_price,
                    },
                )

                created += int(was_created)
                updated += int(not was_created)

                # --------------------------------------------------
                # STEP 7 — SUPPLIER
                # --------------------------------------------------
                supplier = Supplier.objects.filter(name=supplier_name).first()
                if not supplier:
                    supplier = Supplier.objects.create(
                        name=supplier_name,
                        code=generate_supplier_code(supplier_name),
                        is_active=True,
                    )

                supplier.categories.add(parent_cat)

                # --------------------------------------------------
                # STEP 8 — PRICING
                # --------------------------------------------------
                pricing, _ = ProductPricing.objects.update_or_create(
                    product=product,
                    supplier=supplier,
                    defaults={
                        "supplier_price_input": cost_price,
                        "supplier_price_is_inclusive": vat_included,
                        "wholesale_margin_percent": wholesale_margin,
                        "retail_margin_percent": retail_margin,
                        "is_active": is_active,
                    },
                )

                pricing.save()

        except Exception as e:
            raise ValidationError(
                f"Excel row {excel_row}: {e}"
            )

    # ======================================================
    # STEP 9 — SUCCESS
    # ======================================================
    return {
        "created": created,
        "updated": updated,
    }
    
