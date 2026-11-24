# RDL-Bench Data Sources and Terms

This file records where each database snapshot in `DB/` comes from, the terms that apply to it, and how to attribute it. The terms of the upstream data are set by its original publishers. RDL-Bench does not relicense them. `LICENSE.md` covers only the material written by the RDL-Bench authors.

This summary is provided for convenience and is not legal advice. Before commercial or other non-research use, check the original terms linked below.

## How the snapshots were obtained

All seven databases were exported from the public MariaDB server of the **CTU Prague Relational Learning Repository** (Motl and Schulte, arXiv:1511.03086; https://relational.fel.cvut.cz). Each table was exported to CSV and loaded into a read-only DuckDB file. The export script is `scripts/1_data_install.py` in https://github.com/cy623/RDL-Bench. RDL-Bench did not anonymize or remove rows from any database.

The CTU repository re-hosts data from many original publishers and does not attach a single licence to them. The terms below therefore come from each original source. Some other benchmarks that redistribute CTU data label it with their own licence. Such a label is chosen by that redistributor and does not change the original terms.

Please cite the CTU repository when you use any of these databases:

```bibtex
@misc{motl2024ctupraguerelationallearning,
  title         = {The CTU Prague Relational Learning Repository},
  author        = {Jan Motl and Oliver Schulte},
  year          = {2024},
  eprint        = {1511.03086},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/1511.03086}
}
```

## Summary

| Database | Original source | Upstream terms | Redistribution status |
|---|---|---|---|
| Olist | Olist, Brazilian E-Commerce Public Dataset (Kaggle) | CC BY-NC-SA 4.0 | Permitted with attribution, for non-commercial use only, under the same licence |
| Stats | Stack Exchange data dump, Cross Validated (stats.stackexchange.com) | CC BY-SA 2.5 / 3.0, depending on posting date | Permitted with attribution, under the same licence |
| Airline | U.S. Bureau of Transportation Statistics, Airline On-Time Performance | U.S. federal government data | Generally free of copyright restrictions in the U.S.; attribution requested |
| Dallas | Dallas Police Department, officer-involved shooting disclosures | Public-records release (see the Dallas section) | Public records that contain names; see the responsible-use statement |
| NCAA | Kaggle, March Machine Learning Mania 2015 competition data | Kaggle competition rules | **Unclear.** The rules do not expressly grant redistribution |
| Hepatitis | ECML/PKDD Discovery Challenge, Chiba University Hospital data | Released for the discovery challenge; no public licence | **Unclear.** No explicit licence was found |
| Financial | PKDD'99 Discovery Challenge (Berka), anonymized Czech bank data | Released for the discovery challenge; no public licence | **Unclear.** No explicit licence was found |

"Unclear" means the authors could not find a public licence that expressly allows redistribution. These databases have circulated widely in research for many years, including through the CTU repository. Users who need certainty for their use should consult the original publisher.

## Per-database details

### Olist

- **Snapshot:** `DB/Olist.duckdb`. It has 9 tables and 1,550,922 rows. Orders were placed from 2016-09 to 2018-10.
- **Original source:** Brazilian E-Commerce Public Dataset by Olist, https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
- **Upstream licence:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0). This licence permits redistribution and adaptation with attribution. Commercial use is not allowed, and adaptations must be shared under the same licence.
- **Effect on RDL-Bench files:** the questions, answers, splits and support instances derived from Olist are also distributed under CC BY-NC-SA 4.0 (see `LICENSE.md`). They are:
  - `data/instances/Olist/`
  - `data/splits/olist.json`
  - `data/support/olist/`
- **Attribution:** "Brazilian E-Commerce Public Dataset by Olist, CC BY-NC-SA 4.0, via the CTU Prague Relational Learning Repository."

### Stats

- **Snapshot:** `DB/stats.duckdb`. It has 8 tables and 1,029,842 rows. Posts date from 2009-02-02 to 2014-09-14.
- **Original source:** the anonymized Stack Exchange data dump for Cross Validated (stats.stackexchange.com), hosted at the Internet Archive (https://archive.org/details/stackexchange).
- **Upstream licence:** Stack Exchange user contributions are licensed under Creative Commons Attribution-ShareAlike. The version depends on when the content was posted:
  - CC BY-SA 2.5 for content posted before 2011-04-08.
  - CC BY-SA 3.0 for content posted from 2011-04-08 to 2018-05-01.

  Both versions allow adaptations to be released under a later version of the same licence.
- **Effect on RDL-Bench files:** content derived from Stats is distributed under CC BY-SA 4.0. This is the default licence for RDL-Bench annotations (see `LICENSE.md`).
- **Attribution:** "Cross Validated (stats.stackexchange.com) user contributions, Stack Exchange Inc., licensed under CC BY-SA, via the CTU Prague Relational Learning Repository." Stack Exchange asks that republished posts link back to the original post and credit its author. The snapshot keeps post and user identifiers, so the original of a question can be found at `https://stats.stackexchange.com/q/<Id>` and of an answer at `https://stats.stackexchange.com/a/<Id>`.

### Airline

- **Snapshot:** `DB/Airline.duckdb`. It has 19 tables and 481,415 rows. The tables are:
  - `on_time_on_time_performance_2016_1`, with 445,827 domestic flights from January 2016;
  - 18 BTS code lookup tables, named `l_*`.
- **Original source:** U.S. Department of Transportation, Bureau of Transportation Statistics, Airline On-Time Performance Data, https://www.transtats.bts.gov
- **Upstream terms:** works of the U.S. federal government are not subject to copyright in the United States (17 U.S.C. § 105). BTS asks users to credit the source.
- **Attribution:** "Source: Bureau of Transportation Statistics, U.S. Department of Transportation, via the CTU Prague Relational Learning Repository."

### Dallas

- **Snapshot:** `DB/Dallas.duckdb`. It has 3 tables (`incidents`, `officers`, `subjects`) and 812 rows. The data covers 219 incidents from 2003-01-11 to 2016-08-25.
- **Original source:** officer-involved shooting data that the Dallas Police Department published starting in 2014. The CTU repository took it from the Stanford public-affairs data-journalism course collection (2016.padjo.org).
- **Upstream terms:** these are public records released by a municipal police department. The City of Dallas Open Data portal publishes police datasets under the Open Data Commons Attribution License. The authors could not confirm which terms applied to the 2016 copy used here.
- **Personal data:** the department published this data with personal details, and the `officers` and `subjects` tables keep them. These include:
  - the full names of the officers involved;
  - the full names of the people they shot at;
  - race and gender;
  - injury or death outcomes;
  - grand-jury dispositions.

  RDL-Bench does not anonymize these tables. Some v2 questions refer to named individuals.
- **Attribution:** "Dallas Police Department officer-involved shooting data, via 2016.padjo.org and the CTU Prague Relational Learning Repository."
- **Responsible-use statement:** read the statement below before you use this database.

#### Responsible-use statement for the Dallas database

The Dallas database is distributed only to support reproducible, aggregate-level research on question-answering and prediction systems over relational databases. We ask users to follow these conditions:

1. Do not use the data or any model trained on it to identify, profile, contact or make decisions about any individual officer or civilian. This includes uses for employment, legal, enforcement or insurance purposes.
2. Do not present model outputs about named people as statements of fact. Report results only at the level of the benchmark or database.
3. Do not redistribute the `officers` and `subjects` tables separately from the benchmark, and do not join them with other data to enrich them with personal information.
4. Remember that incident records describe serious events affecting real people. They should not be used for demonstrations or examples in a casual or sensational manner.

Concerns or removal requests about this database can be raised through the repository issue tracker, https://github.com/cy623/RDL-Bench/issues.

### NCAA

- **Snapshot:** `DB/NCAA.duckdb`. It has 9 tables and 202,305 rows, covering the 1985 to 2015 seasons of NCAA Division I men's basketball.
- **Original source:** Kaggle, March Machine Learning Mania 2015, https://www.kaggle.com/c/march-machine-learning-mania-2015/data
- **Upstream terms:** the competition data is governed by the rules that participants accepted on Kaggle. Kaggle competition rules usually limit use of the data to the competition, research, education and other non-commercial purposes, and do not expressly grant redistribution. The authors have not been able to confirm the exact 2015 terms. The game results themselves are factual records.
- **Attribution:** "NCAA basketball data from the Kaggle March Machine Learning Mania 2015 competition, via the CTU Prague Relational Learning Repository."
- **Note:** if the publisher asks for this database to be removed, `DB/NCAA.duckdb` can be rebuilt from the CTU server with the export script, and the QA files can stay unchanged.

### Hepatitis

- **Snapshot:** `DB/hepatitis.duckdb`. It has 7 tables (`bio`, `dispat`, `indis`, `inf`, `rel11`, `rel12`, `rel13`) and 12,927 rows. This is the CTU `Hepatitis_std` version prepared by Oliver Schulte. In that version, numeric attributes were discretized and only 500 of the 690 patients are present.
- **Original source:** the hepatitis temporal database collected at Chiba University Hospital, Japan, from 1982 to 2001. It was released for the ECML/PKDD Discovery Challenges (2002 to 2005) and is also available from https://www.cs.sfu.ca/~oschulte/jbn/dataset.html.
- **Upstream terms:** the data was released to participants of the discovery challenge. The authors found no public licence. The records are de-identified clinical data: patients appear only as numeric identifiers.
- **Attribution:** "Hepatitis data from Chiba University Hospital, ECML/PKDD Discovery Challenge, Hepatitis_std version by O. Schulte, via the CTU Prague Relational Learning Repository."
- **Use:** research use only. Do not try to re-identify patients.

### Financial

- **Snapshot:** `DB/financial.duckdb`. It has 8 tables and 1,079,680 rows, covering transactions from 1993 to 1998. This is the CTU `Financial` version by Jan Motl, which added foreign keys and split the birth number into date of birth and gender.
- **Original source:** the PKDD'99 Discovery Challenge Financial Data Set, which contains anonymized data from a Czech bank, prepared by Petr Berka. It is archived at https://web.archive.org/web/20180506061559/http://lisp.vse.cz/pkdd99/Challenge/chall.htm. The dataset is described in P. Berka, "Guide to the Financial Data Set", PKDD 2000 Discovery Challenge.
- **Upstream terms:** the data was released for the discovery challenge. The authors found no public licence.
- **Attribution:** "PKDD'99 Discovery Challenge Financial Data Set (P. Berka), via the CTU Prague Relational Learning Repository."

## Changes to this file

This file was added in November 2026. If you hold rights in any of these sources and have concerns, please open an issue at https://github.com/cy623/RDL-Bench/issues.
