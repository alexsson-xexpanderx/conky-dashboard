#!/usr/bin/env python3
"""Fetch current weather from OpenWeatherMap for the conky dashboard.

Writes `key=value` lines, which is what lua/dashboard.lua reads:

    temp=12.3
    feels=9.1
    icon=03d
    ...

The older two-line form (temperature then icon code) is still produced when one
of the --get_* flags is passed, so existing cron lines keep working.

Uses only the standard library.  The previous version needed pyowm, which is a
large dependency for a single JSON request, and it let exceptions escape: a
failed call under cron truncated the state file and the panel went blank.  Here
a failure leaves the previous reading in place and exits non-zero instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://api.openweathermap.org/data/2.5/weather"
TIMEOUT = 20


def fetch(api_key: str, city: str, ccode: str, units: str) -> dict:
    query = urllib.parse.urlencode(
        {"q": f"{city},{ccode}", "appid": api_key, "units": units}
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}", headers={"User-Agent": "conky-dashboard"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def render_legacy(payload: dict, want_temp: bool, want_icon: bool) -> str:
    """The original two-line output: temperature, then the icon code."""
    lines = []
    if want_temp:
        lines.append(f"{payload['main']['temp']:.1f}")
    if want_icon:
        # OWM always sends at least one entry; guard anyway so a malformed
        # response fails here rather than writing a half-valid file.
        lines.append(payload["weather"][0]["icon"])
    return "\n".join(lines) + "\n"


def render(payload: dict, units: str) -> str:
    """Everything the panel can draw, as `key=value` lines.

    Keyed rather than positional so a new field can be added without the Lua
    and this script having to change in lockstep; unknown keys are ignored by
    the reader and missing ones simply are not drawn.
    """
    main = payload.get("main", {})
    wind = payload.get("wind", {})
    sky = payload["weather"][0]
    sysinfo = payload.get("sys", {})

    fields: dict[str, object] = {
        "units": units,
        "city": payload.get("name", ""),
        "icon": sky.get("icon", ""),
        "description": sky.get("description", ""),
        "temp": main.get("temp"),
        "feels": main.get("feels_like"),
        "temp_min": main.get("temp_min"),
        "temp_max": main.get("temp_max"),
        "humidity": main.get("humidity"),
        "pressure": main.get("pressure"),
        "wind_speed": wind.get("speed"),
        "wind_deg": wind.get("deg"),
        "clouds": payload.get("clouds", {}).get("all"),
        "visibility": payload.get("visibility"),
        # Unix UTC; `tz` is the city's offset in seconds, so the panel can show
        # times in the observed location rather than wherever the machine is.
        "sunrise": sysinfo.get("sunrise"),
        "sunset": sysinfo.get("sunset"),
        "tz": payload.get("timezone", 0),
        "observed": payload.get("dt"),
    }

    lines = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, float):
            lines.append(f"{key}={value:.1f}")
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def write_atomically(path: str, text: str) -> None:
    """Replace `path` in one step so a reader never sees a partial file."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    handle, tmp = tempfile.mkstemp(dir=directory, prefix=".weather-")
    try:
        with os.fdopen(handle, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api_key",
        default=os.environ.get("OWM_API_KEY"),
        help="OpenWeatherMap API key. Prefer the OWM_API_KEY environment "
             "variable: a key on the command line is visible to every user "
             "on the machine via ps.",
    )
    parser.add_argument("--city", required=True, help="City name.")
    parser.add_argument("--ccode", required=True, help="ISO country code.")
    parser.add_argument("--output", help="Write here atomically instead of stdout.")
    parser.add_argument("--get_temp_c", action="store_true", help="Celsius.")
    parser.add_argument("--get_temp_f", action="store_true", help="Fahrenheit.")
    parser.add_argument("--get_weather_icon", action="store_true",
                        help="OWM icon code.")
    args = parser.parse_args()

    if not args.api_key:
        parser.error("no API key: pass --api_key or set OWM_API_KEY")
    if args.get_temp_c and args.get_temp_f:
        parser.error("--get_temp_c and --get_temp_f are mutually exclusive")

    want_temp = args.get_temp_c or args.get_temp_f
    want_icon = args.get_weather_icon
    legacy = want_temp or want_icon

    units = "imperial" if args.get_temp_f else "metric"

    try:
        payload = fetch(args.api_key, args.city, args.ccode, units)
        text = (render_legacy(payload, want_temp, want_icon) if legacy
                else render(payload, units))
    except urllib.error.HTTPError as exc:
        detail = "check the API key" if exc.code == 401 else exc.reason
        print(f"openweather: HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"openweather: network error: {exc}", file=sys.stderr)
        return 1
    except (KeyError, IndexError, ValueError) as exc:
        print(f"openweather: unexpected response: {exc}", file=sys.stderr)
        return 1

    if args.output:
        write_atomically(args.output, text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
