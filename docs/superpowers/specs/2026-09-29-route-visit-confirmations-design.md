# Route Visit Confirmations Design

## Purpose

Build a route visit confirmation module so employees can ask a client whether to visit them on their next due route date. The feature confirms route visits, not orders. It should reduce unnecessary visits while leaving the route operational flow unchanged.

## Scope

Create a new Django app named `route_confirmations`. Confirmation records belong to tenant data, so the app is added to tenant apps. The employee-facing management page lives at `/administrador/confirmaciones/` and appears as a top-level `Confirmaciones` navigation item.

The route client row shows the current confirmation state for the next due visit date and provides the send action when allowed.

## Confirmation Model

Store one confirmation per `RouteClient` and `visit_date`. The stored status values are:

- `Enviada`
- `Confirmada`
- `NO visitar`

Expired pending records keep `status='Enviada'`, but the UI displays them as `Expirada` when `expires_at` is in the past.

Each confirmation stores:

- `route_client`
- `visit_date`
- `status`
- secure one-time token
- `sent_at`
- `expires_at`
- `responded_at`
- public response action marker for client clicks
- `sent_by`
- `responded_by` for staff/admin overrides
- required override note for manual overrides
- JSON receipt list for recipient attempts
- soft-delete timestamp through `TimeStampedModel`

Uniqueness is enforced for active records by `RouteClient + visit_date`.

When a `RouteClient` is deleted or deactivated, related active confirmations are soft-deleted/archived.

## Visit Date

The send service targets the client's next due visit date using the route weekday, `RouteClient.interval_weeks`, and `RouteClient.anchor_date`. If the route client is due today, today is the target visit date.

## Send Behavior

Any authenticated employee/user who can view the route can send a confirmation from the route client row. The send action uses all `Contact.email` addresses for the client. It does not use `Client.email`.

If no contacts have email addresses, the send action fails with a clear warning.

If at least one recipient sends successfully, the confirmation counts as sent. Failed recipients are shown as warnings. The confirmation stores all recipient attempts in its receipt list, including successful and failed attempts.

Sending is synchronous for v1.

Resending is allowed only after expiration. Resend reuses the same confirmation record and replaces the token, `sent_at`, `expires_at`, and receipt list.

## Delivery Architecture

Use a channel-agnostic delivery service with a sender factory. Email is the first sender, backed by the existing Mailgun email channel. SMS and WhatsApp can later be added as new sender classes without changing the confirmation flow.

The service should expose a single route-confirmation send entrypoint and keep channel-specific behavior behind a small sender interface.

## Email

Subject:

`Confirma tu visita de {{ fecha }} de entrega de garrafones de agua`

The date format is capitalized Spanish month, for example `23 Febrero 2026`.

Email body includes:

- client name
- visit date
- `Confirmar visita` button
- `No visitar` button

The email buttons are one-click actions. Each button uses the same confirmation token and carries the action in the URL.

Public links use the same tenant domain as the employee app.

## Public Response Links

The response link is unauthenticated. It validates token, action, expiration, and current response state before recording.

The token remains reusable until a valid response is successfully recorded. Once a response is recorded, the confirmation is locked.

Valid actions:

- `confirmar` records `Confirmada`
- `no-visitar` records `NO visitar`

After a valid click, show a simple public success page with client name, visit date, and selected decision.

If another contact clicks after a response is already recorded, show that the visit was already answered and display the recorded decision.

If the link is expired and no response exists, show:

`Este enlace expiró. Por favor comunícate con nosotros para confirmar tu visita.`

Do not record anything for expired links.

## Route Row UI

The route client row displays a badge for the next due visit confirmation:

- No record: no final badge, with `Enviar confirmación`
- Pending `Enviada`: display `Enviada`, send button disabled
- Expired pending: display `Expirada`, button `Enviar de nuevo`
- `Confirmada`: display `Confirmada`, button disabled
- `NO visitar`: display `NO visitar`, button disabled

`NO visitar` only records and displays the badge. It does not hide the client from the route and does not block creating an order.

## Management Page

`/administrador/confirmaciones/` lists only existing confirmation records. It supports filters for:

- route
- display status
- visit date
- client search

Staff/admin users can manually override any confirmation status, including records already answered by a client. Overrides require a short note, store `responded_by`, and update `responded_at`.

Regular employees can view records but cannot manually override.

## Security

Tokens must be generated with a cryptographically secure random value. Token lookup should not reveal whether a route client or client exists. Invalid, expired, already answered, and malformed requests should return simple public pages, not stack traces or sensitive details.

The public action endpoint must be CSRF-exempt only if needed for GET one-click links; authenticated employee actions stay CSRF-protected POSTs.

Manual override and management access must enforce staff/admin permission for mutating overrides.

## Testing

Unit tests cover:

- next due visit date calculation, including today
- creation/reuse uniqueness by `RouteClient + visit_date`
- send to all contact emails
- no-recipient failure
- partial send success with warning data
- token regeneration on expired resend
- public response success for both actions
- expired link behavior
- already answered link behavior
- staff override with required note
- soft-delete/archive when route client is deactivated/deleted

View tests cover:

- route row context exposes badge/button state
- management filters by route, status, visit date, and client search
- public success/expired/already-answered pages
