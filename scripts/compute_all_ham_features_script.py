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


import os
import argparse
import datetime
import gzip
import shutil
import json
import copy
from urllib.parse import urlparse
import time
import sys
sys.path.append("../")
sys.path.append("../Hamiltonian_features/experimental/fast_double_factorization_features")

import pandas as pd
from Hamiltonian_features.experimental.fast_double_factorization_features.fcidump_to_ham_features_csv import compute_ham_features_csv
# from Hamiltonian_features.experimental.fast_double_factorization_features.compute_ham_features import compute_hypergraph_ham_features


import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler(
    "compute_all_ham_features_script.log.txt",
    delay=False
)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handlers = [console_handler , file_handler]
for h in handlers:
    h.setFormatter(formatter)
    logger.addHandler(h)



import paramiko # for SSH/SFTP
def fetch_file_from_sftp(
        url=None,
        local_path=None,
        ppk_path=None,
        username=None,
        port=22
    ):
    """TODO: docstring

    Args:
        url (_type_, optional): _description_. Defaults to None.
        local_path (_type_, optional): _description_. Defaults to None.
        ppk_path (_type_, optional): _description_. Defaults to None.
        username (_type_, optional): _description_. Defaults to None.
        port (_type_, optional): _description_. Defaults to 22.
    """


    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    remote_path = parsed_url.path.lstrip("/")

    try:
        # Create an SSH client
        with paramiko.SSHClient() as client:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect using the private key file (.ppk)
            client.connect(
                hostname=hostname, 
                port=port, 
                username=username, 
                key_filename=ppk_path
            )

            # Open an SFTP session
            with client.open_sftp() as sftp:
                sftp.get(remote_path, local_path)

        logging.info(f"File fetched successfully from {hostname}")
    except Exception as e:
        logging.error(f"Error: {e}")










def read_in_Hamiltonian_features_database_csv(ham_features_file):
    logging.info(f"accessing {ham_features_file}...")
    if not os.path.exists(ham_features_file):
        logging.info(f"database file does not exist. A new file will be created.")
        ham_features_df_database = None
    else:
        ham_features_df_database = pd.read_csv(args.ham_features_file)
        logging.info(f"number of entries in database:  {len(ham_features_df_database)}")
    
    return ham_features_df_database # may be None.













def main(args):

    time.sleep(2)

    overall_start_time = datetime.datetime.now()
    logging.info(f"===============================================")
    logging.info(f"overall start time: {overall_start_time}")
    logging.info(f"input directory: {args.input_dir}")
    logging.info(f"Hamiltonian features file: {args.ham_features_file}")

    
    input_dir = args.input_dir

    # create backup Hamiltonian_features.csv file
    if os.path.exists(args.ham_features_file):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
        back_up_file_name = args.ham_features_file + ".backup-" + timestamp + ".csv"
        logging.info(f"creating back up file {back_up_file_name}.")
        shutil.copy2(args.ham_features_file, back_up_file_name)



    problem_instance_files = os.listdir(input_dir)
    logging.info(f"parsing {len(problem_instance_files)} files in the input directory")
    for p in problem_instance_files:
        logging.info(f"file: {p}")

    for problem_instance_file_name in problem_instance_files:
        problem_instance_path = input_dir + problem_instance_file_name
        logging.info(f"parsing {problem_instance_path}")
        with open(problem_instance_path, "r") as jf:
            
            # load data from file as a Python dictionary object:
            # Try... because we may have non-JSON files that we will skip.
            try:
                problem_instance = json.load(jf)
            except Exception as e:
                logging.error(f'Error: {e}', exc_info=True)
                continue # to next json file.


            problem_instance_uuid = problem_instance["problem_instance_uuid"]
            problem_instance_short_name = problem_instance["short_name"]
            logging.info(f"problem_instance UUID: {problem_instance_uuid}")
            logging.info(f"problem_instance short name: {problem_instance_short_name}")
            num_hams = len(problem_instance["instance_data"])
            logging.info(f"contains {num_hams} associated Hamiltonians.")

            for i in range(num_hams):
                num_supporting_files = len(problem_instance["instance_data"][i]["supporting_files"])
                logging.info(f"number of supporting files: {num_supporting_files}")

                for j in range(num_supporting_files):
                    # flush log buffer to log file
                    file_handler.flush()


                    fcidump_uuid = problem_instance["instance_data"][i]["supporting_files"][j]["instance_data_object_uuid"]
                    fcidump_url = problem_instance["instance_data"][i]["supporting_files"][j]["instance_data_object_url"]
                    logging.info(f"supporting data file UUID: {fcidump_uuid}.")
                    logging.info(f"supporting data file URL: {fcidump_url}.")

                    parsed_url = urlparse(fcidump_url)
                    fcidump_file_name = parsed_url.path.split("/")[-1]


                    #TODO: hacky way to only grab FCIDUMP files:
                    if "fcidump".lower() in fcidump_file_name.lower():
                        logging.info(f"assuming {fcidump_file_name} is an FCIDUMP file.")
                    else:
                        logging.info(f"assuming {fcidump_file_name} is NOT an FCIDUMP file.  SKIPPING!")
                        continue


                    # check the see if we have already processed FCIDUMP_UUID
                    # TODO: also compare version of the metrics calculation to see if we need to update.
                    #==============================================================

                    # re-read ham_features_df_database ... we may have updated it.
                    ham_features_df_database = read_in_Hamiltonian_features_database_csv(args.ham_features_file)
                    if ham_features_df_database is None:
                        # empty features database... we will process the FCIDUMP
                        logging.info(f"Hamiltonian features database is empty.")
                        logging.info(f"FCIDUMP UUID {fcidump_uuid} not found in feature database.  Processing...")
                    else:
                        if fcidump_uuid in ham_features_df_database["fcidump_uuid"].values:
                            logging.info(f"FCIDUMP UUID {fcidump_uuid} is already in the feature database.  Skipping it!")
                            continue
                        else:
                            logging.info(f"FCIDUMP UUID {fcidump_uuid} not found in feature database.  Processing...")
                            
                    



                    # SFTP download the FCIDUMP file
                    #===============================================================
                    logging.info(f"SFTP downloading file {fcidump_url}...")
                    fetch_file_from_sftp(
                        url=fcidump_url,
                        username=args.sftp_username,
                        ppk_path=args.sftp_key_file, 
                        local_path=fcidump_file_name,
                        port=22
                    )
                    

                    # Decompress the FCIDUMP file (if detected)
                    #===============================================================
                    # hacky way of detecting the file is compressed:
                    if ".gz".lower() in fcidump_file_name.lower():
                        logging.info(f"decompressing file {fcidump_file_name}...")
                        fcidump_file_name_gz = fcidump_file_name
                        fcidump_file_name = fcidump_file_name.split(".gz")[0] # update file name with no .gz
                        
                        with gzip.open(fcidump_file_name_gz, "rb") as f_in:
                            with open(fcidump_file_name, "wb") as f_out:
                                shutil.copyfileobj(f_in, f_out)
                        
                        os.remove(fcidump_file_name_gz)
                    else:
                        logging.info(f"assuming file {fcidump_file_name} is NOT compressed.")




                    # Calculate features of the FCIDUMP file
                    #===============================================================
                    logging.info(f"===============================================")
                    logging.info(f"calculating Hamiltonian features...")
                    ham_features = {}
                    ham_features_start_time = datetime.datetime.now()
                    ham_features = compute_ham_features_csv(
                        filename=fcidump_file_name,
                        save=False,
                        csv_filename=None,
                        verbose_logging=True
                    )
                    ham_features_stop_time = datetime.datetime.now()
                    logging.info(f"Hamiltonian features calculation run time (seconds): {(ham_features_stop_time - ham_features_start_time).total_seconds()}")



                    ham_features["problem_instance_uuid"] = problem_instance_uuid
                    ham_features["problem_instance_short_name"] = problem_instance_short_name
                    ham_features["fcidump_file_name"] = fcidump_file_name
                    ham_features["fcidump_uuid"] = fcidump_uuid
                    ham_features["fcidump_url"] = fcidump_url
                    ham_features["date_of_calculation"] = str(ham_features_stop_time)
                    ham_features["version_of_features_calculation_script"] = 1



                    # Back up df_eigs to a file. 
                    # Sometimes the array is shortened in string representation...
                    # we want all the eigs!
                    ham_features["df_eigs"].tofile(f"df_eigs.{fcidump_uuid}.bin")


                    # Clean up
                    #===============================================================
                    logging.info(f"deleting file {fcidump_file_name}.")
                    os.remove(fcidump_file_name)


                    # Append/Write out features .csv file
                    #===============================================================
                    logging.info(f"appending data to file {args.ham_features_file}")
                    df = pd.DataFrame([ham_features])
                    df.to_csv(
                        args.ham_features_file,
                        mode="a", #append
                        header=not os.path.exists(args.ham_features_file), # write headers if starting a new file.
                        index=False
                    )


                    


    
    # Print overall time.
    #===============================================================
    overall_stop_time = datetime.datetime.now()
    logging.info(f"done.")
    logging.info(f"overall start time: {overall_start_time}")
    logging.info(f"overall stop time: {overall_stop_time}")
    logging.info(f"run time (seconds): {(overall_stop_time - overall_start_time).total_seconds()}")

    
    










if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="a script to update all problem_instance files at once."
    )
    
    parser.add_argument(
        "-i", 
        "--input_dir", 
        type=str, 
        required=True,
        help="Specify directory for problem_instances (.json files)"
    )

    parser.add_argument(
        "--ham_features_file",
        type=str,
        required=True,
        help="The file name of the Hamiltonian features (.csv) file."
    )

    parser.add_argument(
        "--sftp_username", 
        type=str, 
        required=True,
        help="username for SFTP server where FCIDUMP files are stored."
    )

    parser.add_argument(
        "--sftp_key_file", 
        type=str, 
        required=True,
        help="local/path/to/the/keyfile for the SFTP server (corresponding to sftp_username)"
    )

    args = parser.parse_args()
    main(args)


