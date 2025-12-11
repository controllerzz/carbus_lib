# car-bus-lib (async CAN / ISO-TP / UDS stack)

Асинхронная библиотека на Python для работы с CAN-адаптером **CAN-Hacker / Car Bus Analyzer**:

- 📡 **`carbus_async`** – низкоуровневая работа с железкой (CAN/LIN, фильтры, терминаторы и т.д.)
- 📦 **`isotp_async`** – ISO-TP (ISO 15765-2) поверх CAN (single + multi-frame)
- 🩺 **`uds_async`** – UDS (ISO 14229) клиент и сервер (диагностика, чтение VIN и т.п.)
- 🌐 **TCP-bridge** – удалённое подключение к адаптеру через сеть (как будто он воткнут локально)

> Минимальные примеры, никаких «магических» зависимостей — всё на `asyncio`.

---

## Установка

Пока проект в разработке, можно ставить его как editable-модуль из репозитория:

```bash
git clone https://github.com/your_name/carbus_lib.git
cd car_bus_lib
pip install -e .
```

# car-bus-lib

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

## Установка
````bat
    pip install pyserial pyserial-asyncio

    git clone https://github.com/your_name/carbus_lib.git
    cd car-bus-lib
    pip install -e .
````

## 1. Работа с CAN

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
            fd=False,
        )

        # отправка кадра 0x7E0 8 байт
        msg = CanMessage(can_id=0x7E0, data=b"\x02\x3E\x00\x00\x00\x00\x00\x00")
        await dev.send_can(msg, channel=1)

        # приём любого сообщения
        ch, rx = await dev.receive_can()
        print("RX:", ch, rx)

        await dev.close()

    asyncio.run(main())
````


## 2. Информация об устройстве и фильтры

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

## 3. ISO-TP (isotp_async)
ISO-TP канал строится поверх CarBusDevice:
````python
    from isotp_async import IsoTpChannel

    # предполагается, что dev уже открыт и канал CAN настроен
    isotp = IsoTpChannel(
        device=dev,
        channel=1,
        tx_id=0x7E0,   # наш запрос
        rx_id=0x7E8,   # ответ ЭБУ
    )

    # отправить запрос ReadDataByIdentifier F190 (VIN)
    await isotp.send(b"\x22\xF1\x90")

    # получить полный ответ (single или multi-frame)
    resp = await isotp.recv(timeout=1.0)
    print("ISO-TP:", resp.hex())
````

## 4. UDS Client (uds_async.client)

Клиент UDS использует IsoTpChannel:
````python
    from uds_async.client import UdsClient
    from isotp_async import IsoTpChannel

    isotp = IsoTpChannel(dev, channel=1, tx_id=0x7E0, rx_id=0x7E8)
    uds = UdsClient(isotp_channel=isotp)

    # переход в расширенную диагностическую сессию
    await uds.diagnostic_session_control(0x03)

    # чтение VIN (DID F190)
    vin_bytes = await uds.read_data_by_identifier(0xF190)
    print("VIN:", vin_bytes.decode(errors="ignore"))
````

## 5. UDS Server (эмулятор ЭБУ)

Простой UDS-сервер, который отвечает на запрос VIN:
````python
    from uds_async.server import UdsServer, UdsRequest, UdsPositiveResponse
    from isotp_async import IsoTpChannel

    class MyEcuServer(UdsServer):
        async def handle_read_data_by_identifier(self, req: UdsRequest):
            if req.data_identifier == 0xF190:
                # положительный ответ: 62 F1 90 + данные
                return UdsPositiveResponse(b"\x62\xF1\x90DEMO-VIN-1234567")
            # всё остальное обрабатывается базовой реализацией
            return await super().handle_read_data_by_identifier(req)

    async def main():
        dev = await CarBusDevice.open("COM6", baudrate=115200)
        await dev.open_can_channel(channel=1, nominal_bitrate=500_000, fd=False)

        isotp = IsoTpChannel(dev, channel=1, tx_id=0x7E8, rx_id=0x7E0)
        server = MyEcuServer(isotp_channel=isotp)
        await server.serve_forever()

    asyncio.run(main())
````

## 6. Удалённая работа через TCP (tcp_bridge)

### 6.1. Сервер (рядом с адаптером)

На машине, где физически подключён CAN-адаптер:

    python -m carbus_async.tcp_bridge --serial COM6 --port 7000

Адаптер открывается локально, а поверх него поднимается TCP-мост.

### 6.2. Клиент (удалённая машина)

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

## 7. Логирование

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

## 8. Структура проекта

    carbus_async/
      device.py        — асинхронный интерфейс к адаптеру (CAN/CAN-FD)
      protocol.py      — описания команд, флагов и структур протокола
      messages.py      — модель CanMessage и вспомогательные типы
      tcp_bridge.py    — TCP-мост (сервер для удалённой работы)

    isotp_async/
      __init__.py      — IsoTpChannel и вспомогательные сущности

    uds_async/
      client.py        — UdsClient (клиент UDS)
      server.py        — UdsServer (сервер / эмулятор ЭБУ)
      types.py         — структуры запросов/ответов

---

## 9. Лицензия

MIT (можно поменять под нужды проекта).

Pull Requests и предложения по улучшению приветствуются 🚗


