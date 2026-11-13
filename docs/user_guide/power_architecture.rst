800 VDC power architecture
==========================

This study turns the 800 VDC migration question into four reusable calculations:
conversion accounting, a fixed-geometry conductor comparison, DC backup sizing,
and a limited fault-energy sensitivity screen. All presets are **illustrative**.
The default 5 MW hall is synthetic and does not reproduce an Envision installation
or validate any vendor's efficiency claim.

Run and replay
--------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.power_architecture --output outputs/power
   # Edit efficiencies, IT load, annual hours, energy price or backup assumptions:
   python -m datacenter_simulator.analysis.power_architecture \
     --inputs outputs/power/inputs.json --output outputs/power-replay

The core installation includes the offline Plotly report. The gallery additionally
requires ``.[docs]``. No credentials, downloads or GPU hardware are needed.

* :download:`Interactive report </_static/lab/power/power-architecture.html>`
* :download:`Replay inputs </_static/lab/power/inputs.json>`
* :download:`Architecture results </_static/lab/power/architectures.csv>`
* :download:`Stage losses </_static/lab/power/stages.csv>`
* :download:`Conductor results </_static/lab/power/conductors.csv>`
* :download:`SST efficiency sensitivity </_static/lab/power/efficiency_sensitivity.csv>`
* :download:`Backup minima </_static/lab/power/backup.json>`
* :download:`Fault assumptions </_static/lab/power/fault_assumptions.json>`
* :download:`Fault contributions </_static/lab/power/fault_contributions.csv>`
* :download:`Evidence ledger </_static/lab/power/evidence.json>`
* :doc:`Runnable gallery </gallery/analysis/plot_800vdc_architecture>`
* :doc:`API </reference/power_architecture>`

Conversion paths and boundaries
-------------------------------

All paths end at the **same low-voltage IT DC input**, before a common downstream
chip regulator. An SST block includes its internal conversion and isolation
losses: a single equipment block is not a single semiconductor conversion.

.. list-table:: Illustrative equipment paths, source to IT terminal
   :header-rows: 1
   :widths: 18 52 30

   * - Scenario
     - Equipment chain
     - Backup function
   * - Conventional AC
     - MV/LV transformer; AC UPS; rack AC/DC PSU
     - Battery at AC UPS
   * - 800 V sidecar
     - MV/LV transformer; AC UPS; sidecar AC/DC; rack DC/DC
     - AC UPS retained
   * - 800 V row
     - MV/LV transformer; AC UPS; row AC/DC; rack DC/DC
     - AC UPS retained in this preset
   * - Central 800 V SST
     - Aggregate MV AC-to-DC SST; rack DC/DC
     - Protected DC bus storage still required

Removing the standalone AC UPS cabinet does not remove the backup requirement.
Rectification and galvanic isolation also remain inside the appropriate equipment.
The row and sidecar presets have the same assumed efficiencies; only their
conversion-location descriptions differ. Actual distribution lengths, redundancy,
grounding, standby demand and load-dependent efficiency require site-specific data.

For each stage, reverse propagation gives:

.. math::

   P_{in,i} = P_{out,i}/\eta_i, \qquad
   P_{loss,i} = P_{in,i}-P_{out,i}, \qquad
   \eta_{path}=\prod_i\eta_i.

The output CSV retains every stage and verifies input minus IT demand minus losses.
Annual input energy is constant operating power times the specified operating hours;
it is not an hourly workload forecast. The energy-cost difference uses the user's
price per kWh in any consistently chosen currency. It excludes demand charges,
CAPEX, maintenance, replacement costs and financing, so it is not TCO or payback.
Cable and cooling losses are excluded from these totals; this ratio is not PUE.

Defaults assume transformer 99%, AC UPS 97%, rack rectifier 96.5%, sidecar/row
rectifier 98.5%, rack DC/DC 97.5%, and SST 97.5%. The sidecar can consume **more**
input energy in this example. The SST sweep includes worse-than-AC cases.
Break-even SST efficiency is ``AC path efficiency / rack DC/DC efficiency``.
A value above one means no feasible constant-efficiency SST can break even under
the specified assumptions. No generic 5% improvement is imposed.

Conductor calculation
---------------------

``compare_dc_conductors`` reuses :class:`~datacenter_simulator.methods.electrical.DCNetwork`
and ``DCBranch.copper_cable``. The separate example holds receiving power at 1 MW,
one-way length at 2 m, and each pole's cross-section at 1000 mm², at 20 °C.
Resistance includes both outgoing and return paths. The assumed current rating is
2000 A and overload warnings are retained.

Ideal ``P/V`` gives about 18,519 A at 54 V and 1,250 A at 800 V. The solver accounts
for voltage drop and :math:`I^2R` losses, so actual current is higher. Tests compare
its receiving voltage to the high-voltage root of
:math:`V_r^2 - V_s V_r + PR=0`.
This is a two-wire DC thought experiment, not an ampacity or copper-sizing design.
Three-phase AC line current would instead involve :math:`\sqrt{3}V_{LL}` and power
factor; the 54-to-800 V ratio must not be presented as an AC-to-DC copper saving.

Backup and hold-up
------------------

DC bus load includes rack DC/DC loss. For constant demand :math:`P` in kW,
outage duration :math:`t` in seconds, discharge efficiency :math:`\eta`, and
initially available SOC window :math:`u`:

.. math::

   E_{nominal,kWh} = \frac{Pt}{3600\eta u}, \qquad
   P_{storage,kW} = P/\eta.

Energy and power are separate constraints. The example sizes a 60-second battery
requirement and a separate 20 ms ideal capacitor hold-up from 800 to 720 V:

.. math::

   C = \frac{2(1000P)t}{V_{initial}^2-V_{minimum}^2}.

Tests replay the minimum battery through the existing ``dispatch`` implementation
and verify an undersized battery leaves unserved load. These minima omit ageing,
ESR/ESL, recharge, redundancy and auxiliary cooling. The two durations are not
combined into a hybrid controller. PV and BESS integration can use the existing
DC-grid and microgrid APIs; this study makes no chemistry-specific safety claims.

Fault energy: precisely what is calculated
------------------------------------------

The separate fault domain observes 20 ms at an initial 800 V. It contains a local
10 mF capacitor through 50 mΩ, optional remote 30 mF through 100 mΩ, a 2000 A
converter envelope and a 1000 A storage-converter envelope capped at 100 kJ.
Isolation times are assumed at 50 µs, 0.5 ms, 5 ms and 20 ms; they are not ratings
of a named fuse, switch or breaker. Ideal reverse blocking removes only the remote
capacitor path. The local load-side capacitor remains connected after upstream
isolation.

Each independent RC path releases:

.. math::

   E_{released} = \tfrac12 CV_0^2
     \left(1-e^{-2t/(RC)}\right).

Here :math:`t` is the smaller of observation and that path's isolation time; absent
isolation, it is the full observation. Remaining capacitor energy is exported.
Current-limited source contributions are **nominal-voltage energy envelopes**,
:math:`V_0 I_{limit}t`, capped by available bus-side energy when specified.
The combined quantity is labelled a **screening index**.

This is not a shared-bus transient solution or a guaranteed physical upper bound.
Current limiting is assumed immediate. Inductance, control delay, arc impedance,
clamp energy, restrikes, grounding and protection coordination are excluded.
There is no peak fault-current, I²t, arc-flash incident-energy, PPE, working-distance,
selectivity or certification result. A directly coupled battery needs a different
short-circuit model. A low screening value cannot establish that equipment is safe.

Evidence and interpretation
---------------------------

The checked source ledger is dated 2026-11-13. The
`NVIDIA architecture article <https://developer.nvidia.com/blog/nvidia-800-v-hvdc-architecture-will-power-the-next-generation-of-ai-factories/>`_
and `migration roadmap <https://blogs.nvidia.com/blog/800-vdc-power-architecture-ai-factory/>`_
motivate the equipment paths, not the numerical efficiencies. The
`Siemens/NVIDIA protection paper <https://assets.new.siemens.com/siemens/assets/api/uuid:cacbc29b-5d0d-4b12-9053-696eb0b43e74/Protections-for-Data-Centers-Powered-by-Direct-Current-Technical-Paper_original.pdf>`_
discusses multiple protection technologies, isolation and capacitor backfeed.
This simplified implementation does not reproduce that paper's simulated circuit.

`Schneider's publisher summary <https://www.se.com/ww/en/insights/ai-and-technology/artificial-intelligence/800-vdc-safety-in-ai-data-centers-understanding-the-real-arc-flash-risk/>`_
of WP219 motivates architecture-dependent fault studies. Its reported incident
energies are not transferred to this model. The
`UL 489I public catalog scope <https://www.shopulstandards.com/ProductDetail.aspx?UniqueKey=47564>`_
identifies an Outline of Investigation and includes galvanic isolation requirements
for the listed breaker categories. Neither an outline's existence nor a simulated
switching time establishes a particular product's certification or facility approval.

The input article's deployment forecasts, Ulanqab plant details and social-media
comments are not treated as independently verified measurements. Deployment and
certification dates are not hardcoded. The next validation step is manufacturer
loss maps and an independently benchmarked RLC/control/protection network, with
real isolation boundaries and documented fault-current behavior.
