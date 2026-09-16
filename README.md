# FT232H SMBus

Read an SBS smart battery with a FT232H. Tested with the Adafruit FT232H.

Install the FTDI D2XX driver, then run:

```powershell
python -m pip install -r requirements.txt
python sbsreport.py
```

Wire the bus with a common ground and suitable SMBus pull-ups:

- `D0` -> `SCL`
- `D1` -> `SDA`
- jumper `D0` -> `D7` for SCL feedback
- the Adafruit breakout's onboard I2C switch connects `D1` -> `D2` for SDA feedback
- `GND` -> battery/SMBus ground

With the Adafruit I2C switch enabled, only the `D0` -> `D7` feedback jumper is external. The script checks `D7`, not `D8`. Do not power the battery from the FT232H.

Use `python sbsreport.py --no-pec` for a battery that does not support PEC.

Reference: [karosium/smbusb](https://github.com/karosium/smbusb/tree/master)
