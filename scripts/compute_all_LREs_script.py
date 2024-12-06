#!/usr/bin/env python3

# Copyright 2024 L3Harris Technologies, Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import argparse
import datetime
import json
import logging
import math
import os
import sys
from collections import defaultdict
from importlib.metadata import version
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import pandas as pd
from pyLIQTR.utils.resource_analysis import estimate_resources
from qualtran.surface_code.algorithm_summary import AlgorithmSummary
from qualtran.surface_code.ccz2t_cost_model import (
    get_ccz2t_costs_from_grid_search,
    iter_ccz2t_factories,
)

from qb_gsee_benchmark.qre import get_df_qpe_circuit
from qb_gsee_benchmark.utils import retrieve_fcidump_from_sftp


class NoFactoriesFoundError(Exception):
    pass


logger = logging.getLogger()
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler("compute_all_LREs_scripts.log.txt", delay=False)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handlers = [console_handler, file_handler]
for h in handlers:
    h.setFormatter(formatter)
    logger.addHandler(h)


def get_physical_cost(
    num_logical_qubits: int,
    num_T_gates: int,
    hardware_failure_tolerance_per_shot: float,
    n_factories: int,
    physical_error_rate: float,
):
    n_magic = AlgorithmSummary(t_gates=num_T_gates)
    try:
        best_cost, best_factory, best_data_block = get_ccz2t_costs_from_grid_search(
            n_magic=n_magic,
            n_algo_qubits=num_logical_qubits,
            error_budget=hardware_failure_tolerance_per_shot,
            phys_err=physical_error_rate,
            factory_iter=iter_ccz2t_factories(n_factories=n_factories),
            cost_function=(lambda pc: pc.duration_hr),
        )
        return best_cost.duration_hr * 60 * 60, best_cost.footprint
    except TypeError:
        raise NoFactoriesFoundError(
            f"No factories found that meet the performance requirements."
        )


def get_lqre(
    problem_instance: dict, username: str, ppk_path: str, config: dict
) -> dict[str, Any]:
    problem_instance_uuid = problem_instance["problem_instance_uuid"]
    problem_instance_short_name = problem_instance["short_name"]
    logging.info(f"problem_instance UUID: {problem_instance_uuid}")
    logging.info(f"problem_instance short name: {problem_instance_short_name}")
    num_hams = len(problem_instance["tasks"])
    logging.info(f"contains {num_hams} associated Hamiltonians.")

    if (
        "overlap" in config["algorithm_parameters"]
        and "overlap_csv" in config["algorithm_parameters"]
    ):
        raise ValueError("Config cannot specify both 'overlap' and 'overlap_csv'.")

    if config["algorithm_parameters"].get("overlap_csv"):
        overlap_df = pd.read_csv(config["algorithm_parameters"]["overlap_csv"])
        overlaps = {
            row["task_uuid"]: row["overlap"] for index, row in overlap_df.iterrows()
        }
    else:
        overlaps = defaultdict(lambda: config["algorithm_parameters"]["overlap"])

    solution_data: list[dict[str, Any]] = []
    results: dict[str, Any] = {}

    for task in problem_instance["tasks"]:
        if not overlaps.get(task["task_uuid"]):
            logging.info(
                f"Skipping task {task['task_uuid']} because no overlap was provided."
            )
            continue

        logging.info(f"Analyzing task {task['task_uuid']}...")

        num_supporting_files = len(task["supporting_files"])
        logging.info(f"number of supporting files: {num_supporting_files}")

        for supporting_file in task["supporting_files"]:
            # flush log buffer to log file
            file_handler.flush()

            fcidump_uuid = supporting_file["instance_data_object_uuid"]
            fcidump_url = supporting_file["instance_data_object_url"]
            logging.info(f"supporting data file UUID: {fcidump_uuid}.")
            logging.info(f"supporting data file URL: {fcidump_url}.")

            parsed_url = urlparse(fcidump_url)
            fcidump_file_name = parsed_url.path.split("/")[-1]

            # TODO: fix hacky way of only grabbing FCIDUMP files:
            if "fcidump".lower() in fcidump_file_name.lower():
                logging.info(f"assuming {fcidump_file_name} is an FCIDUMP file.")
            else:
                logging.info(
                    f"assuming {fcidump_file_name} is NOT an FCIDUMP file.  SKIPPING!"
                )
                continue

            # TODO: check to see if we have already processed this FCIDUMP file.

            logging.info(f"SFTP downloading file {fcidump_url}...")
            fci = retrieve_fcidump_from_sftp(
                url=fcidump_url,
                username=username,
                ppk_path=ppk_path,
                port=22,
            )

            num_orbitals = fci["H1"].shape[0]
            if num_orbitals >= config["algorithm_parameters"]["max_orbitals"]:
                logging.info(
                    f"Skipping Logical Resource Estimate because number of orbitals ({num_orbitals}) exceeds maximum specified in config ({config['algorithm_parameters']['max_orbitals']})."
                )
                continue

            logging.info(f"===============================================")
            logging.info(f"Calculating Logical Resource Estimate...")

            error_tolerance = task["requirements"]["accuracy"]
            failure_tolerance = 1 - task["requirements"]["probability_of_success"]

            circuit_generation_start_time = datetime.datetime.now()
            (
                circuit,
                num_shots,
                hardware_failure_tolerance_per_shot,
            ) = get_df_qpe_circuit(
                fci=fci,
                error_tolerance=error_tolerance,
                failure_tolerance=failure_tolerance,
                square_overlap=overlaps[task["task_uuid"]] ** 2,
                df_threshold=config["algorithm_parameters"]["df_threshold"],
            )
            circuit_generation_end_time = datetime.datetime.now()
            logging.info(
                f"Circuit initialization time: {(circuit_generation_end_time - circuit_generation_start_time).total_seconds()} seconds."
            )
            logging.info(f"Estimating logical resources...")
            resource_estimation_start_time = datetime.datetime.now()
            logical_resources = estimate_resources(circuit.circuit)
            resource_estimation_end_time = datetime.datetime.now()
            LRE_calc_time = (
                resource_estimation_end_time - resource_estimation_start_time
            ).total_seconds()
            logging.info(f"Resource estimation time (seconds): {LRE_calc_time}")

            task_solution_data = {
                "task_uuid": task["task_uuid"],
                "error_bound": error_tolerance,
                "confidence_level": failure_tolerance,
                "quantum_resources": {
                    "logical": {
                        "num_logical_qubits": logical_resources["LogicalQubits"],
                        "num_T_gates_per_shot": logical_resources["T"],
                        "num_shots": math.ceil(num_shots),
                        "hardware_failure_tolerance_per_shot": hardware_failure_tolerance_per_shot,
                    }
                },
                "run_time": {
                    "preprocessing_time": {
                        "wall_clock_start_time": circuit_generation_start_time.strftime(
                            "%Y-%m-%dT%H:%M:%S.%f"
                        )
                        + "Z",
                        "wall_clock_stop_time": circuit_generation_end_time.strftime(
                            "%Y-%m-%dT%H:%M:%S.%f"
                        )
                        + "Z",
                        "seconds": (
                            circuit_generation_end_time - circuit_generation_start_time
                        ).total_seconds(),
                    },
                },
            }

            try:
                physical_resource_estimation_start = datetime.datetime.now()
                algorithm_runtime_seconds, num_physical_qubits = get_physical_cost(
                    num_logical_qubits=logical_resources["LogicalQubits"],
                    num_T_gates=logical_resources["T"],
                    hardware_failure_tolerance_per_shot=hardware_failure_tolerance_per_shot,
                    n_factories=config["hardware_parameters"]["num_factories"],
                    physical_error_rate=config["hardware_parameters"][
                        "physical_error_rate"
                    ],
                )
                physical_resource_estimation_end = datetime.datetime.now()
                logging.info(
                    f"Physical resource estimation time: {(physical_resource_estimation_end - physical_resource_estimation_start).total_seconds()} seconds."
                )
                task_solution_data["run_time"]["algorithm_run_time"] = (
                    {
                        "seconds": algorithm_runtime_seconds,
                    },
                )
                task_solution_data["run_time"]["overall_time"] = {
                    "seconds": (
                        circuit_generation_end_time - circuit_generation_start_time
                    ).total_seconds()
                    + algorithm_runtime_seconds
                }
            except NoFactoriesFoundError:
                logging.info(
                    f"No factories found that meet the performance requirements. Skipping physical cost estimation."
                )
            solution_data.append(task_solution_data)

    solution_uuid = str(uuid4())
    current_time = datetime.datetime.now(datetime.timezone.utc)
    current_time_string = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    solver_details = {
        "solver_uuid": config["solver_uuid"],
        "solver_short_name": "DF QPE",
        "compute_hardware_type": "quantum_computer",
        "algorithm_details": {
            "algorithm_description": config["algorithm_description"],
            "algorithm_parameters": config["algorithm_parameters"],
        },
        "software_details": [
            {"software_name": "pyLIQTR", "software_version": version("pyLIQTR")},
            {
                "software_name": "qb-gsee-benchmark",
                "software_version": version("qb-gsee-benchmark"),
            },
            {"software_name": "Python", "software_version": sys.version},
        ],
    }
    results = {
        "$schema": "https://raw.githubusercontent.com/isi-usc-edu/qb-gsee-benchmark/refs/heads/main/schemas/solution.schema.0.0.1.json",
        "solution_uuid": solution_uuid,
        "problem_instance_uuid": problem_instance["problem_instance_uuid"],
        "creation_timestamp": current_time_string,
        "is_resource_estimate": True,
        "contact_info": config["contact_info"],
        "solution_data": solution_data,
        "compute_hardware_type": "quantum_computer",
        "solver_details": solver_details,
        "digital_signature": None,
    }

    return results


def main(args: argparse.Namespace) -> None:

    config = json.load(open(args.LRE_config_file, "r"))

    overall_start_time = datetime.datetime.now()
    logging.info(f"===============================================")
    logging.info(f"overall start time: {overall_start_time}")
    logging.info(f"input directory: {args.input_dir}")

    input_dir = args.input_dir

    problem_instance_files = os.listdir(input_dir)
    logging.info(f"parsing {len(problem_instance_files)} files in the input directory")
    for p in problem_instance_files:
        logging.info(f"file: {p}")

    for problem_instance_file_name in problem_instance_files:
        problem_instance_path = os.path.join(input_dir, problem_instance_file_name)
        logging.info(f"parsing {problem_instance_path}")
        with open(problem_instance_path, "r") as jf:
            problem_instance = json.load(jf)

            resource_estimate = get_lqre(
                problem_instance, args.sftp_username, args.sftp_key_file, config=config
            )
            if len(resource_estimate["solution_data"]) > 0:
                with open(
                    os.path.join(
                        args.output_dir,
                        f"{problem_instance['problem_instance_uuid']}_sol_{resource_estimate['solution_uuid']}.json",
                    ),
                    "w",
                ) as f:
                    json.dump(resource_estimate, f, indent=4)

    # Print overall time.
    # ===============================================================
    overall_stop_time = datetime.datetime.now()
    logging.info(f"done.")
    logging.info(f"overall start time: {overall_start_time}")
    logging.info(f"overall stop time: {overall_stop_time}")
    logging.info(
        f"run time (seconds): {(overall_stop_time - overall_start_time).total_seconds()}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="a script to calculate Logical Resource Estimates (LREs) for all problem_instance files.  Outputs are solution.uuid.json files."
    )

    parser.add_argument(
        "-i",
        "--input_dir",
        type=str,
        required=True,
        help="Specify directory for problem_instances (.json files)",
    )

    parser.add_argument(
        "-o",
        "--output_dir",
        type=str,
        required=True,
        help="Specify directory to save resource estimates to (.json files)",
    )

    parser.add_argument(
        "--LRE_config_file",
        type=str,
        required=True,
        help="A JSON file with configuration options and hyperparameters for LRE and a `solver` UUID.",
    )

    parser.add_argument(
        "--sftp_username",
        type=str,
        required=True,
        help="username for SFTP server where FCIDUMP files are stored.",
    )

    parser.add_argument(
        "--sftp_key_file",
        type=str,
        required=True,
        help="local/path/to/the/keyfile for the SFTP server (corresponding to sftp_username)",
    )

    args = parser.parse_args()
    main(args)
