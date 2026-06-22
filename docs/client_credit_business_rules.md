# Reglas de negocio: clientes, facturación, crédito y pagos

Documento funcional para consultoría. Describe las reglas confirmadas para la administración de clientes, facturación, crédito, vencimientos y liquidación de deuda.

Fecha de actualización: 19 de junio de 2026.

## 1. Tipos de cliente

El sistema maneja dos tipos de cliente:

- **Corporativo:** cliente principal sin corporativo padre.
- **Sucursal:** cliente asociado obligatoriamente a un corporativo.

Una sucursal puede usar información de facturación propia o heredar la del corporativo.

## 2. Facturación de sucursales

Una sucursal hereda la información de facturación cuando:

- Requiere facturación.
- `billing_override_enabled` está deshabilitado.

En esta condición:

- La información de facturación se muestra como heredada y no puede editarse desde la sucursal.
- La configuración de crédito permanece independiente y puede editarse desde la sucursal.

Cuando `billing_override_enabled` está habilitado, la sucursal puede administrar su propia información de facturación. Este indicador no controla el acceso a su configuración de crédito.

## 3. Política de crédito

La política de crédito contiene:

- **Puede pagar con crédito:** habilita o deshabilita el uso de crédito.
- **Límite de crédito:** monto máximo de deuda activa autorizado.

Estas propiedades se administran en la pestaña **Crédito**, no en **Datos básicos**.

Reglas:

- Un cliente con crédito deshabilitado no puede realizar ventas a crédito, aunque tenga límite disponible.
- Un cliente sin crédito disponible no puede realizar una nueva venta a crédito.
- No se puede deshabilitar el crédito mientras el cliente tenga deuda activa.
- No se puede mantener un límite mayor que cero si el pago con crédito está deshabilitado.

## 4. Cálculo del crédito disponible

El crédito disponible se calcula como:

```text
crédito disponible = límite de crédito - deuda actual
```

Para determinar si una venta puede realizarse:

1. Se aplica primero cualquier saldo prepagado disponible.
2. Solamente el importe restante utiliza crédito.
3. La deuda resultante no puede superar el límite autorizado.

```text
deuda actual + importe a crédito <= límite de crédito
```

El límite es estricto. No existe tolerancia para excederlo.

## 5. Registro de una venta a crédito

Al registrar una venta a crédito:

1. Se consume primero el saldo prepagado del cliente.
2. El importe restante se registra como deuda.
3. Se crea una transacción de crédito vinculada con la orden.
4. Se crea un registro `pending_credit` para representar el saldo pendiente de liquidación.

El registro `pending_credit` es un marcador de deuda, no dinero recibido. Por lo tanto, nunca debe incluirse en el total efectivamente pagado de una orden o factura.

## 6. Límite estricto de crédito

Toda venta que genere deuda debe rechazarse cuando provoque que la deuda activa supere el límite autorizado.

La validación debe ejecutarse en el servicio que registra la deuda, dentro de una transacción y bloqueando el registro del cliente durante la actualización. Esto evita que dos ventas concurrentes utilicen simultáneamente el mismo crédito disponible.

Los intereses, cargos o ajustes contables no se consideran nuevas ventas para esta validación específica. La restricción estricta aquí descrita aplica a transacciones de tipo compra.

## 7. Modalidades de vencimiento

Cada configuración de crédito utiliza exactamente una de estas modalidades:

### 7.1 Fecha de corte mensual

El cliente debe liquidar el 100% de la deuda correspondiente en una fecha de corte mensual.

Opciones disponibles:

- Día numérico del 1 al 31.
- Último día del mes.

Reglas de cálculo:

- Una venta realizada antes del corte vence en el corte del mismo mes.
- Una venta realizada el día del corte vence ese mismo día.
- Una venta realizada después del corte vence en el corte del mes siguiente.
- Si se selecciona un día que no existe en un mes, se utiliza el último día real de ese mes.
- La opción **Último día del mes** se calcula con el calendario real; no se almacena como día 30.

Esta modalidad puede utilizarse tanto para clientes que requieren factura como para clientes que no la requieren.

### 7.2 Vencimiento posterior a factura

El vencimiento se calcula mediante un número de días naturales posteriores a la fecha real de emisión de la factura.

```text
fecha de vencimiento = fecha de emisión + días naturales autorizados
```

Reglas:

- Solo está disponible para clientes que requieren facturación.
- La fecha inicial es `emmited_at`, no la fecha de la orden ni la fecha de entrega.
- Mientras la factura no tenga fecha de emisión, el vencimiento permanece pendiente y no empieza a correr el plazo.
- No se puede deshabilitar la facturación mientras esta modalidad esté configurada. Primero debe cambiarse a fecha de corte mensual.

## 8. Determinación de vencimiento y morosidad

Una deuda se considera vencida cuando la fecha actual es posterior a su fecha de vencimiento.

- Durante el propio día de vencimiento todavía puede pagarse sin considerarse vencida.
- Para mostrar el estado del cliente se utiliza la fecha más próxima entre sus créditos pendientes.
- Si esa fecha ya pasó, se presenta como crédito vencido.
- Si la modalidad depende de factura y todavía no existe fecha de emisión, se muestra **Pendiente de emisión de factura**.
- Si no existen créditos pendientes, se muestra **Sin créditos pendientes**.

Solo se consideran para vencimiento las órdenes que:

- Tienen una transacción de compra a crédito vinculada.
- Mantienen un importe pendiente de pago.

## 9. Restricciones por deuda vencida

Un cliente con crédito vencido:

- No puede realizar nuevas ventas a crédito.
- Sí puede realizar ventas pagadas completamente con efectivo, transferencia, tarjeta u otro método de contado.
- Sí puede utilizar saldo prepagado para una venta que no genere deuda adicional.
- Sí puede efectuar pagos para liquidar su deuda.

No existe actualmente un mecanismo de autorización para omitir esta restricción. Cualquier bypass deberá definirse posteriormente con permisos, justificación obligatoria y auditoría.

## 10. Liquidación de una orden a crédito

El pago de una orden a crédito debe ejecutarse como una sola operación transaccional:

1. Registrar el pago real.
2. Reducir `current_debt` por el importe liquidado.
3. Crear la transacción de crédito de tipo pago.
4. Vincular la transacción con la orden y el pago.
5. Marcar el registro `pending_credit` como completado.
6. Restaurar inmediatamente el crédito disponible.

Actualmente, la liquidación exige cubrir el saldo pendiente completo de la orden. Los pagos parciales no están habilitados en este flujo.

El crédito restaurado se calcula automáticamente al reducirse la deuda:

```text
nuevo crédito disponible = límite de crédito - nueva deuda actual
```

## 11. Reconciliación de pagos históricos

Para pagos registrados antes de corregir el flujo de liquidación:

- Si existe un pago completado que no redujo la deuda y su importe coincide exactamente con el saldo pendiente, el sistema puede aplicarlo a la deuda sin crear ni cobrar otro pago.
- La reconciliación crea la transacción de reducción de deuda y completa el marcador `pending_credit`.
- Si el importe histórico no coincide con el saldo pendiente, se bloquea un nuevo pago y se exige revisión manual.
- La reconciliación debe ser idempotente: un pago ya aplicado no puede reducir la deuda por segunda vez.

## 12. Fuente de verdad contable

Las fuentes de verdad son:

- `Client.current_debt`: deuda activa agregada del cliente.
- `Client.credit_limit`: límite autorizado.
- `CreditTransaction`: historial auditable de aumentos, pagos y ajustes de deuda.
- `Payment` completado, excluyendo `pending_credit`: dinero efectivamente recibido o saldo prepagado utilizado.

Una orden puede mostrarse como pagada únicamente cuando la suma de pagos completados reales cubre el total de la orden. El marcador `pending_credit`, incluso si está completado, debe excluirse de esta suma.

## 13. Migración de configuraciones existentes

Al introducir las modalidades de vencimiento:

- Los clientes existentes con configuración de crédito y facturación habilitada se migran a **Vencimiento posterior a factura**, conservando `max_payment_days`.
- Los clientes existentes sin facturación se migran a **Fecha de corte mensual — Último día del mes**.
- Una configuración nueva sin facturación utiliza por defecto fecha de corte mensual y último día del mes.
- Una configuración nueva con facturación utiliza inicialmente vencimiento posterior a factura.

## 14. Reglas de interfaz

- Los campos de política de crédito no aparecen en **Datos básicos**.
- La pestaña **Crédito** contiene la política y las condiciones de pago.
- El formulario muestra el día de corte únicamente para modalidad mensual.
- El formulario muestra los días naturales únicamente para modalidad posterior a factura.
- La configuración de notificaciones no se muestra en este formulario.
- La ficha de detalle del cliente muestra el vencimiento de crédito más próximo.
- La edición del cliente incluye un enlace a su ficha de detalle.

Las restricciones visuales siempre deben tener una validación equivalente en el servidor.

## 15. Puntos pendientes de definición

Los siguientes comportamientos no forman parte de las reglas actuales:

- Pagos parciales de una orden a crédito.
- Autorización para vender a crédito a un cliente vencido.
- Reglas de permisos y auditoría para un bypass manual.
- Reprogramación o prórroga individual de vencimientos.
- Aplicación automática de intereses o recargos por mora.
- Manejo de convenios de pago o reestructuración de deuda.

## 16. Observación para consultoría

La facturación y el crédito son configuraciones independientes. Una sucursal puede heredar los datos fiscales del corporativo y, al mismo tiempo, mantener su propio límite, deuda y condiciones de crédito. No existe consolidación automática de crédito o deuda entre el corporativo y sus sucursales.
