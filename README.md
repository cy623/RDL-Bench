# RDL-Bench

RDL-Bench supports natural-language reasoning and prediction over seven relational databases. Version 2.0 adds historical training and validation support instances, publishes fixed QA splits.

## Download

Download [rdl-bench-v2.0-full.zip](https://github.com/cy623/RDL-Bench/releases/download/v2.0/rdl-bench-v2.0-full.zip) from the [v2.0 release](https://github.com/cy623/RDL-Bench/releases/tag/v2.0). The full archive includes all seven DuckDB database snapshots, QA, schema metadata, support instances, historical feature-view code, and a portable data reader. No separate DB.zip is needed for this version.

```bash
unzip rdl-bench-v2.0-full.zip
cd rdl-bench-v2.0
python -m pip install -r requirements.txt
python load_data.py --summary
```


## Dataset layout

```text
rdl-bench-v2.0/
├── DB/                             # Seven read-only database snapshots
├── data/
│   ├── instances/<database>/       # Complete QA JSON and schema metadata
│   ├── splits/<domain>.json        # Ordered QA IDs for each split
│   └── support/<domain>/           # train/validation/test, config and parent mapping
├── history_views/                  # Domain-specific historical feature policies
├── dataset_stats.csv
├── manifest.json
└── load_data.py
```

The database folder names and complete QA filenames under `data/instances/` follow the earlier repository layout. File paths for every domain are listed in `manifest.json`. The `data/instances/` arrays contain the union of the three v2.0 QA splits.

## Dataset statistics

| Database | QA train | QA val | QA test | Support train | Support val | Support test | Prediction test |
|---|---:|---:|---:|---:|---:|---:|---:|
| Olist | 419 | 140 | 140 | 1100 | 366 | 370 | 407 |
| stats | 437 | 146 | 146 | 850 | 290 | 280 | 308 |
| NCAA | 325 | 107 | 105 | 980 | 230 | 213 | 242 |
| hepatitis | 150 | 50 | 50 | 0 | 0 | 0 | 0 |
| financial | 214 | 72 | 71 | 950 | 310 | 310 | 341 |
| Dallas | 244 | 82 | 81 | 520 | 180 | 165 | 198 |
| Airline | 636 | 213 | 212 | 652 | 240 | 249 | 278 |

Totals: 2,425 / 810 / 805 QA questions and 5,052 / 1,616 / 1,587 support instances in train / validation / test. Hepatitis contains only Reasoning tasks and has empty support arrays. Support counts measure labeled entity/time instances; they are not counts of independent tasks or independent future events.

## Training and evaluation

Use QA train/validation to learn and select task-understanding models such as a Task Spec Generator. Original predictive QA answers are future outcomes; their question-level split is not a temporal split of predictor labels. Train predictive models on `support/train.json`, and select hyperparameters/checkpoints on `support/validation.json`. Target-domain few-shot and full-data adaptation also use `support/train.json`.

`support/test.json` contains evaluation-only prediction instances. Its labels must not be used for adaptation, prompt demonstrations or model selection. The fixed expanded Prediction test set combines 187 original predictive QA test questions with 1,587 evaluation-only support instances, following the recorded temporal and instance-identity protocol. Use `load_data.prediction_test()` to obtain exactly these 1,774 instances. The reader assembles this population directly from the existing QA and support/test arrays, without separate copies of the questions or labels. The original QA test contains 618 Reasoning and 187 Prediction questions. Use those 618 questions for Reasoning and the merged 1,774 instances for expanded Prediction evaluation; report which population is used.

Feature construction must use each instance's historical cutoff. Use the supplied historical views, including the published domain-specific availability assumptions. Full snapshots support execution of the SQL retained in QA evidence. 

```python
from load_data import qa, support, prediction_test, open_history

training_questions = qa("olist", "train")
training_labels = support("olist", "train")
test_inputs = prediction_test("olist")  # labels are omitted by default

sample = training_labels[0]
history = open_history("olist", sample["reference_time"])
try:
    rows = history.execute("SELECT COUNT(*) FROM olist_orders_dataset").fetchall()
finally:
    history.close()
```

## Data format

QA records retain `instance_id`, `metadata`, `question`, `evidence`, and `ground_truth`. Support records contain `sample_id`, `domain`, `parent_question_id`, `parent_split`, `question`, `anchor`, `reference_time`, `task_type`, `relevant_tables`, and `label`. Associate a support row with its QA using `(domain, parent_question_id)`; instance IDs are not globally unique across databases.

Support labels are stored scalar database query results; Boolean results are represented as 0/1. Per-instance support execution records are not included in this distribution. QA evidence retains its `golden_sql`. For set-valued Reasoning answers, a stored `raw_value` can be truncated; execute the record's evidence SQL to reconstruct the complete answer.


## Historical feature policy

`load_data.open_history(domain, reference_time)` opens historical views over a read-only database snapshot. Features follow each instance's own reference time; predictor fitting uses support/train, selection uses support/validation, and support/test is evaluation-only. The fixed merged test excludes duplicate instances and training/validation overlaps, and its observation times satisfy the recorded training/validation label-availability boundary. Its membership is determined directly by the published QA test split and support/test arrays; do not sample a replacement test set.

Support anchors use table/key/value. `question_to_support.json` associates support rows with parent QA records. `prediction_test()` omits labels by default; `include_labels=True` adds them for scoring. It reads the predictive questions in the QA test split followed by support/test, with no additional index file or copied test arrays.

