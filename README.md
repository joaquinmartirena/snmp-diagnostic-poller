# SNMP Diagnostic Poller

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
- Profile-based architecture (easy to add new device types)
- VMS NTCIP 1203 support
- SEMEX C5000 traffic controller support (separate alarm and cycle polls)
- Daily log rotation, one file per device
- One-line plain text logs (no ANSI colors in files)
- Read-only: SNMP `GET` only

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

**This tool is strictly read-only.** It only performs SNMP `GET` operations.
It never performs SET operations, resets, activations, schedule changes, or any
other write/configuration change to a device.

## L. Adding new profiles

The project is profile-based. To add a new device type:

1. Create `profiles/<new_profile>.py`.
2. Define the device's OID constants.
3. Implement one or more async polling task(s). Reuse helpers from `common.py`
   (`snmp_get_many`, `snmp_get_chunked`, `value_to_int`, `raw_hex_padded`,
   `build_common_prefix`, `classify_comm_status`, `emit`, `detect_changes`, ...).
4. Expose a `create_<new_profile>_tasks(dev)` factory that returns a list of
   `asyncio.Task` for the device.
5. Register it in `profiles/__init__.py`:

   ```python
   from .new_profile import create_new_profile_tasks

   PROFILE_TASKS = {
       ...
       "NEW_PROFILE_TYPE": create_new_profile_tasks,
   }
   ```

If the new type needs extra config fields, add their defaults in
`normalize_device()` in `diag_poller.py`.

## Project layout

```
.
├── diag_poller.py          # config loading + async orchestration (no device OIDs)
├── common.py               # generic SNMP/value/log helpers
├── config.yaml             # device list
├── requirements.txt
├── README.md
├── profiles/
│   ├── __init__.py         # PROFILE_TASKS registry
│   ├── vms_ntcip1203.py    # VMS_NTCIP1203 profile
│   └── semex_c5000.py      # SEMEX_C5000_V1 profile
└── logs/                   # per-device daily logs (auto-created)
```
