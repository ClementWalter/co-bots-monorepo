import json
import shutil
from pathlib import Path
from string import Template
from xml.dom.minidom import parse

import numpy as np
import pandas as pd
from image_processing.constants import (
    PALETTES_FILE,
    TRAITS_COMPUTED_DIR,
    TRAITS_DIR,
    TRAITS_ORDER,
)
from image_processing.svg_to_path_ordered import dom2dict

#%% Define constants
RECT = Template("<rect x='$x' y='$y' width='$width' height='$height' fill='#$fill' />")


#%% Define functions
def parse_rect(rect):
    corner = np.array([rect.get("x", 0), rect.get("y", 0)])
    if "transform" in rect:
        matrix = (
            np.array(
                rect["transform"].replace("matrix(", "").replace(")", "").split(" ")
            )
            .reshape(3, 2)
            .T.astype(int)
        )
        corner = matrix[:, 2] + np.matmul(
            (matrix[:, :2] - np.identity(2)) / 2,
            np.array([rect.get("width", 0), rect.get("height", 0)]).astype(int),
        )
    return {
        "x": corner[0],
        "y": corner[1],
        "width": rect["width"],
        "height": rect["height"],
        "fill": rect["fill"],
    }


def generate_svg(_codes):
    return (
        """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 45 45\" width=\"450px\" height=\"450px\">"""
        + (
            "".join(
                [
                    RECT.substitute(**{**c, "fill": _codes["fill"][c["fill"]]})
                    for c in _codes["rect"]
                ]
            )
        )
        + "</svg>"
    )


#%% Parse files
rects_list = []
for file in TRAITS_DIR.glob("**/*.svg"):
    doc = parse(str(file))
    rects_list += [
        {**parse_rect(dom2dict(node)), "file": str(file)}
        for node in doc.documentElement.childNodes
        if node.localName == "rect"
    ]

#%% Build dataframe and encode traits
# Encoding scheme
# 1. As is
#     Cost is len(traits_df) * (6 bits * 4 + 6 bits * 1) => 621 * 32 bits = 621 * 4 bytes = 2484 bytes
# 2. With a rects palette
#     Cost is len(traits_df).drop_duplicates() * 32 bits + len(traits_df) * 9 bits = 508 * 32 + 621 * 9 ~ 2730 bytes

traits_df = (
    pd.DataFrame(rects_list)
    .replace({"fill": {"black": "#000000", "white": "#ffffff"}})
    .astype({"x": int, "y": int, "width": int, "height": int})
    .assign(fill=lambda df: df["fill"].str.replace("#", ""))
    .astype({"fill": "category"})
    .assign(
        fill_code=lambda df: df.fill.cat.codes,
        rect=lambda df: df[["x", "y", "width", "height", "fill_code"]]
        .rename(columns={"fill_code": "fill"})
        .astype(int)
        .to_dict("records"),
    )
    .groupby("file")
    .agg(
        {
            "rect": list,
            "fill": lambda c: c.cat.categories.tolist(),
        }
    )
    .reset_index()
    .assign(
        layer=lambda df: pd.Categorical(
            df.file.str.split("/", expand=True)[2], categories=TRAITS_ORDER
        ),
        item=lambda df: df.file.str.split("/", expand=True)[3].str.replace(
            ".svg", "", regex=False
        ),
    )
    .sort_values(["layer", "item"])
    .set_index("file")
)


#%% Dump reconstructed SVG files for visual check
shutil.rmtree(TRAITS_COMPUTED_DIR, ignore_errors=True)
for file_name, codes in traits_df.iterrows():
    file_name_computed = TRAITS_COMPUTED_DIR / Path(file_name).relative_to(TRAITS_DIR)
    file_name_computed.parent.mkdir(exist_ok=True, parents=True)

    with open(file_name_computed, "w") as f:
        f.write(generate_svg(codes))

#%% Dump palettes and traits
with open(PALETTES_FILE, "w") as f:
    json.dump(
        {
            "fill": traits_df.fill.iloc[0],
            "trait": traits_df.rect.to_dict(),
            "layer": TRAITS_ORDER,
            "layerIndexes": traits_df.layer.reset_index(drop=True)
            .drop_duplicates()
            .index.to_list(),
            "item": traits_df.item.to_list(),
        },
        f,
        indent=2,
    )