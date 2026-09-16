import argparse

import ft232h_smbus as bus


ADDRESS_WRITE = 0x16
ADDRESS_READ = 0x17
CAPACITY_MODE = 1 << 15

BATTERY_MODE_FLAGS = {
    15: "capacity values in 10 mWh/10 mW",
    14: "charger broadcasts disabled",
    13: "alarm broadcasts disabled",
    9: "primary battery mode",
    8: "internal charger enabled",
    7: "conditioning cycle requested",
    1: "primary battery support",
    0: "internal charger supported",
}
BATTERY_STATUS_FLAGS = {
    15: "overcharged alarm",
    14: "terminate charge alarm",
    12: "over-temperature alarm",
    11: "terminate discharge alarm",
    9: "remaining capacity alarm",
    8: "remaining time alarm",
    7: "initialized",
    6: "discharging",
    5: "fully charged",
    4: "fully discharged",
}
SBS_ERROR_CODES = {
    0: "OK",
    1: "Busy",
    2: "ReservedCommand",
    3: "UnsupportedCommand",
    4: "AccessDenied",
    5: "Overflow/Underflow",
    6: "BadSize",
    7: "UnknownError",
}


def read_safely(reader, adapter, register, pec_enabled):
    for _ in range(5):
        try:
            value = reader(adapter, ADDRESS_WRITE, register, pec_enabled, ignore_command_nack=True)
            if value is not None:
                return value
        except (OSError, RuntimeError):
            pass
    return None


def word_value(adapter, register, pec_enabled, signed=False):
    raw = read_safely(bus.read_word, adapter, register, pec_enabled)
    if raw is None:
        return None
    return int.from_bytes(raw, "little", signed=signed)


def block_value(adapter, register, pec_enabled):
    return read_safely(bus.read_block, adapter, register, pec_enabled)


def field_text(value, formatter=str):
    return "ERROR" if value is None else formatter(value)


def text_value(data):
    if data is None:
        return "ERROR"
    return data.split(b"\0", 1)[0].decode("ascii", errors="replace")


def active_flags(value, flags):
    return [name for bit, name in flags.items() if value & (1 << bit)]


def battery_mode_text(value):
    flags = active_flags(value, BATTERY_MODE_FLAGS)
    return f"0x{value:04x} ({', '.join(flags) or 'default mode'})"


def capacity_text(value, battery_mode):
    if battery_mode is None:
        return f"{value} (BatteryMode unavailable)"
    if battery_mode & CAPACITY_MODE:
        return f"{value} (10 mWh units, {value / 100:.2f} Wh)"
    return f"{value} mAh"


def rate_text(value, battery_mode):
    if battery_mode is None:
        return f"{value} (BatteryMode unavailable)"
    if battery_mode & CAPACITY_MODE:
        return f"{value} (10 mW units, {value / 100:.2f} W)"
    return f"{value} mA"


def battery_status_text(value):
    flags = active_flags(value, BATTERY_STATUS_FLAGS)
    error = value & 0x0F
    error_name = SBS_ERROR_CODES.get(error, "Reserved/unknown")
    return (
        f"0x{value:04x} ({', '.join(flags) or 'no flags'}; "
        f"SBS error {error} {error_name})"
    )


def minutes_text(value):
    return "not available" if value == 0xFFFF else f"{value} min"


def print_sbs_report(adapter, pec_enabled):
    manufacturer_access = word_value(adapter, 0x00, pec_enabled)
    print("Manufacturer Access:        ", field_text(manufacturer_access, lambda value: f"{value:04x}"))
    print("Manufacturer Name:          ", text_value(block_value(adapter, 0x20, pec_enabled)))
    print("Device Name:                ", text_value(block_value(adapter, 0x21, pec_enabled)))
    print("Device Chemistry:           ", text_value(block_value(adapter, 0x22, pec_enabled)))
    print("Serial Number:              ", field_text(word_value(adapter, 0x1C, pec_enabled)))

    manufacture_date = word_value(adapter, 0x1B, pec_enabled)
    date_text = (
        "ERROR"
        if manufacture_date is None
        else f"{1980 + (manufacture_date >> 9)}.{(manufacture_date >> 5) & 0x0F:02}.{manufacture_date & 0x1F:02}"
    )
    print("Manufacture Date:           ", date_text)

    battery_mode = word_value(adapter, 0x03, pec_enabled)
    print("Remaining Capacity Alarm:   ", field_text(word_value(adapter, 0x01, pec_enabled), lambda value: capacity_text(value, battery_mode)))
    print("Remaining Time Alarm:       ", field_text(word_value(adapter, 0x02, pec_enabled), minutes_text))
    print("Battery Mode:               ", field_text(battery_mode, battery_mode_text))
    print("At Rate:                    ", field_text(word_value(adapter, 0x04, pec_enabled), lambda value: rate_text(value, battery_mode)))
    print("At Rate Time To Full:       ", field_text(word_value(adapter, 0x05, pec_enabled), minutes_text))
    print("At Rate Time To Empty:      ", field_text(word_value(adapter, 0x06, pec_enabled), minutes_text))
    print("At Rate OK:                 ", field_text(word_value(adapter, 0x07, pec_enabled), lambda value: "yes" if value else "no"))
    print("Temperature:                ", field_text(word_value(adapter, 0x08, pec_enabled), lambda value: f"{value * 0.1 - 273.15:.2f} degC"))
    print("Voltage:                    ", field_text(word_value(adapter, 0x09, pec_enabled), lambda value: f"{value} mV"))
    print("Current:                    ", field_text(word_value(adapter, 0x0A, pec_enabled, signed=True), lambda value: f"{value} mA"))
    print("Average Current:            ", field_text(word_value(adapter, 0x0B, pec_enabled, signed=True), lambda value: f"{value} mA"))
    print("Max Error:                  ", field_text(word_value(adapter, 0x0C, pec_enabled), lambda value: f"{value}%"))
    print("Relative State Of Charge    ", field_text(word_value(adapter, 0x0D, pec_enabled), lambda value: f"{value}%"))
    print("Absolute State Of Charge    ", field_text(word_value(adapter, 0x0E, pec_enabled), lambda value: f"{value}%"))
    print("Remaining Capacity:         ", field_text(word_value(adapter, 0x0F, pec_enabled), lambda value: capacity_text(value, battery_mode)))
    print("Full Charge Capacity:       ", field_text(word_value(adapter, 0x10, pec_enabled), lambda value: capacity_text(value, battery_mode)))
    print("Run Time To Empty:          ", field_text(word_value(adapter, 0x11, pec_enabled), minutes_text))
    print("Average Time To Empty:      ", field_text(word_value(adapter, 0x12, pec_enabled), minutes_text))
    print("Average Time To Full:       ", field_text(word_value(adapter, 0x13, pec_enabled), minutes_text))
    print("Charging Current:           ", field_text(word_value(adapter, 0x14, pec_enabled), lambda value: f"{value} mA"))
    print("Charging Voltage:           ", field_text(word_value(adapter, 0x15, pec_enabled), lambda value: f"{value} mV"))
    print("Battery Status:             ", field_text(word_value(adapter, 0x16, pec_enabled), battery_status_text))
    print("Cycle Count:                ", field_text(word_value(adapter, 0x17, pec_enabled)))
    print("Design Capacity:            ", field_text(word_value(adapter, 0x18, pec_enabled), lambda value: capacity_text(value, battery_mode)))
    print("Design Voltage:             ", field_text(word_value(adapter, 0x19, pec_enabled), lambda value: f"{value} mV"))
    print("Specification Info:         ", field_text(word_value(adapter, 0x1A, pec_enabled), lambda value: f"{value:04x}"))

    data = block_value(adapter, 0x23, pec_enabled)
    print("Manufacturer Data:          ", "ERROR" if data is None else data.hex(" "))
    return manufacturer_access


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read a Smart Battery through an FT232H in MPSSE mode.")
    parser.add_argument("--no-pec", action="store_true", help="disable SMBus Packet Error Checking")
    args = parser.parse_args(argv)
    pec_enabled = not args.no_pec

    print("FT232H Smart Battery Specification Report")
    print(f"SMBus read address: 0x{ADDRESS_READ:02x} (PEC {'enabled' if pec_enabled else 'disabled'})")
    print("-------------------------------------------------")

    with bus.open_adapter() as adapter:
        print_sbs_report(adapter, pec_enabled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
