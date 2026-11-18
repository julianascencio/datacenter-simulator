"""Validated inputs for paper-informed speed-to-power screening studies."""

from dataclasses import dataclass

from datacenter_simulator.models.devices import finite, fraction


@dataclass(frozen=True)
class ComputeFleet:
    """H100 node-equivalent defaults from Newkirk et al., S1.1 (not new hardware)."""

    gpu_count: int = 100000
    gpus_per_node: int = 8
    average_node_kw: float = 7.3
    peak_node_kw: float = 8.5
    contingency: float = 1.05

    def __post_init__(self) -> None:
        for name in ("gpu_count", "gpus_per_node"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.gpu_count % self.gpus_per_node:
            raise ValueError("GPU count must describe complete nodes")
        finite("average_node_kw", self.average_node_kw, strict=True)
        finite("peak_node_kw", self.peak_node_kw, self.average_node_kw)
        finite("contingency", self.contingency, 1)

    @property
    def average_it_kw(self) -> float:
        return self.gpu_count / self.gpus_per_node * self.average_node_kw

    @property
    def peak_it_kw(self) -> float:
        return self.gpu_count / self.gpus_per_node * self.peak_node_kw


@dataclass(frozen=True)
class PowerProject:
    """Constant real-dollar costs; energy is delivered at IT + cooling terminals.

    Annual energy/costs describe a repeated design year, not a weather ensemble.
    Replacement occurs after ``replacement_age_years`` operational years.
    """

    name: str
    deployment_years: float
    capital_usd: float
    annual_operating_usd: float
    annual_delivered_kwh: float
    replacement_usd: float = 0
    replacement_age_years: float = 13

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("project name is required")
        for name in ("deployment_years", "capital_usd", "annual_operating_usd", "replacement_usd"):
            finite(name, getattr(self, name))
        finite("annual_delivered_kwh", self.annual_delivered_kwh, strict=True)
        finite("replacement_age_years", self.replacement_age_years, strict=True)


@dataclass(frozen=True)
class SpeedPowerInputs:
    """Editable synthetic scenario, with source-based fleet and financial defaults.

    PV/BESS factors are explicit conservative design-year derates, not a
    calibrated ageing model. No currency conversion or escalation is inferred.
    """

    gpu_count: int = 100000
    discount_rate: float = 0.07
    horizon_years: int = 27
    gpu_hour_value_usd: float = 2.4
    compute_ready_year: float = 0
    minimum_uptime: float = 0.99
    solar_deployment_years: float = 2
    gas_deployment_years: float = 4
    grid_deployment_years: float = 5
    pv_retained_fraction: float = 0.858
    battery_retained_fraction: float = 0.8
    ac_pv_usd_per_kw: float = 1000
    dc_pv_usd_per_kw: float = 800
    battery_usd_per_kwh: float = 150
    battery_replacement_usd_per_kwh: float = 80
    solar_om_fraction: float = 0.02
    gas_usd_per_kw: float = 1500
    gas_heat_rate_mmbtu_per_mwh: float = 8
    gas_usd_per_mmbtu: float = 5
    gas_variable_om_usd_per_kwh: float = 0.005
    gas_fixed_om_usd_per_kw_year: float = 20
    grid_usd_per_kw: float = 150
    grid_usd_per_kwh: float = 0.07

    def __post_init__(self) -> None:
        ComputeFleet(gpu_count=self.gpu_count)
        if isinstance(self.horizon_years, bool) or not isinstance(self.horizon_years, int):
            raise ValueError("horizon_years must be an integer")
        finite("horizon_years", self.horizon_years, strict=True)
        for name in ("minimum_uptime", "pv_retained_fraction", "battery_retained_fraction"):
            fraction(name, getattr(self, name), positive=True)
        for name in self.__dataclass_fields__:
            finite(name, getattr(self, name))
        for name in ("solar_deployment_years", "gas_deployment_years", "grid_deployment_years"):
            if getattr(self, name) >= self.horizon_years:
                raise ValueError("deployment must precede the common horizon")
        if self.compute_ready_year >= self.horizon_years:
            raise ValueError("compute readiness must precede the common horizon")
