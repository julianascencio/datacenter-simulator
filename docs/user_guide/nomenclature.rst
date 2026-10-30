Nomenclature and units
==============================

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Term
     - Meaning in this package
   * - DC
     - Direct current; resistive DC load flow, not an AC-network approximation.
   * - IT
     - Computing and networking equipment; terminal power becomes heat.
   * - CRAC / CRAH
     - Computer room air conditioner / computer room air handler.
   * - CDU
     - Coolant distribution unit, included in a lumped cooling alternative.
   * - COP
     - Heat removed divided by cooling electricity, with the chosen component boundary.
   * - PUE
     - Gross facility energy demand divided by IT energy demand, before generation/storage.
   * - BESS / SOC
     - Battery energy storage system / state of charge.
   * - pu
     - Per-unit value, relative to a defined nominal value or rating.
   * - kW / kWh
     - Power / energy. A row contains average power during its interval.
   * - Gbps / ms
     - Communication rate / latency; latency excludes queueing.
   * - kg/s / m³/s
     - Liquid mass flow / air volumetric flow.
   * - UTC
     - Reference-example timezone. Input timestamps must be timezone-aware.

Lengths are metres and conductor areas are mm². Cable resistance includes both
outgoing and return paths. Temperature differences use kelvin; absolute ambient
and supply temperatures are expressed in degrees Celsius.
