# RDL-Bench Dataset Card

RDL-Bench v2.0 contains 4,040 QA records across Olist, Stats, NCAA, Hepatitis, Financial, Dallas and Airline, with fixed training, validation and test splits. It includes 8,255 historical/evaluation support instances and seven DuckDB snapshots. The data supports relational QA, task understanding, SQL-based reasoning and question-conditioned predictive learning.

## Supervision and evaluation populations

QA train/validation/test contain 2,425/810/805 questions. Historical support train/validation/test contain 5,052/1,616/1,587 labeled instances. The original QA test contains 618 Reasoning and 187 Prediction questions. The fixed expanded Prediction test has 1,774 instances: 187 original predictive QA questions and 1,587 additional evaluation-only instances. Hepatitis has no Prediction tasks. Statistics by domain are in `dataset_stats.csv`.

QA supervision is a question split; it must not be interpreted as chronological predictor-label supervision. Predictor fitting and adaptation use historical support/train, selection uses support/validation, and support/test is evaluation-only. Every support instance is linked to a parent question and an existing bound SQL execution record. Future outcomes, execution SQL, test labels and availability metadata are not model-input features. Gold Task Spec annotations are not generated Task Specs.

## Intended use and source terms

The release supports research on relational reasoning and prediction. Source databases retain their upstream usage and redistribution terms. No additional blanket data license is assigned by this packaging step. RDL-Bench metadata and source attribution from the earlier repository remain available at https://github.com/cy623/RDL-Bench. Cite the associated work and identify the version used.
