/*
 *
 * Copyright 2018 EMBL - European Bioinformatics Institute
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 */

package uk.ac.ebi.eva.accession.dbsnp.io;

import com.mongodb.BulkWriteResult;
import org.springframework.batch.item.ItemWriter;
import org.springframework.data.mongodb.BulkOperationException;
import org.springframework.data.mongodb.core.BulkOperations;
import org.springframework.data.mongodb.core.MongoTemplate;

import uk.ac.ebi.eva.accession.core.model.dbsnp.DbsnpSubmittedVariantOperationEntity;
import uk.ac.ebi.eva.accession.core.batch.listeners.ImportCounts;

import java.util.List;

public class DbsnpSubmittedVariantOperationWriter implements ItemWriter<DbsnpSubmittedVariantOperationEntity> {

    private MongoTemplate mongoTemplate;

    private ImportCounts importCounts;

    public DbsnpSubmittedVariantOperationWriter(MongoTemplate mongoTemplate, ImportCounts importCounts) {
        this.mongoTemplate = mongoTemplate;
        this.importCounts = importCounts;
    }

    @Override
    public void write(List<? extends DbsnpSubmittedVariantOperationEntity> importedSubmittedVariantsOperations)
            throws Exception {
        try {
            BulkOperations bulkOperations = mongoTemplate.bulkOps(BulkOperations.BulkMode.UNORDERED,
                                                                  DbsnpSubmittedVariantOperationEntity.class);
            bulkOperations.insert(importedSubmittedVariantsOperations);
            bulkOperations.execute();
            importCounts.addOperationsWritten(importedSubmittedVariantsOperations.size());
        } catch (BulkOperationException e) {
            BulkWriteResult bulkWriteResult = e.getResult();
            importCounts.addOperationsWritten(bulkWriteResult.getInsertedCount());
            throw e;
        }
    }
}
