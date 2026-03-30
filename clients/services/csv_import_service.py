import csv
import io
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from django.db import transaction

from clients.models import Address, Client, Contact


@dataclass
class ImportSummary:
    created_clients: int
    updated_clients: int
    created_addresses: int
    updated_addresses: int
    created_contacts: int
    updated_contacts: int
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


def get_clients_csv_template() -> str:
    """Return a CSV template for client imports."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "client_name",
            "external_id",
            "type",
            "corporate_name",
            "active",
            "note",
            "address_street",
            "address_exterior_number",
            "address_interior_number",
            "address_locality",
            "address_municipality",
            "address_state",
            "address_zip_code",
            "address_country",
            "address_reference",
            "contact_name",
            "contact_phone",
            "contact_email",
        ]
    )
    writer.writerow(
        [
            "Corporativo Agua Norte",
            "ERP-0001",
            "corporate",
            "",
            "true",
            "Cliente corporativo",
            "Av. Constituyentes 100",
            "100",
            "",
            "Centro",
            "Queretaro",
            "Queretaro",
            "76000",
            "Mexico",
            "Frente a plaza principal",
            "Ana Lopez",
            "4421234567",
            "ana@agua-norte.com",
        ]
    )
    writer.writerow(
        [
            "Sucursal Agua Norte Juriquilla",
            "ERP-0101",
            "branch",
            "Corporativo Agua Norte",
            "true",
            "Sucursal principal",
            "Blvd. Juriquilla 250",
            "250",
            "B",
            "Juriquilla",
            "Queretaro",
            "Queretaro",
            "76230",
            "Mexico",
            "A un lado del parque",
            "Luis Perez",
            "4427654321",
            "luis@agua-norte.com",
        ]
    )
    return output.getvalue()


def import_clients_from_csv(file_bytes: bytes) -> ImportSummary:
    """Import clients, one delivery address, and one contact from CSV rows."""
    decoded = _decode_csv_bytes(file_bytes)
    reader = csv.DictReader(io.StringIO(decoded))

    required_headers = {"client_name", "type", "address_street"}
    missing_headers = [header for header in required_headers if header not in (reader.fieldnames or [])]
    if missing_headers:
        return ImportSummary(0, 0, 0, 0, 0, 0, [f"Encabezados faltantes: {', '.join(missing_headers)}"])

    created_clients = 0
    updated_clients = 0
    created_addresses = 0
    updated_addresses = 0
    created_contacts = 0
    updated_contacts = 0
    errors: List[str] = []

    for row_number, raw_row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in raw_row.items() if k}
        try:
            with transaction.atomic():
                client, client_created = _upsert_client(row)
                address_created = _upsert_delivery_address(client, row)
                contact_result = _upsert_primary_contact(client, row)

                if client_created:
                    created_clients += 1
                else:
                    updated_clients += 1

                if address_created:
                    created_addresses += 1
                else:
                    updated_addresses += 1

                if contact_result == "created":
                    created_contacts += 1
                elif contact_result == "updated":
                    updated_contacts += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Fila {row_number}: {exc}")

    return ImportSummary(
        created_clients=created_clients,
        updated_clients=updated_clients,
        created_addresses=created_addresses,
        updated_addresses=updated_addresses,
        created_contacts=created_contacts,
        updated_contacts=updated_contacts,
        errors=errors,
    )


def _upsert_client(row: Dict[str, str]) -> Tuple[Client, bool]:
    client_name = row.get("client_name", "")
    if not client_name:
        raise ValueError("client_name es obligatorio")

    client_type = _normalize_client_type(row.get("type", ""))
    corporate = None
    if client_type == "branch":
        corporate_name = row.get("corporate_name", "")
        if not corporate_name:
            raise ValueError("corporate_name es obligatorio para tipo branch")
        corporate = _get_or_create_corporate(corporate_name)

    client, created = Client.objects.get_or_create(name=client_name)

    # Self-referential case: branch lists itself as its own corporate.
    # Treat it as a standalone corporate instead of creating a circular reference.
    if corporate is not None and corporate.pk == client.pk:
        client_type = "corporate"
        corporate = None

    client.external_id = row.get("external_id", "") or None
    client.type = client_type
    client.corporate = corporate
    client.active = _parse_bool(row.get("active", "true"), default=True)
    client.note = row.get("note", "") or None
    client.full_clean()
    client.save()
    return client, created


def export_clients_to_csv(clients: Iterable[Client]) -> str:
    """Export clients with one delivery address and one contact to CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "client_name",
            "external_id",
            "type",
            "corporate_name",
            "active",
            "note",
            "address_street",
            "address_exterior_number",
            "address_interior_number",
            "address_locality",
            "address_municipality",
            "address_state",
            "address_zip_code",
            "address_country",
            "address_reference",
            "contact_name",
            "contact_phone",
            "contact_email",
        ]
    )

    for client in clients:
        address = _get_delivery_address(client)
        contact = _get_first_contact(client)
        writer.writerow(
            [
                client.name,
                client.external_id or "",
                client.type,
                client.corporate.name if client.corporate else "",
                "true" if client.active else "false",
                client.note or "",
                address.street if address else "",
                address.exterior_number if address and address.exterior_number else "",
                address.interior_number if address and address.interior_number else "",
                address.locality if address else "",
                address.municipality if address else "",
                address.state if address else "",
                address.zip_code if address else "",
                address.country if address else "",
                address.reference if address and address.reference else "",
                contact.name if contact else "",
                contact.phone if contact and contact.phone else "",
                contact.email if contact and contact.email else "",
            ]
        )

    return output.getvalue()


def _get_delivery_address(client: Client) -> Optional[Address]:
    return client.addresses.filter(type="delivery").first()


def _get_first_contact(client: Client) -> Optional[Contact]:
    return client.contacts.first()


def _upsert_delivery_address(client: Client, row: Dict[str, str]) -> bool:
    street = row.get("address_street", "")
    if not street:
        raise ValueError("address_street es obligatorio")

    # Use the 'delivery' type from Address model choices (Ubicación física)
    address, created = Address.objects.get_or_create(
        client=client, type="delivery"  # Reusing existing Address.type choice
    )
    address.street = street
    address.exterior_number = row.get("address_exterior_number", "") or None
    address.interior_number = row.get("address_interior_number", "") or None
    address.locality = row.get("address_locality", "") or "Queretaro"
    address.municipality = row.get("address_municipality", "") or "Queretaro"
    address.state = row.get("address_state", "") or "Queretaro"
    address.zip_code = row.get("address_zip_code", "") or "76000"
    address.country = row.get("address_country", "") or "Mexico"
    address.reference = row.get("address_reference", "") or None
    address.active = True
    address.full_clean()
    address.save()
    return created


def _upsert_primary_contact(client: Client, row: Dict[str, str]) -> str:
    contact_name = row.get("contact_name", "")
    if not contact_name:
        return "none"

    contact, created = Contact.objects.get_or_create(client=client, name=contact_name)
    contact.phone = row.get("contact_phone", "") or None
    contact.email = row.get("contact_email", "") or None
    contact.full_clean()
    contact.save()
    return "created" if created else "updated"


def _normalize_client_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"corporate", "branch"}:
        raise ValueError("type debe ser corporate o branch")
    return normalized


def _get_or_create_corporate(corporate_name: str) -> Client:
    normalized_input = corporate_name.strip()
    corporate_suffix = "corporativo"

    if normalized_input.lower().endswith(f" {corporate_suffix}"):
        normalized_name = f"{normalized_input[: -len(corporate_suffix)]}{corporate_suffix}"
        base_name = normalized_input[: -len(corporate_suffix)].rstrip()
    else:
        normalized_name = f"{normalized_input} {corporate_suffix}"
        base_name = normalized_input

    corporate = Client.objects.filter(name=normalized_name).first()

    # If a corporate exists with the base name, reuse it and normalize its name.
    if corporate is None and base_name and base_name != normalized_name:
        corporate = Client.objects.filter(name=base_name, type="corporate").first()
        if corporate is not None:
            corporate.name = normalized_name

    if corporate is None:
        corporate = Client(name=normalized_name, type="corporate", active=True)

    if corporate.type != "corporate" or corporate.corporate_id is not None:
        corporate.type = "corporate"
        corporate.corporate = None  # corporates cannot have a parent

    corporate.full_clean()
    corporate.save()
    return corporate


def _parse_bool(value: str, *, default: bool) -> bool:
    if value == "":
        return default

    normalized = value.strip().lower()
    truthy = {"1", "true", "t", "yes", "si", "y", "x"}
    falsy = {"0", "false", "f", "no", "n"}
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    raise ValueError(f"Valor booleano invalido: {value}")
