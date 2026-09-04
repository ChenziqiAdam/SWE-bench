#!/usr/bin/env python3
"""Discrete rational empirical interpolation (rEIM)."""

import argparse
import json
import os

import numpy as np


def reim(data):
    dictionary = np.asarray(data["dictionary"], dtype=np.float64)
    query_dictionary = np.asarray(data["query_dictionary"], dtype=np.float64)
    targets = np.asarray(data["targets"], dtype=np.float64)
    order = int(data["order"])

    dictionary_indices = [int(data["initial_dictionary_index"])]
    sample_indices = []

    for step in range(order):
        selected_column = dictionary_indices[-1]

        if step == 0:
            residual = dictionary[:, selected_column]
        else:
            interpolation_matrix = dictionary[
                np.ix_(sample_indices, dictionary_indices[:-1])
            ]
            values = dictionary[sample_indices, selected_column]
            weights = np.linalg.solve(interpolation_matrix, values)
            residual = (
                dictionary[:, selected_column]
                - dictionary[:, dictionary_indices[:-1]] @ weights
            )

        sample_indices.append(int(np.argmax(np.abs(residual))))

        if step + 1 < order:
            interpolation_matrix = dictionary[
                np.ix_(sample_indices, dictionary_indices)
            ]
            sampled_dictionary = dictionary[sample_indices, :]
            weights = np.linalg.solve(interpolation_matrix, sampled_dictionary)
            all_residuals = (
                dictionary
                - dictionary[:, dictionary_indices] @ weights
            )
            errors = np.max(np.abs(all_residuals), axis=0)
            dictionary_indices.append(int(np.argmax(errors)))

    interpolation_matrix = dictionary[
        np.ix_(sample_indices, dictionary_indices)
    ]
    coefficients = np.linalg.solve(
        interpolation_matrix, targets[sample_indices]
    )
    predictions = query_dictionary[:, dictionary_indices] @ coefficients

    return {
        "coefficients": coefficients.tolist(),
        "dictionary_indices": dictionary_indices,
        "interpolation_matrix": interpolation_matrix.tolist(),
        "predictions": predictions.tolist(),
        "sample_indices": sample_indices,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as input_file:
        data = json.load(input_file)

    result = reim(data)
    os.makedirs(args.output, exist_ok=True)
    output_path = os.path.join(args.output, "output.json")
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(result, output_file, indent=2)
        output_file.write("\n")


if __name__ == "__main__":
    main()
