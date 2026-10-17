# Journal club on AlphaFold alternative conformations: backtest review

Run: `runs/afconf-bt-1` (shipped in `backend/journal_club/examples/`). Card set `afconf`: 6 papers before T, 2 after. T = 2026-07-01, the month after the main model's training cutoff (Claude Opus 5.5, June 2026), so the after-T papers cannot be in its training data. Club and baseline on `claude-opus-5-5`, judge on `claude-sonnet-5-5`. Run on 2026-10-17.

## Why this set

The DESI example had all papers analyse one observation (the same BAO, CMB and SN data), so the map found little real disagreement and directions read as "more data". This set was chosen the other way round:

1. Post-cutoff papers first: arXiv 2608.02866 (Porter lab perspective, 2026-08-03) and bioRxiv 2026.08.28.747824 (ProtMonomer, 2026-08-31).
2. Then the pre-T papers they both cite. The six below are cited by both after-T papers and by SF-Cluster (arXiv 2607.00180, 2026-06-30, left out as it sits on the cutoff).

| card id | citekey | paper | date | role |
|---|---|---|---|---|
| paper2 | delalamo2022alphafold2 | del Alamo et al., eLife 11:e75751 | 2022-03-03 | before |
| paper3 | stein2022speachaf | Stein & Mchaourab, SPEACH_AF, PLoS Comput Biol 18:e1010483 | 2022-08-22 | before |
| paper4 | waymentsteele2024afcluster | Wayment-Steele et al., AF-Cluster, Nature 625:832 | 2024-01-25 | before |
| paper5 | chakravarty2024alphafold | Chakravarty et al., memorisation, Nat Commun 15:7296 | 2024-08-24 | before |
| paper6 | bryant2024cfold | Bryant & Noé, Cfold, Nat Commun 15:7328 | 2024-08-26 | before |
| paper7 | lee2025cfrandom | Lee et al., CF-random, Nat Commun 16 | 2025-07-01 | before |
| 2608_02866v1 | chakravarty2026statespace | Chakravarty, ..., Porter, arXiv 2608.02866v1 | 2026-08-03 | after |
| paper9 | si2026protmonomer | Si, Zhang & Chen, ProtMonomer, bioRxiv 2026.08.28.747824 | 2026-08-31 | after |

## How the cards were made (route 2, the default)

1. PDFs downloaded (publisher open-access copies; arXiv pinned to v1; bioRxiv v1) and saved to the library with `POST /papers` (library papers 2-9).
2. Card set made from the library with `club.Ingest` (the code behind **Make a card set from your library**), now one Claude call per paper in parallel (`JC_CONCURRENCY`). 8 papers in 31.8 s, 0 failures, 4 claims and 3 limits kept per card after the quote gate, $2.00 in all.
3. Three cards got a year-only date (`<year>-01-01`): route 2 gives the ingest only `paper.year` as a hint. They were corrected by hand to the Crossref dates (paper5, paper6, paper7). No card crossed T either way.

Known weaknesses seen on this set:
- Five of eight papers were longer than the ingest's 60 000-character cap (ProtMonomer 115k, AF-Cluster 95k), so limitations stated late in a discussion or in the methods were never shown to the model.
- Journal papers get `paper<N>` card ids (only arXiv papers get their id), so minutes and maps read better by citekey.

## Results

_Filled in after the run._

## Logs

`docs/journal-club/afconf-bt-1-logs/`: `01_download.log`, `02_save_to_library.log`, `03_card_set.log`, `04_date_fix.log`, `05_backtest.log`, and `sources.json` (URL, DOI and library id of every paper).
