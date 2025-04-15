import asyncio
import io
import os
from pathlib import Path

import dotenv
import pandas as pd
from langchain_openai import AzureChatOpenAI

from themefinder import theme_condensation
from utils import download_file_from_bucket, read_and_render


def load_generated_themes() -> tuple[str, pd.DataFrame]:
    dotenv.load_dotenv()
    bucket_name = os.getenv("THEMEFINDER_S3_BUCKET_NAME")
    condensed_themes = pd.read_csv(
        io.BytesIO(
            download_file_from_bucket(
                "app_data/evals/theme_refinement/eval_condensed_topics.csv",
                bucket_name=bucket_name,
            )
        )
    )
    data_dir = Path(__file__).parent / "data/condensation"
    with (data_dir / "expanded_question.txt").open() as f:
        question = f.read()
    return condensed_themes, question


async def evaluate_condensation():
    dotenv.load_dotenv()
    llm = AzureChatOpenAI(
        model_name="gpt-4o",
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    themes, question = load_generated_themes()
    condensed_themes, _ = await theme_condensation(
        themes,
        llm=llm,
        question=question,
    )
    condensed_themes = condensed_themes[["topic_label", "topic_description"]].to_dict(
        orient="records"
    )
    eval_prompt = read_and_render(
        "condensation_eval.txt",
        {"original_topics": themes, "condensed_topics": condensed_themes},
    )
    response = llm.invoke(eval_prompt)
    print(condensed_themes)
    print(f"Theme Condensation Eval Results: \n {response.content}")


if __name__ == "__main__":
    asyncio.run(evaluate_condensation())
