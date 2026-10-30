"""Optional pvlib adapter with explicitly separate array DC and inverter AC power."""

import pandas as pd

from datacenter_simulator.connectors.weather import validate_weather
from datacenter_simulator.models.devices import finite, fraction


def pv_from_weather(
    weather: pd.DataFrame,
    *,
    latitude: float,
    longitude: float,
    dc_rating_kw: float,
    tilt_deg: float = 25,
    azimuth_deg: float = 180,
    inverter_efficiency: float = 0.96,
) -> pd.DataFrame:
    """PVWatts DC/AC chain; explicit weather inputs and no network requests.

    Requires the ``solar`` extra. Output ratings and weather are illustrative
    system assumptions unless supplied with site-specific equipment evidence.
    """
    try:
        from pvlib.location import Location
        from pvlib.modelchain import ModelChain
        from pvlib.pvsystem import PVSystem
        from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS
    except ImportError as error:
        raise ImportError(
            "PV modelling requires pip install 'datacenter-simulator[solar]'"
        ) from error
    validate_weather(weather)
    finite("dc_rating_kw", dc_rating_kw, strict=True)
    finite("latitude", latitude, -90)
    finite("longitude", longitude, -180)
    finite("tilt_deg", tilt_deg)
    finite("azimuth_deg", azimuth_deg)
    if latitude > 90 or longitude > 180 or tilt_deg > 90 or azimuth_deg > 360:
        raise ValueError("invalid solar geometry")
    fraction("inverter_efficiency", inverter_efficiency, positive=True)
    columns = {
        "ghi_w_m2": "ghi",
        "dni_w_m2": "dni",
        "dhi_w_m2": "dhi",
        "ambient_c": "temp_air",
        "wind_speed_m_s": "wind_speed",
    }
    if not set(columns) <= set(weather):
        raise ValueError("PV weather needs irradiance components and wind speed")
    inputs = weather[list(columns)].rename(columns=columns)
    if (inputs[["ghi", "dni", "dhi", "wind_speed"]] < 0).any().any():
        raise ValueError("irradiance and wind cannot be negative")
    system = PVSystem(
        surface_tilt=tilt_deg,
        surface_azimuth=azimuth_deg,
        module_parameters={"pdc0": dc_rating_kw * 1000, "gamma_pdc": -0.004},
        inverter_parameters={"pdc0": dc_rating_kw * 1000, "eta_inv_nom": inverter_efficiency},
        temperature_model_parameters=TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_glass"],
    )
    model = ModelChain(
        system, Location(latitude, longitude), aoi_model="physical", spectral_model="no_loss"
    )
    model.run_model(inputs)
    return pd.DataFrame(
        {"pv_dc_kw": model.results.dc / 1000, "pv_ac_kw": model.results.ac / 1000},
        index=weather.index,
    )
