# Literature check of the first DESI night: did the directions happen?

Run: `runs/desi-bt-1` (8 before-T papers, T = 2025-01-01; club = map → debate → directions on Sonnet 5.5; baseline = one Sonnet call on the same 8 summaries). The backtest judge had a single after-T paper (DESI DR2 II). This check instead searches the real literature 2025-01-01 to 2026-10-17 (INSPIRE-HEP, arXiv, web; every arXiv id verified on its abs page) for papers that did what each direction predicted. `post-cutoff` = v1 after 2026-06-30, i.e. after the predicting model's training data; those are the cleanest evidence.

## Scorecard

| arm | directions | HIT | PARTIAL | MISS | strict | weighted (partial = ½) | directions with a post-cutoff confirmation |
|---|---|---|---|---|---|---|---|
| club (discussion) | 6 | 3 | 3 | 0 | 0.50 | 0.75 | 2 (#1 via 2609.05053, #4 via 2609.04334) |
| baseline (one call) | 9 | 7 | 1 | 1 | 0.78 | 0.83 | 2 (#4 via 2607.07348, #7/#8 via 2607.27410, 2608.01844) |

Against the single-paper judge (club 0/4/2, baseline 1/4/4) the literature is far kinder to both arms: nearly every direction was taken up by someone within 20 months. The club's three partials are all "right question, more specific method than what was published" (cross-covariance on the overlap footprint; θ*-constrained distance-space NEC tests; N_eff folded into the budget). The baseline's one miss (SDSS reprocessed through the DESI pipeline) is a genuine miss.

Reading: both arms point at where the field went. The discussion did not produce measurably better directions than the single call on this test; it produced sharper ones, and the sharpening is what costs them under a strict hit rule.

## Club directions

### 1. Cross-calibrated, common-pipeline reanalysis of the low-z SN anchor; DES5Y 3.9σ shrinks toward the Pantheon+ level — HIT
- arXiv:2511.07517 — DES-Dovekie reanalysis, Popovic et al., v1 2025-11-10. Full DES-SN5YR recalibration (photometric cross-calibration, white-dwarf cross-calibration to low-z surveys, retrained SALT3); with CMB+DESI DR2 the w0waCDM significance drops 4.2σ → 3.2σ.
- arXiv:2506.05471 — Dovekie, Popovic et al., v1 2025-06-05. Joint cross-calibration framework for Pantheon+ and DES.
- arXiv:2609.05053 — Supernovae Unite: Combining Pantheon+ and DES-SN5YR, Camilleri et al., v1 2026-09-04, **post-cutoff**. Single consistent Hubble diagram (2884 SNe), uniform bias corrections; 3.1–3.3σ with CMB+BAO: the compilations converge at the Pantheon+ level.
- Also arXiv:2501.06664 (Vincenzi et al., v1 2025-01-11) reproduces the Efstathiou offset and attributes it to modelling and selection differences.

### 2. Next DESI release judged on the z<0.8 offset and the z~0.7 eBOSS disagreement, with a cross-correlation-resolved DESI-vs-SDSS comparison on the overlap — PARTIAL
- arXiv:2503.14738 — DESI DR2 II, v1 2025-03-18. Sec. III.C.2 revisits the z~0.7 tension with an analytic DESI–eBOSS correlation (C≈0.57 from footprint overlap vs 0.21 in DR1): 3σ → ~2.6σ, 2.3σ/1.5σ with the DESI reanalysis of SDSS; no significant discrepancy.
- arXiv:2503.14742 — Validation of DR2 galaxy/quasar BAO, Andrade et al., v1 2025-03-18. Sec. VII.4 compares DR1/DR2/SDSS at z~0.7 with the DESI reanalysis of the eBOSS LRG catalogue; DR2 lies between DR1 and SDSS.
- arXiv:2607.07348 — Ferri et al., v1 2026-07-08, **post-cutoff**, adjacent: attributes the DESI w0/q0 pull to the lowest redshift bin.
- Why partial: the persistence question was answered and a common-pipeline comparison done, but the correlation is still an analytic estimate, not a measured cross-covariance on the shared footprint.

### 3. From CPL contours to NEC-aware, θ*-constrained distance-space tests and physical models — PARTIAL
- arXiv:2511.07526 — Null Impact of the Null Energy Condition in Current Cosmology, Caldwell et al., v1 2025-11-10. Asks directly whether the best-fit w0wa cosmology violates the NEC; shows it need not.
- arXiv:2506.19053 — Dark Energy Crosses the Line, Özülker et al., v1 2025-06-23. Tests whether the phantom crossing is a CPL artefact against non-crossing physical variants; the data prefer a crossing.
- arXiv:2602.21169 — Revisiting CPL with sign-switching density, Gökçen et al., v1 2026-02-24. Replaces the w = −1 divide with the NEC boundary.
- Also arXiv:2503.14743 (Lodha et al., DESI extended DE), arXiv:2606.30527 (Zaldarriaga et al.), arXiv:2607.18008 (Akarsu et al., **post-cutoff**: organise inference around ρ, p, ρ+p).
- Why partial: NEC-aware tests appeared in volume, but not the specific θ*-constrained D_M/D_H/F_AP-vs-ΛCDM formulation.

### 4. Decompose the w0–wa signal per probe with the SN calibration varied; does the low-z SN pull drive it? — HIT
- arXiv:2502.04212 — Huang et al., v1 2025-02-06. SN magnitude–distance intercept as a systematics diagnostic; correcting the DESY5 low-z sample drops the preference below 2σ.
- arXiv:2609.04334 — Model Predictive Scoring Shows Specific BAO Observations (not SNIa) Drive w0wa Tension, Karim et al., v1 2026-09-03, **post-cutoff**. Leave-one-block-out decomposition across BAO and SN datasets: the preference comes from the LRG2 (z=0.706) BAO point.
- arXiv:2509.13220 — Dynamic or Systematic?, Ormondroyd et al., v1 2025-09-16. Marginalises a low/high-z SN offset; evidence favours it over flexknot dark energy.
- Also arXiv:2502.07185 (Bansal & Huterer, v1 2025-02-11) localises the signal to a 3–4% expansion-rate excess at z~0.7.

### 5. Lyα BAO at z~2.3: multi-visit DESI-pipeline reanalysis plus simulation studies of the quasar cross-correlation BAO shift — HIT
- arXiv:2503.14739 — DESI DR2 I: Lyα BAO, v1 2025-03-18. Coadded repeat observations, 0.65% precision, first explicit theoretical systematic term (0.3%).
- arXiv:2503.13442 — Measuring and unbiasing the BAO shift in the Lyα forest with AbacusSummit, Hadzhiyska et al., v1 2025-03-17. N-body measurement of the shift in auto and cross-correlation.
- arXiv:2503.14741 — Validation of the DR2 Lyα BAO analysis with synthetic datasets, Casas et al., v1 2025-03-18.
- Post-cutoff follow-ups: arXiv:2607.27410 (DR2 IV), arXiv:2607.19619 (three-bin Lyα BAO).

### 6. BAO systematic budgets include N_eff-dependent template bias at the new precision — PARTIAL
- arXiv:2503.14742 — Andrade et al., v1 2025-03-18. Sec. VII.3 reruns DR2 BAO fits with a high-N_eff (3.70) fiducial among four alternatives (shifts within 0.4σ) but deliberately keeps it out of the budget.
- arXiv:2509.08057 — Gsponer et al., v1 2025-09-09. Same secondary-cosmology suite for the DR1 full-shape pipeline.
- arXiv:2606.06591 — Paranjape et al., v1 2026-06-04. Template-free BAO inference removing the template-cosmology dependence.
- Why partial: re-tested, not folded into the budget.

## Baseline directions

### 1. Jointly recalibrated low-z anchor across Pantheon+, Union3, DES5Y; does the spread collapse? — HIT
- arXiv:2601.19424 — Union3.1, Hoyt et al., v1 2026-01-27. Self-consistent host properties for ~2000 SNe; low-z Union3 host masses were overestimated, Pantheon+ underestimated; low-z offset >0.03 → ~0.01 mag; evidence against Λ converges to 3.2–3.4σ across compilations.
- arXiv:2506.05471 — Dovekie; arXiv:2511.07517 — DES-Dovekie (see club 1); arXiv:2609.05053 — Unite, **post-cutoff**.

### 2. Are the DES5Y or Pantheon+ bias corrections in error? Rerun both pipelines on shared overlapping SNe — HIT
- arXiv:2501.06664 — Vincenzi et al., v1 2025-01-11. Reproduces the ~0.04 mag low/high-z offset on the overlapping SNe and decomposes it (43% intrinsic-scatter/host modelling, ~38% selection/bias corrections); rerunning DES with Pantheon+ choices lowers 3.9σ → 3.3σ.
- arXiv:2511.07517 — DES-Dovekie; arXiv:2606.18374 — Watkins et al., v1 2026-06-16: the low-z anchor carries a ~0.05 mag offset; preliminary DEBASS does not show it.

### 3. NEC-aware / parametrisation-independent analyses of D_M, D_H vs θ* — HIT
- arXiv:2503.14743 — Lodha et al. (DESI), v1 2025-03-18. Non-parametric w(z) reconstructions plus physical classes incl. w ≥ −1 quintessence; phantom-crossing preferred, NEC-respecting alternatives disfavoured but not excluded.
- arXiv:2503.22515 — Ye & Piao, v1 2025-03-28. NEC violation and beyond-Horndeski with DR2.
- arXiv:2603.22406 — Shlivko & Poulin, v1 2026-03-23. Phantom crossing arises from mismatched Ω_m across CMB, BAO, SN.
- Also arXiv:2512.20832, 2505.18937, 2504.09681; arXiv:2607.07777 (**post-cutoff**).

### 4. Use the next DESI release to test whether the z<0.8 excess and the z~0.7 eBOSS discrepancy persist — HIT
- arXiv:2503.14738 — DESI DR2 II (see above). arXiv:2504.04417 — Ó Colgáin et al., v1 2025-04-06: tracks DR1 bin fluctuations into DR2. arXiv:2607.07348 — Ferri et al., **post-cutoff**. arXiv:2608.27830 — Sanders et al., unified tracer analysis of DR2 BAO, **post-cutoff**.

### 5. Test the DES5Y w > −1 pull with a homogeneous new low-z sample (ZTF, YSE, DEBASS) — PARTIAL
- arXiv:2606.18374 — Watkins et al., v1 2026-06-16: preliminary DEBASS DR0.5 (55 SNe) replaces the low-z anchor; the offset disappears. arXiv:2508.10877 / 2508.10878 — DEBASS cross-calibration and design (setup, not the test). ZTF DR2 photometry not yet cosmology-grade (arXiv:2509.04073); no YSE cosmology paper found.

### 6. Reanalyse SDSS galaxy and Lyα BAO with the DESI pipeline — MISS
- Closest: DESI DR2 II reuses the 2024 DESI reanalysis of the eBOSS LRG catalogue for its tension estimate; no 2025+ paper reprocesses SDSS galaxy or Lyα data through the DR2 pipeline. Searched INSPIRE titles (eBOSS/SDSS/BOSS × DESI × BAO/reanalysis/Lyman, date>2025), refersto DR2 I/II and DESI 2024 IV, and the web.

### 7. Resolve the Lyα BAO systematics budget (cross-correlation shifts, N-body mocks) — HIT
- arXiv:2503.13442 (Hadzhiyska et al.), arXiv:2503.14741 (Casas et al.), arXiv:2503.14739 (DR2 I); post-cutoff arXiv:2607.27410, 2607.27412, 2607.27411. Caveat: the shifts quantified are nonlinear-growth shifts; no paper isolates a baryon/relative-velocity cross-correlation shift.

### 8. DESI+CMB with joint growth (full-shape) constraints vs evolving DE — HIT
- arXiv:2602.18761 — Forero-Sánchez et al., v1 2026-02-21. DR1 full-shape + DR2 BAO: DESI-only w0wa discrepancy with ΛCDM drops to 1.4σ.
- arXiv:2606.23936 — Forero-Sánchez et al., v1 2026-06-22. Adds the LRG bispectrum; DESI+CMB 2.8σ, "driven primarily by the CMB".
- arXiv:2512.07104 — Zhou, v1 2025-12-08. Post-cutoff arXiv:2608.01844. No DR2 galaxy full-shape release found by 2026-10-17.

### 9. Reanalyse Union3 at the individual-SN level for the low-to-high-z calibration difference — HIT
- arXiv:2601.19424 — Union3.1 (see baseline 1). arXiv:2601.19854 — Banana Split, Rubin et al., v1 2026-01-27. arXiv:2511.07517 — DES-Dovekie (parallel).

## Caveats
- INSPIRE multi-term title search is conservative; web search filled gaps. Two INSPIRE hits without arXiv ids (Kandel et al., EPJC 2026; a JHEAp 2026 NEC paper) were excluded as unverifiable.
- "HIT" means a paper substantially did what the direction described, judged by a reader of abstracts and key sections, not by the original authors.
- The club and baseline were fed the same 8 summaries, so their directions overlap; the comparison is between the discussion process and a single call, not between different information.
- The predicting model (Sonnet 5.5, cutoff mid-2026) could have seen most 2025 papers; only the `post-cutoff` matches are free of that concern, and both arms have two.
