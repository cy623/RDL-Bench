# RDL-Bench

RDL-Bench is a benchmark for task-aware question answering over relational databases. It contains natural-language questions, task metadata, schema information, temporal context, executable evidence or target-construction logic, and structured ground-truth answers.

## Repository Contents

```text
.
├── data/
│   ├── instances/        # Released benchmark instances and metadata
│   └── json/             # Cleaned JSON files and generation/profiling utilities
├── scripts/              # Dataset construction and validation scripts
├── DB_MANIFEST.txt       # File listing for DuckDB database files
├── mysql_csv_MANIFEST.txt# File listing for source CSV files
├── rdlbench/             # Evaluation pipeline in the RDL-Bench paper.  
├── requirements.txt
├── DATASET_CARD.md
└── CITATION.cff
```

## Data Download

The lightweight repository contains benchmark metadata, instance files, and dataset construction scripts.

Large files are provided through the GitHub Release:

- Release page: [RDL-Bench](https://github.com/cy623/RDL-Bench/releases/tag/v1.0)

Please download the following assets from the release page:

- `dataset.zip`: benchmark instance files
- `DB.zip`: database files
- `mysql_csv.zip`: CSV exports
- `json_cleaned.zip`: cleaned JSON construction files

After downloading, place the files under the corresponding directories described in `DATASET_CARD.md`.

## Data Format

Each benchmark instance is represented as JSON with the following main components:

- `instance_id`: unique instance identifier.
- `metadata`: task type, answer nature, complexity, involved tables, and temporal fields when available.
- `question`: primary natural-language question and optional variants.
- `evidence`: SQL evidence for reasoning tasks or target-construction logic for predictive tasks.
- `ground_truth`: structured answer stored in `raw_value`.

Primary evaluation should use the structured `raw_value` field rather than natural-language answer surface forms.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Typical Workflow

The scripts are organized by construction stage:

```text
1_data_install.py              # Export source relational tables to CSV
2_data_2db.py                  # Convert CSV tables to DuckDB databases
3_generate_metajson.py         # Generate metadata JSON files
5_sample_Context.py            # Sample context information
6_repeat_check.py              # Check duplicate or repeated instances
7_generate_raw_value1.py       # Execute SQL and fill structured ground truth
8_generate_nl_answer.py        # Generate formatted natural-language answers
9_check.py                     # Run final consistency checks
```

Some scripts require setting the target domain name and paths before execution. Avoid committing machine-specific absolute paths.

## Notes

- Use only records before the reference time for predictive feature construction.
- Evaluate reasoning tasks against structured ground truth.
- For instances whose answer type is `set`, the answer stored in the released JSON files may be truncated for readability and file-size control. The truncated value should not be treated as the complete gold answer. To obtain the complete set-valued answer, users should reconstruct it from the `evidence` field. For reasoning instances, this usually means executing the provided SQL query against the corresponding database.

## Configuration

`config.yaml` controls all paths and hyperparameters:

```yaml
data_dir:   ../json          # directory with per-dataset JSON files
db_dir:     ../DB            # directory with *.duckdb databases
output_dir: results          # where result JSON files are written
model_name: claude-sonnet-4-6
api_key:    ""               # leave blank if using ANTHROPIC_API_KEY env var
```

## Citation

If you use RDL-Bench, please cite the paper associated with this repository.
