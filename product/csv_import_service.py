import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from django.db import transaction

from clients.models import Client
from product.models import Product, ProductCategory, ProductClientPrice, UNIT_CHOICES


@dataclass
class ProductImportSummary:
    created_products: int
    updated_products: int
    created_client_prices: int
    updated_client_prices: int
    errors: List[str]


def _decode_csv_bytes(file_bytes: bytes) -> str:
    """Decode uploaded CSV bytes trying common encodings used by spreadsheet exports."""
    candidate_encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error: Optional[UnicodeDecodeError] = None

    for encoding in candidate_encodings:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    raise ValueError(
        "No se pudo decodificar el archivo CSV. "
        "Use UTF-8, UTF-8 con BOM o ANSI/Windows-1252."
    ) from last_error


def get_products_csv_template() -> str:
    """Return a CSV template for product and client-specific price imports."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "product_name",
            "presentation",
            "unit_of_measure",
            "base_price",
            "category",
            "client_name",
            "client_price",
        ]
    )
    writer.writerow(["Agua purificada", "20", "lt", "45.00", "Garrafones", "Corporativo Agua Norte", "42.00"])
    writer.writerow(["Agua purificada", "20", "lt", "45.00", "Garrafones", "Sucursal Agua Norte Juriquilla", "43.50"])
    writer.writerow(["Botella PET", "600", "ml", "12.00", "Botellas", "", ""])
    return output.getvalue()


def import_products_and_prices_from_csv(file_bytes: bytes) -> ProductImportSummary:
    """Import products and optional client-specific prices from CSV."""
    decoded = _decode_csv_bytes(file_bytes)
    reader = csv.DictReader(io.StringIO(decoded))

    required_headers = {"product_name", "presentation", "unit_of_measure", "base_price", "client_name", "client_price"}
    missing_headers = [header for header in required_headers if header not in (reader.fieldnames or [])]
    if missing_headers:
        return ProductImportSummary(0, 0, 0, 0, [f"Encabezados faltantes: {', '.join(missing_headers)}"])

    created_products = 0
    updated_products = 0
    created_client_prices = 0
    updated_client_prices = 0
    errors: List[str] = []

    for row_number, raw_row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in raw_row.items() if k}
        try:
            with transaction.atomic():
                product, product_created = _upsert_product(row)
                price_status = _upsert_client_price(product, row)

                if product_created:
                    created_products += 1
                else:
                    updated_products += 1

                if price_status == "created":
                    created_client_prices += 1
                elif price_status == "updated":
                    updated_client_prices += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Fila {row_number}: {exc}")

    return ProductImportSummary(
        created_products=created_products,
        updated_products=updated_products,
        created_client_prices=created_client_prices,
        updated_client_prices=updated_client_prices,
        errors=errors,
    )


def _upsert_product(row: Dict[str, str]) -> Tuple[Product, bool]:
    product_name = row.get("product_name", "")
    presentation = row.get("presentation", "")
    unit_of_measure = _parse_unit_of_measure(row.get("unit_of_measure", ""))
    base_price = _parse_decimal(row.get("base_price", ""), field_name="base_price")

    if not product_name:
        raise ValueError("product_name es obligatorio")
    if not presentation:
        raise ValueError("presentation es obligatorio")

    product, created = Product.all_objects.get_or_create(
        name=product_name,
        presentation=presentation,
        unit_of_measure=unit_of_measure,
    )

    product.price = float(base_price)
    product.active = True
    product.category = _resolve_category(row.get("category", ""))
    product.full_clean()
    product.save()
    return product, created


def _upsert_client_price(product: Product, row: Dict[str, str]) -> str:
    client_name = row.get("client_name", "")
    client_price_raw = row.get("client_price", "")

    if not client_name and not client_price_raw:
        return "none"
    if not client_name or not client_price_raw:
        raise ValueError("client_name y client_price deben enviarse juntos")

    client = Client.objects.filter(name=client_name).first()
    if client is None:
        raise ValueError(f"Cliente no encontrado: {client_name}")

    client_price = _parse_decimal(client_price_raw, field_name="client_price")

    price_row, created = ProductClientPrice.objects.get_or_create(product=product, client=client)
    price_row.price = float(client_price)
    price_row.active = True
    price_row.full_clean()
    price_row.save()
    return "created" if created else "updated"


def _resolve_category(category_name: str) -> ProductCategory | None:
    if not category_name:
        return None
    category, _ = ProductCategory.objects.get_or_create(name=category_name)
    return category


def _parse_unit_of_measure(value: str) -> int:
    if value == "":
        raise ValueError("unit_of_measure es obligatorio")

    by_label = {label.lower(): key for key, label in UNIT_CHOICES}
    normalized = value.strip().lower()
    if normalized.isdigit():
        unit = int(normalized)
        valid_units = {key for key, _ in UNIT_CHOICES}
        if unit in valid_units:
            return unit
        raise ValueError(f"unit_of_measure invalido: {value}")

    if normalized in by_label:
        return by_label[normalized]

    raise ValueError(f"unit_of_measure invalido: {value}")


def _parse_decimal(value: str, *, field_name: str) -> Decimal:
    if value == "":
        raise ValueError(f"{field_name} es obligatorio")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} debe ser numerico") from exc

    if parsed < 0:
        raise ValueError(f"{field_name} no puede ser negativo")
    return parsed
