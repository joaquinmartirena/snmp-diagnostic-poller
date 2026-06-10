# its-toolkit

Toolkit de **diagnóstico, prueba y caracterización** de dispositivos ITS de
campo (paneles VMS/DMS, controladores de tráfico, etc.). No es la plataforma
productiva: es la herramienta que el equipo de ingeniería usa para entender
qué está haciendo un dispositivo en campo y para validar sus capacidades
antes de integrarlas al producto.

## Características

- **CLI único** con cuatro subcomandos: `monitor`, `probe`, `discover` y
  `scenario`.
- **Soporte multi-dispositivo** vía YAML — un único archivo lista todos los
  paneles a operar.
- **Polling concurrente**: cada dispositivo corre en su propia tarea
  asyncio; un timeout no detiene a los demás.
- **Doble gate de escritura**: toda operación de SET pasa por un
  `WriteGuard` que exige confirmación en config (`confirm_write: true`)
  **y** flag de CLI (`--confirm-write`). El modo `monitor`/`probe`/
  `discover` es read-only por construcción.
- **Conocimiento de cada dispositivo cohesionado**: catálogo de OIDs,
  decoders y escenarios PoC viven juntos en
  `itstoolkit/devices/<familia>/`.
- **Familias soportadas**: VMS NTCIP 1203 v3 (Daktronics, Chainzone) y
  SEMEX C5000 (NTCIP 1202).
- **Logs operativos**: una línea horizontal por poll, rotación diaria, un
  archivo por dispositivo. Pensado para `tail -f` y para adjuntar a
  llamadas de soporte.
- **Evidencia estructurada (JSONL)** para escenarios PoC, agrupada por
  panel y por corrida.

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Las dependencias base (`pysnmp`, `PyYAML`) se instalan automáticamente
desde `pyproject.toml`.

Para correr **POC-VMS-15B** (carga de BMPs al panel), instalar también
el extra `graphics`:

```bash
pip install -e .[graphics]      # agrega Pillow
```

## Uso

### Diagnóstico continuo — `monitor`

Loop periódico de lectura. Una línea por poll, por dispositivo:

```bash
cp config.example.yaml config.yaml
# editá config.yaml con los IPs/community reales
itstoolkit monitor --config config.yaml
```

Single-shot interactivo (sin YAML):

```bash
itstoolkit monitor --family vms_ntcip1203 --ip 10.0.0.10 --name p1
# pide community/intervalo por prompt si faltan
```

### Lectura puntual — `probe`

Una iteración completa del adapter y termina. Útil para chequeo rápido:

```bash
itstoolkit probe --config config.yaml         # primer device del YAML
itstoolkit probe --family vms_ntcip1203 --ip 10.0.0.10 --name p1
```

### Mapeo de capacidades — `discover`

SNMP walk desde un OID base. Útil para explorar firmware desconocido:

```bash
itstoolkit discover --ip 10.0.0.10 --community public \
                    --base-oid 1.3.6.1.4.1.1206.4.2.3
```

### Escenarios PoC — `scenario`

Validación end-to-end contra hardware real (algunos escriben). Ver la
[guía completa de PoCs](docs/README_POCS.md) para el detalle de cada
escenario y los criterios de éxito.

Listar:

```bash
itstoolkit scenario list --family vms_ntcip1203
```

Correr los read-only:

```bash
itstoolkit scenario run --config config.yaml \
  --scenario POC-VMS-01 --scenario POC-VMS-02 \
  --scenario POC-VMS-03 --scenario POC-VMS-04
```

Correr todos los `AUTOMATIC` (incluye los que escriben):

```bash
itstoolkit scenario run --config config.yaml --automatic-only --confirm-write
```

Correr todos + limpiar slots de prueba después de cada uno:

```bash
itstoolkit scenario run --config config.yaml \
  --automatic-only --confirm-write --cleanup-after-each
```

> ⚠️ `--confirm-write` solo habilita la mitad-CLI del doble gate. Los
> escenarios con `requires_write=True` quedan `BLOCKED` salvo que el panel
> también tenga `confirm_write: true` en `config.yaml`.

## Arquitectura

```
itstoolkit/
├── cli.py                        # único entrypoint
├── core/                         # núcleo agnóstico
│   ├── config.py                 # cascada defaults → YAML → env → flags → prompt
│   ├── safety.py                 # WriteGuard (doble gate de escritura)
│   ├── evidence.py               # EvidenceRecord + LineLogSink + JsonlSink
│   ├── scenario.py               # contratos Scenario + ScenarioContext
│   ├── transport.py              # contrato Transport
│   └── device.py                 # contrato DeviceAdapter + registry
├── protocols/snmp/               # transporte SNMP v2c
│   ├── client.py                 # SnmpClient (GET + SET con WriteGuard)
│   └── values.py                 # coerción de tipos pysnmp
├── devices/
│   ├── vms_ntcip1203/            # VMS NTCIP 1203 v3
│   │   ├── oids.py               # catálogo de OIDs verificado contra norma
│   │   ├── decoders.py           # bitmaps, enums, message ID codes
│   │   ├── adapter.py            # monitor loop + probe one-shot
│   │   └── scenarios/            # 20 PoCs (ver docs/README_POCS.md)
│   └── semex_c5000/              # SEMEX C5000 (NTCIP 1202)
└── modes/                        # clientes delgados del núcleo
    ├── monitor.py
    ├── probe.py
    ├── discover.py
    └── scenario.py
```

**Invariantes** (verificadas por `tests/test_layering.py`):

- `core/` no conoce dispositivos ni protocolos concretos.
- `protocols/` no conoce dispositivos.
- `devices/` no importa de `modes/` ni del CLI.
- Toda escritura SNMP pasa por `WriteGuard`.

## Layout de evidencia

Los modos que generan registros estructurados (hoy: `scenario`) escriben en:

```
evidence/<family>/<device_name>/<run_ts>/<scenario_id>.jsonl
```

Todos los escenarios de **una misma corrida del CLI** comparten el mismo
`<run_ts>` (timestamp UTC), de modo que los PoCs ejecutados juntos quedan
agrupados bajo una sola carpeta por panel.

Logs del modo `monitor`:

```
logs/<device_name>_<ip>_<YYYY-MM-DD>.log
```

Rotación diaria, una línea por poll.

## Cómo agregar un dispositivo

Es la operación canónica del toolkit: **agregar un paquete**, no modificar
el resto.

1. Crear `itstoolkit/devices/<nuevo>/`.
2. Definir el catálogo en `oids.py`.
3. Agregar decoders en `decoders.py`.
4. Implementar el `DeviceAdapter` en `adapter.py` (`config_schema`,
   `monitor_tasks`, `probe`, opcionalmente `scenarios`).
5. Registrarlo en `__init__.py`:

   ```python
   device_registry.register(NewAdapter.family, NewAdapter)
   ```

El CLI descubre el adapter automáticamente vía `device_registry`. No hace
falta tocar `core/`, `modes/` ni `cli.py`.

## Tests

```bash
pytest tests/ -v
```

Los tests no necesitan hardware real: validan layering, contratos, schemas,
decoders, doble gate, y todos los escenarios PoC contra una sesión SNMP
mockeada. La validación contra paneles reales se hace en campo con el
modo `scenario`.

## Documentación adicional

- [`docs/README_POCS.md`](docs/README_POCS.md) — Guía operativa de los 20
  PoCs: criterios, knobs por panel, hallazgos contra hardware real.
- [`docs/Poc_VMS_SNMP_Python_v4.md`](docs/Poc_VMS_SNMP_Python_v4.md) —
  Spec original del bloque PoCs VMS (decisiones de diseño, justificación
  de cada escenario, renumeración respecto de versiones anteriores).
