Development risk: opposition, delay and cancellation
====================================================

This screening layer complements power, cooling, water and acoustic studies:
engineering feasibility alone does not establish development feasibility.
It compares explicit assumptions, not predicted permitting outcomes.

Run and replay
--------------

.. code-block:: bash

   python -m datacenter_simulator.analysis.development --output outputs/development
   python -m datacenter_simulator.analysis.development --inputs outputs/development/inputs.json --output outputs/development-replay

Exports include an offline interactive probability/delay heatmap, branch and
expected NPV CSV, editable JSON inputs, source context and sensitivity arrays.
The gallery compares baseline, mitigation, relocation and mitigation with no
risk benefit. All dollar inputs and probabilities are synthetic.

Accounting
----------

At month zero pay predevelopment and mitigation. Each month through the
permit decision pay holding costs. On approval pay remaining planned capex,
then receive annual net operating cash flow for the specified operating life.
On cancellation pay exit costs and recover the specified predevelopment value;
do not pay unbuilt capex or receive operating income. Mitigation is incremental
to planned capex and paid in both branches. All values are USD.

Discount a cash flow at month m by (1+r)^(-m/12). Expected NPV is
(1-p) times approved NPV plus p times canceled NPV. Expected cancellation loss
is -p times canceled NPV; it is not p times announced investment. The full
operating life shifts with delay. Therefore delay can defer both capex and
income; its effect is not forced to be monotonic. Construction time is lumped
into the baseline permitting duration. This excludes taxes, financing,
escalation, staged construction, terminal value and fixed-date lease expiry.

Evidence and limits
-------------------

Source: Robinson Meyer, Heatmap, October 6, 2026, "Exclusive: Data Center
Cancellations Top $260 Billion in 2026", user-supplied excerpt. The source
context ledger preserves attributed aggregate figures without reproducing the
article. Its underlying proprietary project records have not been verified.
Reported planned investment canceled is not realized financial loss. Roughly
half of opposed projects canceled is conditional on an opposed cohort, not a
national rate or a site-specific forecast. Missing investment disclosure is
not random; do not divide the reported totals by the disclosure fraction.
The quarter is a subset of the annual figure, not additional investment.
No current legal status or moratorium coverage is established here.

Use local permit records, dated decisions, verified land/water/grid constraints
and community consultation to justify scenario inputs. Noise, water use and
grid impacts can inform engineering alternatives, but this model intentionally
does not convert them into approval probabilities. Spending on mitigation does
not automatically reduce risk. The zero-benefit alternative exposes that
assumption. These results are scenario arithmetic, not investment advice or
an empirical social-acceptance model.
