"""WiZ smart lighting tools for the NikitAI Home Wizard sub-agent.

Uses pywizlight (async, local UDP control — no cloud account/API key).
Each tool wraps its bulb interaction in ``asyncio.run(...)`` so the rest of
the codebase (synchronous dispatcher) doesn't need to change. This assumes
these functions are never called from within an already-running event loop.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from pywizlight import PilotBuilder, wizlight

CONFIG_ENV_VAR = "NIKITAI_WIZ_LIGHTS_CONFIG"


class WizConfigError(Exception):
    """Raised when the WiZ lights config is missing or malformed."""


class WizLightNotFoundError(Exception):
    """Raised when a light name isn't in the config."""


class WizConnectionError(Exception):
    """Raised when a bulb is unreachable (timeout or network error)."""


def _load_config() -> dict[str, str]:
    """Load the friendly-name -> IP mapping from the JSON config file.

    The file path is read from ``NIKITAI_WIZ_LIGHTS_CONFIG`` (no default).
    """
    path = os.environ.get(CONFIG_ENV_VAR)
    if not path:
        raise WizConfigError(
            f"Environment variable {CONFIG_ENV_VAR} is not set. "
            "It must point to a JSON file mapping friendly light names to IP addresses."
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise WizConfigError(f"WiZ lights config file not found at {path!r}") from None
    except json.JSONDecodeError as exc:
        msg = f"WiZ lights config file at {path!r} is not valid JSON: {exc}"
        raise WizConfigError(msg) from exc
    if not isinstance(data, dict):
        raise WizConfigError(f"WiZ lights config at {path!r} must be a JSON object")
    for name, ip in data.items():
        if not isinstance(name, str) or not isinstance(ip, str):
            raise WizConfigError(
                f"WiZ lights config at {path!r} must map string names to string IPs"
            )
    return data


def _get_ip(name: str, config: dict[str, str]) -> str:
    """Look up the IP for a friendly name, raising a clear error if missing."""
    try:
        return config[name]
    except KeyError:
        available = ", ".join(sorted(config.keys()))
        raise WizLightNotFoundError(
            f"Light {name!r} not found in config. Available: {available}"
        ) from None


async def _get_bulb_state(ip: str) -> dict[str, Any]:
    """Query a bulb for its current state."""
    bulb = wizlight(ip)
    try:
        state = await bulb.updateState()
        raw_rgb = state.get_rgb()
        return {
            "on": state.get_state(),
            "brightness": state.get_brightness(),
            "rgb": list(raw_rgb) if raw_rgb is not None else None,
        }
    except Exception as exc:
        raise WizConnectionError(f"Failed to reach bulb at {ip}: {exc}") from exc
    finally:
        await bulb.async_close()


async def _turn_on(ip: str, brightness: int | None, rgb: list[int] | None) -> dict[str, Any]:
    """Turn the bulb on with optional brightness and/or RGB."""
    bulb = wizlight(ip)
    try:
        kwargs = {}
        if brightness is not None:
            if not 0 <= brightness <= 100:
                raise ValueError("brightness must be 0-100")
            kwargs["brightness"] = brightness
        if rgb is not None:
            if not (isinstance(rgb, list) and len(rgb) == 3 and all(0 <= c <= 255 for c in rgb)):
                raise ValueError("rgb must be a list of three integers 0-255")
            kwargs["rgb"] = tuple(rgb)
        builder = PilotBuilder(**kwargs)
        await bulb.turn_on(builder)
        # Best-effort state readback; don't fail the operation if it times out
        try:
            state = await bulb.updateState()
            raw_rgb = state.get_rgb()
            return {
                "on": state.get_state(),
                "brightness": state.get_brightness(),
                "rgb": list(raw_rgb) if raw_rgb is not None else None,
            }
        except Exception:
            return {"on": True, "brightness": brightness, "rgb": rgb}
    except Exception as exc:
        raise WizConnectionError(f"Failed to reach bulb at {ip}: {exc}") from exc
    finally:
        await bulb.async_close()


async def _turn_off(ip: str) -> dict[str, Any]:
    """Turn the bulb off."""
    bulb = wizlight(ip)
    try:
        await bulb.turn_off()
        # Best-effort state readback; don't fail the operation if it times out
        try:
            state = await bulb.updateState()
            raw_rgb = state.get_rgb()
            return {
                "on": state.get_state(),
                "brightness": state.get_brightness(),
                "rgb": list(raw_rgb) if raw_rgb is not None else None,
            }
        except Exception:
            return {"on": False, "brightness": 0, "rgb": None}
    except Exception as exc:
        raise WizConnectionError(f"Failed to reach bulb at {ip}: {exc}") from exc
    finally:
        await bulb.async_close()


async def _set_brightness(ip: str, level: int) -> dict[str, Any]:
    """Set the bulb brightness (0-100)."""
    if not 0 <= level <= 100:
        raise ValueError("brightness must be 0-100")
    bulb = wizlight(ip)
    try:
        await bulb.turn_on(PilotBuilder(brightness=level))
        # Best-effort state readback; don't fail the operation if it times out
        try:
            state = await bulb.updateState()
            raw_rgb = state.get_rgb()
            return {
                "on": state.get_state(),
                "brightness": state.get_brightness(),
                "rgb": list(raw_rgb) if raw_rgb is not None else None,
            }
        except Exception:
            return {"on": True, "brightness": level, "rgb": None}
    except Exception as exc:
        raise WizConnectionError(f"Failed to reach bulb at {ip}: {exc}") from exc
    finally:
        await bulb.async_close()


# ── Public tool functions (synchronous wrappers) ─────────────────────────────
# Each wraps the async body in asyncio.run(...). This assumes these functions
# are never called from within an already-running event loop.


def list_lights() -> list[str]:
    """Return the friendly names from the config file. Pure read, no network call."""
    config = _load_config()
    return sorted(config.keys())


def get_light_state(name: str) -> dict[str, Any]:
    """Query the bulb for on/off state, brightness, and colour if available."""
    config = _load_config()
    ip = _get_ip(name, config)
    return asyncio.run(_get_bulb_state(ip))


def turn_on(
    name: str, brightness: int | None = None, rgb: list[int] | None = None
) -> dict[str, Any]:
    """Turn the bulb on, optionally setting brightness (0-100) and/or an RGB colour."""
    config = _load_config()
    ip = _get_ip(name, config)
    return asyncio.run(_turn_on(ip, brightness, rgb))


def turn_off(name: str) -> dict[str, Any]:
    """Turn the bulb off."""
    config = _load_config()
    ip = _get_ip(name, config)
    return asyncio.run(_turn_off(ip))


def set_brightness(name: str, level: int) -> dict[str, Any]:
    """Set the bulb brightness (0-100)."""
    config = _load_config()
    ip = _get_ip(name, config)
    return asyncio.run(_set_brightness(ip, level))
