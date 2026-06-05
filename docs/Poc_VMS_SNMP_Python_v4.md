# PoC técnica pre-código — VMS NTCIP 1203 v3 con Python + SNMP
# Versión 4

---

## 1. Cambios respecto a la versión anterior

### 1.1 Escenarios eliminados

| ID anterior | Nombre | Motivo |
|---|---|---|
| POC-VMS-06 (v2) | Expiración de manual sin schedule activo | El scheduling se implementa del lado del software (Serviam), no en el panel. |
| POC-VMS-07 (v2) | `dmsEndDurationMessage` — comportamiento real | Mismo motivo. No aplica en el modelo de Serviam. |
| POC-VMS-08 (v3) | Tipos de ventana soportados | Redundante: si el panel no soporta un tipo de ventana, el intento de carga del schedule ya lo detecta. No justifica un escenario separado. |
| POC-VMS-13 (v3) | `commLoss` y `dmsTimeCommLoss` | Requiere corte de red controlado — operación física. Se incorpora como parte del flujo de POC-VMS-09 (v4, recovery tras offline). |

### 1.2 Escenarios modificados

| ID v3 | ID v4 | Cambio |
|---|---|---|
| POC-VMS-08 | POC-VMS-06 | Solo manual vs manual y AUTHORITY. Sin cambios de contenido. |
| POC-VMS-07 | POC-VMS-07 | Renumeración. Sin cambios. |
| POC-VMS-08 | POC-VMS-08 | Renumeración. Sin cambios. |
| POC-VMS-11 (v3) | POC-VMS-10 | Renumeración. Se agrega marcador `REQUIRES_PHYSICAL`: el override externo requiere operación local en consola del fabricante o cambio físico de `dmsControlMode`. |
| POC-VMS-10 | POC-VMS-08 | Renumeración. Sin cambios. |
| POC-VMS-14 (v3) | POC-VMS-12 | Renumeración. Se agrega marcador `REQUIRES_PHYSICAL`: requiere corte físico de red o bloqueo de SNMP en el router. |
| POC-VMS-15 (v3) | POC-VMS-13 | Renumeración. Se agrega marcador `REQUIRES_PHYSICAL`: requiere corte de alimentación eléctrica o reset del VFC. |
| POC-VMS-13 al 22 | POC-VMS-13 al 19 | Renumeración en cascada. Sin cambios de contenido. |

### 1.3 Clasificación por modo de ejecución

Los escenarios se dividen en dos categorías que determinan el comportamiento del runner:

| Categoría | Descripción | Comportamiento del runner |
|---|---|---|
| `AUTOMATIC` | Sin intervención física. El script corre sin pausas. | Se ejecutan en secuencia al iniciar el runner. |
| `REQUIRES_PHYSICAL` | Requiere una acción física del operador (corte de red, reboot, operación en consola local) antes de continuar. | Se saltean en la primera pasada. Al finalizar todos los automáticos, el runner pregunta si continuar con estos. Para cada uno muestra las instrucciones físicas requeridas y espera confirmación (`Enter`) antes de ejecutar. |

### 1.4 Reordenamiento por grupos

| Grupo | Escenarios | Modo |
|---|---|---|
| Conectividad y descubrimiento | POC-VMS-01, 02, 03 | AUTOMATIC |
| Mensajes: lectura y activación | POC-VMS-04, 05 | AUTOMATIC |
| Prioridades | POC-VMS-06 | AUTOMATIC |
| Schedule DEVICE | POC-VMS-07, 08 | AUTOMATIC |
| Divergencia y monitoreo | POC-VMS-09, 10, 11 | POC-VMS-10: REQUIRES_PHYSICAL / POC-VMS-09, 11: AUTOMATIC |
| Recovery y resiliencia | POC-VMS-12, 13 | REQUIRES_PHYSICAL |
| Capacidades de hardware | POC-VMS-13, 14, 15 | AUTOMATIC |
| Errores y fallos | POC-VMS-13, 17, 18, 19 | AUTOMATIC |
---

## 2. Resultado esperado de la PoC

La PoC debe producir tres entregables:

1. **Evidencia cruda**
   - archivos `.jsonl` por escenario;
   - valores SNMP leídos/escritos;
   - timestamps;
   - errores;
   - capturas visuales del panel cuando aplique.

2. **Reporte de resultado**
   - tabla por escenario con `PASS`, `FAIL`, `PARTIAL`, `QUIRK_PROVIDER` o `BLOCKED`;
   - observaciones;
   - impacto sobre el diseño.

3. **Matriz de decisión**
   - qué asunciones se confirman;
   - qué asunciones se rechazan;
   - qué comportamiento debe modelarse como específico de Daktronics/Chainzone;
   - qué debe modificarse en el documento técnico.

---

## 3. Formato de evidencia

Cada escenario debe generar un archivo `.jsonl` en:

```text
poc/snmp-vanguard/evidence/<scenario_id>_<timestamp>.jsonl
```

Cada línea debe tener este formato:

```json
{
  "scenario_id": "POC-VMS-16",
  "step": "activate_crc_error",
  "timestamp_utc": "2026-06-01T15:00:00.000Z",
  "operation": "SNMP_SET",
  "oid_name": "dmsActivateMessage",
  "oid": "1.3.6.1.4.1.1206.4.2.3.6.3.0",
  "snmp_type": "OctetString",
  "value_sent": "FFFF4006000100FF00000000",
  "value_read": null,
  "success": false,
  "error": "messageCRC(7)",
  "notes": "CRC deliberadamente incorrecto para disparar error"
}
```

Cada escenario debe terminar con un resumen:

```json
{
  "scenario_id": "POC-VMS-16",
  "result": "PASS",
  "summary": "Panel retorna codigo de error correcto para cada caso probado.",
  "design_impact": "Mapa de errores fijado en DaktronicsVanguardProvider y ChainzoneProvider."
}
```

---

## 4. Escenarios de prueba

---

## GRUPO 1 — Conectividad y descubrimiento

---

### POC-VMS-01 — Conectividad SNMP base

#### Para qué sirve

Confirmar que el panel responde a SNMP con la versión y credenciales configuradas. Es el primer paso obligatorio antes de cualquier otro escenario. Si este falla, ninguno de los siguientes puede ejecutarse.

#### Cómo se verifica

```bash
python -m scenarios.poc_01_connectivity \
  --config config/panel.chainzone.lab.yaml
```

#### Pasos

1. Leer `sysDescr`.
2. Leer `sysUpTime`.
3. Repetir 5 veces con intervalo de 5 segundos.
4. Registrar latencia de cada GET.
5. Registrar errores SNMP si existen.

#### Criterio de éxito

`PASS` si al menos 5/5 lecturas responden sin timeout.

---

### POC-VMS-02 — Descubrimiento y confirmación de OIDs NTCIP

#### Para qué sirve

Construir el mapa real de OIDs que se usará en el resto de la PoC. No todos los paneles exponen los mismos OIDs aunque sean NTCIP 1203 compliant — hay OIDs opcionales, OIDs propietarios del fabricante y OIDs con rutas distintas según firmware. Este escenario cierra ese mapa antes de escribir una sola línea de código de producción.

#### Cómo se verifica

```bash
python -m scenarios.poc_02_oid_map \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

1. Ejecutar WALK sobre ramas NTCIP conocidas.
2. Ejecutar GET sobre OIDs simbólicos ya conocidos.
3. Registrar `NoSuchObject`, `NoSuchInstance` y errores de tipo.
4. Completar `oids.ntcip1203.v3.yaml` con los OIDs numéricos confirmados.
5. Separar OIDs estándar NTCIP de OIDs propietarios Daktronics/Chainzone.

#### Resultado esperado

Mapa mínimo confirmado para: mensaje activo, activación, duración, prioridad runtime, schedule, reloj, estado técnico, brillo, gráficos.

#### Criterio de éxito

`PASS` si se pueden confirmar los OIDs necesarios para los escenarios POC-VMS-03 a POC-VMS-19.

---

### POC-VMS-03 — Capacidades reales del panel

#### Para qué sirve

Leer y registrar el conjunto completo de capacidades y límites operativos del panel necesarios para poblar `panel_capability_profiles`. Este perfil es el que usa el sistema para validar mensajes MULTI, gestionar slots de memoria, controlar gráficos y fuentes, y configurar schedules. Sin estos valores, cualquier operación posterior puede fallar silenciosamente o producir errores difíciles de diagnosticar. Es lectura pura — sin writes.

El escenario cubre cinco bloques: dimensiones físicas, capacidades de color, memoria de mensajes, fuentes, gráficos, brillo y scheduler.

#### Cómo se verifica

```bash
python -m scenarios.poc_03_panel_limits \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

**Bloque 1 — Dimensiones físicas del display**

1. Leer `vmsSignHeightPixels` — alto total del panel en píxeles.
2. Leer `vmsSignWidthPixels` — ancho total del panel en píxeles.
3. Leer `vmsCharacterHeightPixels` — altura de carácter en píxeles (0 = full matrix).
4. Leer `vmsCharacterWidthPixels` — ancho de carácter en píxeles (0 = full matrix o line matrix).
5. Leer `vmsHorizontalPitch` — distancia horizontal entre centros de píxeles en mm.
6. Leer `vmsVerticalPitch` — distancia vertical entre centros de píxeles en mm.

**Bloque 2 — Color**

7. Leer `dmsColorScheme` — esquema de color: `monochrome1bit(1)`, `monochrome8bit(2)`, `colorClassic(3)` o `color24bit(4)`.

**Bloque 3 — Memoria de mensajes**

8. Leer `dmsMaxChangeableMsg` — slots máximos de mensajes changeable.
9. Leer `dmsMaxVolatileMsg` — slots máximos volatile.
10. Leer `dmsFreeChangeableMemory` — bytes libres disponibles en memoria changeable.
11. Leer `dmsMaxMultiStringLength` — longitud máxima del string MULTI en bytes.
12. Leer `dmsMaxNumberPages` — páginas máximas por mensaje.

**Bloque 4 — Fuentes**

13. Leer `numFonts` — cantidad de slots de fuente disponibles en el panel.
14. Leer `maxFontCharacters` — máximo de caracteres por fuente individual.
15. Leer `fontMaxCharacterSize` — tamaño máximo en bytes del bitmap de un carácter.
16. Leer `defaultFont` — número de fuente usado cuando el mensaje no incluye tag `[fo]`.
17. Para cada slot de `fontTable` (1..`numFonts`): leer `fontNumber`, `fontName`, `fontHeight`, `fontCharSpacing`, `fontLineSpacing`, `fontVersionID`, `fontStatus`. Registrar solo los slots en estado `readyForUse(4)`, `inUse(5)` o `permanent(6)` como fuentes activas. Distinguir `fontIndex` (índice de tabla, solo para OIDs) de `fontNumber` (valor que va en los tags MULTI).

**Bloque 5 — Gráficos**

18. Leer `dmsGraphicMaxEntries` — slots de gráfico disponibles en el panel.
19. Leer `dmsGraphicMaxSize` — tamaño máximo del bitmap de un gráfico en bytes.
20. Leer `dmsGraphicMaxHeight` — altura máxima de un gráfico en píxeles.
21. Leer `dmsGraphicMaxWidth` — ancho máximo de un gráfico en píxeles.
22. Si `dmsGraphicMaxEntries = 0` o retorna `NoSuchObject`: registrar como panel sin soporte de gráficos.

**Bloque 6 — Brillo**

23. Leer `dmsIllumNumLevels` — cantidad de niveles de brillo disponibles.
24. Leer `dmsIllumControl` — modo de control activo: `photocell(1)`, `timer(2)` o `manual(3)`.
25. Leer `dmsIllumManLevel` — nivel actual de brillo en modo manual.

**Bloque 7 — Scheduler**

26. Leer `maxTimeBaseScheduleEntries` — entradas máximas en la tabla de schedules.
27. Leer `maxDayPlans` — Day Plans máximos soportados.
28. Leer `maxDayPlanEvents` — eventos máximos por Day Plan.
29. Leer `numActionTableEntries` — filas disponibles en la Action Table.

**Bloque 8 — MULTI tags**

30. Leer `dmsSupportedMultiTags` — bitmap de tags MULTI soportados por el firmware.

**Cierre**

31. Comparar todos los valores obtenidos contra los del panel Daktronics Vanguard (.240) — documentar diferencias entre fabricantes.
32. Registrar qué OIDs retornaron `NoSuchObject` o `NoSuchInstance` — estos campos quedan como `null` en el perfil.

#### Resultado esperado

Perfil de capacidades completo del panel listo para cargar en `panel_capability_profiles`, cubriendo todos los campos de la tabla: dimensiones, color, memoria, fuentes, gráficos, brillo y scheduler.

#### Criterio de éxito

`PASS` si todos los OIDs de los bloques 1–3 y 7 responden sin error y con valores coherentes. Los bloques 4–6 pueden tener `NoSuchObject` en paneles que no soportan esa capacidad — se registra como ausencia, no como fallo.

#### Impacto en el diseño

Puebla directamente los campos de `panel_capability_profiles`: `width_pixels`, `height_pixels`, `color_depth_bits`, `supports_color_foreground`, `supports_color_background`, `multi_tags_supported`, `fonts_resident`, `supports_graphics`, `graphic_slots_max`, `graphic_max_width`, `graphic_max_height`, `brightness_levels_max`, `supports_brightness_auto`, `max_changeable_messages`, `max_volatile_messages`, `max_multi_string_length`, `max_number_pages`, `max_schedule_entries`, `max_day_plans`, `max_day_plan_events`, `num_action_table_entries`.

---

## GRUPO 2 — Mensajes: lectura y activación

---

### POC-VMS-04 — Lectura del mensaje actualmente mostrado

#### Para qué sirve

Validar que el panel reporta por SNMP el mensaje que está mostrando. Es la base del mecanismo de divergencia: si la lectura del mensaje activo no es confiable, el `MessageMonitor` no puede funcionar.

#### Cómo se verifica

```bash
python -m scenarios.poc_04_read_current_message \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

1. Leer mensaje activo (`dmsMessageMultiString`).
2. Leer tipo de memoria del mensaje activo.
3. Leer número de mensaje activo.
4. Calcular hash canónico del MULTI leído.
5. Registrar evidencia visual del panel.
6. Comparar visual vs SNMP.

#### Resultado esperado

El texto mostrado visualmente coincide con el valor leído por SNMP, o se documenta la transformación aplicada por el firmware.

#### Criterio de éxito

`PASS` si la lectura SNMP es suficiente para implementar `MessageMonitor`.

---

### POC-VMS-05 — Activación manual básica

#### Para qué sirve

Validar que un mensaje enviado por SNMP se muestra en el panel. Es la operación más fundamental del sistema — si esto no funciona, nada de lo que viene después tiene sentido. También valida la secuencia completa de escritura: MULTI string → prioridad → duración → activación → verificación.

#### Cómo se verifica

```bash
python -m scenarios.poc_05_activate_manual \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --message MSG_EMERGENCY_MANUAL \
  --confirm-write
```

#### Pasos

1. Leer y guardar estado inicial del mensaje.
2. Escribir el MULTI del mensaje en slot changeable.
3. Escribir `dmsMessageRunTimePriority`.
4. Escribir duración si aplica.
5. Ejecutar activación via `dmsActivateMessage`.
6. Leer `dmsActivateMsgError` — verificar que es `none(2)`.
7. Esperar 3 segundos.
8. Leer mensaje activo.
9. Comparar hash esperado vs hash reportado.
10. Registrar evidencia visual.

#### Resultado esperado

El panel muestra el mensaje enviado y `dmsActivateMsgError = none(2)`.

#### Criterio de éxito

`PASS` si el mensaje se muestra y puede verificarse por SNMP.

---

## GRUPO 3 — Prioridades

---

### POC-VMS-06 — Modelo de prioridades: manual vs manual

#### Para qué sirve

Validar el comportamiento del panel ante activaciones con distintas prioridades cuando ya hay un mensaje activo enviado desde la plataforma. El modelo de convivencia entre mensajes de Serviam depende de que el panel respete `dmsMessageRunTimePriority`. Este escenario determina el mapeo correcto entre los 6 niveles funcionales de la plataforma (`INFORMATIVE` a `AUTHORITY`) y el rango 1–255 del panel.

El caso scheduler vs manual se excluye porque el scheduling es responsabilidad de Serviam, no del panel.

#### Cómo se verifica

```bash
python -m scenarios.poc_06_priority_model \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Mapeo propuesto a validar

| `priority_code` plataforma | `activePriority` NTCIP | `runTimePriority` NTCIP |
|---|---|---|
| `INFORMATIVE` | 32 | 32 |
| `NORMAL` | 64 | 64 |
| `MAINTENANCE` | 96 | 96 |
| `INCIDENT` | 128 | 128 |
| `EMERGENCY` | 192 | 192 |
| `AUTHORITY` | 254 | 254 |

#### Pasos

**Fase 1 — Manual vs manual**

1. Activar mensaje con `activePriority=128`. Verificar que está en pantalla.
2. Registrar `dmsMessageRunTimePriority` activo.

3. Intentar activar nuevo manual con `activePriority=64` (< activo).
   - Leer `dmsActivateMsgError`.
   - Verificar que el panel NO cambia de mensaje.

4. Intentar activar nuevo manual con `activePriority=128` (= activo).
   - Leer `dmsActivateMsgError`.
   - Verificar que el panel acepta y muestra el nuevo.

5. Intentar activar nuevo manual con `activePriority=192` (> activo).
   - Leer `dmsActivateMsgError`.
   - Verificar que el panel acepta y muestra el nuevo.

**Fase 2 — AUTHORITY resiste todo**

6. Activar mensaje `AUTHORITY` con `activePriority=254`, `runTimePriority=254`.
7. Intentar pisar con `activePriority=192`.
8. Intentar pisar con `activePriority=253`.
9. Intentar pisar con `activePriority=254`.
10. Intentar pisar con `activePriority=255`.

#### Tabla de resultados esperados

| Situación | `activePriority` vs activo | Resultado esperado |
|---|---|---|
| Manual intenta pisar manual | menor | `dmsActivateMsgError = priority(3)`, panel no cambia |
| Manual intenta pisar manual | igual | Panel acepta y muestra el nuevo manual |
| Manual intenta pisar manual | mayor | Panel acepta y muestra el nuevo manual |
| AUTHORITY es pisado con menor | menor o igual - 1 | `dmsActivateMsgError = priority(3)` |
| AUTHORITY es pisado con igual o mayor | igual o mayor | Panel acepta y muestra el nuevo mensaje |

#### Criterio de éxito

`PASS` si todos los casos de la tabla producen el resultado esperado.

`PARTIAL` si la mayoría funciona pero hay desvíos en casos límite — se documenta y se ajusta el mapeo.

`FAIL` si el panel ignora `dmsMessageRunTimePriority` — el modelo de convivencia de mensajes requiere rediseño.

#### Impacto en el diseño

`PASS`: el mapeo propuesto se fija como constantes en `DaktronicsVanguardMultiV3Provider` y `ChainzoneMultiProvider`. `PARTIAL`: se ajusta el mapeo según el comportamiento real.

---

## GRUPO 4 — Schedule DEVICE

> **Nota:** el scheduling de mensajes es responsabilidad de Serviam, no del panel. Este grupo se mantiene como referencia para una posible implementación futura de scheduling en modo dual (software + device). No forma parte del MVP.

---

### POC-VMS-07 — Carga de schedule DEVICE + múltiples Day Plans

#### Para qué sirve

Validar que el panel acepta programación local y que el rediseño del modelo de schedules es implementable. El modelo propuesto requiere múltiples Day Plans con distintos `day_of_week_mask` (ej: Lun-Vie y Sáb-Dom) apuntando a distintos conjuntos de eventos. Este escenario valida tanto la carga básica como la coexistencia de múltiples Day Plans activos simultáneamente.

#### Cómo se verifica

```bash
python -m scenarios.poc_07_schedule_device \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

**Fase 1 — Schedule básico**

1. Leer estado inicial del schedule.
2. Limpiar schedule anterior.
3. Cargar Action Table con al menos 2 mensajes.
4. Cargar Day Plan 1 con una ventana activa para los próximos minutos.
5. Cargar TimeBaseSchedule entry apuntando al Day Plan 1.
6. Activar scheduler con `memType=0x06`.
7. Leer `dmsMsgSourceMode` → debe ser `timebasedScheduler(9)`.
8. Esperar entrada de ventana.
9. Leer mensaje activo y verificar que es el esperado.

**Fase 2 — Múltiples Day Plans**

10. Cargar Day Plan 2 con eventos distintos.
11. Cargar segunda TimeBaseSchedule entry con `day_of_week_mask` distinto apuntando al Day Plan 2.
    - Day Plan 1: `day_of_week_mask = 126` (Lun–Vie).
    - Day Plan 2: `day_of_week_mask = 65` (Sáb–Dom).
12. Verificar que ambas entradas se almacenaron correctamente.
13. Cambiar el reloj del panel a un día hábil → verificar que ejecuta Day Plan 1.
14. Cambiar el reloj del panel a un día de fin de semana → verificar que ejecuta Day Plan 2.
15. Restaurar el reloj del panel al valor correcto.

#### Resultado esperado

El panel ejecuta el mensaje programado localmente y selecciona el Day Plan correcto según el día de la semana.

#### Criterio de éxito

`PASS` si el schedule se carga y ejecuta sin intervención posterior de la plataforma, y si el panel selecciona correctamente el Day Plan según `day_of_week_mask`.

`FAIL` en Fase 2 si el panel no soporta múltiples TimeBaseSchedule entries activas simultáneamente — el rediseño de schedules requiere workaround en el provider.

---

### POC-VMS-08 — Re-sincronización de schedule existente

#### Para qué sirve

Validar que se puede reemplazar un schedule previamente cargado en el panel sin dejar restos del anterior. En operación normal, el operador puede modificar el schedule y la plataforma debe sincronizarlo sobre el panel que ya tiene uno cargado. Si el re-sync no es limpio, el panel puede acumular Day Plans o Action Table entries obsoletas.

#### Cómo se verifica

```bash
python -m scenarios.poc_08_resync_schedule \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

1. Cargar schedule A con mensajes y Day Plan definidos.
2. Confirmar ejecución del schedule A.
3. Cargar schedule B reemplazando A — nuevos mensajes, nuevo Day Plan.
4. Leer tabla de TimeBaseSchedule → verificar que no quedan entradas de A.
5. Leer Action Table → verificar que no quedan acciones de A.
6. Leer Day Plan → verificar que no quedan eventos de A.
7. Confirmar que B se ejecuta correctamente.

#### Resultado esperado

El panel queda con la programación nueva y sin restos de la anterior.

#### Criterio de éxito

`PASS` si el re-sync es determinístico y no acumula entradas obsoletas.

---

## GRUPO 5 — Divergencia y monitoreo

---

### POC-VMS-09 — Expected vs reported sin plataforma

#### Para qué sirve

Validar el núcleo del modelo de divergencia sin base de datos ni workers — con un script Python standalone. Si este algoritmo no funciona con datos reales del panel, el `MessageMonitor` no puede implementarse. Es el test más directo de la hipótesis central del diseño de monitoreo.

#### Cómo se verifica

```bash
python -m scenarios.poc_09_expected_vs_reported \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --expected-message MSG_NORMAL_SCH
```

#### Pasos

1. Definir expected local en archivo JSON.
2. Leer reported desde el panel via SNMP.
3. Calcular `expected_hash` (SHA-256 del MULTI string normalizado).
4. Calcular `reported_hash`.
5. Clasificar:
   - `IN_SYNC` si coinciden;
   - `DIVERGENT` si no coinciden;
   - `UNKNOWN` si no se pudo leer.
6. Simular un cambio externo en el panel y verificar que el script lo detecta como `DIVERGENT`.

#### Resultado esperado

El algoritmo de comparación es viable con datos reales del panel y detecta divergencias en máximo un ciclo de lectura.

#### Criterio de éxito

`PASS` si se puede decidir `IN_SYNC` / `DIVERGENT` de forma confiable usando la lectura SNMP.

---

### POC-VMS-10 — Override externo / UNMANAGED

> ⚠️ **REQUIRES_PHYSICAL** — El runner saltea este escenario en la primera pasada y lo ofrece al final.
>
> **Acción requerida:** cambiar el panel a modo local usando el switch físico del gabinete o la consola web del fabricante (DMP-5000 UI / Venus), y desde ahí activar un mensaje distinto al expected actual. Confirmar con `Enter` cuando esté listo.

#### Para qué sirve

Validar que se puede detectar un cambio realizado fuera de la plataforma — por un técnico en campo vía consola local, o por otro sistema con acceso SNMP. Este es el caso de uso real de la ruta 102: el técnico puede cambiar el mensaje localmente y la plataforma debe detectarlo y marcarlo como `UNMANAGED` sin pisar el cambio automáticamente.

#### Cómo se verifica

```bash
python -m scenarios.poc_10_unmanaged_override \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --external-message MSG_LOW_MANUAL \
  --confirm-write
```

#### Pasos

1. Dejar expected local en blank, default o schedule conocido.
2. Activar un mensaje externo usando un script separado o consola del fabricante (simula técnico en campo).
3. Leer `dmsControlMode` → verificar si el panel cambió a modo local.
4. Leer mensaje activo desde el script de monitoreo.
5. Comparar con expected local.
6. Clasificar como `UNMANAGED` si no existe una intención local que explique el cambio.
7. Verificar que el script de monitoreo NO pisa el mensaje externo automáticamente.

#### Resultado esperado

El cambio externo se detecta como `UNMANAGED` en máximo dos ciclos de lectura. La plataforma no corrige automáticamente.

#### Criterio de éxito

`PASS` si se detecta el override y se clasifica correctamente sin intervención automática.

---

### POC-VMS-11 — Reloj del panel y drift

#### Para qué sirve

Validar si el reloj del panel es confiable para schedules DEVICE-only. Todo el modelo de scheduling autónomo depende de que el `controllerLocalTime` del panel sea correcto — un drift de minutos puede hacer que los eventos del Day Plan se disparen en el momento equivocado sin que ningún error SNMP lo indique.

#### Cómo se verifica

```bash
python -m scenarios.poc_11_clock_drift \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --samples 10 \
  --interval-seconds 60
```

#### Pasos

1. Leer `controllerLocalTime` y `globalTime`.
2. Comparar contra hora UTC del host.
3. Calcular drift con signo (panel - host).
4. Repetir 10 veces con intervalo de 60 segundos.
5. Registrar drift mínimo, máximo y promedio.
6. Ejecutar un schedule con un evento en los próximos minutos y medir la hora real de activación vs la hora configurada.

#### Resultado esperado

El drift es menor a 30 segundos o es estable y modelable (drift constante, no creciente).

#### Criterio de éxito

`PASS` si el drift no compromete la ejecución de schedules con granularidad de minutos.

---

## GRUPO 6 — Recovery y resiliencia

> Escenarios: POC-VMS-12 (`REQUIRES_PHYSICAL`), POC-VMS-13 (`REQUIRES_PHYSICAL`).

---

### POC-VMS-12 — Recovery tras pérdida de comunicación

> ⚠️ **REQUIRES_PHYSICAL** — El runner saltea este escenario en la primera pasada y lo ofrece al final.
>
> **Acción requerida:** cortar la conectividad de red del panel. Opciones: (a) desconectar el cable Ethernet del router Hongdian, (b) bloquear el puerto UDP 161 en el firewall del router, o (c) apagar la interfaz WAN. El script indica cuándo cortar y cuándo restaurar.

#### Para qué sirve

Validar el comportamiento del panel y de la plataforma al recuperar comunicación después de un período offline. En campo con conectividad semi-estable (ruta 102), este es el caso de uso cotidiano: la conexión se corta y se recupera múltiples veces por día. Hay que entender exactamente en qué estado queda el panel y qué debe hacer la plataforma al reconectar.

#### Cómo se verifica

```bash
python -m scenarios.poc_12_recovery_after_offline \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --offline-seconds 360
```

#### Pasos

1. Dejar el panel en estado conocido con mensaje activo.
2. Cortar conectividad de red o bloquear SNMP.
3. Mantener offline por menos de 300 segundos.
4. Restaurar conectividad.
5. Leer mensaje activo, `dmsMsgSourceMode`, `timeBaseScheduleTableStatus`.
6. Repetir con offline mayor a 300 segundos.
7. Comparar si el panel mantuvo mensaje, schedule y reloj en ambos casos.
8. Verificar si el scheduler sigue activo o requiere reactivación.

#### Resultado esperado

Se entiende qué debe hacer la plataforma al recuperar comunicación: revalidar estado, adoptar el mensaje actual, o requerir intervención humana.

#### Criterio de éxito

`PASS` si el estado reportado después del recovery permite tomar una decisión determinística en la plataforma.

---

### POC-VMS-13 — Reboot físico del panel

> ⚠️ **REQUIRES_PHYSICAL** — El runner saltea este escenario en la primera pasada y lo ofrece al final.
>
> **Acción requerida:** cortar la alimentación eléctrica del panel o ejecutar reset desde la interfaz web del VFC (`http://170.51.57.240:1080` → System → Reboot). El script registra el estado previo, indica cuándo hacer el reboot, y continúa automáticamente cuando detecta que `sysUpTime` bajó.

#### Para qué sirve

Documentar el estado exacto del panel después de un reboot físico y definir la secuencia de recuperación que debe ejecutar la plataforma al detectar un reset de `sysUpTime`. El modo de falla principal conocido del Chainzone/Daktronics es que `timeBaseScheduleTableStatus` vuelve a 0 tras un reboot — el scheduler se pierde. En campo con obra vial, los cortes de energía son frecuentes. Sin este escenario el sistema puede quedar mostrando el mensaje de `powerRecovery` indefinidamente sin que la plataforma lo detecte como problema.

#### Cómo se verifica

```bash
python -m scenarios.poc_13_reboot_recovery \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

**Fase 1 — Estado conocido pre-reboot**

1. Cargar schedule con al menos 2 Day Plans y mensajes en memoria changeable.
2. Activar scheduler.
3. Registrar `sysUpTime`, `dmsMsgSourceMode`, `timeBaseScheduleTableStatus`, mensaje activo, `dmsMessageRunTimePriority`.

**Fase 2 — Reboot y lectura inmediata**

4. Cortar alimentación del panel o usar reset del VFC.
5. Esperar reconexión SNMP.
6. Leer `sysUpTime` → confirmar que bajó respecto al valor registrado.
7. Leer `timeBaseScheduleTableStatus` → registrar valor (se espera 0).
8. Leer `dmsMsgSourceMode` → ¿`powerRecovery(10)`, `central(8)` o blank?
9. Leer mensaje activo → registrar qué muestra el panel.
10. Leer `dmsMessageRunTimePriority` del mensaje activo.

**Fase 3 — Qué persiste y qué se pierde**

11. Verificar si los mensajes changeable persisten → intentar activar un slot que existía pre-reboot.
12. Leer `dmsNumChangeableMsg` → ¿cuántos mensajes quedan?
13. Leer Day Plans, TimeBaseSchedule entries y Action Table → registrar qué persiste.

**Fase 4 — Secuencia de recuperación**

14. Si los mensajes persisten: intentar reactivar scheduler directamente con `memType=0x06`.
15. Si los mensajes se perdieron: recargar mensajes primero, luego reactivar scheduler.
16. Leer `timeBaseScheduleTableStatus` → debe volver a 1.
17. Leer `dmsMsgSourceMode` → debe ser `timebasedScheduler(9)`.
18. Verificar que el panel retoma el mensaje correcto según el horario.
19. Documentar la secuencia mínima necesaria para recuperación completa.

#### Resultado esperado

Queda documentado exactamente qué se pierde tras un reboot y cuál es la secuencia determinística de recuperación.

#### Criterio de éxito

`PASS` si la secuencia de recuperación es determinística y repetible en al menos 3 ciclos de reboot.

#### Impacto en el diseño

Confirma que la detección de `sysUpTime` reset en el polling debe disparar una secuencia de recuperación en `Vms.Worker.State`. Define si el `SyncSchedule` post-reboot debe incluir recarga de mensajes changeable o solo reactivación del scheduler. Documenta el comportamiento de `powerRecovery(10)` para el provider.

---

## GRUPO 7 — Capacidades de hardware

---

### POC-VMS-14 — Brillo

#### Para qué sirve

Validar si el control de brillo por SNMP es viable para MVP. El Daktronics Vanguard tiene escala invertida (0=100% brillo). Hay que confirmar si el Chainzone tiene el mismo comportamiento o si la escala es directa, para parametrizar correctamente el provider.

#### Cómo se verifica

```bash
python -m scenarios.poc_14_brightness \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --levels 20,50,80 \
  --confirm-write
```

#### Pasos

1. Leer brillo actual (`dmsIllumManLevel`).
2. Guardar valor inicial.
3. Escribir nivel 20. Leer y registrar resultado visual.
4. Escribir nivel 50. Leer y registrar resultado visual.
5. Escribir nivel 80. Leer y registrar resultado visual.
6. Verificar si la escala es directa o invertida.
7. Restaurar valor inicial.

#### Resultado esperado

El panel acepta SET de brillo y lo reporta correctamente. Queda documentado si la escala es directa (0=apagado, 100=máximo) o invertida (0=máximo, 100=apagado) para el Chainzone.

#### Criterio de éxito

`PASS` si los niveles se aplican y pueden verificarse por SNMP.

---

### POC-VMS-15 — Gráficos

#### Para qué sirve

Validar si la gestión de gráficos debe entrar al MVP o quedar para F-VMS.2. Los gráficos requieren carga de BMP, gestión de slots, verificación de CRC y compatibilidad con el MULTI tag `[g]`. Si el proceso es inestable o propietario, es más seguro excluirlo del MVP.

#### Cómo se verifica

```bash
python -m scenarios.poc_15_graphics \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --graphic ./assets/test.bmp \
  --slot 1 \
  --confirm-write
```

#### Pasos

1. Leer soporte de gráficos (`dmsGraphicMaxEntries`).
2. Leer cantidad de slots disponibles.
3. Cargar BMP compatible en slot 1.
4. Leer estado del slot → `graphicStatus`.
5. Referenciar gráfico desde un MULTI string con `[g1]`.
6. Activar mensaje con gráfico y verificar visualmente.
7. Leer CRC del gráfico cargado.
8. Limpiar slot o restaurar estado.

#### Resultado esperado

Se confirma si gráficos son confiables para el MVP o si deben quedar fuera del alcance inicial.

#### Criterio de éxito

`PASS` si se puede cargar, mostrar y verificar un gráfico de forma repetible.

---

### POC-VMS-16 — Capacidades MULTI del panel

#### Para qué sirve

Validar que el `model_type` y el `capability_profile` declarados no sobredeclaran capacidades respecto al firmware real. Un mensaje con un tag no soportado puede causar `genErr` o comportamiento silencioso. Esta es la base para construir el `MultiValidator` correcto para el Chainzone.

#### Cómo se verifica

```bash
python -m scenarios.poc_16_multi_capabilities \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

1. Leer `dmsSupportedMultiTags` → bitmap de tags soportados.
2. Leer dimensiones del panel (`dmsSignWidth`, `dmsSignHeight`).
3. Leer soporte de color (`dmsColorScheme`).
4. Probar mensajes con: salto de línea, página nueva, justificación, flashing, `[mvt]`, gráfico, tag no soportado.
5. Registrar qué acepta (`dmsActivateMsgError = none(2)`) y qué rechaza para cada tag.
6. Verificar que un tag no soportado retorna error explícito (no silencioso).

#### Resultado esperado

Matriz real de capacidades MULTI del Chainzone, lista para construir el `VmsPanelCapabilityProfile` correcto.

#### Criterio de éxito

`PASS` si se puede construir un `capability_profile` conservador y correcto que no sobredeclara capacidades.

---

## GRUPO 8 — Errores y fallos

---

### POC-VMS-17 — Errores de activación: códigos de `dmsActivateMsgError`

#### Para qué sirve

Provocar intencionalmente cada error posible de `dmsActivateMsgError` y verificar que el panel responde con el código correcto. El objetivo no es que fallen — es saber exactamente qué devuelve cada panel para que el Provider pueda interpretar errores y reportarlos correctamente al sistema. El comportamiento puede diferir entre Daktronics y Chainzone.

#### Cómo se verifica

```bash
python -m scenarios.poc_17_activation_errors \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

**Fase 1 — `messageCRC(7)`**

1. Cargar un mensaje válido en un slot changeable.
2. Leer el CRC real del slot.
3. Activar con CRC deliberadamente incorrecto (ej: CRC+1).
4. Leer `dmsActivateMsgError` → verificar que retorna `messageCRC(7)`.

**Fase 2 — `messageStatus(4)`**

5. Intentar activar un slot en estado `notUsed` (sin mensaje cargado).
6. Leer `dmsActivateMsgError` → verificar que retorna `messageStatus(4)`.

**Fase 3 — `messageNumber(6)`**

7. Intentar activar un número de slot inexistente (ej: slot 999).
8. Leer `dmsActivateMsgError` → verificar que retorna `messageNumber(6)`.

**Fase 4 — `syntaxMULTI(8)`**

9. Cargar un MULTI string con sintaxis deliberadamente inválida (tag malformado).
10. Intentar activarlo directamente (sin pasar por `validateReq`).
11. Leer `dmsActivateMsgError` → verificar que retorna `syntaxMULTI(8)`.
12. Leer `dmsMultiSyntaxError` y `dmsMultiSyntaxErrorPosition` para obtener el detalle.

**Fase 5 — `localMode(9)` (si el panel lo permite)**

13. Si el panel permite SET de `dmsControlMode`: escribir `local(2)` para forzar el modo.
14. Intentar activar un mensaje desde el sistema central.
15. Leer `dmsActivateMsgError` → verificar que retorna `localMode(9)`.
16. Restaurar `dmsControlMode=central(4)`.

#### Tabla de resultados esperados

| Caso provocado | Código esperado | OID de detalle adicional |
|---|---|---|
| CRC incorrecto en activación | `messageCRC(7)` | — |
| Slot en estado `notUsed` | `messageStatus(4)` | — |
| Número de slot inexistente | `messageNumber(6)` | — |
| MULTI con sintaxis inválida | `syntaxMULTI(8)` | `dmsMultiSyntaxError`, `dmsMultiSyntaxErrorPosition` |
| Panel en modo local | `localMode(9)` | `dmsControlMode` |

#### Criterio de éxito

`PASS` si cada caso retorna el código esperado y el código es igual entre Daktronics y Chainzone.

`QUIRK_PROVIDER` si algún panel retorna un código diferente al estándar — se documenta el mapeo específico en el provider correspondiente.

#### Impacto en el diseño

Fija el mapa de errores en `DaktronicsVanguardProvider` y `ChainzoneProvider`. Define el comportamiento del worker ante cada tipo de error: cuáles se pueden reintentar, cuáles requieren re-carga del mensaje, cuáles deben escalar al operador.

---

### POC-VMS-18 — Errores de sintaxis MULTI: `dmsMultiSyntaxError` + posición

#### Para qué sirve

Documentar exactamente qué código retorna cada panel para cada tipo de error sintáctico MULTI, y si la posición reportada en `dmsMultiSyntaxErrorPosition` es precisa. El comportamiento difiere entre fabricantes — en campo ya se observó que el Chainzone (.243) rechaza `[fo,14]` mientras Daktronics requiere `[fo14]`. Este escenario cierra esa brecha para construir el `MultiValidator` correcto.

#### Cómo se verifica

```bash
python -m scenarios.poc_18_multi_syntax_errors \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

Para cada caso de la tabla a continuación:

1. Cargar el MULTI string con el error intencional en un slot changeable.
2. Ejecutar `validateReq` sobre el slot.
3. Leer `dmsMessageStatus` → debe llegar a `error(5)`.
4. Leer `dmsValidateMessageError` → debe ser `syntaxMULTI(5)`.
5. Leer `dmsMultiSyntaxError` → registrar código.
6. Leer `dmsMultiSyntaxErrorPosition` → registrar posición en bytes.
7. Verificar si la posición apunta al byte correcto en el string.

| Caso | MULTI de prueba | Error esperado |
|---|---|---|
| Tag no soportado | `[mvt]TEXT` (si `mvt` no soportado) | `unsupportedTag(3)` |
| Valor de tag inválido | `[jl9]TEXT` (justificación 9 no existe) | `unsupportedTagValue(4)` |
| Texto demasiado largo | STRING > `dmsMaxMultiStringLength` | `textTooBig(5)` |
| Fuente inexistente | `[fo99]TEXT` | `fontNotDefined(6)` |
| Demasiadas páginas | Más páginas que `dmsMaxNumberPages` | `tooManyPages(12)` |
| Gráfico no cargado | `[g99]` | `graphicNotDefined(15)` |
| Sintaxis malformada (Chainzone) | `[fo,14]TEXT` (coma extra) | `other(1)` o `unsupportedTagValue(4)` |

#### Criterio de éxito

`PASS` si cada caso retorna un código de error explícito y `dmsMultiSyntaxErrorPosition` apunta a una posición plausible dentro del string.

`QUIRK_PROVIDER` si algún panel retorna `other(1)` donde se esperaba un código específico — se documenta como comportamiento propietario.

#### Impacto en el diseño

Construye la tabla de errores MULTI por fabricante. Define qué validaciones deben hacerse en el `MultiValidator` antes de enviar el mensaje al panel (validación client-side) vs cuáles se detectan solo después de `validateReq` (validación server-side).

---

### POC-VMS-19 — Escritura parcial fallida: recuperación de slot en estado `modifying`

#### Para qué sirve

Determinar qué estado queda en un slot de mensaje cuando una secuencia de escritura es interrumpida a la mitad — por un corte de red, timeout o error SNMP durante el proceso. Crítico para el diseño del `MessageLoader`: define si se necesita limpieza preventiva (`notUsedReq`) antes de cada escritura o si el panel se recupera solo.

#### Cómo se verifica

```bash
python -m scenarios.poc_19_partial_write_recovery \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

**Fase 1 — Interrupción durante escritura**

1. Iniciar escritura de mensaje: enviar `modifyReq` al slot, escribir el MULTI string.
2. Interrumpir la secuencia antes de enviar `validateReq` (simular timeout o corte).
3. Leer `dmsMessageStatus` del slot → registrar estado (se espera `modifying(3)` o `notUsed(1)`).
4. Intentar leer el contenido parcial del slot.

**Fase 2 — Intento de recuperación**

5. Intentar escribir `notUsedReq` sobre el slot → ¿acepta la limpieza?
6. Leer `dmsMessageStatus` → ¿vuelve a `notUsed(1)`?
7. Si no acepta `notUsedReq`: intentar overwrite directo con `modifyReq` nuevamente.
8. Registrar si el slot queda bloqueado o si se puede recuperar.

**Fase 3 — Escritura completa post-recuperación**

9. Después de limpiar el slot, ejecutar la escritura completa nuevamente.
10. Verificar que el slot llega a `valid(4)` correctamente.
11. Activar el mensaje y confirmar que se muestra.

#### Resultado esperado

El slot puede limpiarse con `notUsedReq` y reutilizarse sin necesidad de reiniciar el panel. La secuencia de recuperación es determinística.

#### Criterio de éxito

`PASS` si la recuperación del slot es posible con `notUsedReq` y la escritura posterior es exitosa.

`QUIRK_PROVIDER` si el slot queda bloqueado y requiere una operación especial del fabricante — se documenta la secuencia de desbloqueo.

#### Impacto en el diseño

Define si el `MessageLoader` debe ejecutar siempre `notUsedReq` antes de comenzar una escritura (limpieza preventiva) o solo ante error previo detectado. Si el slot puede quedar bloqueado, el worker debe incluir una verificación de estado del slot antes de cada operación de carga.

---

### POC-VMS-20 — Panel en `localMode`: detección y comportamiento

#### Para qué sirve

Verificar exactamente qué ocurre cuando el panel está en `dmsControlMode=local(2)`: si el polling sigue funcionando (solo lectura), qué error retorna ante un intento de activación, y si se puede detectar la condición antes de intentar operar. Caso real: técnico en campo toma control físico del panel durante una obra.

#### Cómo se verifica

```bash
python -m scenarios.poc_20_local_mode \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

**Fase 1 — Detección del modo local**

1. Leer `dmsControlMode` → registrar valor actual (se espera `central(4)`).
2. Si el panel permite SET de `dmsControlMode`: escribir `local(2)` para forzar el modo (o solicitar asistencia para cambio físico si no es escribible remotamente).
3. Leer `dmsControlMode` → confirmar que está en `local(2)`.

**Fase 2 — Comportamiento del polling en `localMode`**

4. Ejecutar ciclo de polling completo: `sysUpTime`, `dmsMsgSourceMode`, `dmsMsgTableSource`, `shortErrorStatus`.
5. Registrar si todos los GET responden correctamente.
6. Verificar que el polling de lectura no se ve afectado por el modo local.

**Fase 3 — Intento de activación en `localMode`**

7. Intentar activar un mensaje via `dmsActivateMessage`.
8. Registrar si el SET retorna `genErr`, `noError`, o error SNMP.
9. Leer `dmsActivateMsgError` → verificar que retorna `localMode(9)`.
10. Verificar que el mensaje en pantalla NO cambió.

**Fase 4 — Restauración y comportamiento post-`localMode`**

11. Restaurar `dmsControlMode=central(4)` (o solicitarlo físicamente).
12. Intentar activar el mensaje nuevamente → debe funcionar.
13. Verificar que el worker puede retomar el control sin re-onboarding completo.

#### Tabla de comportamiento esperado

| Operación | En `localMode` | Comportamiento esperado |
|---|---|---|
| GET `sysUpTime` | `local(2)` | Responde normalmente |
| GET `dmsMsgSourceMode` | `local(2)` | Responde normalmente |
| GET `dmsControlMode` | `local(2)` | Retorna `local(2)` |
| SET `dmsActivateMessage` | `local(2)` | `genErr` + `dmsActivateMsgError=localMode(9)` |
| SET `dmsActivateMessage` | `central(4)` | Funciona normalmente |

#### Criterio de éxito

`PASS` si se puede detectar `localMode` antes de intentar activar, el error es explícito (`localMode(9)`) y el polling de lectura sigue funcionando en ese estado.

#### Impacto en el diseño

Define el comportamiento del worker al detectar `dmsControlMode=local(2)` en el ciclo de polling: registrar la condición como `UNMANAGED`, suspender intentos de activación, no marcar el panel como inaccesible (el polling sigue), y alertar al operador. Al recuperar `central(4)`, el worker retoma las activaciones pendientes sin re-onboarding.
