# Before-T reference set for the DESI DR2 backtest

Target paper: arXiv:2503.14738 (DESI DR2 Results II, v1 2025-03-18). Split T = 2025-01-01.
Context and selection rationale: `/Users/jacky/Documents/temp/research/review/target_paper.md`, section 5.

Downloaded 2026-10-17 from `https://arxiv.org/pdf/<id>` (bare URL succeeded for every ID; no v1 fallback was needed).
Each file was checked with `file` (all report "PDF document, version 1.5") and must exceed 50 KB.
Title, first author and v1 date were read from each paper's `https://arxiv.org/abs/<id>` page (`citation_title`, first `citation_author`, and the `[v1]` line of the submission history).

| filename | arXiv | title | first author | v1 date | size | status |
|---|---|---|---|---|---|---|
| 2404.03002_desi-2024-vi-bao-cosmology.pdf | [2404.03002](https://arxiv.org/abs/2404.03002) | DESI 2024 VI: Cosmological Constraints from the Measurements of Baryon Acoustic Oscillations | DESI Collaboration (A. G. Adame) | 2024-04-03 | 3,898,877 B (3.7 MB) | OK |
| 2404.03000_desi-2024-iii-galaxy-bao.pdf | [2404.03000](https://arxiv.org/abs/2404.03000) | DESI 2024 III: Baryon Acoustic Oscillations from Galaxies and Quasars | DESI Collaboration (A. G. Adame) | 2024-04-03 | 3,677,757 B (3.5 MB) | OK |
| 2404.03001_desi-2024-iv-lya-bao.pdf | [2404.03001](https://arxiv.org/abs/2404.03001) | DESI 2024 IV: Baryon Acoustic Oscillations from the Lyman Alpha Forest | DESI Collaboration (A. G. Adame) | 2024-04-03 | 3,355,666 B (3.2 MB) | OK |
| 1807.06209_planck-2018-vi.pdf | [1807.06209](https://arxiv.org/abs/1807.06209) | Planck 2018 results. VI. Cosmological parameters | Planck Collaboration (N. Aghanim) | 2018-07-17 | 9,317,371 B (8.9 MB) | OK |
| 2401.02929_des-sn5yr.pdf | [2401.02929](https://arxiv.org/abs/2401.02929) | The Dark Energy Survey: Cosmology Results With ~1500 New High-redshift Type Ia Supernovae Using The Full 5-year Dataset | DES Collaboration (T. M. C. Abbott) | 2024-01-05 | 14,626,143 B (13.9 MB) | OK |
| 2007.08991_eboss-final-cosmology.pdf | [2007.08991](https://arxiv.org/abs/2007.08991) | The Completed SDSS-IV extended Baryon Oscillation Spectroscopic Survey: Cosmological Implications from two Decades of Spectroscopic Surveys at the Apache Point observatory | eBOSS Collaboration (Shadab Alam) | 2020-07-17 | 2,951,228 B (2.8 MB) | OK |
| 2408.07175_efstathiou-sn-systematics.pdf | [2408.07175](https://arxiv.org/abs/2408.07175) | Evolving Dark Energy or Supernovae Systematics? | George Efstathiou | 2024-08-13 | 1,340,080 B (1.3 MB) | OK |
| 2412.13894_lewis-chamberlain.pdf | [2412.13894](https://arxiv.org/abs/2412.13894) | Understanding acoustic scale observations: the one-sided fight against Lambda | Antony Lewis (with Ewan Chamberlain) | 2024-12-18 | 3,275,400 B (3.1 MB) | OK |

Result: 8 of 8 downloaded, 0 failed. All files pass the `file` check and the 50 KB minimum.

Date check: all 8 v1 submission dates are before T = 2025-01-01 (earliest 2018-07-17, latest 2024-12-18). None flagged.

Note: the PDFs were not opened or executed; verification used `file` and byte size only. For the collaboration papers the arXiv metadata lists the collaboration as first author; the first named individual is given in parentheses.

## Version pinning (added 2026-10-17)

The bare arXiv PDF URL serves the latest version, and three papers had versions posted after T = 2025-01-01. Those files were replaced with the last version before T:

| arXiv | versions | on disk |
|---|---|---|
| 2401.02929 (DES-SN5YR) | v1 2024-01-05, v2 2024-01-08, v3 2024-06-07, v4 2025-07-20 | **v3** |
| 2408.07175 (Efstathiou) | v1 2024-08-13, v2 2024-10-16, v3 2025-02-03 | **v2** |
| 2412.13894 (Lewis & Chamberlain) | v1 2024-12-18, v2 2025-02-27, v3 2025-04-23 (uses DESI DR2) | **v1** |

The other five have no version after T (2404.03002 v3 2024-11-04; 2404.03000 v1; 2404.03001 v4 2024-09-27; 1807.06209 v4 2021-08-09; 2007.08991 v2 2024-07-09).
