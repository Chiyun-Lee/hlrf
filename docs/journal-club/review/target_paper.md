# Target paper trace: DESI DR2 Results II (arXiv:2503.14738)

Prepared 2026-10-17 for the journal-club backtest. The target is the "after T" paper; the job of the club is to read only "before T" papers and point toward the direction the target took.

## 1. Verified identifiers

| field | value | source |
|---|---|---|
| arXiv ID | 2503.14738 (v1 2025-03-18, v3 2025-10-09) | [arxiv.org/abs/2503.14738](https://arxiv.org/abs/2503.14738) (VERIFIED) |
| Title | DESI DR2 Results II: Measurements of Baryon Acoustic Oscillations and Cosmological Constraints | arXiv abs page `citation_title` |
| Authors | DESI Collaboration; M. Abdul-Karim, J. Aguilar, S. Ahlen, S. Alam, ... (collaboration author list, ~190 names) | arXiv abs page `citation_author` |
| Date | submitted 2025-03-18 | arXiv abs page |
| Venue | Phys. Rev. D 112, 083515 (2025), DOI [10.1103/tr6y-kpc6](https://doi.org/10.1103/tr6y-kpc6) | arXiv `citation_doi`; [INSPIRE record](https://inspirehep.net/api/arxiv/2503.14738) `publication_info` |
| Citation count | 1848 (1586 excluding self-citations), INSPIRE, 2026-10-17 | [INSPIRE](https://inspirehep.net/api/arxiv/2503.14738). Semantic Scholar paper-level endpoint returned HTTP 429 on 7 attempts over ~1 min; count not obtained there. |
| References | 176 entries, 163 of which INSPIRE links to a record | INSPIRE `references` |
| Local PDF | `/Users/jacky/Documents/temp/research/papers/2503.14738_desi-dr2-bao-cosmology.pdf` (12 MB, `file` reports PDF) | manifest row appended |

Abstract (from arXiv): "We present baryon acoustic oscillation (BAO) measurements from more than 14 million galaxies and quasars drawn from the Dark Energy Spectroscopic Instrument (DESI) Data Release 2 (DR2), based on three years of operation. ... The results are well described by a flat ΛCDM model, but the parameters preferred by BAO are in mild, 2.3σ tension with those determined from the cosmic microwave background (CMB) ... This tension is alleviated by dark energy with a time-evolving equation of state parametrized by w0 and wa ... with a favored solution in the quadrant with w0>-1 and wa<0. This solution is preferred over ΛCDM at 3.1σ for the combination of DESI BAO and CMB data. When also including SNe, the preference for a dynamical dark energy model over ΛCDM ranges from 2.8-4.2σ depending on which SNe sample is used."

## 2. Direction the target represents (one sentence)

With three years of DESI BAO data, test whether the DR1 hint of evolving dark energy survives: the target finds that DESI BAO alone is now in 2.3σ tension with Planck ΛCDM, and that DESI+CMB (+SNe) prefer a w0>-1, wa<0 (phantom-crossing) w0waCDM solution over ΛCDM at 2.8-4.2σ, with the significance depending on the SN sample.

## 3. Shortlist of references that led to the target

Notes on sourcing. The Semantic Scholar `references` endpoint for this paper returned only 14 malformed entries (bibliography parsing failure on the 190-author PRD format), so the `isInfluential` flag was unusable; the shortlist is built from (a) the citing sentences in the target's own text (arXiv HTML version, section/bracket numbers below are the target's), (b) INSPIRE's linked reference records with citation counts, and (c) how directly the target builds on each. Semantic Scholar did return a few context sentences (e.g. for Cobaya, for DESI design refs [4-6], [17-19]); none of those changed the ranking. Citation counts are INSPIRE, 2026-10-17. All arXiv IDs below were checked against their arxiv.org abs page (HTTP 200, title and date read from the page): all VERIFIED, none FAIL.

| # | arXiv ID | title | authors | date | cites | role in target (bracket = target's ref number) |
|---|---|---|---|---|---|---|
| 1 | [2404.03002](https://arxiv.org/abs/2404.03002) VERIFIED | DESI 2024 VI: Cosmological Constraints from the Measurements of Baryon Acoustic Oscillations | DESI Collaboration | 2024-04-03 | 2162 | Direct predecessor (DR1 key paper, cited 18 times as [38]): "The analysis of the DESI DR1 measurements from [21, 22] in [38] provided tight constraints on parameters of the ΛCDM model and intriguing hints of evolving dark energy, with significances ranging from ∼2.5σ to ∼3.9σ depending on the combination of datasets." |
| 2 | [2404.03000](https://arxiv.org/abs/2404.03000) VERIFIED | DESI 2024 III: Baryon Acoustic Oscillations from Galaxies and Quasars | DESI Collaboration | 2024-04-03 | 596 | DR1 galaxy/quasar BAO measurement [21]; the DR2 fitting pipeline is "described in detail in [21]". "In its first year of observations, DESI already achieved BAO measurements competitive with those of all previous surveys combined [21, 22]." |
| 3 | [2404.03001](https://arxiv.org/abs/2404.03001) VERIFIED | DESI 2024 IV: Baryon Acoustic Oscillations from the Lyman Alpha Forest | DESI Collaboration | 2024-04-03 | 426 | DR1 Lyα BAO [22]; the DR2 analogue is companion paper DR2 I ([2503.14739](https://arxiv.org/abs/2503.14739), [63]) whose result is combined with the galaxy BAO for all cosmology inference. |
| 4 | [1807.06209](https://arxiv.org/abs/1807.06209) VERIFIED | Planck 2018 results. VI. Cosmological parameters | Planck Collaboration | 2018-07-17 | 23663 | CMB anchor [24]: sets the sound-horizon scaling, the ΛCDM parameters that DESI BAO are in 2.3σ tension with, and the θ* scale the target says DESI agrees with. |
| 5 | [2401.02929](https://arxiv.org/abs/2401.02929) VERIFIED | The Dark Energy Survey: Cosmology Results With ~1500 New High-redshift Type Ia Supernovae Using The Full 5-year Dataset | DES Collaboration | 2024-01-05 | 842 | DESY5 SN sample [31], one of the "three recent SNe datasets and likelihoods available for cosmology"; the SN sample that gives the strongest (4.2σ) preference for w0waCDM. |
| 6 | [2202.04077](https://arxiv.org/abs/2202.04077) VERIFIED | The Pantheon+ Analysis: Cosmological Constraints | Brout, Scolnic et al. | 2022-02-08 | 1837 | Pantheon+ SN likelihood [113] (data release is [2112.03863](https://arxiv.org/abs/2112.03863), [29]); the weakest-preference SN sample (2.8σ). |
| 7 | [2311.12098](https://arxiv.org/abs/2311.12098) VERIFIED | Union Through UNITY: Cosmology with 2,000 SNe Using a Unified Bayesian Framework | Rubin, Aldering et al. | 2023-11-20 | 587 | Union3 SN sample [30], third SN likelihood used in the target. |
| 8 | [2007.08991](https://arxiv.org/abs/2007.08991) VERIFIED | The Completed SDSS-IV eBOSS: Cosmological Implications from two Decades of Spectroscopic Surveys | eBOSS Collaboration (Alam et al.) | 2020-07-17 | 1755 | Previous-generation BAO cosmology [41]: the benchmark the target checks consistency against ("DR2 BAO results are consistent with DESI DR1 and SDSS") and the LRG2 discrepancy carried over from DR1. |
| 9 | [2408.07175](https://arxiv.org/abs/2408.07175) VERIFIED | Evolving Dark Energy or Supernovae Systematics? | Efstathiou | 2024-08-13 | 181 | Main external critique of the DR1 result [154]: "noted an offset in the differences between the standardized brightnesses of low- and high-z SNe for objects in common between the DESY5 and Pantheon+ samples"; motivates the target's per-SN-sample reporting. |
| 10 | [2412.13894](https://arxiv.org/abs/2412.13894) VERIFIED | Understanding acoustic scale observations: the one-sided fight against Λ | Lewis, Chamberlain | 2024-12-18 | 42 | [152] "discusses the general limitations of such models in fitting DESI+CMB data"; frames the BAO-vs-CMB ΛCDM tension in terms of θ*/Ωm, the framing the target adopts. |
| 11 | [2405.13588](https://arxiv.org/abs/2405.13588) VERIFIED | DESI 2024: Constraints on Physics-Focused Aspects of Dark Energy using DESI DR1 BAO Data | Lodha, Shafieloo et al. (DESI) | 2024-05-22 | 241 | DR1 follow-up [151] on phantom crossing and physical DE models; the DR2 analogue is companion paper [2503.14743](https://arxiv.org/abs/2503.14743) ([49]). Sister paper [2405.04216](https://arxiv.org/abs/2405.04216) ([149], crossing statistics) is cited for the non-parametric phantom-crossing evidence. |
| 12 | [2402.14070](https://arxiv.org/abs/2402.14070) VERIFIED | Baryon Acoustic Oscillation Theory and Modelling Systematics for the DESI 2024 results | Chen, Howlett et al. | 2024-02-21 | 83 | Methodology [87]: the broadband spline fitting basis "introduced in the DR1 analysis, described in detail in [87]", reused unchanged in DR2. |

Also relevant but dated after the proposed T (so excluded from the before-T set): [2502.07185](https://arxiv.org/abs/2502.07185) VERIFIED (Bansal & Huterer, 2025-02-11, "Expansion-history preferences of DESI DR2 and external data", [176]) and [2503.06712](https://arxiv.org/abs/2503.06712) VERIFIED (DES final BAO+SN implications, 2025-03-09, [42]).

## 4. One level back: chain for the top 3

Own references of each, ranked by INSPIRE citation count, keeping the ones that are on-topic rather than tooling (full lists via `https://inspirehep.net/api/arxiv/<id>`).

- **2404.03002 (DESI 2024 VI)** → [1807.06209](https://arxiv.org/abs/1807.06209) Planck 2018 VI (23663); [1607.03155](https://arxiv.org/abs/1607.03155) BOSS DR12 cosmological analysis (3485); [gr-qc/0009008](https://arxiv.org/abs/gr-qc/0009008) Chevallier & Polarski, the w0wa (CPL) parametrization (3063).
- **2404.03000 (DESI 2024 III)** → [astro-ph/0501171](https://arxiv.org/abs/astro-ph/0501171) Eisenstein et al. 2005, first BAO detection in SDSS LRGs (5296); [1607.03155](https://arxiv.org/abs/1607.03155) BOSS DR12 (3485); [1611.00036](https://arxiv.org/abs/1611.00036) DESI Part I science and survey design (2662).
- **1807.06209 (Planck 2018 VI)** → [1502.01589](https://arxiv.org/abs/1502.01589) Planck 2015 XIII (14344); [astro-ph/9805201](https://arxiv.org/abs/astro-ph/9805201) Riess et al. 1998 (19622) and [astro-ph/9812133](https://arxiv.org/abs/astro-ph/9812133) Perlmutter et al. 1999 (18893), the SN discovery of acceleration; [1607.03155](https://arxiv.org/abs/1607.03155) BOSS DR12 (3485).

So the chain is: SN acceleration (1998) → first BAO detection (2005) → BOSS/eBOSS BAO cosmology (2016-2020) + Planck (2018) → DESI DR1 BAO and its w0wa hint (April 2024) → DR2 (target).

## 5. Proposed split T and the before-T set of 8

**T = 2025-01-01.** Everything in the set is on arXiv by 2024-12-18; the target appears 2025-03-18. This T lets the club see the DR1 result, the three SN samples, and the first round of critique/interpretation, which is the material the DR2 paper actually responds to. (A harder variant would be T = 2024-04-01, pre-DR1, asking whether eBOSS + Planck + DESY5 + Union3 alone point toward a DESI w0wa preference; not recommended as the primary test because the direction would then be far less determined.)

| # | arXiv ID | title (short) | reason it belongs in the club |
|---|---|---|---|
| 1 | [2404.03002](https://arxiv.org/abs/2404.03002) | DESI 2024 VI | The DR1 cosmology paper; the target is explicitly its three-year update and inherits its data combinations and questions. |
| 2 | [2404.03000](https://arxiv.org/abs/2404.03000) | DESI 2024 III | Galaxy/quasar BAO pipeline and systematics budget that DR2 reuses; shows what a 3x larger sample will tighten. |
| 3 | [2404.03001](https://arxiv.org/abs/2404.03001) | DESI 2024 IV | Lyα BAO half of the DESI distance ladder; needed to see why DR2 splits into companion papers I and II. |
| 4 | [1807.06209](https://arxiv.org/abs/1807.06209) | Planck 2018 VI | The CMB side of the BAO-CMB ΛCDM tension that the target quantifies at 2.3σ. |
| 5 | [2401.02929](https://arxiv.org/abs/2401.02929) | DES-SN5YR | The SN sample driving the strongest w0wa preference; the club should anticipate SN-sample dependence. |
| 6 | [2007.08991](https://arxiv.org/abs/2007.08991) | eBOSS final cosmology | Previous-generation BAO cosmology; consistency with SDSS is one of the target's headline checks. |
| 7 | [2408.07175](https://arxiv.org/abs/2408.07175) | Efstathiou, evolving DE or SN systematics? | The strongest pre-T objection; the target's SN-by-SN significance table and the DES rebuttal discussion answer it directly. |
| 8 | [2412.13894](https://arxiv.org/abs/2412.13894) | Lewis & Chamberlain, one-sided fight against Λ | Pre-T theoretical framing of why DESI+CMB cannot be fit by ΛCDM-like models; the target adopts the θ*-consistent, Ωm-shifted interpretation. |

Alternates if one of the 8 is swapped: [2202.04077](https://arxiv.org/abs/2202.04077) Pantheon+, [2311.12098](https://arxiv.org/abs/2311.12098) Union3, [2405.13588](https://arxiv.org/abs/2405.13588) physics-focused DE, [2402.14070](https://arxiv.org/abs/2402.14070) BAO modelling systematics, [gr-qc/0009008](https://arxiv.org/abs/gr-qc/0009008) CPL parametrization.

Reference PDFs are not downloaded yet; IDs for the 8: 2404.03002, 2404.03000, 2404.03001, 1807.06209, 2401.02929, 2007.08991, 2408.07175, 2412.13894.

## 6. Leakage note

The target (2025-03-18) and its DR2 result were widely reported and have ~1850 citations by now, so any model with a training cutoff after March 2025 has very likely seen the headline numbers (2.3σ BAO-CMB tension, 3.1σ DESI+CMB, 2.8-4.2σ with SNe, w0>-1 and wa<0). The model running this backtest (Fable 5.1, stated knowledge cutoff June 2026) is therefore past the target date; the backtest cannot be treated as blind. Mitigations: (a) require the club to cite only before-T papers and to state predictions as numbers it derives from those papers, not recall; (b) score on reasoning traceable to the 8 inputs rather than on matching the target's final figures; (c) optionally use a model with a cutoff before 2025-03 for a second run and compare. Note that even the DR1 result (April 2024) is well inside any current model's training data, so "pointing to the direction" is only informative if the club is also asked to say what DR2 should change relative to DR1 (tension growth vs dissolution, SN-sample dependence, Lyα/galaxy consistency), which is where the before-T papers disagree.

## Sources used

- arXiv abs page: https://arxiv.org/abs/2503.14738 ; arXiv HTML (bibliography and citing sentences): https://arxiv.org/html/2503.14738
- INSPIRE record and references: https://inspirehep.net/api/arxiv/2503.14738 ; batch metadata for linked references via `https://inspirehep.net/api/literature?q=recid:...`
- Semantic Scholar: https://api.semanticscholar.org/graph/v1/paper/arXiv:2503.14738/references (returned 14 malformed entries); paper-level endpoint returned 429 on all attempts.
- Each shortlist arXiv ID: `https://arxiv.org/abs/<id>` fetched 2026-10-17, title and date read from page metadata.
