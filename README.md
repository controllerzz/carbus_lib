# carbus-lib

Асинхронная Python-библиотека для работы с CAN / CAN-FD адаптерами
**CAN-Hacker / Car Bus Analyzer**: низкоуровневый CAN/LIN, ISO-TP, UDS и удалённый
доступ к адаптеру через сеть.

- 📡 **`carbus_async`** — работа с железом: CAN/CAN-FD, фильтры, терминатор 120 Ω, периодическая отправка, хуки
- 📦 **`isotp_async`** — ISO-TP (ISO 15765-2): single- и multi-frame
- 🩺 **`uds_async`** — UDS (ISO 14229): клиент и сервер (эмуляция ЭБУ)
- 🌐 **Remote / TCP-bridge** — удалённый доступ к адаптеру через сеть, как к локальному

> Python ≥ 3.10 · зависимости: `pyserial`, `pyserial-asyncio` · целиком на `asyncio`
> Протестировано на устройствах с **Протоколом версии 22**
> Поддерживаемые устройства: https://canhacker.ru/shop/

---

## Содержание

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [CAN-FD и BRS](#can-fd-и-brs)
- [Приём и хуки](#приём-и-хуки)
- [Периодическая отправка](#периодическая-отправка)
- [Фильтры](#фильтры)
- [Терминатор](#терминатор)
- [Информация об устройстве](#информация-об-устройстве)
- [Маршрутизация по CAN-ID](#маршрутизация-по-can-id)
- [ISO-TP](#iso-tp)
- [UDS клиент](#uds-клиент)
- [UDS сервер](#uds-сервер)
- [Удалённая работа](#удалённая-работа)
- [Логирование](#логирование)
- [Примеры](#примеры)
- [Лицензия](#лицензия)

---

## Возможности

- CAN / CAN-FD: отправка и приём, BRS (bit-rate switching)
- Настройка каналов по битрейту или по точным bit-timing
- Фильтры по 11- и 29-битным ID, очистка фильтров
- Управление встроенным терминатором 120 Ω
- Периодическая отправка кадров (статичные данные или с модификацией на лету)
- Хуки на приём кадров по ID и по маске данных
- Маршрутизация принятых кадров по CAN-ID в отдельные очереди
- ISO-TP (single + multi-frame)
- UDS клиент и UDS сервер (эмуляция ЭБУ)
- Удалённая работа через relay-сервер и TCP-мост
- Подробное логирование всего протокольного трафика

---

## Установка

Из PyPI:

```bash
python -m pip install carbus-lib
```

Либо editable-режим из репозитория (нужно для разработки):

```bash
git clone https://github.com/controllerzz/carbus_lib.git
cd carbus_lib
pip install -e .
```

---

## Быстрый старт

Открыть устройство, настроить классический CAN-канал, отправить и принять кадр.

```python
import asyncio
from carbus_async import CarBusDevice, CanMessage


async def main():
    dev = await CarBusDevice.open("COM6", baudrate=115200)

    # классический CAN, 500 kbit/s, канал 1
    await dev.open_can_channel(channel=1, nominal_bitrate=500_000)

    # внутренний терминатор 120 Ω (если поддерживается устройством)
    await dev.ensure_terminator(channel=1, enabled=True)

    # отправка кадра
    msg = CanMessage(can_id=0x7E0, data=b"\x02\x3E\x00\x00\x00\x00\x00\x00")
    await dev.send_can(msg, channel=1)

    # приём любого кадра -> (channel, CanMessage)
    ch, rx = await dev.receive_can()
    print("RX:", ch, hex(rx.can_id), rx.data.hex())

    await dev.close()


asyncio.run(main())
```

Классический CAN через `open_can_channel` поддерживает битрейты
10k / 20k / 33.3k / 50k / 62.5k / 83.3k / 95.2k / 100k / 125k / 250k / 400k / 500k / 800k / 1M.

---

## CAN-FD и BRS

### 1. По стандартным битрейтам

```python
await dev.open_can_channel(
    channel=1,
    nominal_bitrate=500_000,   # арбитражная фаза
    data_bitrate=2_000_000,    # фаза данных (используется при BRS)
    fd=True,
    brs=True,
)
```

Поддерживаемые битрейты (CAN-модуль 120 МГц, точка выборки ~80%):

- **nominal:** 125k / 250k / 500k / 1M
- **data:** 500k / 1M / 2M / 4M / 5M

> На этих адаптерах FD-канал настраивается точными bit-timing, а не одиночным
> индексом скорости данных — иначе канал открывается, но FD/BRS-кадры не уходят
> в шину. `open_can_channel` делает это автоматически. Если тактовая модуля не
> 120 МГц, передайте её через `can_clock_hz=...`.

### 2. По точным bit-timing

Для нестандартных скоростей задайте тайминги напрямую:

```python
from carbus_async import CanTiming

await dev.open_can_channel_custom(
    channel=1,
    nominal_timing=CanTiming(prescaler=15, tq_seg1=12, tq_seg2=3, sjw=1),  # 500k @ 120 МГц
    data_timing=CanTiming(prescaler=6,  tq_seg1=7,  tq_seg2=2, sjw=1),     # 2M  @ 120 МГц
    fd=True,
    brs=True,
)
```

### Отправка FD-кадра

Тип кадра задаётся флагами `fd` / `brs` в самом `CanMessage`:

```python
# FD-кадр с переключением скорости (BRS), 16 байт данных
msg = CanMessage(can_id=0x100, data=bytes(range(16)), fd=True, brs=True)
await dev.send_can(msg, channel=1)
```

> Допустимые длины данных CAN-FD: 0–8, 12, 16, 20, 24, 32, 48, 64 байт.

---

## Приём и хуки

Способы приёма:

```python
ch, msg = await dev.receive_can()                                  # с любого канала
msg = await dev.receive_can_on(channel=1)                          # только канал 1
msg = await dev.receive_can_on_timeout(channel=1, timeout=1.0)     # None при таймауте
```

Хуки (вызываются на каждый подходящий принятый кадр):

```python
# по CAN-ID
@dev.on_can_id(0x7E0)
async def on_engine(ch, msg):
    print("ENGINE:", hex(msg.can_id), msg.data.hex())

# по CAN-ID + совпадению данных по маске
@dev.on_can_match(
    can_id=0x7E0,
    value=b"\x02\x10\x00",
    mask=b"\xFF\xFF\x00",
)
async def on_session_control(ch, msg):
    print("DiagnosticSessionControl")
```

---

## Периодическая отправка

```python
from carbus_async import PeriodicCanSender

sender = PeriodicCanSender(dev)

# статичные данные, период 100 мс (классический CAN)
sender.add(
    "heartbeat",
    channel=1,
    can_id=0x123,
    data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
    period_s=0.1,
)

# CAN-FD + BRS со счётчиком в первом байте
def mod(tick, data):
    b = bytearray(data)
    b[0] = tick & 0xFF
    return bytes(b)

sender.add(
    "cnt",
    channel=1,
    can_id=0x100,
    data=b"\x00" * 8,
    period_s=0.5,
    fd=True,
    brs=True,
    modify=mod,
)

# управление задачами
await sender.remove("cnt")   # остановить и удалить одну задачу
await sender.stop_all()      # остановить все
```

Параметры `add(...)`: `channel`, `can_id`, `data`, `period_s`,
`modify` (функция `(tick, data) -> bytes`, может быть async), `extended`,
`fd`, `brs`, `rtr`, `echo`, `confirm`, `autostart`.

---

## Фильтры

11-битные фильтры занимают индексы `0..27`, 29-битные — `28..35`.

```python
# очистить все фильтры на канале 1
await dev.clear_all_filters(1)

# пропускать только ответы с ID 0x7E8 (11-бит)
await dev.set_std_id_filter(channel=1, index=0, can_id=0x7E8, mask=0x7FF)

# 29-битный фильтр
await dev.set_ext_id_filter(channel=1, index=28, can_id=0x18DAF110)
```

---

## Терминатор

```python
await dev.set_terminator(channel=1, enabled=True)
await dev.set_terminator(channel=2, enabled=False)

# проверка поддержки и включение
if await dev.has_terminator(channel=1):
    await dev.set_terminator(channel=1, enabled=True)

# включить, только если устройство это поддерживает
await dev.ensure_terminator(channel=1, enabled=True)
```

---

## Информация об устройстве

```python
info = await dev.get_device_info()

print("HW:", info.hardware_name)
print("FW:", info.firmware_version)
print("Serial:", info.serial_int)
print("Каналы:", info.channel_types)          # {1: 'CANFD', 2: 'CAN', ...}
print("Частоты:", info.channel_frequencies)   # {1: 120000000, ...} Гц

print("Фичи:",
      "gateway" if info.feature_gateway else "",
      "isotp" if info.feature_isotp else "",
      "txbuf" if info.feature_tx_buffer else "",
      "txtask" if info.feature_tx_task else "")
```

---

## Маршрутизация по CAN-ID

`CanIdRouter` раскладывает принятые кадры по отдельным очередям на каждый CAN-ID —
удобно, когда на одном канале несколько независимых потоков.

```python
from carbus_async import CanIdRouter

router = CanIdRouter(dev, channel=1)
await router.start()

q = router.get_queue(0x7E8)      # очередь только для кадров с ID 0x7E8
msg = await q.get()
print(msg.data.hex())

await router.stop()
```

Роутер можно передать в `open_isotp(..., router=router)`, чтобы держать несколько
ISO-TP соединений на одном канале, не «перехватывая» кадры друг друга.

---

## ISO-TP

ISO-TP-канал строится поверх `CarBusDevice`:

```python
from isotp_async import open_isotp

isotp = await open_isotp(dev, channel=1, tx_id=0x7E0, rx_id=0x7E8)

# ReadDataByIdentifier F190 (VIN)
await isotp.send_pdu(b"\x22\xF1\x90")

# полный ответ (single или multi-frame)
resp = await isotp.recv_pdu(timeout=5.0)
print("ISO-TP:", resp.hex())
```

---

## UDS клиент

```python
from isotp_async import open_isotp
from uds_async import UdsClient

isotp = await open_isotp(dev, channel=1, tx_id=0x7E0, rx_id=0x7E8)
uds = UdsClient(isotp)

await uds.diagnostic_session_control(0x03)        # extended session
vin = await uds.read_data_by_identifier(0xF190)
print("VIN:", vin.decode(errors="ignore"))
await uds.tester_present()
```

Доступные сервисы: `diagnostic_session_control`, `read_data_by_identifier`,
`write_data_by_identifier`, `security_access_get_seed`,
`security_access_send_key`, `tester_present`.

---

## UDS сервер

Эмуляция ЭБУ: на каждый сервис (SID) вешается обработчик, возвращающий полный
ответный PDU. Отрицательный ответ — через `UdsNegativeResponse`.

```python
from isotp_async import open_isotp
from uds_async import UdsServer
from uds_async.exceptions import UdsNegativeResponse

# слушаем запросы на 0x7E0, отвечаем на 0x7E8
isotp = await open_isotp(dev, channel=1, tx_id=0x7E8, rx_id=0x7E0)
server = UdsServer(isotp)

@server.service(0x22)   # ReadDataByIdentifier
async def on_rdbi(req: bytes) -> bytes:
    did = (req[1] << 8) | req[2]
    if did == 0xF190:
        return b"\x62\xF1\x90" + b"WVWZZZ1KZAW000001"
    raise UdsNegativeResponse(req_sid=0x22, nrc=0x31)   # requestOutOfRange

await server.serve_forever()
```

---

## Удалённая работа

### Через relay-сервер (любой IP)

Можно воспользоваться бесплатным сервером:

```
IP:   185.42.26.80
PORT: 9000
```

**Сервер / Relay** (машина с белым IP):

```bash
carbus-relay-server --host 0.0.0.0 --port 9000
# или
python -m carbus_async.remote.server --host 0.0.0.0 --port 9000
```

**Агент** (машина, к которой подключён адаптер):

```bash
carbus-relay-agent --port COM6 --baudrate 115200 --server <IP_СЕРВЕРА>:9000 --serial 5957 --password 1234
# или
python -m carbus_async.remote.agent --port COM6 --baudrate 115200 --server <IP_СЕРВЕРА>:9000 --serial 5957 --password 1234
```

| параметр | назначение |
|---|---|
| `--server <IP>:9000` | адрес и порт relay-сервера |
| `--serial 5957`      | серийный номер устройства |
| `--password 1234`    | пароль для удалённого доступа |

**Клиент** (удалённая машина):

```python
from carbus_async import open_remote_device

dev = await open_remote_device("185.42.26.80", 9000, serial=5957, password="1234")
# дальше — обычный API CarBusDevice
```

### Через TCP-мост в локальной сети

**Сервер** (рядом с адаптером):

```bash
python -m carbus_async.tcp_bridge --serial COM6 --port 7000
```

**Клиент** (та же сеть) — тот же API, но через `open_tcp`:

```python
import asyncio
from carbus_async import CarBusDevice, CanMessage


async def main():
    dev = await CarBusDevice.open_tcp("192.168.1.10", 7000)

    await dev.open_can_channel(channel=1, nominal_bitrate=500_000)

    msg = CanMessage(can_id=0x321, data=b"\x01\x02\x03\x04")
    await dev.send_can(msg, channel=1)

    ch, rx = await dev.receive_can()
    print("REMOTE RX:", ch, hex(rx.can_id), rx.data.hex())

    await dev.close()


asyncio.run(main())
```

---

## Логирование

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

Логгеры:

- `carbus_async.wire.*` — сырые кадры по USB/TCP (TX/RX)
- `carbus_async.device.*` — высокоуровневые события, ошибки, `BUS_ERROR`
- дополнительные логгеры в `isotp_async` / `uds_async`

---

## Примеры

Готовые скрипты — в каталоге [`example/`](example):

| файл | что показывает |
|---|---|
| `can_periodic_message.py`        | периодическая отправка (классический CAN) |
| `canfd_periodic_message.py`      | периодическая отправка CAN-FD / BRS |
| `can_message_hook.py`            | хуки на приём кадров |
| `uds_service22_scaner.py`        | скан UDS-сервиса 0x22 (RDBI) |
| `uds_id_scaner.py`               | перебор идентификаторов (DID) |
| `uds_ecu_emulated.py`            | эмуляция ЭБУ (UDS-сервер) |
| `car_ecus_emulated.py`           | эмуляция нескольких ЭБУ |
| `remote_can_periodic_message.py` | периодика через relay-сервер |
| `remote_can_bridge.py`           | мост CAN ↔ удалённое устройство |
| `remote_relay.py`                | запуск relay-сервера |

---

## Лицензия

MIT — распространяется «как есть», без каких-либо гарантий. См. [LICENSE](LICENSE).

Pull Requests и предложения по улучшению приветствуются 🚗
