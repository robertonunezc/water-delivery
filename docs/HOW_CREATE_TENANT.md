# Steps for create a tenant
1. Create a subdomain
    . namecheap
    . Got to advance config for the domain
    . Add a new A record with the name and the IP for the URL to redirect.
2. Configure Nginx
    . NO CHANGES ARE REQUIRED HERE
3. Creates the tenant in the APP
    . ./manage.py shell
    . from tenant_client.services import 
    create_tenant_with_domain
    . from datetime import date, timedelta

    . tenant, dom = create_tenant_with_domain(
        name="pabel",
        schema_name="pabel",
        domain_name="pabel.gestionpurificadora.com",
        paid_until=date.today() + timedelta(days=3365),
        on_trial=True
    )
4. Creates tenant super user
The command create_tenant_superuser is already automatically wrapped to have a schema flag. Create a new super user with

./manage.py create_tenant_superuser --username=pab_user --schema=pabel

