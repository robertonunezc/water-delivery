# Order Receipt Signature And Email Design

## Context

The create-order flow currently completes payments through `payment.services.process_payment_request` and then redirects the user away from the order screen. The requested feature adds an optional receipt signing step after successful order completion, plus a reusable sign/resend action for completed orders.

The receipt is a durable signed PDF stored privately in Cloudflare R2. Email delivery sends the PDF as an attachment. R2 objects remain private; the app generates temporary access only when it needs to retrieve the PDF for an authenticated backend action such as resending.

## Goals

- Add a checkout checkbox labeled `Firmar y enviar recibo` below the `Terminar Pedido` button.
- When checked, complete/register the order payment first, then redirect the authenticated user to a mobile-friendly receipt signing form.
- Add a reusable completed-order action for signing, retrying, or resending the receipt.
- Store exactly one signed receipt per order and reuse that signed PDF forever.
- Store receipt metadata and the contact snapshot used at signing time.
- Generate a PDF containing full product lines, payments, totals, order date information, contact snapshot, and embedded signature.
- Upload the generated PDF to private Cloudflare R2.
- Send the PDF by email attachment for now, while keeping the sending backend ready for SMS and WhatsApp later.
- If PDF creation/upload succeeds but email delivery fails, keep the receipt saved as unsent and allow retry/resend.
- Add backend/model/service/view tests. No UI tests.

## Non-Goals

- No unauthenticated customer signing links.
- No role-specific permissions beyond requiring an authenticated user.
- No separate storage of the raw signature image; the signed PDF is the source of truth.
- No public or permanent PDF links.
- No SMS or WhatsApp implementation in this iteration.
- No multiple receipt versions per order.

## Data Model

Add `OrderReceipt` in the `orders` app. It should inherit `TimeStampedModel` to get `created_at`, `updated_at`, and soft-delete compatibility.

Fields:

- `order`: `OneToOneField` to `orders.Order`, related name `receipt`.
- `method`: delivery method, initially `email`; choices should be easy to extend with `sms` and `whatsapp`.
- `sent_at`: nullable datetime set only after successful delivery.
- `pdf_url`: private R2 object key or canonical private R2 URI, for example `receipts/orders/<order_id>.pdf`. This is not a public URL and not a long-lived signed URL.
- `contact_name`: receipt snapshot.
- `contact_email`: receipt snapshot and email recipient.
- `contact_phone`: receipt snapshot.
- `contact_position`: receipt snapshot.
- `created_by`: nullable user who created/signed the receipt.

Rules:

- One signed receipt per order. Attempts to create a second receipt should reuse or reject in favor of the existing receipt.
- Receipt signing is only allowed for completed orders.
- Resend uses the existing PDF and contact snapshot.
- If `sent_at` is null, the UI should present retry/send.

## User Flow

### Create Order

1. User builds an order and reaches checkout.
2. User optionally checks `Firmar y enviar recibo`.
3. User clicks `Terminar Pedido`.
4. The existing payment/order completion flow runs first.
5. If completion succeeds and the checkbox was checked, the frontend redirects to the receipt signing URL for that order.
6. If the checkbox was not checked, the existing redirect behavior remains.

### Completed Order Actions

Completed order list/detail actions should reflect receipt state:

- No receipt: show a sign/send receipt action.
- Receipt exists and `sent_at` is null: show retry/send receipt action.
- Receipt exists and `sent_at` has a value: show resend receipt action.

These actions should be available to authenticated users only.

## Signing Form

The signing form is mobile-friendly and authenticated.

Contact handling:

- If the client has multiple contacts, show a contact dropdown before signing.
- If the client has one contact, preselect and use it.
- If contact values are missing, the user may fill them in manually.
- Contact fields are editable and saved as the receipt snapshot, independent of future edits to the client contact.
- Email is required for email delivery.

Signature handling:

- Capture the hand signature in a browser canvas.
- Submit the signature image data only as part of receipt creation.
- Embed the signature image into the generated PDF.
- Do not store the raw signature image separately.

Submission result:

- On successful PDF creation and email delivery, set `sent_at` and show success.
- If PDF creation/upload succeeds but email fails, save the receipt, leave `sent_at` null, and show that resend/retry is available.
- If PDF creation or R2 upload fails, do not create a completed receipt record.

## PDF Generation

Create a receipt PDF generator service under the `orders` app, for example `orders/services/receipt_pdf_service.py`. Add a PDF generation dependency such as `reportlab` if the environment does not already provide one.

PDF content:

- Business/app heading.
- Order number.
- Client name.
- Order date and receipt creation date.
- Product lines with product name/presentation, quantity, unit price, and line total.
- Subtotal, discount, total, and charged amount when present.
- Payments with method, amount, and payment date.
- Contact snapshot: name, email, phone, position.
- Embedded signature.

The generator returns PDF bytes so storage and delivery remain separate from rendering.

## Private R2 Storage

Create a storage service abstraction for receipt PDFs, for example `orders/services/receipt_storage_service.py`.

Responsibilities:

- Upload PDF bytes to private R2.
- Return the private object identifier stored in `OrderReceipt.pdf_url`.
- Retrieve PDF bytes for resend using backend credentials.
- Generate short-lived signed URLs only when needed for backend/admin preview or internal retrieval.

Configuration should come from environment variables, following current settings style:

- R2 account endpoint.
- R2 bucket.
- R2 access key id.
- R2 secret access key.
- Optional receipt object prefix.
- Optional signed URL expiration seconds.

Implementation should use existing `boto3` dependency.

## Delivery Architecture

Use a sender registry/factory.

Components, grouped in a focused receipt delivery service module such as `orders/services/receipt_delivery_service.py`:

- `ReceiptDeliveryService`: coordinates delivery for an existing `OrderReceipt`.
- `ReceiptSenderFactory`: returns the sender for a method.
- `EmailReceiptSender`: current implementation. It retrieves PDF bytes, attaches the PDF, and sends to `OrderReceipt.contact_email`.
- Future senders: `SmsReceiptSender`, `WhatsappReceiptSender`.

The public service API should accept a receipt and method, not raw order details. This keeps resend and future channels consistent.

Email behavior:

- Attach the stored signed PDF.
- Use the receipt contact snapshot email.
- Update `sent_at` only when the sender succeeds.
- Leave `sent_at` null when sending fails.

## Error Handling

- Missing contact email for `email`: validation error before generating a PDF.
- Duplicate receipt creation: redirect to the existing receipt resend/retry flow.
- Non-completed order signing: reject with a clear error.
- PDF generation failure: no receipt saved.
- R2 upload failure: no receipt saved.
- Email failure after upload: receipt saved, `sent_at` null, retry available.

## Test Plan

No UI tests.

Backend tests:

- `OrderReceipt` enforces one receipt per order.
- Receipt form context preselects the only contact.
- Receipt form context exposes a contact dropdown when multiple contacts exist.
- Creating a receipt saves editable contact snapshot values.
- Creating a receipt rejects non-completed orders.
- Creating a receipt rejects missing email for email delivery.
- Successful receipt creation calls PDF generation, uploads to storage, calls email sender, and sets `sent_at`.
- Email failure after upload keeps the receipt with `sent_at` null.
- Retry/resend reuses the existing `pdf_url` and does not generate a new PDF.
- Create-order payment success with `Firmar y enviar recibo` checked returns or uses the receipt signing redirect.

## Implementation Notes

- Keep payment completion logic in `payment.services`; do not mix receipt delivery into payment processing.
- Add receipt orchestration in an order receipt service module.
- Keep Cloudflare R2 access behind a storage service so tests can mock it.
- Update list/detail templates to show receipt actions for completed orders.
- Update `orders/static/orders/js/create_order.js` so the checkbox changes post-success navigation only after the payment endpoint reports success.
