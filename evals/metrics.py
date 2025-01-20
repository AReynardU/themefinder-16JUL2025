import json

import numpy as np
import pandas as pd
from langchain_openai import AzureChatOpenAI
from sklearn import metrics, utils
from sklearn.preprocessing import MultiLabelBinarizer

from utils import read_and_render


def calculate_sentiment_metrics(df: pd.DataFrame) -> dict[str, float]:
    """Calculate accuracy metrics for sentiment analysis predictions.

    Args:
        df (pd.DataFrame): DataFrame containing 'ai_position' and 'supervisor_position' columns

    Returns:
        dict[str, float]: Dictionary with keys:
            - accuracy: Score comparing AI and supervisor positions
    """
    ai = df["ai_position"]
    supervisor = df["supervisor_position"]
    correct_predictions = (ai == supervisor).sum()
    total_predictions = len(df)
    accuracy = correct_predictions / total_predictions
    return {"accuracy": accuracy}


def calculate_generation_metrics(
    llm: AzureChatOpenAI, generated_topics: pd.DataFrame, topic_framework: dict
) -> dict[str, float | int]:
    """Calculate precision and recall metrics for generated themes against a framework.

    Args:
        llm (AzureChatOpenAI): Language model for evaluation
        generated_topics (pd.DataFrame): DataFrame containing generated themes as columns
        topic_framework (dict): Dictionary containing reference framework themes

    Returns:
        dict[str, float | int]: Dictionary with keys:
            - Precision N topics: Number of generated topics
            - Precision N not well grounded: Count of topics below threshold
            - Precision Average Groundedness: Mean groundedness score
            - Recall N not Captured: Count of framework topics not captured
            - Recall Average topic Representation: Mean representation score
    """
    precision_scores = llm.invoke(
        read_and_render(
            "generation_eval.txt",
            {"topic_list_1": generated_topics, "topic_list_2": topic_framework},
        )
    )
    precision_scores = list(json.loads(precision_scores.content).values())
    recall_scores = llm.invoke(
        read_and_render(
            "generation_eval.txt",
            {"topic_list_1": topic_framework, "topic_list_2": generated_topics},
        )
    )
    recall_scores = list(json.loads(recall_scores.content).values())
    threshold = 3
    return {
        "Precision N topics": len(generated_topics.columns),
        "Precision N not well grounded": sum([i < threshold for i in precision_scores]),
        "Precision Average Groundedness": np.mean(precision_scores).round(2),
        "Recall N not Captured": sum([i < threshold for i in recall_scores]),
        "Recall Average topic Representation": np.mean(recall_scores).round(2),
    }


def calculate_mapping_metrics(
    df: pd.DataFrame,
    column_one: str,
    column_two: str,
    n_samples: int = 1000,
) -> dict[str, float | tuple[float, float]]:
    """Calculate theme mapping metrics (includes F1 score with bootstrap confidence intervals).

    Args:
        df (pd.DataFrame): DataFrame containing the two columns to compare
        column_one (str): Name of the first label column
        column_two (str): Name of the second label column
        n_samples (int, optional): Number of bootstrap samples to generate. Defaults to 1000.

    Returns:
        dict[str, float | tuple[float, float]]: Dictionary with keys:
            - f1_score (float): Observed F1 score
            - f1_confidence_interval (tuple[float, float]): 95% confidence interval (lower, upper)
            - accuracy_score (float): Overall accuracy between the two columns
            - overlap_rate (float): Rate of overlapping assignments between columns

    Raises:
        ValueError: If input columns are empty or contain no valid labels
    """
    no_valid_columns_error_message = "Input columns contain no valid labels"
    source_one_lol = df[column_one].apply(lambda row: list(set(row))).tolist()
    source_two_lol = df[column_two].apply(lambda row: list(set(row))).tolist()
    if not any(source_one_lol) or not any(source_two_lol):
        raise ValueError(no_valid_columns_error_message)
    # Create and fit MultiLabelBinarizer
    mlb = MultiLabelBinarizer(sparse_output=True)
    all_labels = {
        label for sample in source_one_lol + source_two_lol for label in sample
    }
    mlb.fit([all_labels])
    # Transform to sparse matrices
    source_one_sparse = mlb.transform(source_one_lol)
    source_two_sparse = mlb.transform(source_two_lol)
    # Calculate observed F1 score
    observed_f1 = metrics.f1_score(
        source_one_sparse, source_two_sparse, average="samples"
    )
    # Generate bootstrap samples
    n_instances = source_one_sparse.shape[0]
    bootstrap_samples = pd.DataFrame(
        {
            "sample": range(n_samples),
            "f1": [
                metrics.f1_score(
                    y_true=source_one_sparse[indices],
                    y_pred=source_two_sparse[indices],
                    average="samples",
                )
                for indices in (
                    utils.resample(
                        range(n_instances), replace=True, n_samples=n_instances
                    )
                    for _ in range(n_samples)
                )
            ],
        }
    )
    # Calculate confidence interval
    lower_bound, upper_bound = np.percentile(bootstrap_samples["f1"], [2.5, 97.5])
    confint = np.round(lower_bound, 2), np.round(upper_bound, 2)
    # Overlapping assignments
    count = 0
    for sublist1, sublist2 in zip(source_one_lol, source_two_lol, strict=False):
        if set(sublist1).intersection(set(sublist2)):
            count += 1
    return {
        "f1_score": observed_f1,
        "f1_confidence_interval": confint,
        "accuracy_score": metrics.accuracy_score(
            y_true=source_one_sparse, y_pred=source_two_sparse
        ),
        "overlap_rate": count / len(source_one_lol),
    }
