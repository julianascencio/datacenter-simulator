Connect electricity generation
======================================

The integration boundary is a pandas Series of interval-average **electrical
power**. It works with measured datasets or outputs from generation simulators,
including PV, wind, biogas, fuel cells and other X-to-electricity processes.
Available power is separate from the optional dispatchable backup capacity.

CSV contract
--------------------

.. code-block:: text

   timestamp,power_kw
   2026-01-01T00:00:00+00:00,35.0
   2026-01-01T01:00:00+00:00,36.5

.. code-block:: python

   from datacenter_simulator.connectors import generation_from_csv
   from datacenter_simulator import simulate
   from datacenter_simulator.use_cases import reference_center, reference_profiles

   profiles, _ = reference_profiles(hours=2)
   biogas = generation_from_csv("biogas.csv", profiles.index)
   result = simulate(reference_center(), profiles, generation={"Biogas": biogas})

Series contract
-----------------------

Use an output Series from your generation model. This example converts watts
upstream of a 97% inverter into facility-bus kW:

.. code-block:: python

   from datacenter_simulator.connectors import generation_from_series

   pv_at_facility = generation_from_series(
       model_output_w, profiles.index, unit="W", conversion_efficiency=0.97
   )
   result = simulate(center, profiles, generation={"PV": pv_at_facility})

If the source is already AC power after its inverter, use efficiency 1 to avoid
double-counting losses. For a biogas/X-to-power process, use **net electrical
output after process auxiliaries** at the integration boundary. Export the
relevant Series from ``x2power-simulator`` or another simulator; this package
does not depend on or assume any unverified package-specific output API.

Weather or instantaneous PV samples must first be converted to interval-average
generation using an appropriate external model and resampling method. Different
interval lengths cannot be made consistent by merely relabeling timestamps.

For ``orbitalpv`` outputs, additionally model transmission, receiver and
conversion efficiencies before treating orbital power as terrestrial supply.
The adapter does not assume that satellite-generated power arrives at a data center.

Generation CSVs must cover exactly the same intervals as demand. Offset-aware
timestamps are converted to the simulation timezone, but gaps and duplicate
timestamps raise errors. W, kW and MW are accepted explicitly.
