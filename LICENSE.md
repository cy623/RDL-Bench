# RDL-Bench Licences

RDL-Bench combines three kinds of material, and each is licensed separately.

| Material | Files | Licence |
|---|---|---|
| Code | `load_data.py`, `history_views/`, `verify_checksums.py`, and in this repository also `rdlbench/` and `scripts/` | MIT (below) |
| Benchmark annotations: questions, answers, SQL, splits, support instances, metadata, statistics and documentation | `data/`, `dataset_stats.csv`, `manifest.json`, `*.md`, `CITATION.cff` | CC BY-SA 4.0, except for the Olist files listed below |
| Annotations derived from Olist | `data/instances/Olist/`, `data/splits/olist.json`, `data/support/olist/` | CC BY-NC-SA 4.0 |
| Database snapshots | `DB/*.duckdb` | **Not licensed by the RDL-Bench authors.** The upstream terms apply; see `DATA_SOURCES.md` |

These licences cover only the contributions of the RDL-Bench authors. They grant no rights in the upstream data. Annotations contain values taken from the databases, such as entity names in answers, and those values stay subject to the upstream terms in `DATA_SOURCES.md`. The Stats-derived annotations are released under CC BY-SA 4.0 as permitted by the Stack Exchange CC BY-SA licences. The Olist-derived annotations follow the CC BY-NC-SA 4.0 licence of the Olist data. Use of the Dallas database is subject to the responsible-use statement in `DATA_SOURCES.md`.

- CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/
- CC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/

Attribution for the annotations: "RDL-Bench v2.0, Yao Cheng and Siqiang Luo, https://github.com/cy623/RDL-Bench". Please also cite the associated paper (see `CITATION.cff`).

## MIT License (code)

Copyright (c) 2026 Yao Cheng and Siqiang Luo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
