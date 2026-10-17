# DESI journal-club summary set: audit

Audited 2026-10-17. Nine structured summaries (8 before-T, 1 target). Each summary has 10 `quote:`/`loc:` pairs; every quote was checked verbatim against its PDF with `check_quotes.py` (normalised substring match, >= 40 chars).

> **Resolved after the audit (2026-10-17).** The leakage came from the PDF, not the summary: the bare arXiv URL serves the latest version. All three papers with post-T versions were re-pinned (DES-SN5YR v3, Efstathiou v2, Lewis & Chamberlain v1; see `research/papers/desi_before_T/MANIFEST.md`), the Lewis and Efstathiou summaries were rewritten from the pinned PDFs, and all 8 before-T files now pass `check_quotes.py` with 0 failures and 0 hits for `DR2 | Data Release 2 | 2025 | 14738`. Contradiction C2 below cited Efstathiou v3's Appendix A (BAO+SN combination), which does not exist in v2; C1, C3-C6 stand. Re-run the checks with `uv run python research/summaries/check_quotes.py <summary.md> <paper.pdf>`.

## File table

| id | citekey | role | date | quotes ok/total | checks |
|---|---|---|---|---|---|
| 1807.06209 | planck2018vi | before | 2018-07-17 | 10/10 | pass |
| 2007.08991 | eboss2020 | before | 2020-07-17 | 10/10 | pass |
| 2401.02929 | dessn5yr2024 | before | 2024-01-05 | 10/10 | pass |
| 2404.03000 | desi2024iii | before | 2024-04-03 | 10/10 | pass |
| 2404.03001 | desi2024iv | before | 2024-04-03 | 10/10 | pass |
| 2404.03002 | desi2024vi | before | 2024-04-03 | 10/10 | pass |
| 2408.07175 | efstathiou2024 | before | 2024-08-13 | 10/10 | pass |
| 2412.13894 | lewis2024 | before | 2024-12-18 | 10/10 | **LEAKAGE** (see below) |
| 2503.14738 | desidr2ii | target | 2025-03-18 | 10/10 | pass |

Checks: (1) quote verification fail=0, missing_loc=0 for all 9; (2) all before-T dates < 2025-01-01, target date 2025-03-18; (3) leakage grep for `DR2`, `2025`, `Data Release 2`, `14738` across before-T files.

## Failed check: 2412.13894_lewis-chamberlain.md (leakage)

- The frontmatter date (2024-12-18) is the arXiv v1 date, but the PDF on disk (`research/papers/desi_before_T/2412.13894_lewis-chamberlain.pdf`) is **v3, dated 23 Apr 2025**, which post-dates the target paper (2025-03-18) and uses **DESI DR2 BAO** as its data. The summary faithfully reports this: its Data section begins "DESI DR2 BAO measurements at seven effective redshifts ..." and the executive summary names "DESI DR2 BAO data" and carries a summariser note ("the PDF summarised is v3, 2025-04-23, using DESI DR2").
- Consequence: the claim "Four of the DESI redshift bins (LRG2, LRG3+ELG1, ELG2 and Lya) have central values inside the NEC exclusion region" and the quoted best-fit (w0 = -0.50, wa = -1.47) are derived from DR2, i.e. from the target paper's data. A journal club working from this summary would see the target's numbers before T.
- The quote check passes only because the quotes are verbatim from v3; the problem is the source file, not the transcription.
- Fix: replace the PDF with arXiv **2412.13894v1** (Dec 2024, which used DESI DR1), re-run the summariser and `check_quotes.py`, and drop the DR2 sentences. Until then, exclude this file from the before-T set or treat its Sec. IV data comparison as post-T.

## Contradictions across the 8 before-T papers (what the journal club should find)

### C1. DES-SN5YR evolving dark energy vs Efstathiou SN systematics (direct)
- dessn5yr2024: "Fitting DES-SN5YR alone to the Flat- w0waCDM model gives an equation of state that is slightly over 2σ from a cosmological constant, marginally preferring a time-varying dark energy" (Sec. 4.1.4) and "Critically, the DES-SN5YR analysis shown here demonstrates that contamination due to SN classification and host-galaxy matching is not a limiting systematic for SN cosmology" (Sec. 6).
- efstathiou2024: "Most of the low redshift surveys are offset by ∼ 0.04−0.05 mag. relative to the more distant DES supernovae." (Sec. 3) and "Evidently, the recalibrated DES5Y catalogue does not show a statistically significant preference for a time varying equation-of-state." (Sec. 3).
- Tension: DES claims systematics are subdominant; Efstathiou shows a 0.04 mag low-z offset erases the evolving-DE signal. DES itself concedes "the low- z sample is the one for which we have the least systematic control" (Sec. 5.1.2), which is exactly where Efstathiou finds the offset.

### C2. DESI 2024 VI "all probes contribute" vs Efstathiou "driven by DES5Y" (direct)
- desi2024vi: "All three of the primary BAO, CMB and SN Ia probes contribute partially to this tension and the results including the 3 SN Ia datasets are mutually consistent with each other." (Sec. 8); "combinations of DESI with CMB or with type Ia supernovae (SN Ia) individually prefer w0 > −1 and wa < 0" (Abstract).
- efstathiou2024: "Fig. 8 shows clearly that the ∼ 3σ evidence for dynamical dark energy apparent in lower panel is driven by the DES5Y SN." (App. A); "The cosmology inferred from Pantheon+ sample alone is consistent with the Planck ΛCDM model and shows no preference for evolving dark energy." (Abstract).
- Tension: contradictory attribution of the same signal. DESI VI lists 2.5σ (Pantheon+) to 3.9σ (DES5Y); Efstathiou reads the Pantheon+ combination as consistent with ΛCDM.

### C3. DESI 2024 VI / DESI 2024 III phantom-direction deviations vs Lewis-Chamberlain NEC bound (physical)
- desi2024vi: "combinations of DESI with CMB or with type Ia supernovae (SN Ia) individually prefer w0 > −1 and wa < 0" (Abstract), implying w < -1 at z > 1.
- desi2024iii: "We find our measurements are systematically larger than the prediction of the Planck 2018-ΛCDM at z <0.8." (Abstract), i.e. D_M below ΛCDM.
- lewis2024: "These inequalities demonstrate that certain deviations from ΛCDM are impossible for any physical non-interacting dark energy model that respects the null energy condition within the context of FRW cosmological models." (Abstract); "Current acoustic data favour ΛCDM over other NEC-consistent models up to statistical fluctuations." (Sec. V).
- Tension: Lewis derives D_M(z) >= D_M^Λ(z) at fixed θ*, so the direction in which DESI deviates (D_M < D_M^Λ, phantom w) cannot come from any NEC-respecting dark energy. Either the deviations are fluctuations/systematics, or the fix is more radical than w0waCDM. (Caveat: this file is leakage-tainted; the inequality derivation itself is v1 content, the data comparison is DR2.)

### C4. DESI 2024 VI vs Planck 2018 and eBOSS 2020 on Λ (quantitative)
- planck2018vi: "Combining Planck data with Pantheon supernovae and BAO data, the equation of state of dark energy is tightly constrained to w0 =−1.03± 0.03, consistent with a cosmological constant." (Sec. 8).
- eboss2020: "The SDSS BAO measurements demonstrate that the observed cosmic acceleration is best described by a dark energy equation of state that is consistent with a cosmological constant to better than 6% precision when combined with the Planck temperature and polarization data." (Sec. VII); wp = -1.020 ± 0.029 in w0waCDM.
- desi2024vi: DESI+CMB prefers w0waCDM at 2.6σ, 2.5/3.5/3.9σ with Pantheon+/Union3/DES-SN5YR.
- Tension: same CMB, same SN family, BAO from a different survey: Λ at 1σ becomes a 2.5-3.9σ departure. The club should ask what changed (DESI z < 0.8 BAO, DES-SN5YR replacing Pantheon, w0+wa < 0 prior, or the (w0, wa) prior volume Lewis warns about).

### C5. DESI 2024 III vs eBOSS 2020 at z ~ 0.7 (data-level)
- desi2024iii: "Accordingly, we found a large discrepancy between the DESI BAO measurement at zeff = 0.71 and the SDSS measurement at zeff = 0.7." (Sec. 9), up to ~3σ in D_M/r_d.
- eboss2020: "After accounting for the covariance between BAO and RSD measurements, the measurement differs from the ΛCDM prediction by 3.0 standard deviations." (Sec. VI.A, about the z ~ 1.48 quasar sample); the pull test rates the whole SDSS set as Gaussian, with the largest BAO pull (-1.75) at the z ~ 0.7 eBOSS LRG.
- Tension: the bin where DESI and SDSS disagree is the one SDSS already flagged as its largest BAO pull, in the opposite direction. DESI III admits "we have not identified any sources of non-statistical discrepancy from both sets of the data." (Sec. 8.2). Since the z < 0.8 excess drives C3/C4, this discrepancy matters.

### C6. Matter density: DES-SN5YR vs DESI 2024 VI vs Planck (ΛCDM, same model)
- dessn5yr2024: "Using supernova data alone and including systematic uncertainties we find Ω M = 0 .352 ± 0.017 in flat-ΛCDM" (Abstract).
- desi2024vi: "DESI BAO data alone are consistent with the standard flat ΛCDM cosmological model with a matter density" Ω_m = 0.295 ± 0.015 (Abstract); planck2018vi: Ω_m = 0.315 ± 0.007.
- Tension: DES is ~2.5σ above DESI and ~2σ above Planck within flat ΛCDM. Efstathiou traces it to the high-z residual: "The corrected DESY5 constraints are still skewed to high values of Ω m as a consequence of the negative residual at z >1 in Fig. 5" (Sec. 3). A high-Ω_m SN sample pushed into w0waCDM with a low-Ω_m BAO sample is a known route to a spurious (w0 > -1, wa < 0) signal.

### Agreement worth noting (not a contradiction)
- H0 cannot be rescued by late-time dark energy: planck2018vi ("none of the studied extensions convincingly removes the gap"), eboss2020 ("In all cases, the central values remain below H0 = 68 km s−1Mpc−1"), desi2024vi (H0 = 68.53 ± 0.80 from BAO+BBN), lewis2024 ("null-energy consistent dark energy can only exacerbate the Hubble tension"). The w0waCDM signal, if real, makes the Hubble tension worse.

## Limitations shared by 2+ papers

### L1. Unaccounted systematics or dataset inconsistency as the unexcluded explanation (desi2024vi, efstathiou2024, desi2024iii, planck2018vi)
- desi2024vi: "It remains important to thoroughly examine unaccounted-for sources of systematic uncertainties or inconsistencies between the different datasets that might be contributing to these results." (Sec. 8)
- efstathiou2024: "Whether the magnitudes offsets evident in Figs. 3 and 4 are indicative of systematic errors in one or both SN compilations is a more controversial question." (Sec. 3)
- desi2024iii: "While this 2.5 σ–3σ discrepancy warrants attention, we have not identified any sources of non-statistical discrepancy from both sets of the data." (Sec. 8.2)
- planck2018vi: "Although the TT,TE,EE likelihoods are not perfect, thePlanck parameter results presented in this paper can be considered accurate to within their error bars." (Sec. 8)

### L2. Low-redshift SN calibration is the weak link (dessn5yr2024, efstathiou2024, lewis2024)
- dessn5yr2024: "it is important to recognize that (a) the low- z sample is the one for which we have the least systematic control" (Sec. 5.1.2)
- efstathiou2024: "Most of the low redshift surveys are offset by ∼ 0.04−0.05 mag. relative to the more distant DES supernovae." (Sec. 3)
- lewis2024 (open question): whether the SN-driven thawing pull at z < 0.2 is physical given inter-compilation differences.

### L3. High-redshift SN bias corrections are large and uncertain (dessn5yr2024, efstathiou2024)
- dessn5yr2024: "the very high-redshift SNe are the ones for which bias-corrections are large ( > 0.1 mag) and more uncertain" (Sec. 5.1.2)
- efstathiou2024: "The corrected DESY5 constraints are still skewed to high values of Ω m as a consequence of the negative residual at z >1 in Fig. 5" (Sec. 3); open question on an independent test of the BBC bias-correction framework.

### L4. The (w0, wa) / CPL parameterisation is unphysical or degenerate and over-interpretable (desi2024vi, lewis2024, eboss2020, dessn5yr2024)
- desi2024vi: "However, we caution against over-interpretation of this result, since at least some of the (w0, wa) models preferred by our analysis could be mapped to quintessence models" (Sec. 5.2); "DESI alone does not have sufficient power to break the degeneracy between w0 and wa" (Sec. 5.2)
- lewis2024: "Although the CPL parameterization is convenient and easy to implement, it is fundamentally unphysical, so results using it must be interpreted with care." (Sec. V)
- eboss2020: "However, since many of these models have parameter choices that make them indistinguishable from ΛCDM, those models all can be made consistent with our observations." (Sec. VII)
- dessn5yr2024: "The best fit value for w or Ω M is thus an insufficient summary of the SN information, as a small shift along the degeneracy direction can result in large shifts in the best-fit values" (Sec. 4.1.3)

### L5. Everything hangs on standard pre-recombination physics fixing r_d / θ* (eboss2020, lewis2024, planck2018vi, desi2024vi)
- eboss2020: "As summarized in Knox and Millea [176], there have been many attempts to reconcile the H0 tension by modifying the value of rd, with limited success." (Sec. IV.B)
- lewis2024: the inequalities hold only at fixed θ*, Ω_m h², Ω_b h² (Methods); desi2024vi: H0 requires a BBN prior or θ*; planck2018vi: H0 = 67.4 ± 0.5 is a ΛCDM-conditional number.

### L6. 2-3σ anomalies individually dismissed as fluctuations (desi2024vi, desi2024iii, planck2018vi, eboss2020)
- desi2024vi: "This appears to be a simple statistical fluctuation and we do not regard it as significant." (Sec. 3.2, LRG F_AP at z = 0.51)
- desi2024iii: the z ~ 0.7 SDSS-DESI discrepancy "is likely an upper limit" (Sec. 8.2)
- planck2018vi: "The joint combined likelihood shifts the value preferred by the TT data downwards towards AL = 1, but the error also shrinks, increasing the signiﬁcance of AL > 1 to 2.8σ" (Sec. 6.2); Lyα BAO 1.7-2.3σ low
- eboss2020: z ~ 1.48 quasar BAO+RSD at 3.0σ from ΛCDM (Sec. VI.A)
- Together these are the same low-z/high-z pattern the target paper later reads as a signal; the club should ask whether four separately-dismissed 2-3σ pulls add up.

### L7. Neutrino-mass bounds are prior- and model-dependent (desi2024vi, eboss2020)
- desi2024vi: "We also caution that the upper bound obtained is strongly dependent on the choice of prior for P mν." (Sec. 7.1)
- eboss2020: "Note that these are not Bayesian evidences, because we do not account for the prior volume." (Sec. VI.C)

### L8. Lyα BAO is treated as second-class or incompletely validated (planck2018vi, desi2024iv)
- planck2018vi: "The errors on these high-redshift BAO measurements are still quite large in comparison with the galaxy measurements and so we do not include them in our default BAO compilation." (Sec. 5.1)
- desi2024iv: "It is important to note that we have not redone the SDSS analysis with our analysis pipeline." (Sec. 7.3); no simulation study of relative-velocity bias for the dominant quasar cross-correlation (Sec. 7.4). Note desi2024iii did reanalyse BOSS/eBOSS galaxy catalogues with the DESI pipeline, so the DESI+SDSS combinations in III and IV are built differently.

## Expected journal-club output

A debate that (a) finds C1+C2+C6 and concludes the DES-SN5YR low-z calibration and high Ω_m are the single most likely non-cosmological driver, (b) finds C3+C5 and notes that the BAO deviation sits in the bin SDSS already pulled on and in an NEC-forbidden direction, (c) predicts that a larger BAO sample alone will either erase the z < 0.8 excess or sharpen a tension with the CMB that no NEC-consistent dark energy can absorb. The target paper (desidr2ii) reports the second branch: 2.3σ DESI-CMB tension in ΛCDM, 3.1σ for w0waCDM with CMB, 2.8/3.8/4.2σ with Pantheon+/Union3/DESY5, and a phantom crossing near z ~ 0.4, with the SN calibration still named as the open systematic.
