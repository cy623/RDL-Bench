config = {
    # 1. statistics (Demographics & Categorical Entities)
    # table。generate“(type=0)(sex=1)”“60-69(age=5)”question
    "dispat": ["sex", "age", "type"], 

    # 2.  (Clinical Pathology Features)
    # tablecheck/。generate“ F4 (fibros=4)”“ (activity=4)”question
    "bio": ["fibros", "activity"],
    
    # 3. Extreme and boundary values (Edge Cases/Specific Metrics - Lab Results)
    # （）。
    # （ che 0-9, ttt 0-5），generate“(che)3”“(got)3”numeric valuequestion
    "indis": ["got", "gpt", "che", "ttt", "ztt", "tcho", "tp", "alb", "tbil", "dbil"],
    
    # 4. time/ (Duration/Temporal Anchors)
    # date(Date)，time。generate“(dur=4)”question
    "inf": ["dur"]
}

{'dispat': {'sex': ['1', '0'], 'age': ['2', '5', '3', '0', '4'], 'type': ['0', '1']}, 
 'bio': {'fibros': ['2', '3', '4', '0', '1'], 'activity': ['1', '2', '4', '0', '3']}, 
 'indis': {'got': ['1', '3', '0', '2', '4'], 
           'gpt': ['2', '3', '0', '1'], 
           'che': ['8', '3', '0', '5', '1'], 
           'ttt': ['2', '1', '4', '0', '5'], 
           'ztt': ['1', '5', '0', '2', '3'], 
           'tcho': ['2', '0', '1', '3'], 
           'tp': ['1', '2', '3', '0'], 
           'alb': ['1', '0'], 
           'tbil': ['0', '1'], 
           'dbil': ['0', '1']}, 
 'inf': {'dur': ['3', '1', '2', '0', '4']}
 }

promt = """
You are an expert Data Scientist and Database Evaluation Specialist. Your task is to construct a high-quality benchmark for NL2SQL and RAG systems. You will generate questions that are logically grounded in the database's temporal distribution. The JSON file is a Database Context (Schema & Profiling) file. 

Objective:
Generate 20 unique question-SQL pairs for Retrieval, Analytical, and Relational Reasoning categories.    
Current Batch Task:

Batch Number: Batch #1

Start ID Number: 001

Quantity: Generate 20 instances.

1. Query Categories & Requirements
Retrieval: Focus on precise data fetching. Use various filters (numerical ranges, string matching, date comparisons).

Analytical: Focus on multi-dimensional aggregation. Use GROUP BY, HAVING, and aggregate functions (SUM, AVG, COUNT, MAX/MIN).

Relational Reasoning: High Difficulty. Focus on multi-hop logic. Must involve multiple JOINs, subqueries (IN, EXISTS, NOT EXISTS), or set operations (EXCEPT, INTERSECT).

2. Autonomous Temporal Selection (CRITICAL)
For each question, you must autonomously select a specific reference_time or time range based on the temporal_coverage provided in the Profiling:

Validity: The time you choose must fall within the min and max dates of the involved tables.

Realism: Do not pick dates where data is non-existent (e.g., if a certain card type only appears after 1995, do not ask about it in 1994).

Diversity: Vary the time points across the instances (e.g., some questions from early 1994, others from late 1997) to test the model's robustness across different data scales. 

Output Format (Strict JSON List)：

[
  {
    "instance_id": "RDB_FIN_XXXX",
    "metadata": {
      "query_type": "Retrieval / Analytical / Relational Reasoning",
      "answer_nature": "Sets / Scalars / Boolean / Rankings",
      "complexity": {
        "level": "Easy / Medium / Hard",
        "sql_features": ["JOIN", "GROUP_BY", "DATE_RANGE", "etc"],
        "tables_involved": ["table_a", "table_b"]
      },
      "reference_time": "YYYY-MM-DD HH:mm:ss" // The specific point you chose
    },
    "question": {
      "primary_nl": "The natural language question (e.g., 'As of March 1996, how many...').",
      "nl_variants": [
        "A formal version of the question.",
        "A version using specific date ranges mentioned in the SQL.",
        "A shorthand version (e.g., 'March '96 stats for...')."
      ]
    },
    "evidence": {
      "golden_sql": "SELECT ... WHERE date <= 'YYYY-MM-DD' ... ;", // Must match reference_time
      "reasoning_steps": "Explanation of the temporal logic used."
    },
    "ground_truth": {
      "raw_value": null, 
      "formatted_nl_answer": null,
      "nl_answer_variants": [
            "text": null ,
            "text": null 
      ]
    }
  }
]  

Strict Quality Guidelines：instance.

Sequential ID: Start the instance_id from RDB_FIN_[START_ID_NUMBER] and increment by 1 for each instance.

Logical Diversity: Do NOT repeat the logical patterns, table combinations, or business scenarios used in previous batches.

Linguistic Diversity: nl_variants must reflect real-world user behavior.

Schema Adherence: Only use tables and columns defined in the provided Schema.

Logical Grounding: Use the Data Profiling info to ensure questions are meaningful. Do not ask for values or categories that have 0\% distribution in the profiling data.

No Hallucinations: Do not invent table relationships that are not supported by the Foreign Keys in the Schema. 
"""


prompt2 = """ 
Role:
You are an expert Data Scientist specializing in Information Extraction and Precision NL2SQL. Your task is to generate complex, instance-level questions that require exact matching of real-world entities sampled from the database. The JSON file is a Database Context (Schema & Profiling) file. 
Start ID Number: 241
Mandatory Entity Seeds (The "Knowledge Base"):
You MUST incorporate the following real-world values into your questions:

['inf': {'dur': ['3', '1', '2', '0', '4']}]
Generate 10 questions. These should NOT be general. They MUST be specific (e.g., "how many loans in Karvina...").
Autonomous Temporal Selection (CRITICAL)：
For each question, you must autonomously select a specific reference_time or time range based on the temporal_coverage provided in the Profiling:

Validity: The time you choose must fall within the min and max dates of the involved tables.

Realism: Do not pick dates where data is non-existent (e.g., if a certain card type only appears after 1995, do not ask about it in 1994).

Diversity: Vary the time points across the instances (e.g., some questions from early 1994, others from late 1997) to test the model's robustness across different data scales. 

1. Generation Strategies
Specific Constraint: Use at least one entity from the seeds above per question.
Output Format (Strict JSON List)：

[
  {
    "instance_id": "RDB_FIN_XXXX",
    "metadata": {
      "query_type": "Retrieval / Analytical / Relational Reasoning",
      "answer_nature": "Sets / Scalars / Boolean / Rankings",
      "complexity": {
        "level": "Easy / Medium / Hard",
        "sql_features": ["JOIN", "GROUP_BY", "DATE_RANGE", "etc"],
        "tables_involved": ["table_a", "table_b"]
      },
      "reference_time": "YYYY-MM-DD" // The specific point you chose
    },
    "question": {
      "primary_nl": "The natural language question (e.g., 'As of March 1996, how many...').",
      "nl_variants": [
        "A formal version of the question.",
        "A version using specific date ranges mentioned in the SQL.",
        "A shorthand version (e.g., 'March '96 stats for...')."
      ]
    },
    "evidence": {
      "golden_sql": "SELECT ... WHERE date <= 'YYYY-MM-DD' ... ;", // Must match reference_time
      "reasoning_steps": "Explanation of the temporal logic used."
    },
    "ground_truth": {
      "raw_value": null, 
      "formatted_nl_answer": null,
      "nl_answer_variants": [
            "text": null ,
            "text": null 
      ]
    }
  }
]  
Strict Quality Guidelines:
Exact Case-Sensitivity: Use the entities exactly as provided in the seeds (e.g., if it's north Moravia, do not write North Moravia).
No Hallucinations: Do not create fake entities. If the seed is Bank ST, do not invent Bank XY. """ 


prompt3 = """Role:
You are an expert Financial Risk Analyst and Data Scientist. Your task is to generate "Prospective" questions that require a model to analyze historical behavioral patterns (before $T_{obs}$) to predict future events (after $T_{obs}$).
The JSON file is a Database Context (Schema & Profiling) file. 
Objective:
Generate 20 unique question-SQL pairs for Prospective categories.    
Current Batch Task:

Batch Number: Batch #1

Start ID Number: 701

Quantity: Generate 20 instances.

Temporal Boundary:
Observation Point ($T_{obs}$):
Rule: Any data after $T_{obs}$ is "The Future" and is strictly invisible to the model during inference.  


Output Format (Strict JSON List)：
Notice the label_sql field—this is the SQL that runs on the Future Data to get the answer.

[
  {
    "instance_id": "RDB_FIN_[ID]",
    "metadata": {
      "query_type": "Predictive", 
      "answer_nature": "Sets / Scalars / Boolean / Rankings",
      "complexity": {
        "level": "Easy / Medium / Hard",
        "sql_features": ["JOIN", "GROUP_BY", "DATE_RANGE", "etc"],
        "tables_involved": ["table_a", "table_b"]
      },
      "prediction_window": "90 days", // The duration into the future being predicted
      "signal_period": "180 days",    // How far back the model should look before T_obs
      "reference_time": "[T_obs]"
    },
    "question": {
      "primary_nl": "Based on the transaction patterns leading up to [T_obs], is account 123 likely to [future_event] within the next [X] months?",
      "nl_variants": [
        "Predict whether account 123 will...",
        "Looking at the history before [T_obs], what is the status of account 123 by [T_obs + X]?"
      ]
    },
   "evidence": {

      "golden_sql": "SELECT ... WHERE date <= 'YYYY-MM-DD' ... ;", // Must match reference_time

      "reasoning_steps": "Explanation of the temporal logic used."

    },

    "ground_truth": {

      "raw_value": null, 

      "formatted_nl_answer": null,

      "nl_answer_variants": [

            "text": null ,

            "text": null 

      ]

    },
  }
]  
Strict Quality Guidelines:
Causal Wall: The primary_nl must only ask about the future. The label_sql must only query dates strictly greater than $T_{obs}$.
Binary or Quantitative: Predictions should ideally be binary (Yes/No) or a specific count/amount (e.g., "Total spending in the next month").
Feasibility: Only ask questions that can be answered using the provided Schema (e.g., don't ask about "customer satisfaction" if there's no survey table).
No Peeking: Do not mention any specific events that happen after $T_{obs}$ in the primary_nl."""



prompt4 = """ 
Role:
You are a Professional Data Communicator. Your task is to transform structured database query results (raw_value) into clear, accurate, and diverse natural language answers based on the provided context.
Input Data:

1. Linguistic Rules (Critical):
Handling Zero Results (total_count: 0):
Provide a polite and clear "no results found" response within the context of the question.
Handling Scalar/Analytical Results:
If the answer is a single number (e.g., an average or count), the answer should be direct and include units if applicable.
Handling Predictive Results (Type 4):
Use probabilistic or forward-looking language (e.g., "Based on the history, it is predicted that...")
2. Output Style Variants:
formatted_nl_answer: Standard, clear, and complete.
concise: Short and to the point (perfect for mobile screens).
professional: Analytical, using formal financial terminology.
friendly/conversational: Helpful, like a personal banking assistant.
3. Output Format:
Please return ONLY the updated ground_truth object in JSON format: 

{
    "instance_id": "RDB_FIN_XXXX",
    "ground_truth": {
          "raw_value": { ... }, // Keep original
          "formatted_nl_answer": "The standard natural language answer here.",
          "nl_answer_variants": [
            { "style": "concise", "text": "Short version." },
            { "style": "professional", "text": "Formal/Analytical version." },
            { "style": "friendly", "text": "Assistant-style version." }
          ]
    }
} 
"""