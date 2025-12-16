import pandas as pd
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from products.models import Product, Category, ProductPricing
from suppliers.models import Supplier


class Command(BaseCommand):
    help = "Import or update products from Excel (sheet name must be 'Product')"

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Absolute path to Excel file"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        file_path = options["file_path"]

        try:
            excel = pd.ExcelFile(file_path)
        except Exception as e:
            raise CommandError(f"Could not open Excel file: {e}")

        if "Product" not in excel.sheet_names:
            raise CommandError("Excel file must contain a sheet named 'Product'")

        df = excel.parse("Product")

        created = 0
        updated = 0

        for row_index, row in df.iterrows():
            product_no = row.get("Product No.")

            if pd.isna(product_no):
                self.stdout.write(
                    self.style.WARNING(f"Row {row_index + 2}: Missing Product No — skipped")
                )
                continue

            product_no = int(product_no)

            category_name = str(row.get("Category", "")).strip()
            subcategory_name = str(row.get("Subcategory", "")).strip()
            product_name = str(row.get("Product", "")).strip()
            supplier_name = str(row.get("Supplier", "")).strip()

            if not category_name or not product_name:
                self.stdout.write(
                    self.style.WARNING(f"Row {row_index + 2}: Missing category or product name — skipped")
                )
                continue

            # Category
            parent_category, _ = Category.objects.get_or_create(
                name=category_name,
                parent=None,
                defaults={"is_active": True}
            )

            category = parent_category
            if subcategory_name:
                category, _ = Category.objects.get_or_create(
                    name=subcategory_name,
                    parent=parent_category,
                    defaults={"is_active": True}
                )

            # Supplier (optional)
            supplier = None
            if supplier_name:
                supplier, _ = Supplier.objects.get_or_create(
                    name=supplier_name,
                    defaults={"is_active": True}
                )

            # Product
            product, was_created = Product.objects.get_or_create(
                product_no=product_no,
                defaults={
                    "name": product_name,
                    "category": category,
                    "uom": row.get("UOM") or "",
                    "is_active": str(row.get("Is Active", "")).lower() == "yes",
                }
            )

            if was_created:
                created += 1
            else:
                product.name = product_name
                product.category = category
                product.uom = row.get("UOM") or product.uom
                product.is_active = str(row.get("Is Active", "")).lower() == "yes"
                product.save()
                updated += 1

            # Pricing
            if supplier:
                ProductPricing.objects.update_or_create(
                    product=product,
                    supplier=supplier,
                    defaults={
                        "supplier_price_input": Decimal(str(row.get("Price", 0) or 0)),
                        "supplier_price_is_inclusive": str(row.get("Vat Included", "")).lower() == "yes",
                        "wholesale_margin_percent": Decimal(str(row.get("Wholesale Profit (%)", 0) or 0)),
                        "retail_margin_percent": Decimal(str(row.get("Retail Profit (%)", 0) or 0)),
                        "is_active": True,
                    }
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete → Created: {created}, Updated: {updated}"
            )
        )
