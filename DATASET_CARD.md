# RDL-Bench Dataset Card

RDL-Bench v2.0 contains 4,040 QA records across Olist, Stats, NCAA, Hepatitis, Financial, Dallas and Airline, with fixed training, validation and test splits. It includes 8,255 historical/evaluation support instances and seven DuckDB snapshots. The data supports relational QA, task understanding, SQL-based reasoning and question-conditioned predictive learning.

## Supervision and evaluation populations

QA train/validation/test contain 2,425/810/805 questions. Historical support train/validation/test contain 5,052/1,616/1,587 labeled instances. The original QA test contains 618 Reasoning and 187 Prediction questions. The fixed expanded Prediction test has 1,774 instances: 187 original predictive QA questions and 1,587 additional evaluation-only instances. Hepatitis has no Prediction tasks. Statistics by domain are in `dataset_stats.csv`.

QA supervision is a question split; it must not be interpreted as chronological predictor-label supervision. Predictor fitting and adaptation use historical support/train, selection uses support/validation, and support/test is evaluation-only. Every support instance is linked to a parent question and an existing bound SQL execution record. Future outcomes, execution SQL, test labels and availability metadata are not model-input features. Gold Task Spec annotations are not generated Task Specs.

## Intended use

The release supports research on question answering, relational reasoning and prediction over relational databases. Cite the associated work and state the version you used, for example "RDL-Bench v2.0". The release is not intended for operational decisions about any person, organization or account represented in the databases.

## Data sources and licences

All seven databases were exported from the CTU Prague Relational Learning Repository. Each keeps the terms of its original publisher.

| Database | Original source | Upstream terms |
|---|---|---|
| Olist | Brazilian E-Commerce Public Dataset by Olist | CC BY-NC-SA 4.0 |
| Stats | Stack Exchange data dump (Cross Validated) | CC BY-SA 2.5 / 3.0 |
| Airline | U.S. Bureau of Transportation Statistics | U.S. government data |
| Dallas | Dallas Police Department disclosures | Public records; responsible-use statement applies |
| NCAA | Kaggle March Machine Learning Mania 2015 | Kaggle competition rules |
| Hepatitis | ECML/PKDD Discovery Challenge (Chiba University Hospital) | Challenge release; no public licence found |
| Financial | PKDD'99 Discovery Challenge (Berka) | Challenge release; no public licence found |

`DATA_SOURCES.md` gives full provenance, attribution text and caveats for each database. `LICENSE.md` gives the licences for the RDL-Bench contributions:

- the code is under MIT;
- the annotations are under CC BY-SA 4.0;
- the Olist-derived annotations are under CC BY-NC-SA 4.0.

The database snapshots are not relicensed.

## Personal and sensitive data

- **Dallas** contains public records of police officer-involved shootings. It includes the names, race and gender of the officers and of the people they shot at, injury and death outcomes, and grand-jury dispositions. The names were published by the Dallas Police Department and are not anonymized in RDL-Bench. Some v2 questions refer to named individuals. Use of this database is subject to the responsible-use statement in `DATA_SOURCES.md`: aggregate-level research only, and no profiling of or decisions about individuals.
- **Hepatitis** contains de-identified clinical records in which patients appear only as numeric identifiers. Do not attempt re-identification.
- **Financial** contains anonymized bank data and **Stats** contains public Stack Exchange contributions, which keep user display names.

## Integrity

The v2.0 release page provides `SHA256SUMS`, which lists a SHA-256 checksum for every file in the archive, and `verify_checksums.py`. To check a download, put both files in the unzipped folder and run `python verify_checksums.py`, or run `sha256sum -c SHA256SUMS`. Add `--skip-db` for a quick check that leaves out the database snapshots. `SHA256SUMS` is the authoritative checksum list. Some entries in the `files` section of `manifest.json` are outdated (see below).

## Known packaging notes

- The `files` section of `manifest.json` was written before the final edits to `CHANGELOG.md`, `DATASET_CARD.md` and the six `data/support/<domain>/test_metadata.json` files, so their recorded checksums are outdated. The final edit to each `test_metadata.json` added an `audit_path_base` field and did not change labels or instance lists. The section also lists a `README.md` that the archive does not contain; the README is kept in this repository instead. All database, QA and support files match their recorded checksums.
- The archive contains four macOS `.DS_Store` files and a `__MACOSX` folder. They can be deleted safely.

- The `audit_path` field in `data/support/<domain>/test_metadata.json` names `provenance/support/<domain>.jsonl`. These provenance files are not included in the distribution. The field is kept unchanged so that the data stays identical to v2.0.
- Instance IDs are unique only within a database. Join support rows to QA records on `(domain, parent_question_id)`.
