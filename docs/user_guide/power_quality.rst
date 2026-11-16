Weak-grid power quality and E-STATCOM sizing
============================================

This workflow screens fast facility load swings using a balanced AC Thevenin
network, a reactive-only STATCOM, and a finite-energy E-STATCOM. It complements
the hourly dispatch and DC distribution models. It is a **quasi-static planning
model**, not PSCAD, an EMT solver, or a standards-compliant flickermeter.

Run and replay
--------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.power_quality --output outputs/power-quality
   python -m datacenter_simulator.analysis.power_quality \
     --inputs outputs/power-quality/inputs.json \
     --profile outputs/power-quality/profile_input.csv \
     --output outputs/power-quality-replay

Open ``power-quality.html`` for offline interactive plots, candidate screening,
and evidence boundaries. The output includes per-interval MW/Mvar, voltage,
energy, converter losses, saturation flags and energy-balance residuals. Inputs
and all 54 profile/grid/device candidate results are exported. A custom profile
must contain ``time_s,load_mw,load_mvar`` at uniform interval starts beginning at
zero. Every row, including the last, represents a full interval.

The load boundary is the **aggregate receiving PCC**, including downstream
facility consumption. No extra UPS/transformer loss is silently added. A profile
from the facility energy simulation must be converted from kW to MW and sampled
at appropriate resolution; interpolation of hourly data cannot recover genuine
subsecond workload fluctuations. There is no UPS battery dispatch in this case.

See :doc:`../gallery/analysis/plot_estatcom_power_quality` and
:doc:`../reference/power_quality`. Download the
:download:`offline report </_static/lab/power-quality/power-quality.html>`,
:download:`inputs </_static/lab/power-quality/inputs.json>`,
:download:`sizing results </_static/lab/power-quality/sizing.csv>` and
:download:`evidence ledger </_static/lab/power-quality/evidence.json>`.

Source case and evidence status
-------------------------------

The two user-supplied post screenshots describe a 200 MVA facility at 35 kV,
SCR 4, a 100 MVA E-STATCOM, supercapacitor H = 4.52 s, and a double-conversion
UPS with its battery disabled. They report:

.. list-table:: External reported results, not reproduced here
   :header-rows: 1

   * - Metric
     - Without support
     - With support
   * - Short-term flicker Pst
     - 11.3
     - 4.67
   * - PCC active-power peak-to-peak swing
     - 99.7 MW
     - 55.5 MW

The raw client profile, PSCAD project, meter validation, exact controller,
phase waveforms, usable storage limits, author and canonical post URL are
unavailable. The evidence ledger records screenshot hashes and missing inputs.
The example's sinusoidal/burst load shapes, X/R = 10, source voltage 1.05 pu,
controller settings, efficiencies and SOC window are **synthetic assumptions**.
The screenshot author/vendor is not attributed to Siemens Energy.

The stated H does not establish its energy or power base. Only **if**
H = E_nom / S_converter does 4.52 s at 100 MVA imply 452 MJ = 125.56 kWh.
The illustrative SOC range 0.1 to 0.9 allows 361.6 MJ of total operating swing.
At initial SOC 0.5, only 180.8 MJ is available for discharge before losses.
This is short-duration buffering, not hours of backup energy.

Network and controller equations
--------------------------------

All P/Q/S quantities are balanced three-phase totals. Nominal line-to-line
voltage and three-phase MVA define the impedance base:

.. math::

   S_{sc}=SCR\,S_b, \qquad Z_b=V_{LL,b}^2/S_b,
   \qquad |Z_{pu}|=1/SCR.

The receiving bus solves the high-voltage root of the constant-PQ two-bus
circuit. With ``s=(P+jQ)/S_b``, ``z=R+jX`` and source voltage ``e``:

.. math::

   y^2 + (2\operatorname{Re}(z s^*)-e^2)y + |z s|^2=0,
   \qquad y=|V|^2.

The complex voltage is recovered from ``V=(y+conj(z)*s)/e``. Grid source power
includes ``z*|s|²/y`` losses; PCC power excludes upstream losses. Both swings
are exported. No positive root raises an infeasibility error; sizing retains
that case as failed. This is an algebraic solvability test, not stability proof.

The sampled load filter starts at the first load and updates with
``alpha=1-exp(-dt/tau)``. The filtered state at each interval end is used as the
interval's held grid-power target. Requested injection is:

.. math::

   P_{req}=P_{load}-P_{filtered}+(E-E_{initial})/\tau_{recovery}.

Positive P discharges the capacitor into the PCC. Active power is limited by
its rating, current energy, efficiency and duration before allocating Q.
Reactive control solves the algebraic droop equation with remaining capacity:

.. math::

   Q_{inj}=\operatorname{clip}\left(K_v(V_{ref}-|V|),
                  -\sqrt{S_{rated}^2-P_{inj}^2},
                   \sqrt{S_{rated}^2-P_{inj}^2}\right).

Thus rising voltage commands less injection or more absorption. Low voltage
commands injection. The converter uses **P priority** and an apparent-power
circle, not a voltage-dependent current-limit or switching model. Reported
saturation flags reveal unmet commands; Q-only operation still has its full
reactive rating when stored energy is zero.

Energy uses MJ and MW seconds:

.. math::

   E_{k+1}=E_k-\left(P_{inj}+P_{loss}\right)\Delta t,

where discharge losses are ``P*(1/eta_discharge-1)`` and charging losses are
``(-P)*(1-eta_charge)``. Reactive/standby converter losses are excluded. The
initial and terminal inventory are exported; a nonzero depletion is not free
energy or a sustainable operating saving. Long-duration mean-load increases
ultimately pass through to the grid even when the initial step is smoothed.

The ideal benchmark adds a second identical voltage-source phasor behind
``Z_aux=ratio*Z_grid``. The equivalent impedance is their parallel combination;
original-grid and auxiliary-source powers are kept separate. This checks the
physics of a stronger, actively supplied bus. Its unbounded sustained energy
makes it unsuitable as a realizable storage sizing result.

Sizing and failure cases
------------------------

The default sweep considers 25/50/100 MVA and 50/225/452 MJ independently,
SCR 2/4/8, and the input plus a second bursty load shape. Targets of 60 MW PCC
swing and 0.025 pu voltage excursion are **illustrative screens**, not utility
limits or Pst targets. A candidate passes only when all tested cases pass.
All failed and infeasible cases remain visible. There is no cost ranking or
global minimum claim. Add representative measured profiles, more sizes,
controller variants and actual utility limits before making a design decision.

A separate 80-to-180 MW sustained-step stress case exposes finite buffering.
It is labelled and excluded from the pulse-sizing envelope. All candidates
can fail a more demanding envelope; that result must not be hidden.

Flicker: import results instead of relabelling voltage variation
----------------------------------------------------------------

IEC 61000-4-15 specifies the flickermeter. IEEE 1453-2022 covers flicker
measurement, planning/emission limits and assessment. A voltage peak-to-peak
range or RMS statistic is not Pst. The balanced model also cannot reveal
phase-specific unbalance or waveform distortion.

To retain the supplied study's three line-to-line assessment, import externally
computed results using ``--flicker results.csv``. Required columns are:

``case,window_start_s,duration_s,channel,pst,meter,waveform_reference``.

Each case/window requires exactly AB, BC and CA; duration must be 600 seconds,
Pst must be finite/nonnegative, and meter/version and waveform references must
be present and consistent. The importer reports the maximum and its channel.
It rejects positive-sequence-only, missing and duplicate channel sets. The
importer does not verify the external meter's standard test vectors, scaling,
frequency, transformer response, settling, source waveforms or compliance.
The appropriate measurement wiring for other installations requires an explicit
study specification; three line-to-line channels are not prescribed universally.

Validation and next evidence needed
-----------------------------------

Tests check Kirchhoff's voltage/power balances, a resistive analytical root,
load-flow failure, Q sign, P-Q limits, energy conservation, charging/discharging
bounds, zero-energy STATCOM behavior, auxiliary-source energy, sustained load,
timestep sensitivity, failed sizing candidates and complete line-to-line Pst
aggregation. These are numerical verification, not measured validation.

For PSCAD benchmarking, obtain the original timestamped load/voltage/power
traces, circuit and controller parameters, H definition and storage voltage
limits. Compare the same boundaries and windows, export errors, and test meter
responses independently. Fast UPS/rectifier/DC-link interactions, PLL dynamics,
harmonics, unbalance, switching, protection and frequency stability need EMT or
appropriate validated dynamic models.

Primary references
------------------

* `Siemens Energy E-STATCOM for data centers <https://assets.siemens-energy.com/dam/59ee537b-fec7-4d97-b8a4-b2c000c4147c/2025_04_09_ST1835a-008_Broschuere-E-STATCOM_for_Data_Centers_A4_Screen-pdf_Original%20file.pdf>`_:
  architectural motivation for supercapacitor active support and reactive control.
* `IEC 61000-4-15:2010 <https://webstore.iec.ch/en/publication/4173>`_:
  public flickermeter scope; the full normative implementation is not reproduced.
* `IEEE 1453-2022 <https://standards.ieee.org/ieee/1453/10459/>`_:
  public scope of voltage fluctuation/flicker assessment.
