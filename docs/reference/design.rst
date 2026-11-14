Facility design
===============

.. automodule:: datacenter_simulator.models.design
   :members:

.. automodule:: datacenter_simulator.methods.facility_design
   :members:

.. automodule:: datacenter_simulator.analysis.design
   :members:

.. automodule:: datacenter_simulator.utilities.design
   :members:

.. automodule:: datacenter_simulator.use_cases.design
   :members:

Site-first feasibility
----------------------

.. automodule:: datacenter_simulator.methods.feasibility
   :members:

The runnable :doc:`../gallery/analysis/plot_site_feasibility` explores density,
orientation and storeys, exporting option metrics, hall coordinates and equipment
counts to CSV. The existing facility model supplies cooling and electrical
losses, module derating and N/N+1/2N equipment counts independently per hall.
Grid capacity constrains **facility** demand, not just IT demand. Whole halls
are admitted; insufficient land or power returns a zero-capacity option.

Scope and evidence
~~~~~~~~~~~~~~~~~~

Conceptual source: Nuno Mourão (PODIUM), *Data Center Design Automation: A New
Paradigm for Feasibility and Early Design*, Autodesk University 2026, BLD4108:
user-supplied slide deck (slide 12) and class handout (worked rack-density case).
The documents motivate reusable rules, capacity derived from geometry, multiple
options, quantities and deterministic validation. Their reported project
outcomes and time savings have not been independently verified here.

The source's 120 MW example implies 3,000 racks at 40 kW and 6,000 at 20 kW.
Its reported 8,338/16,115 tCO2e and 302/315 kgCO2e/m² imply approximately
27,609/51,159 m². These are source-specific structural results, not calibrated
presets. The runnable example keeps that arithmetic separate from synthetic
screening inputs. Higher density does not universally reduce whole-life carbon.

The screening model supports flat rectangular sites, uniform setbacks, a
full-width reserved plant/access strip and rectangular hall modules. Rack
geometry and a support-area allowance must fit each module. The plant strip is
an input reservation, **not** a verified equipment-yard fit. Equipment BOQ counts
are installed modules across independent halls, not a shared campus plant.
Shell cost and structural carbon are area-factor allowances only; equipment,
land, fees, operational emissions and lifecycle boundaries need separate data.

It does not generate structural members or validate loads, foundations, egress,
fire separation, terrain, arbitrary easements, water, fiber, permitting or supplier
availability. A selected option is a screening candidate, not a buildable design.
CSV coordinates use a local metre frame and zero-based floor levels. No Autodesk
integration, IFC export, supplier connector or agent is claimed. Those require
additional schemas and validation; agents may propose inputs while this engine
keeps generation and arithmetic reproducible.
