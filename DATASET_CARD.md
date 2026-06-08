# Dataset Card: RDL-Bench

## Overview

RDL-Bench is a benchmark for question answering over relational databases. It covers reasoning tasks answered from observable database states and predictive tasks whose targets are constructed from future records under temporal constraints.

## Data Components

- Natural-language questions and paraphrases
- Task metadata
- Schema information
- SQL evidence or target-construction logic
- Temporal context
- Structured ground truth

## Domains

The benchmark includes multiple real-world relational database domains, including e-commerce, finance, sports, healthcare, transportation, social platforms, and government data.

## Intended Use

The dataset is intended for research on relational database question answering, task routing, text-to-SQL, table QA, and relational predictive modeling.

## Evaluation

Use task-appropriate metrics. Reasoning tasks should be evaluated against structured answers. Predictive classification and regression should be evaluated separately.

## Limitations

Results may depend on schema complexity, answer type, temporal signal strength, and domain-specific data distribution. Users should verify source data licenses before redistribution.
