"""Helpers shared by the scripts that write the Markdown reports."""

import pandas as pd


def markdown_table(frame: pd.DataFrame, columns: dict[str, tuple[str, str]]) -> str:
    """Render a DataFrame as a Markdown table.

    `columns` lists, in display order, each column with its header text and format spec.
    """
    header = "| " + " | ".join(title for title, _ in columns.values()) + " |"
    divider = "|" + "---|" * len(columns)
    rows = [
        "| " + " | ".join(format(row[name], spec) for name, (_, spec) in columns.items()) + " |"
        for _, row in frame.iterrows()
    ]
    return "\n".join([header, divider, *rows])
