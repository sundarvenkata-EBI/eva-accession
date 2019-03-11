# Copyright 2019 EMBL - European Bioinformatics Institute
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This script is a "sign-off" script to finalize an accessioning import and performs the following tasks:
# 1. Update evapro metadata tables with the appropriate assemblies and taxonomies
# 2. Update import_progress table with the proper import status

import argparse
import os
from argparse import RawTextHelpFormatter
from run_accession_import_jobs import assembly_info, get_args_from_private_config_file


def insert_assembly_in_evapro(program_args):
    """
    Invoke the insert assembly script in https://github.com/EBIvariation/metadata/blob/master/evapro/insert_new_assembly.py
    """
    program_args["assembly_code"] = program_args["assembly_name"]
    # Assembly code eventually gets used as part of database name lookup in the website:
    # See https://github.com/EBIvariation/eva-web/blob/master/src/js/variant-widget/filters/eva-species-filter-form-panel.js#L88
    # Therefore, we need to restrict its value based on https://docs.mongodb.com/manual/reference/limits/#Restrictions-on-Database-Names-for-Windows
    for invalid_char_for_mongodb_dbname in '/\. "$*<>:|?':
        program_args["assembly_code"] = program_args["assembly_code"].replace(invalid_char_for_mongodb_dbname, "")
    program_args["assembly_code"] = program_args["assembly_code"].replace()
    return os.system("{python3_path} {insert_assembly_script_path} -a {assembly_accession} -c {assembly_code} "
                     "--host {evapro_host} -u {evapro_user} -d {evapro_db} "
                     "-t {scientific_name} -e {eva_name} --from-dbsnp"
                     .format(**program_args))




def finalize_import(command_line_args):
    program_args = command_line_args.copy()
    program_args["eva_name"] = program_args["scientific_name"].split("_")[0]
    program_args.update(get_args_from_private_config_file(command_line_args["private_config_file"]))
    for _, assembly_name, assembly_accession in command_line_args["assembly_info"][1:]:
        program_args["assembly_name"] = assembly_name
        program_args["assembly_accession"] = assembly_accession
        if insert_assembly_in_evapro(program_args) == 0:
            update_import_progress_table(program_args)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Make final updates to EVAPRO and Import Progress tables after successful import to accession',
        formatter_class=RawTextHelpFormatter)
    parser.add_argument("-s", "--species", help="Species for which the process has to be run (e.g., pig_9823)",
                        required=True)
    parser.add_argument("--scientific-name", help="Scientific name for the species (e.g. sus_scrofa)", required=True)
    parser.add_argument("-a", "--assembly-info", help="One or more build,assembly name,accession combinations "
                                                      "for which the process has to be run "
                                                      "(GCA preferred for assembly name) "
                                                      "e.g. 150,Sscrofa11.1,GCA_000003025.6",
                        nargs='+', type=assembly_info, required=True)
    parser.add_argument("-p", "--private-config-file",
                        help="Path to the configuration file with private connection details, credentials etc.,",
                        required=True)
    args = {}
    try:
        args = parser.parse_args()
        finalize_import(vars(args))
    except Exception as ex:
        print(ex)
