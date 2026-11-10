3D airflow and heat CFD
=======================

The native CFD solver calculates three velocity components, pressure and air
temperature through time on a three-dimensional Cartesian mesh. It connects
rack geometry and heat loads to a room-air flow calculation and an offline
interactive field viewer. It uses NumPy/SciPy; OpenFOAM is not required or called.

Run the simulator
-----------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.cfd --mesh-study --output outputs/cfd
   # Equivalent installed entry point:
   datacenter-cfd --grid 30 24 15 --seconds 180 --flow 2 --output outputs/cfd-fine

Open ``outputs/cfd/cfd-3d.html``. Select normal or half airflow, scrub/play the
saved transient frames, rotate the 3D field, toggle vectors and switch among
temperature, speed and pressure. Plan height and vertical-section position are
independent controls. Temperature colors share a common scale across scenarios.

`Open the CFD viewer <../_static/lab/cfd/cfd-3d.html>`_ ·
:doc:`Runnable tutorial <../gallery/analysis/plot_cfd_heat_3d>` ·
:doc:`API <../reference/cfd>`

The example contains four permeable rack zones releasing 3 kW each to room air.
It compares 2 and 1 m³/s supply for 120 seconds with a high-level return opening. Inputs, heat loads, airflow
resistance and effective mixing coefficients are illustrative. Simulating 120 s
does not imply a steady-state solution; the final temperature-change rate is
reported explicitly.

Edit and connect a design
-------------------------

The report explores completed Python simulations. To change physics or geometry,
edit ``case-0-inputs.json`` and rerun:

.. code-block:: bash

   datacenter-cfd --inputs outputs/cfd/case-0-inputs.json \
     --mesh-study --output outputs/my-cfd

The JSON contains ``grid``, ``settings`` and ``sources``. Grid dimensions are
metres and integer cell counts. Source powers are kW released into room air.
Sources have a named bounding box and linear momentum resistance in 1/s.
Fluid and numerical inputs include supply temperature/flow, density, specific
heat, effective kinematic viscosity and thermal diffusivity, expansion coefficient,
gravity, duration, maximum timestep, CFL safety factor and snapshot interval.

.. code-block:: python

   from datacenter_simulator.analysis.cfd import export_cfd_study
   from datacenter_simulator.methods.facility_design import design_facility
   from datacenter_simulator.models.design import DesignInputs
   from datacenter_simulator.models.cfd import CFDSettings
   from datacenter_simulator.use_cases.cfd import cfd_from_design

   design = design_facility(DesignInputs(it_peak_kw=120, growth_fraction=0,
                                         rack_limit_kw=30, racks_per_row=2))
   case = cfd_from_design(design, air_heat_fraction=0.15,
                         settings=CFDSettings(supply_flow_m3_s=2.5),
                         cells=(24, 24, 12))
   export_cfd_study("outputs/design-cfd", case, check_mesh=True)

This maps exact rack coordinates and IT loads from the design workflow. The
room-air heat fraction is mandatory: a facility chilled-water coil captures
heat through the air first, whereas direct-to-chip cooling may bypass room air.
The facility cooling model's liquid-loop fraction cannot infer this distinction.
Non-rack distribution and UPS losses are excluded by this adapter.

Equations and numerical method
------------------------------

With z upward, kinematic pressure :math:`\pi=p/\rho`, velocity :math:`\mathbf{u}`,
temperature :math:`T`, rack heat :math:`q` in W/m³ and resistance :math:`a` in 1/s:

.. math::

   \nabla\cdot\mathbf{u} &= 0 \\
   \frac{\partial\mathbf{u}}{\partial t} + (\mathbf{u}\cdot\nabla)\mathbf{u}
   &= -\nabla\pi + \nu_{eff}\nabla^2\mathbf{u}
      + g\beta(T-T_s)\mathbf{e}_z - a\mathbf{u} \\
   \frac{\partial T}{\partial t} + \nabla\cdot(\mathbf{u}T)
   &= \alpha_{eff}\nabla^2T + \frac{q}{\rho c_p}.

* **Staggered mesh:** pressure/temperature at cell centres, normal velocity at
  faces. This avoids collocated pressure/velocity checkerboarding.
* **Momentum:** first-order explicit Euler, first-order upwind momentum convective
  derivatives, centred viscous diffusion, explicit Boussinesq force and
  semi-implicit linear/quadratic rack drag and optional distributed fan forcing. Wall ghosts enforce tangential no slip.
* **Pressure projection:** solve :math:`\nabla^2\pi=\nabla\cdot\mathbf{u}^*/\Delta t`
  then :math:`\mathbf{u}=\mathbf{u}^*-\Delta t\nabla\pi`. The sparse operator
  uses the same gradient/divergence pair as the correction and is factorized
  once. The return boundary is half a cell from the final pressure centre.
* **Heat:** conservative finite-volume face fluxes, monotonized-central MUSCL
  reconstruction and SSP-RK2 thermal time integration; centred diffusion.
  ``thermal_scheme="upwind"`` retains the legacy first-order option. The coupled
  momentum/heat solver remains first-order overall. Source-to-grid volume overlaps preserve every rack's total watts
  even on coarse meshes. Subcell capture does not resolve the rack flow physics.
* **Time:** adaptive advection/diffusion and acceleration limits, exact saved
  frame times, and an additional projected-flux thermal CFL check. Non-finite
  fields, excessive CFL or reaching ``max_steps`` raise explicit errors.

Boundary conditions
-------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Boundary
     - Implemented condition
   * - Supply at x=0
     - Full-width slot from floor to inlet height; prescribed normal volume flow,
       zero tangential velocity and prescribed temperature. Partial-height cell
       faces use their opening fraction.
   * - Return at x=L
     - Configurable rectangular opening at zero gauge pressure; closed faces are impermeable; predictor velocity is extrapolated
       with zero normal gradient, then pressure-corrected. Zero diffusive heat
       flux. Any backflow uses ``return_temperature_c`` (supply if omitted), and its volume is reported.
   * - Other walls
     - No penetration, no slip and zero heat flux. No wall conduction or radiation.
   * - Rack envelopes
     - Permeable fluid zones containing heat and isotropic linear drag. They are
       not impermeable boxes or conjugate solid domains. Optional distributed fan pressure curves and quadratic resistance are available.

The return opening is configured with ``return_y_m``, ``return_z_m``,
``return_width_m`` and ``return_height_m``. Omitted dimensions span the entire
wall for compatibility. Partial-face areas enter both the pressure matrix and
velocity correction. The reference case uses a 3 × 0.6 m high-level opening.
Refine its edge cells: area conservation does not resolve a subcell jet.
The native model does not yet support arbitrary wall placements or duct meshes.

Backflow can materially affect results. Inspect ``max_return_backflow_m3_s``
and prescribe a defensible return-reservoir temperature instead of assuming that
backflow always brings supply-temperature air.

Verification, resolution and limits
-----------------------------------

Tests recover a manufactured pressure field, preserve uniform unheated air,
match uniform adiabatic heat storage and the analytical ventilation heat pickup,
demonstrate approximately second-order refinement of an analytical diffusion
mode, verify 3D buoyancy response, and audit mass/heat conservation. Source
overlap, invalid geometry, max-step failure, design conversion and VTK ordering
are also checked.

Each step exports velocity divergence, volume-flow imbalance, the pressure
linear-system residual, temperature-change rate, timestep/CFL, return backflow,
stored heat and integrated boundary heat. The energy residual is

.. math::

   E_{stored}(t) + \int_0^t H_{out}(\tau)d\tau - P_{heat}t,

where :math:`H_{out}` includes both advective transport and conduction at the
supply slot. Small residuals establish numerical conservation, not accuracy of
flow patterns, turbulence or rack temperature predictions.

``--mesh-study`` compares approximately half/base/1.5-times cell counts along
each dimension using the same duration and physical inputs. It reports peak and
mean air temperature and the end-time thermal change rate. It does not calculate
Richardson extrapolation or assert mesh independence. Refine sources and vents,
test timestep/mixing sensitivity and obtain measured validation before using
results for engineering decisions. The sparse direct solver has a 100,000-cell
guard; cost and memory grow rapidly for 3D factorization. Start with the default
3,200 cells and refine deliberately.

Effective viscosity/diffusivity are constant, uncalibrated mixing assumptions.
This is not a RANS/LES model or DNS at the default resolution. The solver omits
resolved server blades, individual servers, conjugate solid heat storage, humidity,
radiation, compressibility and turbulence transport equations. A temperature
excursion giving :math:`\beta|T-T_s|>0.1` triggers a Boussinesq screening warning.
Rack-zone values are air temperatures, not silicon or equipment-surface values.
No measured data center validation or compliance claim is made.

Exports and tools
-----------------

Each scenario has an inputs JSON, summary JSON, per-step history CSV, rack-air
probe CSV, final-cell CSV, full transient NPZ and final VTK. Array order in NPZ
is ``(time, x, y, z)`` for scalar fields and ``(time, component, x, y, z)`` for
velocity. VTK uses x-fastest ordering on cell-centre points and opens in ParaView.
``comparison.csv``, optional ``mesh-sensitivity.csv`` and ``evidence.json`` are
shared across the report. ``case-0`` is the input case; ``case-1`` is half flow.

For notebooks, :func:`~datacenter_simulator.utilities.cfd.temperature_slice`
returns a Plotly figure from any stored frame and a requested height.

Primary references
------------------

* `Chorin (1968): Numerical solution of the Navier-Stokes equations
  <https://math.berkeley.edu/~chorin/chorin68.pdf>`_: projection-method lineage.
  The implementation here is original, simplified and not a reproduction of all
  details of that paper.
* `Notus models and equations <https://doc.notus-cfd.org/d3/d7d/models.html>`_:
  incompressible momentum/heat equations and Boussinesq coupling.
* `NISTIR 8298: CFD verification, validation and uncertainty
  <https://www.nist.gov/publications/summary-industrial-verification-validation-and-uncertainty-quantification-procedures>`_:
  numerical verification, physical validation and uncertainty are separate tasks.

Accuracy studies and measurements
---------------------------------

.. code-block:: bash

   datacenter-cfd-accuracy --output outputs/cfd-accuracy
   datacenter-cfd --inputs case-0-inputs.json --measurements temperature-probes.csv

The accuracy command runs equal-ratio coarse/middle/fine meshes, separate
halved timestep caps, and declared heat, airflow and effective-mixing sensitivity
cases. Its default is a 20-second study; a user-supplied JSON retains its duration.
The timestep report records actual timesteps and whether the requested caps were
active. Adaptive CFL limits can make a requested cap change ineffective.

The three-grid Richardson/GCI calculation rejects oscillatory, divergent,
degenerate and implausible-order sequences. It reports absolute kelvin uncertainty
on peak/mean temperature rise, not a misleading percentage of Celsius temperature.
Eligibility is conditional on asymptotic convergence, not proof of it. GCI excludes
boundary, turbulence, geometry and measurement errors.

:doc:`Accuracy tutorial <../gallery/analysis/plot_cfd_accuracy>` demonstrates the
workflow and its limits. The ordinary viewer's coarse/base/fine sensitivity uses
its original unequal ratios and does not claim GCI from those runs.

A probe CSV requires ``time_s,x_m,y_m,z_m,observed_c``; optional
``standard_uncertainty_c`` adds normalized residuals. Four-dimensional linear
interpolation evaluates saved fields at the observation position/time.
Extrapolation beyond saved times or the cell-centre envelope is rejected.
Increase snapshot frequency before comparing fast transients. Outputs are
``measurement-comparison.csv`` and ``measurement-metrics.json``. Bias, MAE and
RMSE describe the supplied observations; use independent held-out measurements
with documented sensor and operating uncertainty after calibration.

Rack fan and resistance inputs
------------------------------

Optional ``fan_pressure_pa`` is shutoff pressure, ``fan_free_speed_m_s`` is
free-delivery axial velocity, ``fan_axis`` is 0/1/2 and ``fan_direction`` is ±1.
The actuator curve is :math:`\Delta p=\Delta p_0\max(1-(u_+/u_0)^2,0)`.
Distributed acceleration is pressure divided by air density and rack length
along the fan axis. This actuator approximation needs a measured pressure/flow
curve and adequate resolution; it does not resolve blades or enforce a fixed
flow independent of resistance. ``inertial_drag_per_m`` adds a Forchheimer-like
quadratic resistance to ``drag_per_s``. Fan work and viscous dissipation are not
added to the thermal source; include equipment heat explicitly in ``heat_kw``.

MUSCL verification advects an analytical temperature pulse and checks reduced
error and absence of new extrema. Fan-force tests check integrated pressure force,
shutoff at free speed, and quadratic resistance. Restricted-return tests check
aperture area, impermeability, pressure projection and global mass/heat closure.
These tests strengthen numerical evidence without claiming measured accuracy.

* `NASA: spatial grid convergence
  <https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html>`_:
  Richardson extrapolation and GCI factor of safety.
* `NASA: TVD reconstruction and limiters
  <https://www.grc.nasa.gov/WWW/winddocs/user/keywords/tvd.html>`_:
  limited higher-order advection methods.
