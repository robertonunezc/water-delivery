"""
Django management command to populate the database with test data.

Usage:
    python manage.py populate_test_data
    python manage.py populate_test_data --clients 100
    python manage.py populate_test_data --orders 20
"""
import random
from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from clients.models import Client, Contact, Address
from product.models import Product, ProductCategory, ProductClientPrice
from routes.models import Route, RouteClient
from core.models import Transport, Employee
from orders.models import Order, OrderProduct, OrderStatus
from payment.models import Payment


class Command(BaseCommand):
    help = 'Populate the database with test data (users, clients, products, routes, orders, payments)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clients',
            type=int,
            default=50,
            help='Number of clients to create (default: 50)',
        )
        parser.add_argument(
            '--orders',
            type=int,
            default=10,
            help='Number of orders per client (default: 10)',
        )

    def handle(self, *args, **options):
        num_clients = options['clients']
        orders_per_client = options['orders']

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Starting Test Data Population")
        self.stdout.write("=" * 60 + "\n")

        # Create users
        admin_user, regular_user = self.create_users()
        self.stdout.write("")
        # Creteate employees
        self.stdout.write("Creating employees...")
        employees = self.create_employees([admin_user, regular_user])
        # Create clients
        clients = self.create_clients(num_clients)
        self.stdout.write("")

        # Create products
        products = self.create_products()
        self.stdout.write("")

        # Create product-client prices
        self.create_product_client_prices(products, clients)
        self.stdout.write("")

        # Create transports and routes
        routes = self.create_transports_and_routes(clients, employees)
        self.stdout.write("")

        # Create orders for each client
        orders = self.create_orders(clients, products, regular_user, orders_per_client)

        # Print summary
        self.print_summary(admin_user, regular_user, clients, products, routes, orders)

    def create_users(self) -> tuple[User, User]:
        """Create admin and non-admin users."""
        self.stdout.write("Creating users...")

        # Create admin user
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@waterdelivery.com',
                'first_name': 'Admin',
                'last_name': 'User',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created admin user: {admin_user.username}"))
        else:
            self.stdout.write(f"  - Admin user already exists: {admin_user.username}")

        # Create non-admin user
        regular_user, created = User.objects.get_or_create(
            username='staff',
            defaults={
                'email': 'staff@waterdelivery.com',
                'first_name': 'Staff',
                'last_name': 'User',
                'is_staff': True,
                'is_superuser': False,
            }
        )
        if created:
            regular_user.set_password('staff123')
            regular_user.save()
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created staff user: {regular_user.username}"))
        else:
            self.stdout.write(f"  - Staff user already exists: {regular_user.username}")

        return admin_user, regular_user

    def create_employees(self, users) -> list[Employee]:
        """Create test employees."""
        self.stdout.write("Creating employees...")

        employees = []
        for user in users:
            employee, created = Employee.objects.get_or_create(
                user=user,
                defaults={
                    'nombre': user.first_name,
                    'apellidos': user.last_name,
                    'curp': f'CURP{user.id:04d}XXXXXX',
                    'rfc': f'RFC{user.id:04d}XXX',
                    'position': 'staff',
                    'street_number': 'Calle Falsa 123',
                    'city': 'Queretaro',
                    'state': 'Queretaro',
                    'zip_code': '76000',
                }
            )
            employees.append(employee)
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created employee for user: {user.username}"))
            else:
                self.stdout.write(f"  - Employee already exists for user: {user.username}")
        employee_data = [
            {'nombre': 'Juan',
                'apellidos': 'Pérez',
                'curp': 'JUAP850101HDFRRL09',
                'rfc': 'JUAP850101XXX',
                'position': 'driver'},
            {'nombre': 'María',
                'apellidos': 'López',
                'curp': 'MALP900202MDFRRL08',
                'rfc': 'MALP900202XXX',
                'position': 'driver'},
            {'nombre': 'Carlos',
                'apellidos': 'Gómez',
                'curp': 'CAGO920303HDFRRL07',
                'rfc': 'CAGO920303XXX',
                'position': 'manager'},
            {'nombre': 'Pedro',
                'apellidos': 'Martínez',
                'curp': 'PEMA880404HDFRRL06',
                'rfc': 'PEMA880404XXX',
                'position': 'driver'},
            {'nombre': 'Luis',
                'apellidos': 'Hernández',
                'curp': 'LUHE910505HDFRRL05',
                'rfc': 'LUHE910505XXX',
                'position': 'driver'},
            {'nombre': 'Roberto',
                'apellidos': 'Sánchez',
                'curp': 'ROSA870606HDFRRL04',
                'rfc': 'ROSA870606XXX',
                'position': 'driver'},
        ]
        for data in employee_data:
            employee, created = Employee.objects.get_or_create(
                curp=data['curp'],
                defaults={
                    'nombre': data['nombre'],
                    'apellidos': data['apellidos'],
                    'rfc': data['rfc'],
                    'position': data['position'],
                    'street_number': 'Calle Falsa 123',
                    'city': 'Queretaro',
                    'state': 'Queretaro',
                    'zip_code': '76000',
                }
            )
            employees.append(employee)
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created employee: {data['nombre']} {data['apellidos']}"))
            else:
                self.stdout.write(f"  - Employee already exists: {data['nombre']} {data['apellidos']}")
        return employees
    def create_clients(self, count: int = 50) -> list[Client]:
        """Create test clients with addresses and contacts."""
        self.stdout.write(f"Creating {count} clients...")

        clients = []
        client_names = [
            "Oficinas Centrales", "Bodega Norte", "Sucursal Centro", "Empresa Tech",
            "Restaurante El Sol", "Hotel Plaza", "Gimnasio Fitness", "Escuela Primaria",
            "Hospital Regional", "Farmacia San José", "Tienda Abarrotes", "Panadería La Rosa",
            "Carnicería Don Pedro", "Taller Mecánico", "Estética Bella", "Consultoría Legal",
            "Despacho Contable", "Clínica Dental", "Veterinaria Patitas", "Librería Cultura",
            "Papelería El Lápiz", "Ferretería Industrial", "Mueblería Casa", "Zapatería Elegante",
            "Boutique Moda", "Óptica Visión", "Joyería Diamante", "Floristería Jardín",
            "Pastelería Dulce", "Cafetería Aroma", "Heladería Fría", "Tortillería Maíz",
            "Lavandería Express", "Cerrajería Segura", "Imprenta Gráfica", "Agencia Viajes",
            "Constructora Atlas", "Inmobiliaria Norte", "Aseguradora Protección", "Banco Regional",
            "Cooperativa Ahorro", "Centro Comercial", "Supermercado Grande", "Minimarket 24h",
            "Gasolinera Norte", "Autolavado Express", "Refaccionaria Motor", "Pollería El Gallo",
            "Mariscos Del Mar", "Pizzería Italia"
        ]

        # Contact name data
        first_names = ["Ana", "Miguel", "Laura", "José", "Carmen", "Francisco", "María", "Antonio",
                       "Patricia", "Roberto", "Alejandra", "Jorge", "Sofía", "Ricardo", "Gabriela"]
        last_names = ["García", "Martínez", "López", "Hernández", "González", "Rodríguez",
                      "Pérez", "Sánchez", "Ramírez", "Torres", "Flores", "Rivera", "Gómez"]
        positions = ["Gerente", "Encargado", "Recepcionista", "Administrador", "Compras", "Dueño"]
        shared_address_data = {
            'street': 'Av. Universidad',
            'exterior_number': '123',
            'interior_number': 'Local 1',
            'locality': 'Centro',
            'municipality': 'Querétaro',
            'state': 'Querétaro',
            'zip_code': '76000',
            'country': 'México',
            'reference': 'Cerca de la plaza principal',
            'active': True,
        }

        for i in range(count):
            name = client_names[i] if i < len(client_names) else f"Cliente Test {i + 1}"

            client, created = Client.objects.get_or_create(
                name=name,
                defaults={
                    'active': True,
                    'type': 'branch',
                    'balance': Decimal('0.00'),
                    'credit_limit': Decimal(random.choice([1000, 2000, 5000, 10000])),
                    'current_debt': Decimal('0.00'),
                    'can_pay_with_credit': True,
                    'note': f'Cliente de prueba #{i + 1}',
                    'address_link': f'https://maps.google.com/?q=Queretaro+{name.replace(" ", "+")}',
                }
            )
            clients.append(client)

            delivery_address, delivery_created = Address.objects.get_or_create(
                client=client,
                type='delivery',
                defaults=shared_address_data,
            )

            billing_defaults = {
                'street': delivery_address.street,
                'exterior_number': delivery_address.exterior_number,
                'interior_number': delivery_address.interior_number,
                'locality': delivery_address.locality,
                'municipality': delivery_address.municipality,
                'state': delivery_address.state,
                'zip_code': delivery_address.zip_code,
                'country': delivery_address.country,
                'reference': delivery_address.reference,
                'active': delivery_address.active,
            }
            _, billing_created = Address.objects.get_or_create(
                client=client,
                type='billing',
                defaults=billing_defaults,
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created client: {client.name}"))
                self.stdout.write("    → Ensured delivery and billing addresses")

                # Create 1-2 contacts for each client
                num_contacts = random.randint(1, 2)
                for _ in range(num_contacts):
                    contact_first = random.choice(first_names)
                    contact_last = random.choice(last_names)
                    Contact.objects.create(
                        client=client,
                        name=f"{contact_first} {contact_last}",
                        email=f"{contact_first.lower()}.{contact_last.lower()}@{name.lower().replace(' ', '')}.com"[:100],
                        phone=f"442{random.randint(1000000, 9999999)}",
                        position=random.choice(positions),
                    )
                self.stdout.write(f"    → Created {num_contacts} contact(s)")
            else:
                self.stdout.write(f"  - Client already exists: {client.name}")
                if delivery_created or billing_created:
                    self.stdout.write("    → Added missing delivery/billing address")

        return clients

    def create_products(self) -> list[Product]:
        """Create test products."""
        self.stdout.write("Creating products...")

        # Create category
        category, _ = ProductCategory.objects.get_or_create(name="Agua")

        products_data = [
            {
                'name': 'Garrafón',
                'presentation': '20',
                'unit_of_measure': 1,  # lt
                
                'category': category,
            },
            {
                'name': 'Botella',
                'presentation': '500',
                'unit_of_measure': 2,  # ml
               
                'category': category,
            },
        ]

        products = []
        for product_data in products_data:
            product, created = Product.objects.get_or_create(
                name=product_data['name'],
                presentation=product_data['presentation'],
                defaults=product_data
            )
            products.append(product)
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created product: {product}"))
            else:
                self.stdout.write(f"  - Product already exists: {product}")

        return products

    def create_product_client_prices(
        self,
        products: list[Product],
        clients: list[Client]
    ) -> list[ProductClientPrice]:
        """
        Create product prices for each client with 3 different price tiers.

        Price tiers:
        - Tier 1 (clients 1-17): Base price
        - Tier 2 (clients 18-34): Medium price (+20%)
        - Tier 3 (clients 35-50): Premium price (+40%)
        """
        self.stdout.write("Creating product-client prices...")

        # Base prices for each product
        base_prices = {
            'Garrafón': 25.00,
            'Botella': 10.00,
        }

        # Price multipliers for each tier
        tier_multipliers = [1.0, 1.2, 1.4]  # Base, +20%, +40%

        prices = []
        for idx, client in enumerate(clients):
            # Determine tier (0, 1, or 2)
            tier = min(idx // 17, 2)
            multiplier = tier_multipliers[tier]

            for product in products:
                base_price = base_prices.get(product.name, 15.00)
                final_price = round(base_price * multiplier, 2)

                price, created = ProductClientPrice.objects.get_or_create(
                    product=product,
                    client=client,
                    defaults={
                        'price': final_price,
                        'note': f'Precio Tier {tier + 1}',
                    }
                )
                prices.append(price)

                if created:
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ Price: {client.name[:20]:20s} | {product.name:10s} = ${final_price:.2f} (Tier {tier + 1})"
                    ))
                else:
                    self.stdout.write(f"  - Price exists: {client.name[:20]:20s} | {product.name:10s}")

        return prices

    def create_transports_and_routes(self, clients: list[Client], employees: list[Employee]) -> list[Route]:
        """
        Create 5 routes with transports and assign 10 clients to each route.
        """
        self.stdout.write("Creating transports and routes...")

        drivers = []
        for employee in employees:
            if employee.position == 'driver':
                drivers.append(employee)
            
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created driver: {employee.nombre} {employee.apellidos}"))
            else:
                self.stdout.write(f"  - Driver already exists: {employee.nombre} {employee.apellidos}")

        # Create transports
        self.stdout.write(f"\n Drivers {len(drivers)} found. Creating transports...")
        transports = []
        transport_data = [
            {'license_plate': 'ABC-123', 'model': 'Ford F-150 2022', 'capacity_liters': 2000},
            {'license_plate': 'DEF-456', 'model': 'Chevrolet Silverado 2021', 'capacity_liters': 2500},
            {'license_plate': 'GHI-789', 'model': 'Nissan NP300 2023', 'capacity_liters': 1800},
            {'license_plate': 'JKL-012', 'model': 'Toyota Hilux 2022', 'capacity_liters': 2200},
            {'license_plate': 'MNO-345', 'model': 'Ram 1500 2021', 'capacity_liters': 2400},
        ]

        for idx, data in enumerate(transport_data):
            transport, created = Transport.objects.get_or_create(
                license_plate=data['license_plate'],
                defaults={
                    'model': data['model'],
                    'capacity_liters': data['capacity_liters'],
                    'is_active': True,
                    'assigned_driver': drivers[idx],
                }
            )
            transports.append(transport)
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created transport: {transport}"))
            else:
                self.stdout.write(f"  - Transport already exists: {transport}")

        # Create routes - one per transport with different weekdays
        weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
        route_names = [
            'Ruta Norte',
            'Ruta Sur',
            'Ruta Centro',
            'Ruta Este',
            'Ruta Oeste',
        ]

        routes = []
        for idx, (name, weekday, transport) in enumerate(zip(route_names, weekdays, transports)):
            route, created = Route.objects.get_or_create(
                transportation=transport,
                weekday=weekday,
                defaults={
                    'name': name,
                    'description': f'Ruta de reparto {name.lower()} - {weekday.capitalize()}',
                    'is_active': True,
                }
            )
            routes.append(route)
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created route: {route}"))
            else:
                self.stdout.write(f"  - Route already exists: {route}")

        # Assign 10 clients to each route
        self.stdout.write("\nAssigning clients to routes (10 per route)...")
        clients_per_route = 10

        for route_idx, route in enumerate(routes):
            start_idx = route_idx * clients_per_route
            end_idx = start_idx + clients_per_route
            route_clients = clients[start_idx:end_idx]

            for seq, client in enumerate(route_clients, start=1):
                route_client, created = RouteClient.objects.get_or_create(
                    route=route,
                    client=client,
                    defaults={
                        'sequence': seq,
                        'is_active': True,
                        'notes': f'Asignado automáticamente - Secuencia {seq}',
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ {route.name}: #{seq} - {client.name}"))
                else:
                    self.stdout.write(f"  - Already assigned: {client.name} to {route.name}")

        return routes

    def create_orders(
        self,
        clients: list[Client],
        products: list[Product],
        staff_user: User,
        orders_per_client: int = 10
    ) -> list[Order]:
        """
        Create orders for each client.

        Each client gets orders with random products and quantities.
        Orders are spread across the last 30 days with different statuses.
        Each completed order gets a payment with a different payment method.
        """
        self.stdout.write(f"Creating {orders_per_client} orders per client...")

        orders = []
        # Status distribution: 70% completed, 20% pending, 10% cancelled
        statuses = [
            OrderStatus.COMPLETED.value,
            OrderStatus.COMPLETED.value,
            OrderStatus.COMPLETED.value,
            OrderStatus.COMPLETED.value,
            OrderStatus.COMPLETED.value,
            OrderStatus.COMPLETED.value,
            OrderStatus.COMPLETED.value,
            OrderStatus.PENDING.value,
            OrderStatus.PENDING.value,
            OrderStatus.CANCELLED.value,
        ]

        # Payment methods to cycle through for completed orders
        # Excluding 'balance' and 'credit' which require special handling with client balance/credit
        payment_methods = ['cash', 'credit_card', 'debit_card', 'bank_transfer', 'paypal', 'cash', 'credit_card']

        for client in clients:
            # Get client's product prices
            client_prices = {
                pp.product_id: pp.price
                for pp in ProductClientPrice.objects.filter(client=client)
            }

            completed_order_idx = 0

            for order_num in range(orders_per_client):
                # Random date within last 30 days
                days_ago = random.randint(0, 30)
                order_date = timezone.now() - timedelta(days=days_ago)

                # Select status - spread them out
                status = statuses[order_num % len(statuses)]

                # Create order with initial total of 0
                order = Order.objects.create(
                    client=client,
                    total_amount=Decimal('0.00'),
                    status=status,
                    notes=f'Orden de prueba #{order_num + 1} para {client.name}',
                    owner=staff_user,
                )
                # Update order_date manually (since auto_now_add is set)
                Order.objects.filter(pk=order.pk).update(order_date=order_date)

                # Add 1-3 random products to the order
                total = Decimal('0.00')
                num_products = random.randint(1, min(3, len(products)))
                selected_products = random.sample(products, num_products)

                for product in selected_products:
                    quantity = random.randint(1, 10)
                    unit_price = Decimal(str(client_prices.get(product.id, 25.00)))

                    OrderProduct.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                    )
                    total += unit_price * quantity

                # Update order total
                order.total_amount = total
                order.cantidad_cobrada = total if status == OrderStatus.COMPLETED.value else None
                order.save()

                # Create payment for completed orders with different payment methods
                if status == OrderStatus.COMPLETED.value:
                    payment_method = payment_methods[completed_order_idx % len(payment_methods)]
                    Payment.objects.create(
                        amount=total,
                        method=payment_method,
                        client=client,
                        order=order,
                        status='completed',
                        created_by=staff_user,
                    )
                    completed_order_idx += 1

                orders.append(order)

            self.stdout.write(self.style.SUCCESS(f"  ✓ Created {orders_per_client} orders for: {client.name}"))

        return orders

    def print_summary(
        self,
        admin_user: User,
        regular_user: User,
        clients: list[Client],
        products: list[Product],
        routes: list[Route],
        orders: list[Order],
    ) -> None:
        """Print a summary of created data."""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("SUMMARY - Test Data Population Complete"))
        self.stdout.write("=" * 60)

        self.stdout.write(f"\n👤 Users created:")
        self.stdout.write(f"   - Admin: {admin_user.username} (password: admin123)")
        self.stdout.write(f"   - Staff: {regular_user.username} (password: staff123)")

        self.stdout.write(f"\n👥 Clients: {len(clients)} total")

        self.stdout.write(f"\n📦 Products: {len(products)} total")
        for product in products:
            self.stdout.write(f"   - {product}")

        self.stdout.write(f"\n💰 Product Prices (3 tiers):")
        self.stdout.write(f"   - Tier 1 (Clients 1-17):  Garrafón $25.00, Botella $10.00")
        self.stdout.write(f"   - Tier 2 (Clients 18-34): Garrafón $30.00, Botella $12.00")
        self.stdout.write(f"   - Tier 3 (Clients 35-50): Garrafón $35.00, Botella $14.00")

        self.stdout.write(f"\n🚛 Routes: {len(routes)} total (10 clients each)")
        for route in routes:
            client_count = route.route_clients.count()
            self.stdout.write(f"   - {route.name}: {client_count} clients ({route.get_weekday_display()})")

        self.stdout.write(f"\n📋 Orders: {len(orders)} total")
        completed = sum(1 for o in orders if o.status == OrderStatus.COMPLETED.value)
        pending = sum(1 for o in orders if o.status == OrderStatus.PENDING.value)
        cancelled = sum(1 for o in orders if o.status == OrderStatus.CANCELLED.value)
        self.stdout.write(f"   - Completed: {completed}")
        self.stdout.write(f"   - Pending: {pending}")
        self.stdout.write(f"   - Cancelled: {cancelled}")

        self.stdout.write(f"\n💳 Payments: {completed} total (one per completed order)")
        self.stdout.write(f"   Payment methods used: cash, credit_card, debit_card, bank_transfer, paypal")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Access admin at: http://localhost:8000/admin/")
        self.stdout.write("=" * 60 + "\n")
