# SNMP Diagnostic Poller

> **⚠️ ARCHIVED / OUTDATED**
>
> Este documento describe la arquitectura **vieja** (`shared/`, `polling/`,
> `pocs/`, `diag_poller.py`, `poc_runner.py`) que **ya no existe** en el
> repositorio. Se conserva sólo como referencia histórica del formato de
> log y de los campos del poller.
>
> Para la arquitectura, instalación y uso actuales del toolkit, ver el
> [`README.md` en la raíz del repositorio](../README.md).

## A. Purpose

A standalone, **read-only** diagnostic tool for polling ITS field devices over
SNMP v2c. It continuously reads key status objects from each device, decodes
them, and writes one compact horizontal line per poll to a plain text log
(ideal for `tail -f`, support calls, and later analysis).

It is intended for field diagnostics and troubleshooting. It **never** changes
device state — only SNMP `GET` operations are issued.

## B. Features

- YAML configuration for multiple devices
- Interactive fallback for a single device when no config is given
- Concurrent multi-device polling (asyncio); one device failing never stops the others
- Layered architecture: `shared/` primitives, `polling/` profiles, `pocs/` scenarios
- All SNMP OIDs centralized in `shared/oid_providers/` (no OIDs hardcoded in profiles)
- Profile-based polling (easy to add new device types)
- VMS NTCIP 1203 support
- SEMEX C5000 traffic controller support (separate alarm and cycle polls)
- Daily log rotation, one file per device
- One-line plain text logs (no ANSI colors in files)
- Read-only by construction: polling uses `SnmpClient(allow_write=False)`

## C. Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requirements: `pysnmp`, `PyYAML`.

Then create your local config from the example:

```bash
cp config.example.yaml config.yaml
# edit config.yaml with your real devices
```

The repository ships only `config.example.yaml` (placeholder values).
`config.yaml` is git-ignored so real IPs and community strings are never
committed.

## D. Running

With a config file (recommended, supports multiple devices):

```bash
python diag_poller.py --config config.yaml
```

Interactive fallback (single device, prompts for the basics):

```bash
python diag_poller.py
```

Stop with `Ctrl+C`; all polling tasks are cancelled cleanly.

## E. Configuration file

The repo includes `config.example.yaml` with placeholder values. Create your
own local `config.yaml` from it (`config.yaml` is git-ignored):

```bash
cp config.example.yaml config.yaml
```

Then edit `config.yaml` with your real devices:

```yaml
devices:
  - name: vms_243
    type: VMS_NTCIP1203
    ip: 170.51.57.243
    port: 161
    community: public
    interval_seconds: 60

  - name: semex_c5000_01
    type: SEMEX_C5000_V1
    ip: 170.51.57.250
    port: 161
    community: public
    alarm_interval_seconds: 30
    cycle_interval_seconds: 2
    cycle_change_log: false
```

Fields:

| Field | Applies to | Default | Description |
|-------|------------|---------|-------------|
| `name` | all | (required) | Device name used in logs and log filenames |
| `type` | all | (required) | Profile: `VMS_NTCIP1203` or `SEMEX_C5000_V1` |
| `ip` | all | (required) | Device IP address |
| `port` | all | `161` | SNMP UDP port |
| `community` | all | `public` | SNMP v2c community string |
| `interval_seconds` | VMS | `60` | Seconds between VMS polls |
| `alarm_interval_seconds` | SEMEX | `30` | Seconds between alarm polls |
| `cycle_interval_seconds` | SEMEX | `2` | Seconds between cycle (signal status) polls |
| `cycle_change_log` | SEMEX | `false` | Append `CHANGE=` to cycle lines (see section J) |

## F. Log files

Each device writes to its own daily file:

```
logs/<device_name>_<ip>_<YYYY-MM-DD>.log
```

The path is recomputed before every write, so logs rotate automatically at
midnight without restarting. Devices are never mixed in the same file.

## G. Log line structure

Every line begins with a common prefix:

```
[YYYY-MM-DD HH:MM:SS] DEVICE=<name> TYPE=<profile> IP=<ip> PORT=<port> POLL=<poll_type> COMM_STATUS=<status>
```

`POLL` is `vms`, `alarm`, or `cycle`.

`COMM_STATUS` is the **communication/poll** status (not a device operational
status):

- `OK` — required OIDs read successfully
- `TIMEOUT` — SNMP timeout / transport failure
- `SNMP_ERROR` — agent returned a non-zero `error_status`
- `PARTIAL` — the PDU succeeded but some OIDs had no value (optional fields missing)

When `COMM_STATUS` is `TIMEOUT` or `SNMP_ERROR`, the profile fields are filled
with `?` placeholders and the poller continues.

## H. VMS log fields

| Field | Meaning |
|-------|---------|
| `CTRL` | `dmsControlMode` — `local(2)`, `central(4)`, `centralOverride(5)`, else `unknown(n)` |
| `SRC` | `dmsMsgSourceMode` — `central(8)`, `timebasedScheduler(9)`, `commLoss(12)`, else `unknown(n)` |
| `MSG` | `dmsMsgTableSource` raw MessageIDCode as compact uppercase hex |
| `MULTI` | Active message MULTI text (quoted, sanitized to one line, max 500 chars). May be `unavailable` or `read_error` |
| `ERR` | `shortErrorStatus` decoded bit names joined by `;`, or `none` |
| `ERR_RAW` | `shortErrorStatus` as 4-char uppercase hex |
| `CHANGE` | Appears only when a value changed vs. the previous successful poll |

`shortErrorStatus` bits decoded: `communicationsError`, `powerError`,
`attachedDeviceError`, `lampError`, `pixelError`, `photocellError`,
`messageError`, `controllerError`, `temperatureWarning`, `climateControlError`,
`criticalTemperatureError`, `drumRotorError`, `doorOpen`, `humidityWarning`
(plus `reservedBit0` and `unknownBitN` for anything else).

Example:

```
[2026-05-27 11:51:24] DEVICE=vms_243 TYPE=VMS_NTCIP1203 IP=170.51.57.243 PORT=161 POLL=vms COMM_STATUS=OK CTRL=central(4) SRC=timebasedScheduler(9) MSG=0300049DD5 MULTI="ALMUERZO" ERR=none ERR_RAW=0000
```

Change example:

```
... COMM_STATUS=OK CTRL=central(4) SRC=commLoss(12) ... CHANGE=SRC:central(8)->commLoss(12);ERR:none->messageError
```

## I. SEMEX alarm log fields

| Field | Meaning |
|-------|---------|
| `ALARM1` / `ALARM1_RAW` | `unitAlarmStatus1` — `none` if zero, else `unknown` (bit meanings TBD); raw 8-char hex |
| `ALARM2` / `ALARM2_RAW` | `unitAlarmStatus2` — same convention |
| `SHORT_ALARM` / `SHORT_ALARM_RAW` | `shortAlarmStatus` — same convention; raw 4-char hex |
| `UPTIME` | Uptime-like counter used for restart detection |
| `RESTART` | `unknown` (first poll), `no`, or `detected` (uptime went backwards) |
| `CHANGE` | Alarm polls always log changes vs. the previous successful poll |

> The alarm decoders are placeholders. Until the device's bit definitions are
> confirmed, non-zero alarms show as `unknown` with the raw hex preserved.

Example:

```
[2026-05-27 11:51:30] DEVICE=semex_c5000_01 TYPE=SEMEX_C5000_V1 IP=170.51.57.250 PORT=161 POLL=alarm COMM_STATUS=OK ALARM1=none ALARM1_RAW=00000000 ALARM2=none ALARM2_RAW=00000000 SHORT_ALARM=none SHORT_ALARM_RAW=0000 UPTIME=123456 RESTART=no
```

## J. SEMEX cycle log fields

| Field | Meaning |
|-------|---------|
| `PHASES` | Phase status groups G1..G4. Per group: `R,Y,G,DW,W,VC,PC,ON` as byte hex |
| `RINGS` | Ring status R1..R4 |
| `CHANNELS` | Channel status groups C1..C4. Per channel: `R,Y,G` |
| `COORD` | Coordination scalars: `PATTERN,SYS_PATTERN,LOCAL_FREE,CYCLE,SYNC` (decimal) |

`CHANGE` behavior: because cycle status changes every couple of seconds,
`CHANGE=` is **not** logged for cycle polls by default. Set
`cycle_change_log: true` on the device to enable it. Alarm polls always log
changes.

Example:

```
[2026-05-27 11:51:32] DEVICE=semex_c5000_01 TYPE=SEMEX_C5000_V1 IP=170.51.57.250 PORT=161 POLL=cycle COMM_STATUS=OK PHASES=G1:R=00,Y=00,G=04,DW=FF,W=00,VC=01,PC=00,ON=04|G2:... RINGS=R1=02|R2=01|R3=00|R4=00 CHANNELS=C1:R=00,Y=00,G=04|C2:... COORD=PATTERN=3,SYS_PATTERN=3,LOCAL_FREE=0,CYCLE=45,SYNC=1
```

## K. Safety

**The poller is strictly read-only.** All polling SNMP access goes through
`shared.snmp_client.SnmpClient(allow_write=False)`, which raises
`WriteNotAllowedError` if any write is ever attempted on it. The poller never
performs SET operations, resets, activations, or schedule changes.

The write restriction is modeled structurally so it extends to the PoC layer:

- Polling always instantiates `SnmpClient(allow_write=False)`.
- Read-only PoC scenarios also use `allow_write=False`.
- A PoC scenario that declares `requires_write = True` may run against a
  writable client **only** when both `confirm_write: true` is set in the panel
  config **and** `--confirm-write` is passed on the CLI. If either is missing,
  the PoC runner must block the scenario.

## L. Architecture & layering

The toolkit is split into three top-level packages with a strict dependency
direction:

- **`shared/`** — device-agnostic primitives (`snmp_client`, `value_utils`,
  `config_loader`, `evidence_writer`) and `oid_providers/`. Imports from neither
  of the other two packages.
- **`polling/`** — the read-only poller (profiles + log helpers). Depends only
  on `shared`; never imports `pocs`.
- **`pocs/`** — proof-of-concept scenarios (may issue gated writes). Depends
  only on `shared`; never imports `polling`.

Invariants enforced:

- `polling/` never imports `pocs/`, and `pocs/` never imports `polling/`.
- `shared/` imports neither.
- All numeric SNMP OIDs live in `shared/oid_providers/` and nowhere else.
- Polling instantiates SNMP only with `allow_write=False`.

### OID providers

OIDs are organized as provider classes under `shared/oid_providers/`:

- `NtcipBase` — SNMPv2-MIB system group + NTCIP 1201 global objects.
- `Ntcip1203V3(NtcipBase)` — all DMS OIDs (NTCIP 1203 v3).
- `DaktronicsVanguard(Ntcip1203V3)` — Daktronics quirks (none yet).
- `SemexC5000Provider` — NTCIP 1202 ASC OIDs + cycle/alarm OID builders.

Resolve one with `OidProviderRegistry.resolve("VMS_NTCIP1203")`.

### Adding new profiles

1. Add the device's OIDs as a provider in `shared/oid_providers/` and register
   it in `OidProviderRegistry`. **Do not put OIDs in the profile.**
2. Create `polling/profiles/<new_profile>.py`. Resolve OIDs via
   `OidProviderRegistry.resolve(...)`. Reuse `shared.value_utils`,
   `shared.snmp_client` (always `SnmpClient(allow_write=False)`), and
   `polling.common` (`build_common_prefix`, `emit`, `detect_changes`, ...).
3. Expose a `create_<new_profile>_tasks(dev)` factory returning a list of
   `asyncio.Task`.
4. Register it in `polling/profiles/__init__.py` (`PROFILE_TASKS`).
5. If the type needs extra config fields, add their defaults in
   `normalize_device()` in `shared/config_loader.py`.

## Project layout

```
its-diag-toolkit/
├── diag_poller.py                  # async orchestration + interactive prompt
├── poc_runner.py                   # PoC entrypoint (skeleton)
├── config.example.yaml
├── requirements.txt
│
├── shared/
│   ├── snmp_client.py              # SnmpClient (allow_write guard) + GET helpers
│   ├── config_loader.py            # load_config / normalize_device
│   ├── evidence_writer.py          # timestamps, log paths, file writers
│   ├── value_utils.py              # pysnmp value coercion/formatting
│   └── oid_providers/              # the only home for numeric OIDs
│       ├── __init__.py             # OidProviderRegistry.resolve()
│       ├── base.py                 # NtcipBase (sys + NTCIP 1201)
│       ├── ntcip1203_v3.py         # Ntcip1203V3 (DMS OIDs)
│       ├── daktronics_vanguard.py  # DaktronicsVanguard(Ntcip1203V3)
│       └── semex_c5000.py          # SemexC5000Provider (NTCIP 1202 ASC)
│
├── polling/
│   ├── common.py                   # log line helpers + detect_changes
│   └── profiles/
│       ├── __init__.py             # PROFILE_TASKS registry
│       ├── vms_ntcip1203.py        # VMS profile (no hardcoded OIDs)
│       └── semex_c5000.py          # SEMEX profile (no hardcoded OIDs)
│
├── pocs/
│   └── vms/
│       ├── runner.py               # scenario runner (skeleton)
│       ├── base_scenario.py        # BaseScenario contract (skeleton)
│       ├── config/panels/
│       │   └── panel.daktronics.example.yaml
│       └── scenarios/              # individual scenarios (empty)
│
├── docs/
└── logs/                           # per-device daily logs (auto-created)
```
