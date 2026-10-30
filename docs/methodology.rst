Model boundaries and equations
======================================

This page describes the original radial ``DCNetwork`` / ``simulate`` workflow.
For the complementary meshed DC, electrothermal, hydraulic, weather, dispatch,
contingency and workload methods added in 0.2, see :doc:`user_guide/engineering`.
Its exclusions below apply to this original workflow, not every package module.

Devices and electrical networks
---------------------------------------

``Electrical.power_kw(u)`` evaluates

.. math::

   P(u)=P_{idle}+(P_{peak}-P_{idle})u^a, \qquad 0\le u\le1.

Power is at the DC equipment terminal, including internal PSU and fan demand.
All terminal power becomes heat. Positions and dimensions are in metres. The
reference racks aggregate multiple servers; the model also accepts individual devices.

The electrical solver is a **resistive direct-current load flow**, distinct from
the so-called DC approximation for AC transmission networks. It supports one
regulated source and a radial tree of constant-power loads, cables and regulated
DC/DC converters. A backward demand sweep and forward voltage sweep converge
to a high-voltage operating point:

.. math::

   I=P_{receive}/V_{receive},\qquad
   V_{receive}=V_{send}-IR,\qquad P_{loss}=I^2R.

Units are converted internally between kW and W. Cable resistance includes both
conductors. Copper convenience calculations use 0.01724 ohm mm²/m at 20°C and
0.00393/K temperature coefficient (NBS copper wire tables). Cable ampacity is an
input; installation methods and thermal derating are not inferred. Converters
use constant efficiency or an optional bounded ``ConverterMap`` and reset the
receiving bus to its nominal voltage.

Overcurrent, power rating and undervoltage conditions are reported. Voltage
collapse, nonconvergence, unknown nodes, parallel parents and disconnected
topologies raise errors. A 380/400/800 V comparison is possible by changing the
source distribution voltage; the reference equipment terminals remain at 48 V.
These are illustrative configurations, not certification to an OCP specification.

Excluded: AC faults/reactive power, DC arc or protection coordination, ground
faults, bipolar pole imbalance, converter control dynamics, harmonic studies,
meshed load flow and active A/B electrical source sharing. Ratings do not trip
automatically; this is a demand study, not a protection simulator.

Communications
----------------------

Links are full duplex. Each traffic demand takes one shortest baseline-latency
path. Offered traffic is accumulated separately in each direction and compared
with link capacity. Failed links or nodes can be supplied to test rerouting and
disconnection. Per-packet serialization time is added to propagation/processing
delay to produce a latency **lower bound**. No queuing, packet loss, ECMP, protocol
emulation or coupling between network throughput and IT utilization is implied.
Device port counts and rates are checked against the graph.

Cooling and heat rejection
----------------------------------

Presets cover DX/CRAC, chilled water/CRAH, rear-door heat exchangers,
direct-to-chip with CDU, and single-phase immersion. The configurable thermal
capacity bounds removed heat; excess heat is explicitly reported.

.. math::

   Q_{liquid}=f_{liquid}Q_{removed},\quad
   Q_{air}=(1-f_{liquid})Q_{removed},\quad
   P_{cool}=Q_{liquid}/COP_{liquid}+Q_{air}/COP_{air}+P_{aux}.

The liquid compressor term becomes zero when the optional idealized **dry-cooler**
economizer can meet supply temperature plus approach. Residual air cooling still
needs mechanical cooling. Chilled-water capture represents heat at the CRAH coil,
not direct-to-chip capture. Fan/pump demand uses a 20% operating floor plus a
cubic part-load term, scaled by rated thermal capacity. This is an illustrative
affinity-law surrogate, not a calibrated fan or pump curve. Air-cooled heat
rejection is assumed: no evaporative water consumption is calculated.

.. math::

   Q_{rejected}=Q_{removed}+P_{cool},\quad
   \dot m=Q_{liquid}/(c_p\Delta T),\quad
   \dot V_{air}=Q_{air}/(\rho_{air}c_{p,air}\Delta T_{air}).

The COP ambient adjustment is linear, bounded for numerical robustness. Preset
coefficients, capacities, capture fractions and coolant properties are assumptions;
they are not measured manufacturer data or claims of universal technology ranking.
The reference keeps IT power identical across technologies to isolate facility
cooling effects; reductions in internal server fan power are not credited.

``ThermalZone`` separately integrates a well-mixed thermal mass with a constant
envelope conductance using an analytical exponential step. It is demonstrated
for a cooling failure. The main steady-state simulation does not integrate room
temperature. No CFD, rack hotspots, humidity, dewpoint control, condensation,
hydraulic pressure drop or two-phase immersion physics is modeled.

Facility, generation and storage boundary
-------------------------------------------------

.. math::

   P_{facility}=P_{DC\ source}/\eta_{rectifier}+P_{cool}+P_{other},\quad
   PUE=\frac{\sum_tP_{facility,t}\Delta t}{\sum_tP_{IT,t}\Delta t}.

DC losses can be partly or wholly inside the conditioned space. Rectifier,
battery and other auxiliary losses are outside that space in this model.
PUE uses **gross demand before generation and storage**, not grid import, and
excludes battery charging and battery losses from the demand-study boundary.
It is not a certified operational PUE meter implementation.

Generation profiles supply available interval-average electrical power at the
common facility bus (AC-equivalent meter boundary). Apply conversion losses in
the adapter if the original power is upstream of an inverter. The internal DC
network remains fed through the modeled rectifier. The separate ``simulate_dc_microgrid`` and ``DCGrid`` APIs now support direct
DC-coupled generation and bidirectional multi-source resistive load flow;
see :doc:`user_guide/engineering` for their different boundaries.

Surplus generation charges the battery before export/curtailment. Deficits draw
from the battery, then the limited grid connection, then ideal backup capacity.
Remaining demand is unserved. Charge/discharge powers are at the facility bus;
SOC updates include their respective efficiencies. There is no simultaneous
charging/discharging. Dispatch is greedy self-consumption, not cost optimization.

.. math::

   P_{gen}+P_{dis}+P_{grid,in}+P_{backup}+P_{unserved}
   =P_{demand}+P_{charge}+P_{grid,out}+P_{curtailed}.

All timestamps must be timezone-aware, unique and increasing. Profiles use
regular intervals whose duration equals ``dt_hours``. A timestamp marks the
start of an interval; a row is the average over that interval. No final interval
is silently dropped. Missing/negative/non-finite generation fails validation.
Adapters never silently interpolate, fill gaps or reinterpret units.

Supply or cooling shortfalls leave requested demand unchanged and emit flags.
They do not predict served compute, actual temperatures, cascading failures or
automatic load shedding. Such scenarios are feasibility screens only.

Validation and maturity
-------------------------------

Tests include an independent analytical two-bus voltage solution, converter
input/output currents, multi-voltage conservation, voltage collapse and overloads,
directional traffic and rerouting, heat/fluid balances, thermal equilibrium,
randomized battery trajectories, exact SOC limits, time alignment, PUE boundaries
and report generation. Numerical invariants do not establish real-world accuracy.
Measured facility validation and vendor calibration remain open. The advanced
DC solver has an optional independent PyPSA comparison; see
:doc:`research/engineering` for exactly what is checked.

This initial implementation was substantially AI-generated from the stated
requirements, physical balances and the references listed here. It may contain
errors; model assumptions and outputs should be reviewed as the project matures.
