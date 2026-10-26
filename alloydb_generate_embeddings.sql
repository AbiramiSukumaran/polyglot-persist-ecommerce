-- Generate embeddings for product images using google_ml.image_embedding.
--
-- Instructions:
-- 1. Replace <STORAGE_BUCKET_NAME> with your Cloud Storage bucket name.
-- 2. Run once (about a minute). If it times out, run it again; rows already embedded are skipped.
--
-- Note: Only SKUs that have a corresponding image in UploadImages/ are processed,
-- as google_ml.image_embedding fails the entire transaction if any referenced
-- object does not exist in Cloud Storage.

UPDATE products_core_table
SET img_embeddings = google_ml.image_embedding(
    model_id => 'multimodalembedding@001',
    image => 'gs://<STORAGE_BUCKET_NAME>/' || sku || '.jpg',
    mimetype => 'image/jpeg')
WHERE sku IN (
    SELECT
        sku
    FROM
        products_core_table
    WHERE
        img_embeddings IS NULL
        AND sku IN (
            'ACC-LS-SL-37',
            'ACC-NP-MF-87',
            'ACC-WL-CL-08',
            'AP-BT-KR-56',
            'AP-HAT-WL-26',
            'AP-JS-SF-17',
            'AP-LG-FL-96',
            'AP-RJ-LW-75',
            'AP-SC-RC-64',
            'AP-SH-CR-86',
            'AP-SH-V5-GRY',
            'AP-SW-CB-18',
            'AP-TS-CW-45',
            'AP-YM-CS-05',
            'BK-AI-FH-11',
            'BK-CS-BC-60',
            'BK-DS-IN-90',
            'BK-FIC-CF-73',
            'BK-MA-AC-47',
            'BK-PH-DM-12',
            'BK-PY-AP-22',
            'CRAFT-CK-BG-84',
            'EL-AC-FP-38',
            'EL-CA-HS-58',
            'EL-CAM-DC-91',
            'EL-CH-GN-19',
            'EL-CP-WL-42',
            'EL-DOCK-PG-13',
            'EL-DR-C1-25',
            'EL-EB-NC-14',
            'EL-FT-WG-44',
            'EL-HD-PR-55',
            'EL-INK-HY-83',
            'EL-KEY-MECH-02',
            'EL-MIC-US-77',
            'EL-MON-4K-01',
            'EL-MOU-RGB-03',
            'EL-MT-TV-95',
            'EL-PB-20K-36',
            'EL-PL-SW-82',
            'EL-SC-WL-65',
            'EL-SH-HG-30',
            'EL-SL-KE-50',
            'EL-SM-NI-59',
            'EL-SPK-BT-23',
            'EL-SSD-1T-71',
            'FIT-DB-AD-28',
            'FIT-YB-ST-92',
            'FOOD-TEA-OG-51',
            'HG-BF-MU-48',
            'HG-BL-OC-10',
            'HG-BL-WB-100',
            'HG-BM-PS-76',
            'HG-CB-BL-32',
            'HG-CH-GM-72',
            'HG-CL-MF-33',
            'HG-CS-SS-89',
            'HG-CU-ES-27',
            'HG-DC-LS-70',
            'HG-DF-EO-79',
            'HG-DS-AH-80',
            'HG-EM-PM-49',
            'HG-EO-SP-99',
            'HG-FJ-IN-63',
            'HG-FP-SS-66',
            'HG-FP-WF-94',
            'HG-LM-MW-09',
            'HG-MT-MF-61'
        )
);
