from contextlib import contextmanager

import ftd2xx


def find_adapter_index():
    matches = [
        index for index in range(ftd2xx.createDeviceInfoList())
        if ftd2xx.getDeviceInfoDetail(index, update=False)["id"] == 0x04036014
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one FT232H, found {len(matches)}.")
    return matches[0]


def exchange(adapter, data, length):
    if adapter.write(data) != len(data):
        raise RuntimeError("Short USB write.")
    response = adapter.read(length)
    if len(response) != length:
        raise RuntimeError("USB read timeout.")
    return response


def pins(value):
    return bytes([0x80, value, 0x03]) * 10


START = pins(0x01) + pins(0x00)
STOP = pins(0x02) + pins(0x00) + pins(0x01) + pins(0x03)


def write_byte(value):
    return bytes([0x11, 0, 0, value]) + pins(0x02) + b"\x22\x00" + pins(0x02)


def write_byte_with_gpio_ack(value):
    return (
        bytes([0x11, 0, 0, value])
        + pins(0x02)
        + pins(0x03)
        + b"\x81"
        + pins(0x02)
    )


@contextmanager
def open_adapter():
    with ftd2xx.open(find_adapter_index()) as adapter:
        adapter.setTimeouts(2000, 2000)
        adapter.setLatencyTimer(2)
        adapter.setBitMode(0, 0)
        try:
            adapter.setBitMode(0, 2)
            adapter.purge(3)
            if exchange(adapter, b"\xaa\x87", 2) != b"\xfa\xaa":
                raise RuntimeError("MPSSE handshake failed.")
            adapter.write(bytes.fromhex("8a 97 8c 85 86 cf 07 9e 07 00 80 03 03"))
            idle = exchange(adapter, b"\x81\x87", 1)[0]
            if idle & 0x85 != 0x85:
                raise RuntimeError(f"SCL, SDA, and D7 must idle HIGH; pins=0x{idle:02X}.")
            feedback_low = exchange(
                adapter,
                pins(0x02) + pins(0x00) + b"\x81" + pins(0x02) + pins(0x03) + b"\x87",
                1,
            )[0]
            if feedback_low & 0x84:
                raise RuntimeError(
                    "Check the D0-D7 SCL feedback jumper and the D1-D2 SDA feedback "
                    "connection (or enable the Adafruit I2C switch)."
                )
            adapter.write(b"\x96")
            yield adapter
        finally:
            try:
                try:
                    exchange(adapter, b"\x80\x00\x00\x82\x00\x00\x81\x87", 1)
                except (OSError, RuntimeError):
                    pass
            finally:
                adapter.setBitMode(0, 0)


def transaction(adapter, values, *, stop_on_nack=True, gpio_ack=False):
    acknowledgements = []
    try:
        for index, value in enumerate(values):
            prefix = START if index == 0 else b""
            if gpio_ack:
                acknowledged = not (
                    exchange(adapter, prefix + write_byte_with_gpio_ack(value) + b"\x87", 1)[0] & 4
                )
            else:
                acknowledged = not (exchange(adapter, prefix + write_byte(value) + b"\x87", 1)[0] & 1)
            acknowledgements.append(acknowledged)
            if not acknowledged and stop_on_nack:
                break
        return acknowledgements
    finally:
        exchange(adapter, STOP + b"\x81\x87", 1)


def probe_address(adapter, address):
    return all(transaction(adapter, (address,)))


def probe_command(adapter, address, command):
    return all(transaction(adapter, (address, command)))


def probe_command_write(adapter, address, command):
    acknowledgements = transaction(adapter, (address, command, 3, 0, 0, 0, 0))
    return sum(acknowledged for index, acknowledged in enumerate(acknowledgements) if index in (1, 2, 3, 5, 6))


def select_register(adapter, address, register, *, ignore_command_nack=False):
    idle = exchange(adapter, pins(0x03) + b"\x81\x87", 1)[0]
    if idle & 5 != 5:
        raise RuntimeError("Bus not idle high before read.")
    for index, (value, prefix) in enumerate((
        (address, START),
        (register, b""),
        (address + 1, pins(0x02) + pins(0x03) + START),
    )):
        nack = exchange(adapter, prefix + write_byte(value) + b"\x87", 1)[0] & 1
        if nack and not (index == 1 and ignore_command_nack):
            return False
    return True


def read_byte(adapter, acknowledge):
    ack = 0x00 if acknowledge else 0xFF
    return exchange(adapter, b"\x20\x00\x00\x13\x00" + bytes([ack]) + pins(0x02) + b"\x87", 1)[0]


def pec_crc(values):
    crc = 0
    for value in values:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def read_payload(adapter, length, pec_enabled, prefix):
    data = bytes(read_byte(adapter, pec_enabled or index < length - 1) for index in range(length))
    if pec_enabled:
        received_pec = read_byte(adapter, False)
        expected_pec = pec_crc((*prefix, *data))
        if received_pec != expected_pec:
            raise RuntimeError(f"PEC mismatch: received 0x{received_pec:02X}, expected 0x{expected_pec:02X}")
    return data


def read_word(adapter, address, register, pec_enabled=False, *, ignore_command_nack=False):
    try:
        if not select_register(adapter, address, register, ignore_command_nack=ignore_command_nack):
            return None
        return read_payload(adapter, 2, pec_enabled, (address, register, address + 1))
    finally:
        exchange(adapter, STOP + b"\x81\x87", 1)


def read_block(adapter, address, register, pec_enabled=False, *, ignore_command_nack=False, min_length=1, max_length=32):
    try:
        if not select_register(adapter, address, register, ignore_command_nack=ignore_command_nack):
            return None
        length = read_byte(adapter, True)
        if not min_length <= length <= max_length:
            raise RuntimeError(f"Invalid SMBus block length {length}.")
        return read_payload(adapter, length, pec_enabled, (address, register, address + 1, length))
    finally:
        exchange(adapter, STOP + b"\x81\x87", 1)