# Plan de Implementacion de Cobranza por Sesiones

## Objetivo
Implementar el modulo de cobranza del diagrama (incidencias -> gestion -> promesas -> verificacion -> politicas -> bitacora) en unidades de trabajo pequenas, independientes y acumulativas, para continuar en multiples sesiones sin perder contexto.

## Principios de ejecucion
- No duplicar logica financiera existente: reutilizar clients/services/balance_service.py y payment/models.py.
- Orquestacion en capa de servicios: reglas de cobranza en un modulo/app dedicado.
- Trazabilidad total: cada accion relevante debe quedar en bitacora.
- Cambios pequenos por PR: preferir 200-400 lineas por PR.
- Cada sesion termina con: estado, decisiones, riesgos, siguiente paso y comando de validacion.

## Alcance funcional (derivado del PDF)
- Deteccion de nuevas incidencias de cobranza.
- Gestion por cliente (caso activo).
- Registro y seguimiento de promesas de pago.
- Verificacion de cumplimiento de promesas.
- Aplicacion de politicas para incumplimiento.
- Registro en bitacora y notificaciones a areas.
- Proceso iterativo cliente por cliente.

## Estructura de trabajo por bloques

### Bloque 0. Preparacion y base tecnica
Objetivo: dejar listo el terreno para implementar sin retrabajo.

Unidad 0.1: Crear app de cobranza y estructura minima
- Entregables:
  - App nueva (recomendado: collections o cobranza).
  - Registro en INSTALLED_APPS.
  - Archivos base: models.py, services.py, admin.py, urls.py, tests.py.
- Criterio de salida:
  - Migraciones corren sin errores.
  - App visible en admin (aunque vacia).

Unidad 0.2: Convenciones y contrato de dominio
- Entregables:
  - Enumeraciones iniciales de estados de caso, tipos de incidencia, tipos de accion.
  - Documento corto de reglas en el modulo (docstring + comentarios puntuales).
- Criterio de salida:
  - Tipos y nombres consolidados para evitar renombres posteriores.

Sesion sugerida: 1

---

### Bloque 1. Modelo de datos de cobranza
Objetivo: persistir programa, caso, incidencias y bitacora.

Unidad 1.1: Modelos nucleares
- Entregables:
  - CollectionProgram.
  - CollectionCase.
  - CollectionIncident.
  - CollectionActionLog (bitacora).
- Reglas:
  - Heredar de TimeStampedModel cuando aplique.
  - Indices para consultas por cliente, estado y fecha.
- Criterio de salida:
  - Migracion creada y aplicada.
  - Tests basicos de creacion y relaciones.

Unidad 1.2: Unicidad e idempotencia minima
- Entregables:
  - Restriccion para evitar incidencias duplicadas por cliente/tipo/periodo.
  - Regla para caso activo unico por cliente (si aplica al negocio).
- Criterio de salida:
  - Tests de no-duplicacion.

Sesion sugerida: 1

---

### Bloque 2. Motor de deteccion de incidencias
Objetivo: detectar automaticamente clientes con riesgo/cobranza.

Unidad 2.1: Servicio de deteccion
- Entregables:
  - Servicio detect_new_incidents(check_date).
  - Reglas iniciales:
    - Vencimiento por dias de credito (max_payment_days).
    - Exceso de deuda/limite de credito.
    - Reglas temporales para fecha de corte (si aplica).
- Criterio de salida:
  - Retorna incidentes consistentes y repetibles.
  - Sin side effects fuera de la app de cobranza.

Unidad 2.2: Creacion/actualizacion de casos
- Entregables:
  - Servicio open_or_update_cases(incidents).
  - Enlace incidencia <-> caso.
- Criterio de salida:
  - Caso nuevo para cliente sin caso activo.
  - Caso existente se actualiza, no duplica.

Sesion sugerida: 1

---

### Bloque 3. Promesas de pago y seguimiento
Objetivo: capturar negociacion y su ciclo de vida.

Unidad 3.1: Modelo PaymentPromise
- Entregables:
  - Campos: monto prometido, fecha prometida, estado, notas, negociado_por.
  - Estado minimo: negotiated, fulfilled, broken, cancelled.
- Criterio de salida:
  - Promise ligada a caso.
  - Admin basico para registrar promesa.

Unidad 3.2: Servicio de gestion de promesas
- Entregables:
  - create_promise(case, ...)
  - mark_promise_fulfilled(...)
  - mark_promise_broken(...)
  - Registro automatico en bitacora.
- Criterio de salida:
  - Transiciones validas de estado.
  - Tests de transicion.

Sesion sugerida: 1

---

### Bloque 4. Verificacion contra pagos reales
Objetivo: validar cumplimiento de promesas con datos del sistema.

Unidad 4.1: Motor de verificacion
- Entregables:
  - verify_promises(check_date).
  - Consulta a pagos/deuda del cliente usando modelos existentes.
- Criterio de salida:
  - Marca fulfilled o broken de forma deterministica.
  - Genera bitacora con evidencia minima (monto, fecha, referencia).

Unidad 4.2: Reglas de tolerancia
- Entregables:
  - Definir tolerancia de monto/fecha (si negocio la requiere).
- Criterio de salida:
  - Casos borde cubiertos por tests.

Sesion sugerida: 1

---

### Bloque 5. Politicas por incumplimiento
Objetivo: ejecutar acciones de credito/restriccion al fallar gestion.

Unidad 5.1: Catalogo de politicas
- Entregables:
  - PolicyExecution model o estructura equivalente.
  - Politicas iniciales configurables:
    - Deshabilitar pago con credito.
    - Alertar a departamentos internos.
    - Marcar cliente en estado restringido para seguimiento.
- Criterio de salida:
  - Politica aplicada y trazada en bitacora.

Unidad 5.2: Orquestacion de fallo de gestion
- Entregables:
  - apply_failed_management_policies(case).
  - Integracion con notificaciones.
- Criterio de salida:
  - Flujo completo de incumplimiento funciona extremo a extremo.

Sesion sugerida: 1

---

### Bloque 6. Notificaciones de cobranza
Objetivo: automatizar recordatorios y avisos por estado de cobranza.

Unidad 6.1: Plantillas y tipos
- Entregables:
  - Tipos de notificacion de cobranza conectados a estados de caso/promesa.
  - Mensajes base para: recordatorio futuro, promesa incumplida, restriccion aplicada.
- Criterio de salida:
  - Notificaciones creadas con payload consistente.

Unidad 6.2: Envios por lotes
- Entregables:
  - process_daily_collections_notifications(check_date).
- Criterio de salida:
  - Estadisticas de envio (sent/failed/skipped).

Sesion sugerida: 1

---

### Bloque 7. UI operativa (Admin)
Objetivo: habilitar operacion real del equipo de cobranza.

Unidad 7.1: Vistas de lista y filtros
- Entregables:
  - Lista de casos por estado, antiguedad, monto de deuda, cliente.
  - Filtro de "promesas vencidas".
- Criterio de salida:
  - Operador identifica trabajo diario en menos de 2 clicks.

Unidad 7.2: Acciones de operador
- Entregables:
  - Registrar gestion.
  - Crear promesa.
  - Marcar resultado de seguimiento.
  - Aplicar politica manual.
- Criterio de salida:
  - Todas las acciones generan bitacora.

Sesion sugerida: 1-2

---

### Bloque 8. Reportes y cierre
Objetivo: medir recuperacion y salud del proceso.

Unidad 8.1: KPIs minimos
- Entregables:
  - Casos abiertos/cerrados.
  - Promesas cumplidas/incumplidas.
  - Monto recuperado en periodo.
- Criterio de salida:
  - Reporte visible y validable por negocio.

Unidad 8.2: Validacion integral
- Entregables:
  - Suite de pruebas final del modulo.
  - Checklist de regresion en pagos/credito.
- Criterio de salida:
  - Flujo completo aprobado.

Sesion sugerida: 1

---

## Plan de sesiones sugerido (resumen)
- Sesion 1: Bloque 0 + Bloque 1.
- Sesion 2: Bloque 2.
- Sesion 3: Bloque 3.
- Sesion 4: Bloque 4.
- Sesion 5: Bloque 5.
- Sesion 6: Bloque 6.
- Sesion 7: Bloque 7.
- Sesion 8: Bloque 8 + hardening.

## Definicion de terminado por sesion
Cada sesion debe cerrar con:
1. Codigo y migraciones en verde.
2. Tests unitarios del bloque implementado.
3. Nota de decisiones tecnicas tomadas.
4. Lista de pendientes concretos del siguiente bloque.
5. Riesgos detectados y mitigacion.

## Plantilla de handoff entre sesiones (copiar/pegar)
Usa esta plantilla al final de cada sesion en docs o en el PR:

- Fecha:
- Sesion numero:
- Bloque y unidades completadas:
- Archivos tocados:
- Migraciones nuevas:
- Tests agregados/actualizados:
- Estado actual del flujo de cobranza:
- Decisiones tomadas:
- Riesgos abiertos:
- Siguiente unidad exacta:
- Comando de verificacion rapido:

## Context pack para retomar rapido en la siguiente sesion
Antes de continuar, revisar:
- docs/Modulo de cobranza.pdf
- docs/COBRANZA_SESIONES_PLAN.md
- clients/models.py (ClientCreditConfig, BalanceTransaction, CreditTransaction)
- clients/services/balance_service.py
- payment/models.py
- notification/services.py

## Backlog inicial de tickets (listos para crear)
- COB-001: Crear app de cobranza y estructura base.
- COB-002: Modelos CollectionProgram/Case/Incident/ActionLog.
- COB-003: Motor de deteccion de incidencias.
- COB-004: Modelo y servicios de promesas de pago.
- COB-005: Verificacion automatica de promesas.
- COB-006: Politicas por incumplimiento y restriccion.
- COB-007: Integracion de notificaciones de cobranza.
- COB-008: Admin operativo de casos y promesas.
- COB-009: KPIs y reporte de cobranza.
- COB-010: Pruebas integrales y regresion.

## Recomendaciones para no perder contexto
- Mantener 1 PR por bloque o sub-bloque (no mezclar objetivos).
- Escribir handoff al cierre de cada sesion.
- No iniciar una unidad sin criterio de salida claro.
- Si una unidad crece demasiado, dividir en subunidad A/B y cerrar A primero.
