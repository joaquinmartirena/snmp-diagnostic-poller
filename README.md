# its-toolkit

Toolkit de **diagnóstico, prueba y caracterización** de dispositivos ITS de
campo (paneles VMS/DMS, controladores de tráfico, etc.). No es la plataforma
productiva: es la herramienta que el equipo de ingeniería usa para entender
qué está haciendo un dispositivo en campo y para validar sus capacidades.

## Características

- **CLI único** con subcomandos: `monitor`, `probe`, `discover`.
- **Soporte multi-dispositivo** vía YAML (un único archivo lista todos los
  paneles a monitorear).
- **Polling concurrente**: cada dispositivo corre en su propia tarea asyncio;
  un timeout no detiene a los demás.
- **Read-only por construcción**: toda escritura pasa por un `WriteGuard`
  con doble gate (`confirm_write` en config + `--confirm-write` en CLI). Hoy
  el toolkit es solo lectura; las escrituras llegan con los escenarios PoC.
- **Conocimiento de cada dispositivo cohesionado**: catálogo de OIDs,
  decoders y (en el futuro) escenarios viven juntos en
  `itstoolkit/devices/<familia>/`.
- **Familias soportadas**: VMS NTCIP 1203 v3 (Daktronics, Chainzone) y
  SEMEX C5000 (NTCIP 1202).
- **Logs operativos**: una línea horizontal por poll, rotación diaria, un
  archivo por dispositivo. Pensado para `tail -f` y para adjuntar a
  llamadas de soporte.

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Las dependencias (`pysnmp`, `PyYAML`) se instalan automáticamente desde
`pyproject.toml`.

## Uso

### Diagnóstico continuo (monitor)

Con YAML multi-dispositivo:

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

### Lectura puntual (probe)

```bash
itstoolkit probe --config config.yaml         # primer device del YAML
itstoolkit probe --family vms_ntcip1203 --ip 10.0.0.10 --name p1
```

### Mapeo de capacidades (discover)

```bash
itstoolkit discover --ip 10.0.0.10 --community public \
                    --base-oid 1.3.6.1.4.1.1206.4.2.3
```

## Arquitectura

```
itstoolkit/
├── cli.py                        # único entrypoint
├── core/                         # núcleo agnóstico
│   ├── config.py                 # cascada defaults → YAML → env → flags → prompt
│   ├── safety.py                 # WriteGuard (doble gate de escritura)
│   ├── evidence.py               # EvidenceRecord + LineLogSink + JsonlSink
│   ├── transport.py              # contrato Transport
│   └── device.py                 # contrato DeviceAdapter + registry
├── protocols/snmp/               # transporte SNMP v2c
│   ├── client.py                 # SnmpClient (read-only por default)
│   └── values.py                 # coerción pysnmp
├── devices/
│   ├── vms_ntcip1203/            # VMS NTCIP 1203 v3
│   └── semex_c5000/              # SEMEX C5000 (NTCIP 1202)
└── modes/                        # clientes delgados del núcleo
    ├── monitor.py
    ├── probe.py
    └── discover.py
```

**Invariantes** (verificadas por `tests/test_layering.py`):

- `core/` no conoce dispositivos ni protocolos concretos.
- `protocols/` no conoce dispositivos.
- `devices/` no importa de `modes/`.
- Toda escritura pasa por `WriteGuard`.

## Cómo agregar un dispositivo

Es la operación canónica del toolkit: **agregar un paquete**, no modificar
el resto.

1. Crear `itstoolkit/devices/<nuevo>/`.
2. Definir el catálogo en `oids.py`.
3. Agregar decoders en `decoders.py`.
4. Implementar el `DeviceAdapter` en `adapter.py` (`config_schema`,
   `monitor_tasks`, `probe`).
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
decoders y la cascada de config. La validación contra paneles reales se
hace en campo.
