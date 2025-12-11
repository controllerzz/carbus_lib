class CarBusError(Exception):
    ...


class SyncError(CarBusError):
    ...


class CommandError(CarBusError):
    ...