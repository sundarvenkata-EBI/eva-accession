# Copyright 2020 EMBL - European Bioinformatics Institute
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

import click
import collections
import copy
import json
import logging
import os
import psycopg2

from ebi_eva_common_pyutils.config_utils import get_pg_metadata_uri_for_eva_profile
from run_release_in_embassy.release_metadata import get_release_assemblies_for_taxonomy


logger = logging.getLogger(__name__)
# Processes, in order, that make up the workflow and the arguments that they take
workflow_process_arguments_map = collections.OrderedDict(
    [("copy_accessioning_collections_to_embassy", ["private-config-xml-file", "taxonomy-id", "assembly-accession",
                                                   "release-species-inventory-table", "dump-dir"]),
     ("run_release_for_assembly", ["private-config-xml-file", "taxonomy-id",
                                   "assembly-accession", "release-species-inventory-table",
                                   "release-folder", "release-jar-path", "job-repo-url", "memory"]),
     ("merge_dbsnp_eva_release_files", ["bgzip-path", "tabix-path", "bcftools-path",
                                        "vcf-sort-script-path", "assembly-accession",
                                        "release-folder"]),
     ("sort_bgzip_tabix_release_files", ["bgzip-path", "tabix-path",
                                         "vcf-sort-script-path", "assembly-accession",
                                         "release-folder"]),
     ("validate_release_vcf_files", ["private-config-xml-file", "taxonomy-id",
                                     "assembly-accession", "release-species-inventory-table",
                                     "release-folder",
                                     "vcf-validator-path", "assembly-checker-path"])
     ])

workflow_process_template_for_nextflow = """
process {workflow-process-name} {{
    memory='{memory} GB'
    input:
        val flag from {previous-process-output-flag}
    output:
        val true into {current-process-output-flag}
    script:
    \"\"\"
    export PYTHONPATH={script-path} &&  ({python3-path} -m run_release_in_embassy.{process-with-args} 1>> {assembly-release-folder}/release_3847_{assembly-accession}.log 2>&1)
    \"\"\"
}}
"""


def get_release_properties_for_current_assembly(common_release_properties, taxonomy_id, assembly_accession, memory):
    release_properties = copy.deepcopy(common_release_properties)
    release_properties["taxonomy-id"] = taxonomy_id
    release_properties["assembly-accession"] = assembly_accession
    release_properties["memory"] = memory
    release_properties["assembly-release-folder"] = \
        os.path.join(release_properties["release-folder"], assembly_accession)
    os.makedirs(release_properties["assembly-release-folder"], exist_ok=True)
    release_properties["dump-dir"] = os.path.join(release_properties["assembly-release-folder"], "dumps")
    os.makedirs(release_properties["dump-dir"], exist_ok=True)
    return release_properties


def generate_workflow_file_for_assembly(release_properties):
    workflow_file_name = os.path.join(release_properties["assembly-release-folder"],
                                      "{0}_release_workflow.nf".format(release_properties["assembly-accession"]))
    with open(workflow_file_name, "w") as workflow_file_handle:
        header = "#!/usr/bin/env nextflow"
        workflow_file_handle.write(header + "\n")
        # This hack is needed to kick-off the initial process in Nextflow
        release_properties["previous-process-output-flag"] = "true"
        # Ensure that PYTHONPATH is properly set so that scripts can be run
        # as "python3 -m run_release_in_embassy.<script_name>"
        release_properties["script-path"] = os.environ["PYTHONPATH"]
        process_output_flag_index = 1
        for workflow_process_name, workflow_process_args in workflow_process_arguments_map.items():
            release_properties["workflow-process-name"] = workflow_process_name + "_" + \
                                                          release_properties["assembly-accession"].replace('.', '_')
            release_properties["current-process-output-flag"] = "flag" + str(process_output_flag_index)
            process_output_flag_index += 1
            release_properties["process-with-args"] = "{0} {1}".format(workflow_process_name,
                                                                       " ".join(["--{0} {1}".format(arg,
                                                                                                    release_properties[
                                                                                                        arg])
                                                                                 for arg in workflow_process_args]))
            workflow_file_handle.write(workflow_process_template_for_nextflow.format(**release_properties) + "\n")
            # Set the flag that will capture the output status of the current process
            # This variable will be used to decide whether the next process should be started
            # See http://nextflow-io.github.io/patterns/index.html#_mock_dependency
            release_properties["previous-process-output-flag"] = "flag" + str(process_output_flag_index - 1)
    return workflow_file_name


def prepare_release_workflow_file_for_assembly(common_release_properties, taxonomy_id, assembly_accession, memory):
    release_properties = get_release_properties_for_current_assembly(common_release_properties, taxonomy_id,
                                                                     assembly_accession, memory)

    return generate_workflow_file_for_assembly(release_properties)


def get_common_release_properties(common_release_properties_file):
    return json.load(open(common_release_properties_file))


def run_release_for_species(common_release_properties_file, taxonomy_id, memory):
    common_release_properties = get_common_release_properties(common_release_properties_file)
    private_config_xml_file = common_release_properties["private-config-xml-file"]
    release_species_inventory_table = common_release_properties["release-species-inventory-table"]
    with psycopg2.connect(get_pg_metadata_uri_for_eva_profile("development", private_config_xml_file), user="evadev") \
        as metadata_connection_handle:
        release_assemblies = get_release_assemblies_for_taxonomy(taxonomy_id, release_species_inventory_table,
                                                                 metadata_connection_handle)
        release_assembly_workflow_files = [prepare_release_workflow_file_for_assembly(common_release_properties,
                                                                                      taxonomy_id, assembly_accession,
                                                                                      memory)
                                           for assembly_accession in release_assemblies]
        for workflow_file_name in release_assembly_workflow_files:
            workflow_report_file_name = workflow_file_name.replace(".nf", ".report.html")
            workflow_command = "{0} run {1} -c {2} -with-report {3} -bg".format(
                common_release_properties["nextflow-binary-path"], workflow_file_name,
                common_release_properties["nextflow-config-path"], workflow_report_file_name)
            logger.info("Running workflow file {0} with the following command:\n\n {1} \n\n"
                        "Use the above command with -resume if this workflow needs to be resumed in the future"
                        .format(workflow_file_name, workflow_command))
            os.system(workflow_command)


@click.option("--common-release-properties-file", help="ex: /path/to/release/properties.json", required=True)
@click.option("--taxonomy-id", help="ex: 9913", required=True)
@click.option("--memory",  help="Memory in GB. ex: 8", default=8, type=int, required=False)
@click.command()
def main(common_release_properties_file, taxonomy_id, memory):
    run_release_for_species(common_release_properties_file, taxonomy_id, memory)


if __name__ == "__main__":
    main()