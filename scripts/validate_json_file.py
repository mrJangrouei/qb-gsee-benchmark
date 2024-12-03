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

import sys
import json
import requests
import argparse

# additional package(s):
import jsonschema





def main(args):
    input_json_file = args.file
    
    try:
        with open(input_json_file, "r") as json_file:
            file_contents = json.load(json_file)
    except Exception as e:
        print(f"Error: {e}")
        print(f"\n\nCannot read the file {input_json_file}...\n\n")
        sys.exit(1)

    # pull out the $schema field as specified in the JSON file:
    try:
        schema_url = file_contents["$schema"]
        print(f"\n\nSchema URL to fetch: {schema_url}\n\n")
    except Exception as e:
        print(f"Error: {e}")
        print(f"\n\nThe JSON file may be missing the $schema field...\n\n")
        sys.exit(1)

    
    # fetch the schema from the URL (http request):
    try:
        schema = requests.get(schema_url).json()
    except Exception as e:
        print(f"Error: {e}")
        print(f"\n\nFailed to retrieve the schema from the URL...\n\n")
        sys.exit(1)
    
    # validate ... no output implies success!
    try:
        jsonschema.validate(instance=file_contents, schema=schema)
        print("\n\nJSON file is valid per the schema!\n\n")
    except Exception as e:
        # print(f"Error: {e}") ## lots of output.
        print(f"\n\nJSON file has FAILED schema validation!\n\n")
        sys.exit(1)






if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check that a JSON file adheres to the $schema field within the file."
    )
    
    parser.add_argument(
        "file", 
        type=str, 
        help="the/path/to/the/ JSON file you want to validate."
    )

    args = parser.parse_args()

    main(args)

