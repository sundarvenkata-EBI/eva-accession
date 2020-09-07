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
import logging
import os
import psycopg2
import signal
import sys
import traceback

from run_release_in_embassy.release_metadata import get_release_assemblies_for_taxonomy, \
    get_target_mongo_instance_for_taxonomy
from ebi_eva_common_pyutils.config_utils import get_mongo_uri_for_eva_profile, get_pg_metadata_uri_for_eva_profile
from ebi_eva_common_pyutils.mongo_utils import copy_db
from ebi_eva_common_pyutils.network_utils import get_available_local_port, forward_remote_port_to_local_port
from pymongo.uri_parser import parse_uri


logger = logging.getLogger(__name__)
collections_assembly_attribute_map = {
    "dbsnpSubmittedVariantEntity": "seq",
    "dbsnpSubmittedVariantOperationEntity": "inactiveObjects.seq",
    "submittedVariantEntity": "seq",
    "submittedVariantOperationEntity": "inactiveObjects.seq",
    "dbsnpClusteredVariantEntity": "asm",
    "dbsnpClusteredVariantOperationEntity": "inactiveObjects.asm",
    "clusteredVariantEntity": "asm",
    "clusteredVariantOperationEntity": "inactiveObjects.asm"
}


def mongo_data_copy_to_remote_host(local_forwarded_port, private_config_xml_file, assemblies,
                                   collections_to_copy_list, dump_dir):
    collections_to_copy_map = collections_assembly_attribute_map
    if collections_to_copy_list:
        collections_to_copy_map = {key: value for (key, value) in collections_assembly_attribute_map.items()
                                   if key in collections_to_copy_list}
    mongo_params = parse_uri(get_mongo_uri_for_eva_profile("production", private_config_xml_file))
    # nodelist is in format: [(host1,port1), (host2,port2)]. Just choose one.
    # Mongo is smart enough to fallback to secondaries automatically.
    mongo_host = mongo_params["nodelist"][0][0]
    for assembly in assemblies:
        logger.info("Beginning data copy for assembly: " + assembly)
        for collection, collection_assembly_attribute_name in sorted(collections_to_copy_map.items()):
            logger.info("Begin processing collection: " + collection)
            # Curly braces when they are not positional parameters
            query = """'{{"{0}": {{"$in":["{1}"]}}}}'""".format(collection_assembly_attribute_name, assembly)
            sharded_db_name = "eva_accession_sharded"
            dump_output_dir = "{0}/dump_{1}".format(dump_dir, assembly.replace(".", "_"))
            mongodump_args = {"db": sharded_db_name, "host": mongo_host,
                              "username": mongo_params["username"], "password": mongo_params["password"],
                              "authenticationDatabase": "admin", "collection": collection,
                              "query": query, "out": dump_output_dir
                              }
            mongorestore_args = {"db": "acc_" + assembly.replace(".", "_"),
                                 "dir": "{0}/{1}/{2}.bson".format(dump_output_dir, sharded_db_name, collection),
                                 "collection": collection, "port": local_forwarded_port}
            logger.info("Running export to {0} with query {1} against {2}.{3} in production"
                        .format(dump_output_dir, query, sharded_db_name, collection))
            copy_db(mongodump_args, mongorestore_args)


def copy_accessioning_collections_to_embassy(private_config_xml_file, taxonomy_id,
                                             collections_to_copy, release_species_inventory_table, dump_dir):
    MONGO_PORT = 27017
    local_forwarded_port = get_available_local_port(MONGO_PORT)
    port_forwarding_process_id = None
    exit_code = 0
    try:
        with psycopg2.connect(get_pg_metadata_uri_for_eva_profile("development", private_config_xml_file),
                              user="evadev") as \
                metadata_connection_handle:
            tempmongo_instance = get_target_mongo_instance_for_taxonomy(taxonomy_id, release_species_inventory_table,
                                                                        metadata_connection_handle)
            logger.info("Forwarding remote MongoDB port 27017 to local port {0}...".format(local_forwarded_port))
            port_forwarding_process_id = forward_remote_port_to_local_port(tempmongo_instance, MONGO_PORT,
                                                                           local_forwarded_port)
            logger.info("Beginning data copy to remote MongoDB host {0}...".format(tempmongo_instance))

            assemblies = get_release_assemblies_for_taxonomy(taxonomy_id, release_species_inventory_table,
                                                             metadata_connection_handle)
            mongo_data_copy_to_remote_host(local_forwarded_port, private_config_xml_file,
                                           assemblies, collections_to_copy, dump_dir)
    except Exception as ex:
        logger.error("Encountered an error while copying species data to Embassy for assemblies in "
                      + tempmongo_instance + "\n" + traceback.format_exc())
        exit_code = -1
    finally:
        if port_forwarding_process_id:
            os.kill(port_forwarding_process_id, signal.SIGTERM)
            os.system('echo -e "Killed port forwarding from remote port with signal 1 - SIGTERM. '
                      '\\033[31;1;4mIGNORE OS MESSAGE ' # escape sequences for bold red and underlined text
                      '\'Killed by Signal 1\' in the preceding/following text\\033[0m".')
        logger.info("Copy process completed with exit_code: " + str(exit_code))
        sys.exit(exit_code)


@click.option("--private-config-xml-file", help="ex: /path/to/eva-maven-settings.xml", required=True)
@click.option("--taxonomy-id", help="ex: 9913", required=True)
@click.option("--collections-to-copy", "-c", default=None,
              help="ex: dbsnpSubmittedVariantEntity,dbsnpSubmittedVariantOperationEntity", multiple=True,
              required=False)
@click.option("--release-species-inventory-table", default="dbsnp_ensembl_species.release_species_inventory",
              required=False)
@click.option("--dump-dir", help="ex: /path/to/dump", required=True)
@click.command()
def main(private_config_xml_file, taxonomy_id, collections_to_copy, release_species_inventory_table, dump_dir):
    copy_accessioning_collections_to_embassy(private_config_xml_file, taxonomy_id, collections_to_copy,
                                             release_species_inventory_table, dump_dir)


if __name__ == "__main__":
    main()