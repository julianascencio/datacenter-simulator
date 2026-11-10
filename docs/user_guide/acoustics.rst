3D noise and acoustic design
============================

The acoustic studio calculates octave-band sound-pressure levels in three
dimensions, receiver LAeq, source contributions and conditional input-uncertainty
intervals. It compares source treatment and room absorption with the same
equipment layout. It is an engineering energy-propagation model, not a wave
solver or a substitute for measured facility validation.

Run and inspect
---------------

.. code-block:: bash

   datacenter-noise --output outputs/noise
   # Edit noise-0-inputs.json, then rerun:
   datacenter-noise --inputs outputs/noise/noise-0-inputs.json --output outputs/custom-noise
   # Match receiver names and operating conditions to independent observations:
   datacenter-noise --inputs outputs/noise/noise-0-inputs.json --measurements measurements.csv

Open ``outputs/noise/noise-3d.html``. Select a scenario, A-weighted level or an
individual octave band, receiver, horizontal height and vertical section.
Shared color scales allow direct comparison. Source near fields are masked.
The viewer explores completed simulations; changing inputs requires rerunning
Python. No network is needed to open the report.

`Open acoustic studio <../_static/lab/noise/noise-3d.html>`_ ·
:doc:`Runnable example <../gallery/analysis/plot_noise_3d>` ·
:doc:`API <../reference/acoustics>`

Input contract
--------------

* Supply **unweighted octave-band sound power** in dB re 1 pW at nominal centres
  63, 125, 250, 500, 1000, 2000, 4000 and 8000 Hz. Do not enter a sound-pressure
  rating at an unspecified measurement distance or split one overall dBA number
  into fabricated bands. Each source carries a provenance field.
* Give source coordinates, a conservative excluded near-field radius, directivity
  factor Q, operating duty fraction and any measured source insertion loss.
  Duty is an energy average over a common observation period; no startup peaks,
  waveforms or tonal phase are inferred.
* ``room`` mode requires six surface absorption spectra: x=0, x=L, y=0, y=W,
  floor and ceiling. Area-weighted absorption controls the diffuse contribution.
  Uniform-field approximations are weak for strongly nonuniform absorption.
* ``free_field`` mode omits reverberation. It does not add terrain, ground
  interference, weather refraction, barriers or building facade transmission.
* Relative humidity is **percent**, e.g. 70, not 0.7. Temperature is °C, pressure
  kPa and coordinates metres. Background is an optional unweighted receiver
  sound-pressure spectrum, assumed spatially uniform and fixed.
* The optional planning criterion is user-defined. It is not a jurisdictional
  compliance limit, hearing-exposure assessment or noise rating classification.

The example spectra, 75 dBA target, source treatment and absorption improvements
are illustrative assumptions, not product ratings or measured site data.

Physics and calculation
-----------------------

Each source's band sound power is converted to watts. For a receiver distance r,
the direct gain is :math:`G_d=Q/(4\pi r^2)\,10^{-\alpha r/10}`, where atmospheric
absorption :math:`\alpha` is in dB/m. The optional room term is

.. math::

   G_r = \frac{4}{S\bar a/(1-\bar a)+4mV},\qquad
   m=\alpha\ln(10)/10.

S is total room surface area, V volume and :math:`\bar a` area-weighted absorption.
The energy sum is converted to pressure with :math:`p^2=\rho c\sum W(G_d+G_r)`;
the report uses a 20 µPa pressure reference. The dry-air impedance approximation
uses the specified temperature and pressure. Directivity affects the direct
term only, avoiding multiplication of total reverberant source power by Q.

Atmospheric coefficients follow the ISO 9613-1 analytical equations, evaluated
at exact base-10 octave centres corresponding to the displayed nominal labels.
This is a band-centre approximation, not integration of each band spectrum.
The implementation is not a complete ISO 9613-2 outdoor compliance method.

Band energies and independent sources are summed logarithmically; tabulated
A-weighting corrections produce LAeq. Correlated tones require phase-aware
calculations and are outside this model. Sabine and Eyring RT60 estimates and
an approximate Schroeder transition identify bands where diffuse-room reasoning
may be inappropriate. The room model does not resolve standing-wave modes.

Uncertainty and measured validation
-----------------------------------

Monte Carlo draws use independent Gaussian offsets for different sources,
perfect correlation across each source's bands, and a common propagation offset
across all sources and receivers. The fixed seed makes comparisons reproducible.
The 2.5–97.5 percentile interval is conditional on these declared input errors.
It omits uncertain geometry, absorption, background, tonal structure and model
discrepancy; it must not be described as total predictive accuracy.

The measurements CSV requires ``receiver,observed_dba``. Receiver names and
operating periods must match. The command exports signed bias, MAE, RMSE,
maximum absolute error and per-receiver residuals. It does not fit on those
observations or quietly claim experimental validation. Use held-out observations
after any calibration, and document instrument and operating uncertainty.

Bridge to the thermal design
----------------------------

.. code-block:: python

   from datacenter_simulator.models.acoustics import AcousticReceiver
   from datacenter_simulator.use_cases.acoustics import noise_from_cfd
   from datacenter_simulator.use_cases.cfd import reference_cfd_case

   thermal = reference_cfd_case()
   # Replace these illustrative spectra with independently sourced Lw data.
   spectra = {rack.name: (65, 70, 75, 79, 81, 79, 75, 70) for rack in thermal.sources}
   acoustic = noise_from_cfd(
       thermal, spectra, (AcousticReceiver("Aisle", 1, 3, 1.5),),
       provenance="illustrative example; not measured",
   )

Only geometry is shared. Thermal watts and steady CFD gauge pressure cannot
provide sound-power spectra or acoustic pressure fluctuations. Noise generation
by fans and ducts requires acoustic source data or an appropriate aeroacoustic
model; that physics is not inferred here.

Exports and verification
------------------------

Each scenario exports inputs/summary JSON, receiver/source/room/cell CSVs,
full octave arrays in NPZ, and LAeq plus a validity mask in VTK for ParaView.
NPZ scalar field dimensions are x,y,z; octave fields append an eight-band axis.
The VTK point ordering is x-fastest, at cell-centre coordinates.

Tests check the 6.0206 dB distance-doubling law, 3.0103 dB addition of identical
incoherent sources, directivity, duty and insertion loss, independent published
atmospheric coefficients, room-constant limits, near-field exclusions,
uncertainty reproducibility and held-out measurement comparison.
Map sampling density changes visualization resolution, not propagation physics.
Receiver values are evaluated at their exact coordinates.

References
----------

* `ASHRAE Handbook: Sound and Vibration
  <https://handbook.ashrae.org/Handbooks/F17/IP/f17_ch08/f17_ch08_ip.aspx>`_:
  sound-power/pressure distinction, energetic addition and direct/diffuse fields.
* `ISO 9613-1 <https://www.iso.org/standard/17426.html>`_: atmospheric absorption.
* `SPM9613 user manual, section 3.9 <https://www.poweracoustics.com/UsersMan.pdf>`_:
  independent 20 °C, 70% RH reference coefficients used by tests.
