# car-bus-lib (async CAN / ISO-TP / UDS stack)

Асинхронная библиотека на Python для работы с CAN-адаптером **CAN-Hacker / Car Bus Analyzer**:

- 📡 **`carbus_async`** – низкоуровневая работа с железкой (CAN/LIN, фильтры, терминаторы и т.д.)
- 📦 **`isotp_async`** – ISO-TP (ISO 15765-2) поверх CAN (single + multi-frame)
- 🩺 **`uds_async`** – UDS (ISO 14229) клиент и сервер (диагностика, чтение VIN и т.п.)
- 🌐 **`TCP-bridge`** – удалённое подключение к адаптеру через сеть (как будто он воткнут локально)

> Python 3.11 и выше  
> Никаких «магических» зависимостей — всё на `asyncio`.  
> _*Тестировалось на устройствах с Протоколом Версии 22_

---

## Установка

Пока проект в разработке, можно ставить его как editable-модуль из репозитория:

```bash
git clone https://github.com/controllerzz/carbus_lib.git
cd carbus_lib
pip install -e .
```

# carbus-lib

Асинхронная библиотека для работы с CAN / CAN-FD, ISO-TP и UDS.  
Поддерживает локальное подключение через USB CDC и удалённую работу через TCP-bridge.  

---

## Возможности

- CAN / CAN-FD отправка и приём
- Настройка каналов, скоростей, режимов, BRS
- Фильтры ID, очистка фильтров, управление терминатором 120 Ω
- ISO-TP (single + multi-frame)
- UDS Client и UDS Server (эмуляция ЭБУ)
- TCP-мост: удалённая работа с адаптером так, как будто он подключён локально
- Логирование всего протокольного трафика

---

## Работа с CAN

Простейший пример: открыть устройство, настроить канал и отправить / принять кадр.

````python
import asyncio
from carbus_async.device import CarBusDevice
from carbus_async.messages import CanMessage

async def main():
    dev = await CarBusDevice.open("COM6", baudrate=115200)

    # классический CAN 500 kbit/s
    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
    )

    # включаем терминатор 120 Ω на канале 1
    await dev.set_terminator(channel=1, enabled=True)

    # отправка кадра 0x7E0 8 байт
    msg = CanMessage(can_id=0x7E0, data=b"\x02\x3E\x00\x00\x00\x00\x00\x00")
    await dev.send_can(msg, channel=1)

    # приём любого сообщения
    ch, rx = await dev.receive_can()
    print("RX:", ch, rx)

    await dev.close()

asyncio.run(main())
````

Возможность настройки канала через Bit Timing
````python
# CANFD+BRS 500/2000 kbit/s
await dev.open_can_channel_custom(
    channel=1,
    nominal=(15, 12, 3, 1),  # Prescaler, tqSeg1, tqSeg2, SyncJW
    data=(6, 7, 2, 1),  # Prescaler, tqSeg1, tqSeg2, SyncJW
    fd=True,
    brs=True,
)
````

## Информация об устройстве и фильтры

Пример запроса DEVICE_INFO и настройки фильтров:
````python
info = await dev.get_device_info()

print("HW:", info.hardware_name)
print("FW:", info.firmware_version)
print("Serial:", info.serial_int)

# очистить все фильтры на канале 1
await dev.clear_all_filters(1)

# разрешить только ответы с ID 0x7E8 (11-битный стандартный ID)
await dev.set_std_id_filter(
    channel=1,
    index=0,
    can_id=0x7E8,
    mask=0x7FF,
)

# включить/выключить терминатор 120 Ω
await dev.set_terminator(channel=1, enabled=True)
````

## ISO-TP (isotp_async)
ISO-TP канал строится поверх CarBusDevice:
````python
from isotp_async.transport import IsoTpChannel

can_tr = CarBusCanTransport(dev, channel=1, rx_id=0x7E8)
isotp = IsoTpChannel(can_tr, tx_id=0x7E0, rx_id=0x7E8)

# отправить запрос ReadDataByIdentifier F190 (VIN)
await isotp.send_pdu(b"\x22\xF1\x90")

# получить полный ответ (single или multi-frame)
resp = await isotp.recv_pdu(timeout=30.0)
print("ISO-TP:", resp.hex())
````

## UDS Client (uds_async.client)

Клиент UDS использует IsoTpChannel:
````python
from isotp_async import CarBusCanTransport
from isotp_async.transport import IsoTpChannel
from uds_async import UdsClient

can_tr = CarBusCanTransport(dev, channel=1, rx_id=0x7E8)
isotp = IsoTpChannel(can_tr, tx_id=0x7E0, rx_id=0x7E8)
uds = UdsClient(isotp)

vin = await uds.read_data_by_identifier(0xF190)
print("VIN:", vin.decode(errors="ignore"))
````



## Удалённая работа через TCP (tcp_bridge)

### 1. Сервер (рядом с адаптером)

На машине, где физически подключён CAN-адаптер:

    python.exe -m carbus_async.tcp_bridge --serial COM6 --port 7000

Адаптер открывается локально, а поверх него поднимается TCP-мост.

### 2. Клиент (удалённая машина)

На другой машине можно использовать тот же API, как с локальным COM, но через `open_tcp`:
````python
import asyncio
from carbus_async.device import CarBusDevice
from carbus_async.messages import CanMessage

async def main():
    dev = await CarBusDevice.open_tcp("192.168.1.10", 7000)

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
        fd=False,
    )

    msg = CanMessage(can_id=0x321, data=b"\x01\x02\x03\x04")
    await dev.send_can(msg, channel=1)

    ch, rx = await dev.receive_can()
    print("REMOTE RX:", ch, rx)

    await dev.close()

asyncio.run(main())
````

## Логирование

Для отладки удобно включить подробное логирование:
````python
    import logging

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
````
Логгеры:

- `carbus_async.wire.*` — сырые кадры по USB/TCP (TX/RX)
- `carbus_async.device.*` — высокоуровневые события, ошибки, BUS_ERROR
- дополнительные логгеры в isotp_async / uds_async

---

## Лицензия

MIT. 
  
    ДАННОЕ ПРОГРАММНОЕ ОБЕСПЕЧЕНИЕ ПРЕДОСТАВЛЯЕТСЯ «КАК ЕСТЬ», БЕЗ КАКИХ-ЛИБО ГАРАНТИЙ, ЯВНО ВЫРАЖЕННЫХ ИЛИ ПОДРАЗУМЕВАЕМЫХ, ВКЛЮЧАЯ ГАРАНТИИ ТОВАРНОЙ ПРИГОДНОСТИ, СООТВЕТСТВИЯ ПО ЕГО КОНКРЕТНОМУ НАЗНАЧЕНИЮ И ОТСУТСТВИЯ НАРУШЕНИЙ, НО НЕ ОГРАНИЧИВАЯСЬ ИМИ. НИ В КАКОМ СЛУЧАЕ АВТОРЫ ИЛИ ПРАВООБЛАДАТЕЛИ НЕ НЕСУТ ОТВЕТСТВЕННОСТИ ПО КАКИМ-ЛИБО ИСКАМ, ЗА УЩЕРБ ИЛИ ПО ИНЫМ ТРЕБОВАНИЯМ, В ТОМ ЧИСЛЕ, ПРИ ДЕЙСТВИИ КОНТРАКТА, ДЕЛИКТЕ ИЛИ ИНОЙ СИТУАЦИИ, ВОЗНИКШИМ ИЗ-ЗА ИСПОЛЬЗОВАНИЯ ПРОГРАММНОГО ОБЕСПЕЧЕНИЯ ИЛИ ИНЫХ ДЕЙСТВИЙ С ПРОГРАММНЫМ ОБЕСПЕЧЕНИЕМ.  
  


Pull Requests и предложения по улучшению приветствуются 🚗


