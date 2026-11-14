BESS value and resilience
========================

Use case and evidence
---------------------

The attached post about RENMAD/ATA Insights' **BESS for data centers: power,
resilience & renewables** motivates three separate questions: operating cost,
critical-load continuity and fast power buffering. The
`organizer's event page <https://my.atainsights.com/en/webinar/webinar-bess-for-data-centers-power-resilience-renewables/>`_
focuses on Italy. This example instead explores the post's mainland-Spain
commercial question using an explicitly fictional facility. It does not claim
to reproduce the webinar, validate its participants' systems or establish that
Spanish data centers make BESS profitable without support.

Energy Data Insights integration
--------------------------------

The solar inputs were actually retrieved with the published
``energy-data-retrieval==0.1.0`` package's
``energy_data_retrieval.sources.pvgis.PVGISClient.hourly`` connector, not generated
with a sine curve. The source is European Commission JRC PVGIS 5.3, Madrid
40.4168 N, 3.7038 W, 2023, 1 kWp, 30-degree tilt, south-facing, 14% system loss.
The packaged 168-row snapshot covers 15–21 June and scales provider P in W to
kW per kWp. Source inputs, metadata, request record, raw-response hash and CSV
hash are in ``data/bess_madrid_pvgis.json``. The loader verifies the CSV hash.

PVGIS values are **modelled output, not measured meter data**. The original
UTC ten-minute timestamp offset is retained. For this screening, each value
represents constant power for the following one-hour step; this modelling
assumption is not a statement that the provider measured interval energy.
The same timestamp axis aligns all inputs. Synthetic tariff/load patterns use
Europe/Madrid civil hours. No 2026 weather or market observations are claimed.

EDI also informs the economic boundary: its
`REE adjustment-cost analysis <https://github.com/julianascencio/energy-data-insights/blob/main/docs/ree-adjustment-bess.md>`_
explains why system-wide adjustment revenues and differently weighted price
averages cannot be treated as accessible battery revenue. This study therefore
assigns **zero ancillary-service revenue and zero subsidies**, and does not
subtract those published REE prices to invent a trading spread. Licensed hourly
prices, contracted charges and eligibility evidence are still required for a
real Spanish investment decision.

Reproduce offline::

    python -m pip install -e '.[docs]'
    python examples/analysis/plot_bess_value.py
    python -m pytest tests/test_bess_value.py

The :doc:`../gallery/analysis/plot_bess_value` exports comparison, dispatch and
334 outage-sweep rows under ``outputs/bess-value``. No private EDI repository
credential or live service is required for execution. For an explicit live
refresh on Python 3.12+, install ``.[edi]`` and call
``retrieve_edi_pvgis_year(path)``. It preserves native responses and provenance
separately; it never silently replaces the reviewed offline snapshot.

Model and accounting
--------------------

* A synthetic 2.5–4 MW facility demand already includes cooling and auxiliaries;
  PUE must not be applied a second time. PV is assumed at 6 MWp.
* Storage is an assumed 3 MW / 6 MWh system, with the existing ``Battery`` model
  defining asymmetric efficiencies and physical SOC limits. Neither rating,
  efficiency nor lifetime is inferred from a project catalogue.
* MILP minimizes import energy, one horizon-wide peak charge and variable
  discharge wear. The illustrative peak rate is EUR 2/kW **per modelled week**,
  not a regulated Spanish tariff or a monthly price charged every hour.
* Binary modes prevent simultaneous charging/discharging, including at negative
  prices. Grid charging is allowed; exports and load shedding are disallowed.
  All power is at the AC facility bus. Energy conservation includes conversion
  losses. Initial SOC equals final SOC, excluding free inventory depletion.
* The economic and reserve cases have identical 80% initial/final SOC and differ
  only in the normal-operation reserve floor (10% versus 80%). The reserve is
  released to the physical 10% minimum during an independent outage replay.
* The counterfactual is the same load, PV and prices without BESS. If its peak
  exceeds the connection limit, ``baseline_exceeds_connection`` flags a service
  mismatch: cost differences alone then cannot establish a comparable saving.
* Reduced PV curtailment is reported, but no renewable provenance is assigned to
  battery discharge: grid charging and initial inventory can have mixed origins.
* The normal schedule has perfect price/load/solar foresight. Its achievable
  savings are an optimistic benchmark before forecast error and operating limits.

Resilience and rapid fluctuations
--------------------------------

Each two-hour outage begins with the corresponding pre-step SOC from normal
operation. The 167 complete starts are tested for each policy, with assumed
1.5 MW critical load and zero PV as a conservative stress. These start times
are not an outage probability distribution; the served fraction is not an
availability, Tier, SLA or loss-of-load probability claim. Baseline without
BESS loses 3 MWh per stress event. No avoided-outage revenue is added to energy
savings. Islanding, grid-forming controls and instantaneous transfer are assumed
available, not established by the energy-balance calculation.

The separate one-second load-step calculation reports ideal bidirectional BESS
power and the minimum lossless energy swing for a chosen grid ramp limit. It
includes the cumulative energy trajectory and initial headroom requirement.
It does not simulate voltage, frequency, reactive power, inverter control delay,
thermal limits or protection. Hourly energy scheduling cannot validate any of
those fast phenomena.

Commercial interpretation
-------------------------

The example week gives approximately EUR 8,519 economic-policy operating saving
versus EUR 1,967 with the 80% reserve, after the assumed variable wear charge.
The reserve covers all tested 1.5 MW/two-hour stresses; the economic policy can
leave the full 3 MWh unserved. These are **scenario outputs**, not observed site
results or annual forecasts. PV/weather seasonality and long outage tails matter.

The break-even function discounts independently supplied annual operating
savings less fixed O&M. The gallery uses explicit annual sensitivities rather
than multiplying a summer week by 52. It excludes replacements, taxes,
financing and salvage. A real no-subsidy business case requires full-year local
load/PV/prices, a vendor quotation and degradation/replacement model, actual
contract/network charges, and validated control/backup requirements.

API
---

.. automodule:: datacenter_simulator.models.bess_value
   :members:

.. automodule:: datacenter_simulator.connectors.edi_bess
   :members:

.. automodule:: datacenter_simulator.methods.bess_value
   :members:

.. automodule:: datacenter_simulator.analysis.bess_value
   :members:

.. automodule:: datacenter_simulator.use_cases.bess_value
   :members:
