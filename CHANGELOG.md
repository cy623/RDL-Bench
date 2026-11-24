# RDL-Bench Release Changes

## Version 2.0

- Publish fixed QA splits with 2,425 training, 810 validation and 805 test questions.
- Add 5,052 historical training and 1,616 historical validation prediction instances.
- Publish 1,587 evaluation-only support/test instances and the fixed 1,774-instance merged Prediction test population.
- Include all seven database snapshots, schema metadata, sample-to-parent mappings, bound label SQL and domain-specific historical feature views.
- Some QA identifiers differ from earlier public files; do not combine v1.0 instance files with v2.0 support files.

## Documentation update (November 2026)

No new version was released. The v2.0 archive and all data in it are unchanged; only the repository documentation and the release page were updated.

- Add `SHA256SUMS`, which lists a checksum for every file in the v2.0 archive, and `verify_checksums.py`, a checker that needs only the Python standard library. Both are attached to the v2.0 release page.
- Document the outdated entries in the `files` section of `manifest.json`. They cover `CHANGELOG.md`, `DATASET_CARD.md` and six `data/support/<domain>/test_metadata.json` files, whose recorded checksums predate final edits; the edits to `test_metadata.json` only added an `audit_path_base` field. The section also lists a `README.md` that the archive does not contain. All database, QA and support files match their recorded checksums. `SHA256SUMS` is now the authoritative checksum list.
- Add `DATA_SOURCES.md`, which gives the provenance, upstream terms and attribution for each of the seven databases, together with a responsible-use statement for Dallas.
- Add `LICENSE.md`:
  - code under MIT;
  - annotations under CC BY-SA 4.0;
  - Olist-derived annotations under CC BY-NC-SA 4.0;
  - database snapshots keep their upstream terms.
- Update `README.md` and `DATASET_CARD.md` with sections on intended use, data sources, personal and sensitive data, integrity and known packaging notes.
- Add `type` and `license` fields to `CITATION.cff`.
