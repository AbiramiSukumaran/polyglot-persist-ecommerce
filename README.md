---
id: multidb-cross-cloud-retail
summary: Build an Intelligent Ecommerce Catalog using AlloyDB, MongoDB, Cloud Storage, BigQuery, and the MCP Toolbox.
authors: Abirami Sukumaran, Shweta Shetye
keywords: event:GoogleCloudNext2026, docType:Codelab, category:Cloud, product:AlloyDbForPostgresql, product:Bigquery, product:CloudRun
layout: paginated

---

# Build an Intelligent Ecommerce Catalog with Multi-database Persistence

## Introduction

In modern retail, your data is a diverse, sprawling ecosystem. You have rock-solid transactional data (pricing and inventory), "messy" polymorphic catalogs (electronics specs vs. apparel sizes), and petabytes of behavioral logs. Forcing these into a single monolith doesn't just create technical debt—it kills the user experience.

In this codelab, you will architect a Polyglot Powerhouse that harmonizes:

- [AlloyDB](https://cloud.google.com/alloydb/docs): Your transactional backbone for high-speed consistency and image embeddings.
- [MongoDB Atlas on Google Cloud](https://www.mongodb.com/docs/atlas/): Your flexible, schema-agnostic catalog layer.
- [Cloud Storage](https://cloud.google.com/storage/docs): Your analytical brain for real-time trend forecasting.
- [BigQuery](https://cloud.google.com/bigquery/docs): Your high-res digital warehouse.

The "secret sauce"? You’ll use the [MCP Toolbox for Databases](https://mcp-toolbox.dev/documentation/introduction/) to intelligently orchestrate and unify the data sources running on Cloud Run as a semantic bridge, then deploy a multi-agent chat app using [Agent Development Kit (ADK)](https://adk.dev/). You’re not just building a search bar; you’re building an intelligent retail brain that understands context, respects constraints, and bridges the gap between raw data and human intent.

### The Impossible User Query

Standard e-commerce agents fail at multi-dimensional reasoning (combining negative constraints, visual similarity, and real-time inventory). For example, I typically want to talk to a retail site like this:

"Hey, I’m planning a high-altitude photography trip. Show me some weather-resistant backpacks similar in style to the ‘AeroGlow Pro’ but without any leather components. Also, let me know if they are actually in stock and if other photographers have complained about the strap durability in the reviews."

### Why this query is "The Agent Killer":

* **Visual Similarity (AlloyDB + Vector Search):** "Similar in style to the AeroGlow Pro" requires image embedding comparison.
* **Negative Constraint (MongoDB):** "Without any leather" requires filtering through flexible, nested attributes that aren't usually in a standard SQL schema.
* **Real-Time Inventory (AlloyDB):** "Actually in stock" requires a live transactional check (not a stale search index).
* **Semantic Synthesis (BigQuery + Multi-Agent):** Analyzing reviews for "strap durability" requires the agent to summarize unstructured feedback from BigQuery on the fly.

Most retail bots would just see 'Backpack' and 'Leather' and show 10 leather backpacks. How are we stopping that? 

Because we aren't just matching keywords. We’re using the MCP Toolbox to let our agents 'reason' across all these sources the transactional truth in AlloyDB and the flexible attributes in MongoDB simultaneously. Let’s build it.

### What you'll do

-   Provision an **[AlloyDB](https://cloud.google.com/alloydb/docs)** cluster for core product data
-   Configure **[MongoDB Atlas on Google Cloud](https://www.mongodb.com/docs/atlas/)** to store semi-structured product details
-   Create a **[Cloud Storage](https://cloud.google.com/storage/docs)** bucket to serve product images
-   Deploy the **[MCP Toolbox for Databases](https://mcp-toolbox.dev/documentation/)** to **[Cloud Run](https://cloud.google.com/run/docs)** for uniform data access
-   Run ETL processes to push data into **[BigQuery](https://cloud.google.com/bigquery/docs)** for analytics
-   Converse with an AI agent in natural language.

![Ecommerce multi database architecture](architecture-diagram.png)

### Prerequisites

-   A web browser such as [Chrome](https://www.google.com/chrome/)
-   A Google Cloud project with billing enabled
-   A free [MongoDB Atlas on Google Cloud](https://www.mongodb.com/cloud/atlas) account

## Before you begin

Duration: 05:00

### Create a Google Cloud Project
1. In the Google Cloud Console, on the project selector page, select or create a Google Cloud project.
2. Make sure that billing is enabled for your Cloud project. 


### Start Cloud Shell

Cloud Shell is a command-line environment running in Google Cloud that comes preloaded with necessary tools.

1. Click Activate Cloud Shell at the top of the Google Cloud console.
Once connected to Cloud Shell, verify your authentication:
```bash
gcloud auth list
```

Confirm your project is configured:
```bash
gcloud config get project
```
If your project is not set as expected, set it:
```bash
export PROJECT_ID=<YOUR_PROJECT_ID>
gcloud config set project $PROJECT_ID
```

### Enable required APIs

Run this command to enable all the required APIs:

```bash
gcloud services enable \
  alloydb.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  secretmanager.googleapis.com \
  compute.googleapis.com \
  servicenetworking.googleapis.com \
  aiplatform.googleapis.com
```

## Set up Cloud Storage

Duration: 03:00

Cloud Storage serves as a massive store for unstructured media assets, such as
product images.

1.  In the Google Cloud Console, navigate to **Cloud Storage**, and click
   **Create bucket**.
2.  Give your bucket a globally unique name (e.g., `ecommerce-app-images`).
3.  Click **Create**.
4.  To allow the demo application to access the images without authentication,
    clear the **Enforce public access prevention on this bucket** option, and
    click **Confirm**.
5.  Go to the **Permissions** tab.
6.  In **Permissions**, click **Grant access**.
7.  In **New principals**, enter `allUsers`.
8.  In **Select a role**, select **Cloud Storage** > **Storage Object User**.
9.  Click **Save**, and then click **Allow Public Access** to confirm that you
    are making the resource public.

### Upload placeholder images

The project (https://github.com/AbiramiSukumaran/polyglot-persist-ecommerce)
uses placeholder images for the best visual experience.

1.  In your Cloud Shell, clone the repository:
    ```bash
    git clone https://github.com/AbiramiSukumaran/polyglot-persist-ecommerce.git
    ```

2.  Navigate to the `UploadImages` folder:

    ```bash
    cd UploadImages
    ```

3.  In the Google Cloud Console, navigate to **Cloud Storage**, and click
   **Buckets**.
4.  Click the name of your newly created bucket.
5.  Click **Upload** > **Upload files**, select the downloaded sample images,
    and click
   **Open**.

## Set up AlloyDB

Duration: 10:00

AlloyDB serves as the single source of truth for structured, transactional, and
critical data like product IDs, names, SKUs, prices, and inventory. AlloyDB also
powers the AI agent with similarity search capabilities for recommendations and
natural language queries.

> Note:
To quickly set up a cluster, instance, and network for your
development environment using a web interface, follow the steps in this
[codelab](https://codelabs.developers.google.com/easy-alloydb-setup).

### Provision an AlloyDB Cluster

1.  In the Google Cloud Console, navigate to **AlloyDB for PostgreSQL**.
2.  Click **Create Cluster**.
3.  For **Cluster ID**, enter `ecommerce-cluster`.
4.  Set a strong password for the `postgres` user. For learning purposes, you
    can use `alloydb`.
5.  For **Database Version**, keep the default.
6.  For **Region**, select `us-central1` (or your preferred region).

### Configure Primary Instance

1.  For **Instance ID**, enter `ecommerce-cluster-primary`.
2.  In **Zonal Availability**, select **Single zone**.
3.  For **Machine Type**, choose a small machine type (e.g., N2, 4 vCPUs, 32 GB
    RAM).
4.  In **Private IP Connectivity**, select **Private Services Access (PSA)**,
    and select the `default` network.

    If default network isn't already set, click **Confirm network setup** to
    create one.

5.  In **Public IP Connectivity**, select the **Enable Public IP** checkbox for the MCP
    toolbox to connect properly in this codelab.

6.  In **Authorised external networks**, enter `0.0.0.0/0`. Select the **I
    acknowledge the risks** checkbox and click **Save**.
7.  Click **Create Cluster**.

Note: Ensure you note down your public IP addres (it looks similar to
`34.124.240.26`).

> Note:
It takes up to 10 minutes for the cluster and instance to be
created.

### Initialize the Database

1.  Click **AlloyDB Studio** from the left navigation menu.
2.  In **Database** drop-down, select `postgres`.
3.  Select **Built-in authentication** to sign in to the database.
4.  For **Username**, use the `postgres` user.
5.  For **Password**, enter the password you set earlier.
6.  Click **Authenticate**.
7.  In the editor view, open a new untitled query tab.
8.  Copy the following DDL and click **Run**:

    ```sql
    CREATE TABLE products_core_table (
      product_id UUID PRIMARY KEY,
      name VARCHAR(255) NOT NULL,
      sku VARCHAR(50) UNIQUE NOT NULL,
      price NUMERIC(10, 2) NOT NULL,
      stock INT NOT NULL
    );
    ```

1.  In your Cloud Shell, navigate to the project root folder.

2. Open the `alloydb_insert_queries.sql` file in your Cloud Shell and copy the insert queries.

    ```bash
    cat alloydb_insert_queries.sql
    ```

3.  In a new untitled query tab, paste only the `INSERT` statements and click **Run**.
4.  In a new untitled query tab, copy the following DDL and click **Run** to create an index on the `products_core_table` table:

    ```sql
    CREATE INDEX idx_products_core_sku ON products_core_table(sku);
    ```

### Create image embeddings for AI agent to fetch similar products

The AI agent integration uses image embeddings to fetch similar products. The
embeddings are generated using the `multimodalembedding@001` model and stored in
the AlloyDB database. The embeddings are 1408 dimensional vectors and are stored
in the `img_embeddings` column.

Before we can generate embeddings, we must grant required roles to the AlloyDB
service account to access Cloud Storage.

#### Grant roles to AlloyDB service account to access Cloud Storage

We grant the Storage Object User and Storage Object Viewer role to the AlloyDB
service account to enable it to read objects from the Cloud Storage bucket.

1.  Navigate to **IAM and admin**.
2.  Click **Grant access**.
3.  In the **New principals** field, enter the search for AlloyDB service
    account. The service account looks similar to
    `service-991742412753@gcp-sa-alloydb.iam.gserviceaccount.com`.
4.  Click **Select a role**.
5.  Find and select the **Storage Object User** role.
6.  Click **Add another role** and select the **Storage Object Viewer** role.
6.  Click **Add another role** and select the **Vertex AI User** role.
7.  Click **Save**.

#### Enable extensions

For building this app, we will use the extensions `pgvector` and
`google_ml_integration`. The `pgvector` extension allows you to store and search
vector embeddings. The `google_ml_integration` extension provides functions you
use to access Vertex AI prediction endpoints to get predictions in SQL. Enable
these extensions by running the following DDLs:

1.  In the Google Cloud Console, navigate to **AlloyDB for PostgreSQL**.
1.  Click **AlloyDB Studio** from the left navigation menu.
1.  In the editor view, open a new untitled query tab.
2.  Copy the following DDL and click **Run**:

    ```sql
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS google_ml_integration;
    ```

#### Initialize database with embeddings

1.  Add the img_embeddings column to the `products_core_table`.

    ```sql
    ALTER TABLE products_core_table
    ADD COLUMN img_embeddings vector(1408);
    ```

2.  Generate embeddings for the images and store them in the `img_embeddings`
    column.

    ```sql
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
        AND sku IS NOT NULL
        LIMIT 10
    );
    ```

    Replace `<STORAGE_BUCKET_NAME>` with your Cloud Storage bucket name.


3. Repeat the earlier query at least 5 times to generate image embeddings for the
    entire set, as the Studio has a 5-minute limitation. If this query times
    out, change the `LIMIT` to `5` and rerun the query ten times. This step
    might take a couple of minutes to complete.

## Set up MongoDB Atlas on Google Cloud

Duration: 05:00

MongoDB stores rich, semi-structured product details and flexible user behavior
data (like clicks and views).\

### Create MongoDB cluster

1.  Go to [MongoDB Atlas on Google Cloud](https://www.mongodb.com/cloud/atlas),
    select a free tier account.
2.  Select the **Free** cluster tier, and enter a name for the cluster, for example
    `ecommerce-cluster`.
3.  Select **Google Cloud** as the provider and ensure the region aligns with
    your Google Cloud region (e.g., `us-central1`).
4.  Click **Create Deployment**.
5.  Click **Close**.

### Configure Network Access

1.  In the Atlas console, go to **Database & Network Access**.
2.  Click **IP Access List**.
3.  Click **Add IP Address**.
4.  Add `0.0.0.0/0`, which allows access from anywhere.
5.  Click **Confirm**.

> Note:
Using `0.0.0.0/0` allows access from any IP
address. This is acceptable for a temporary demo, but in production, you
should restrict access to specific IP ranges.

### Create a Database User

1.  In the Atlas console, go to **Database & Network Access**.
2.  Click **Database Users**.
3.  Click **Add New Database User**.
4.  Select **Password** as the authentication method.
5.  Enter username as `store-user` and password as `storeuser`.
6.  Click **Add Built In Role**, select **Read and write to any database**.
7.  Click **Add User**.

### Get the Connection String

1.  Go to **Database > Clusters** > **Connect**.
2.  In the **Connect your application**, click **Drivers**.
3.  Copy the connection string that is shown in **Add your connection string into
    your application code**. The string looks something like this:

    ```bash
    mongodb+srv://store-user:<db_password>@ecommerce-cluster.g8vaekh.mongodb.net/?appName=ecommerce-cluster
    ```

    Replace `db_password` with your MongoDB password. In this codelab, it is
    `storeuser`.

Save this connection string. You will use it later for the
`MONGODB_CONNECTION_STRING` environment variable.

### Create Database and Collection

1.  In the Atlas console, go to **Database > Clusters > Browse Collections**.
2.  Click **Create Database** and enter the details:
    -   **Database Name:** `ecommerce_db`
    -   **Collection Name:** `product_details_collection`
3.  Click **Create Database**.
4.  In the Data Explorer, select the Collection Name.
5.  Click the **Add Data (+)** icon, and then click **Insert document**.
6.  Copy the JSON content from
    [product_details_export.json](https://github.com/AbiramiSukumaran/polyglot-persist-ecommerce/blob/master/product_details_export.json)
    and paste it into the **Insert Document** editor dialog.
7.  Click **Insert** to insert the array of documents and verify that 192
    documents are added.
8.  In the Data Explorer, click **Create collection (+)** next to the
    `ecommerce_db` database.
9.  Enter `user_interactions_collection` for the collection name, and click **Create Collection**.
10. In the Data Explorer, select the `user_interactions_collection` collection.
11. Click the **Add Data (+)** icon, and then click **Insert document**.
12. Copy the JSON content from
    [user_interactions_export.json](https://github.com/AbiramiSukumaran/polyglot-persist-ecommerce/blob/master/user_interactions_export.json)
    and paste it into the **Insert Document** editor dialog.
13. Click **Insert Document**.

## Set up BigQuery

Duration: 03:00

BigQuery aggregates and analyzes historical user behavior to generate
intelligent reporting and recommendations.

### Create the Dataset

1.  In the Google Cloud Console, navigate to **BigQuery**.
2.  Next to your project ID in the Explorer pane, click the three-dot menu and
    select **Create dataset**.
3.  Enter `ecommerce_analytics` for the **Dataset ID**.
4.  Click **Create dataset**.

### Create the Analytics Table

1.  Open a new query in the BigQuery workspace.
2.  Run the following SQL statement to create the summary table linking users to
    product interactions:

```sql
CREATE TABLE ecommerce_analytics.user_product_interactions (
    user_id STRING DEFAULT 'any user',
    product_id STRING,
    interaction_score INT
);
```

### Grant roles to Compute service account for MCP Toolbox

We grant roles to the Compute service account used for our Toolbox. This is done
to enable the MCP Toolbox to access BigQuery, Secret Manager, and other cloud
services.

> Note:
To find the Project Number, on the Google Cloud Console,
click **Cloud Overview > Dashboard**. Note the Project Number listed in the
**Project info** card.

To grant roles, complete the following steps:

1.  Navigate to **IAM and admin**.
2.  Click **Grant access**.

3.  In the **New principals** field, enter the default Compute service account named
    `YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com`. Replace
    `YOUR_PROJECT_NUMBER` with your Google Cloud Project Number.

4.  Click **Select a role**.
5.  Find and select the **BigQuery Data Editor** role.
6.  Click **Add another role** and select the **BigQuery Job User** role.
7.  Click **Add another role** and select the **Secret Manager Secret Accessor**
    role.
7.  Click **Add another role** and select the **Editor** role.
8.  Click **Save**.

## Understand the Application End to End

To learn about how each component works with each other, we will create a simple
ecommerce application that uses multiple databases and services. The application
is built with a Python (Flask) backend and integrates multiple Google Cloud
services and databases.

### Understand the directory structure

In the next section, you will clone the
[`polyglot-persist-ecommerce`](https://github.com/AbiramiSukumaran/polyglot-persist-ecommerce)
repository and use it to run the application locally. Once we test the
application locally, we will deploy both MCP Toolbox and the application to
Cloud Run.

Explore the downloaded files in this directory. The following high level
directories are present:

*   `UploadImages`: stores image assets, primarily used for documentation or visual
    content for the ecommerce product catalog.
*   `static`: stores the application's static web assets, such as CSS and
    JavaScript files, used to style and add interactivity to the user interface
    ( source).
*   `templates`: stores the HTML templates (likely Jinja2 for Flask) used by the
    Python application to dynamically render web pages for the ecommerce catalog
    ( source).


The files in this repository work together to build, configure, and deploy a
multidb ecommerce application. Central files like `app.py` orchestrate the
backend by integrating diverse data sources defined in SQL and JSON files, while
configuration files ensure seamless deployment to cloud environments:

*   `app.py`: orchestrates Flask backend and multi-database integrations.
*   `agentengine.py`: Core logic for initializing and configuring Vertex AI
    agents.
*   `.env`: stores secrets for database and storage connections.
*   `tools.yaml`: configures MCP Toolbox for multidb database operations.
*   `Dockerfile`: defines container image and environment setup.
*   `requirements.txt`: lists Python libraries needed for application runtime.
*   `tools.yaml`: configurations for MCP Toolbox.
*   `Procfile`: specifies production execution commands for deployment.
*   `alloydb_insert_queries.sql`: contains SQL queries for relational data.
*   `product_details_export.json` and `user_interactions_export.json`:
    provides sample JSON data for NoSQL database.
*   `README.md`: guides setup, deployment, and project understanding.

### End-to-End Flow of the Application

*   **AlloyDB Setup**: Provision a high-performance cluster and use the provided SQL scripts to create the products_core_table with vector columns for image embeddings.
*   **MongoDB Atlas Setup**: Deploy a cluster on Google Cloud to store fluid product attributes in product_details and log real-time clickstreams in user_interactions.
*   **BigQuery Analytics**: Create a dataset to aggregate interaction logs, enabling complex analytical queries that identify "Top 5" trending items across millions of events.
*   **Cloud Storage Repository**: Create a public bucket to house high-resolution product imagery, ensuring each asset is accessible via a signed or public URL for the frontend.
*   **MCP Toolbox Deployment**: Deploy the Toolbox to Cloud Run, establishing it as the central RESTful bridge that translates natural language intent into multi-database queries.
*   **Tools.yaml Configuration**: Define your "Tools"—such as get_product_core_data or get_top_5_views—mapping specific SQL and NoSQL operations to simple, agent-readable names.
*   **Flask Backend Logic**: Implement app.py routes that interface with the MCP Toolbox, handling the coordination of data retrieval and serving as the API for the UI.
*   **Multi-Agent Orchestration**: Configure the ADK agents within the code to reason through user intent, selecting the right "Tool" to solve complex, multi-source retail queries.
*   **Frontend Integration**: Build an index.html interface featuring the product catalog with interactions recording feature, Analytics tab to understand product performance analytics, and a dedicated "Agent Tab" that uses the ADK multi-agent chat to provide a seamless conversational shopping experience.

Now let’s implement the orchestration and deployments.

## Setup MCP Toolbox and Deploy to Cloud Run

Duration: 10:00

The MCP Toolbox abstracts our multiple data sources, letting our application
fetch and write data uniformly.

### Install MCP Toolbox Locally

1.  In your Cloud Shell, navigate to the project root folder

2.  Download the MCP Toolbox binary and make it executable:

    ```bash
    export VERSION=1.14.0
    curl -L -o toolbox https://storage.googleapis.com/genai-toolbox/v$VERSION/linux/amd64/toolbox
    chmod +x toolbox
    ```

### Configure tools.yaml

You need to define the abstractions for AlloyDB, MongoDB, and BigQuery. The
`tools.yaml` file tells the MCP toolbox how to interact with each other.

1.  Create and edit the file `tools.yaml` using the embedded editor:

    ```bash
    cloudshell edit tools.yaml
    ```

    The complete `tools.yaml` file can be found in the [GitHub Repository](https://github.com/AbiramiSukumaran/polyglot-persist-ecommerce/blob/master/tools.yaml). Copy its contents into your new `tools.yaml` file.

2.  Update the host, user, passwords, project IDs, and connection strings to
    match the infrastructure you provisioned in earlier steps:

    | Database | Field | Example Value |
    |---|---|---|
    | AlloyDB/BigQuery | `project_id` | `YOUR_PROJECT_ID` |
    | AlloyDB | `region` | `us-central1` |
    | AlloyDB | `cluster` | `ecommerce-cluster` |
    | AlloyDB | `instance` | `ecommerce-cluster-primary` |
    | AlloyDB | `database` | `postgres` |
    | AlloyDB | `password` | `alloydb` |
    | MongoDB | `connection_string`  | `mongodb+srv://*****:*****storeuser*****@ecommerce-cluster.*****.mongodb.net`

### Grant roles to Compute service account for MCP Toolbox

We grant roles to the Compute service account used for our Toolbox. This is done
to enable the MCP Toolbox to access AlloyDB.

1.  Navigate to **IAM and admin**.
2.  Click **Grant access**.

3.  In the **New principals** field, enter the default Compute service account named
    `YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com`. Replace
    `YOUR_PROJECT_NUMBER` with your Google Cloud Project Number.

    > Note:
    **Project Number:** To find the Project Number, on the
    Google Cloud Console, click **Cloud Overview > Dashboard**. Note the
    Project Number listed in the **Project info** card.

4.  Click **Select a role**.
5.  Find and select the **BigQuery Data Editor** role.
6.  Click **Add another role** and select the **AlloyDB Client** role.
7.  Click **Add another role** and select the **Service Usage Consumer** role.
8.  Click **Add another role** and select **Storage Object Viewer** role.
9.  Click **Save**.

### Test your tool UI

1.  In your cloudshell terminal, run the toolbox locally to serve the UI:

    ```bash
    ./toolbox --ui
    ```

2.  Open the Web Preview in Cloud Shell on port 5000 and navigate to the tools
    page. For example, depending on your session URL, you can view it at:
    `https://5000-cs-71152278760-default.cs-asia-southeast1-cash.cloudshell.dev/ui`

> Note:
**Accessing MCP UI in Cloud Shell:** Cloud Shell exposes
local ports using Web Preview. Instead of opening `localhost:8080`, you must
use the web preview URL and append `/ui`, for example:
`https://5000-cs-.../ui?authuser=0`. Without this, it just shows a "Hello
World" plain message instead of the loaded UI dashboard.

The following MCP toolbox UI is seen:

![MCP Toolbox UI](toolbox-ui.png)

### Deploy to Cloud Run

Deploy the MCP Toolbox to Cloud Run to make it available as a secure, managed
service that our application can use to query the databases. We will store the
configuration in Secret Manager to protect sensitive connection details.

1.  Open a new Cloud Shell session.
2.  Navigate to the project root folder

3.  Upload the `tools.yaml` config to Google Secret Manager:

    ```bash
    gcloud secrets create tools --data-file=tools.yaml
    ```

    Note: To add a new version to the existing secret, use the following
    command:

    ```bash
    gcloud secrets versions add tools --data-file=tools.yaml
    ```

4.  Deploy using the public MCP Toolbox container image:

    ```bash
    export IMAGE=us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest
    export PROJECT_ID=$(gcloud config get-value project)

    gcloud run deploy toolbox \
        --image $IMAGE \
        --region us-central1 \
        --service-account $(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")-compute@developer.gserviceaccount.com \
        --set-secrets "/app/tools.yaml=tools:latest" \
        --args="--tools-file=/app/tools.yaml","--address=0.0.0.0","--port=8080","--ui" \
        --allow-unauthenticated
    ```

5.  Once deployed, note down the provided Cloud Run Service URL. It should look
    like `https://toolbox-*********-uc.a.run.app/ui`.

## Set up the ecommerce application and deploy to Cloud Run

Duration: 05:00

With our databases running and the MCP Toolbox abstraction deployed, we can run
the Flask web application!

To serve the product catalog, the Flask application processes data by performing
the following steps:

1.  **Fetch core data**: Retrieves the full list of products from AlloyDB
    (`list_products_core`).
2.  **Fetch extended details**: Retrieves all product details from MongoDB
    (`list_all_product_details`).
3.  **Combine lists**: Concatenates the two lists.
4.  **Enrich with media**: Adds the Cloud Storage image URL to every item.

### Generate reasoning engine application path

To initialize and register an AI agent using Google Cloud's Vertex AI Reasoning
Engine, run the following command:

1.  In your cloudshell terminal, navigate to the project root
    folder.

2. Run the requirements.txt to install the dependencies

    ```bash
    pip install -r requirements.txt
    ```

2.  Run the `agentengine.py` script to generate the reasoning engine application
    path:

    ```bash
    python agentengine.py
    ```

The output will be similar to the following:

```bash
projects/991742412753/locations/us-central1/reasoningEngines/4933254136889081856
```

### Configure the Environment Variables

1.  Create a `.env` file and edit it:

    ```bash
    cloudshell edit .env
    ```

2.  Replace the values with your specific database connections and your new
    Cloud Run Toolbox URL:

    ```ini
    # 1. MongoDB Connection String
    MONGODB_CONNECTION_STRING="mongodb+srv://<db_user>:<db_password>@cluster0.mongodb.net"

    # 2. MCP Toolbox Server Location
    # Must match the address where you run the toolbox server
    MCP_TOOLBOX_SERVER_URL="https://toolbox-*********-uc.a.run.app"

    # 3. Google Cloud Storage Bucket Name
    GCS_PRODUCT_BUCKET="ecommerce-app-images"

    # 4. Fallback image URL
    FALLBACK_IMAGE_URL="https://storage.googleapis.com/ecommerce-media-bold-circuit-492711-n9/fallback.jpg"

    # 5. Google Gen AI Vertex AI flag
    GOOGLE_GENAI_USE_VERTEXAI=TRUE

    # 6. Project ID
    PROJECT_ID=*****

    # 7. Google Cloud Location of AlloyDB, BigQuery databases
    GOOGLE_CLOUD_LOCATION=us-central1

    # 8. Reasoning engine application path
    APP_NAME=projects/*****/locations/us-central1/reasoningEngines/*****

    # 9. Model ID
    MODEL=gemini-2.5-flash
    ```

    > Note:
    You may notice that not all images load immediately;
    some links might go missing or mispoint based on how properties map to
    product SKUs in the cloned application dataset. Double-check your GCS
    bucket's public access policies and ensure file names map correctly.

### Deploy the Frontend to Cloud Run

1.  Deploy the web application to Cloud Run to complete the architecture:

    ```bash
    gcloud run deploy polyglot --source . --platform managed \
      --region us-central1 \
      --allow-unauthenticated \
      --set-env-vars \
      MONGODB_CONNECTION_STRING="<MONGODB_CONNECTION_STRING>", \
      MCP_TOOLBOX_SERVER_URL="<MCP_TOOLBOX_SERVER_URL>", \
      GCS_PRODUCT_BUCKET="<GCS_PRODUCT_BUCKET>", \
      FALLBACK_IMAGE_URL="<FALLBACK_IMAGE_URL>", \
      GOOGLE_GENAI_USE_VERTEXAI=TRUE, \
      PROJECT_ID="YOUR_PROJECT_ID", \
      GOOGLE_CLOUD_LOCATION=us-central1, \
      APP_NAME="<YOUR_REASONING_ENGINE_APP_PATH>", \
      MODEL="gemini-2.5-flash"
    ```

    Replace the following values:

    *   `YOUR_PROJECT_ID`: Your Google Cloud Project ID.
    *   `YOUR_REASONING_ENGINE_APP_PATH`: The output from running `python agentengine.py`, for example, `projects/991742412753/locations/us-central1/reasoningEngines/4933254136889081856`.
    *   `MCP_TOOLBOX_SERVER_URL`: The URL of your MCP Toolbox server, for
        example `https://toolbox-*********-uc.a.run.app`.
    *   `GCS_PRODUCT_BUCKET`: The name of your Google Cloud Storage bucket, for
        example `ecommerce-app-images`.
    *   `MONGODB_CONNECTION_STRING`: The connection string for your MongoDB
        database, for example `mongodb+srv://store-user:storeuser@ecommerce-cluster.g8vaekh.mongodb.net`
    *   `FALLBACK_IMAGE_URL`: The URL of the fallback image, for example
        `https://storage.googleapis.com/ecommerce-app-images/fallback.jpg`

    > Note:
    If deployment fails, run the `gcloud auth login` command to authorize the
    deployment, and then run the deploy command again.

Your application is now live! Open the service URL provided by Cloud Run to see
the Multidb Ecommerce catalog. The URL will be similar to
`https://polyglot-*********-uc.a.run.app/`.

## Explore the application

1.  Click **Product Catalog** to view all products.<br>

    ![Product Catalog](ecommerice-screen-1.png)

1.  Click a product icon to view product details. You will notice that the
    images are sourced from Cloud Storage, the product details are fetched from
    MongoDB and the product inventory is fetched from AlloyDB.

    ![Product Details](ecommerice-screen-2.png)


1.  Interact with the product catalog to generate mock views and writes sent to
    **MongoDB**.

1.  Click the **ETL & Analytics** to view the product analytics. You will notice
    that the product analytics are fetched from BigQuery.<br>

    ![Product ETL and Analytics](ecommerice-screen-3.png)


1.  Click the **AI agent** tab to interact with the AI agent. Ask natural
    language questions such as the following:<br>

    ```
    I’m planning a high-altitude photography trip. 
    Show me some weather-resistant backpacks similar in style to aero glow pro 
    but without any leather components. Also, let me know if they are actually in 
    stock and if other photographers have complained about the strap durability 
    in the reviews.
    ```
    <br><br>
    ![AI Agent](ecommerice-screen-4.png)

You can see that the search returns exactly what we asked for - a backpack without 
leather components, in stock and with no complaints about strap durability in the reviews.

![AI Agent](ecommerice-screen-5.png)

## Clean up

To avoid ongoing charges to your Google Cloud account, delete the resources
created during this codelab.

Run these cloud shell commands:

```bash
gcloud run services delete toolbox --region us-central1 --quiet
gcloud run services delete multi-db-app --region us-central1 --quiet
bq rm -r -f -d $PROJECT_ID:ecommerce_analytics
gcloud storage rm --recursive gs://ecommerce-app-images
gcloud alloydb clusters delete ecommerce-cluster --region us-central1 --force --quiet
```

Optionally, to delete the entire Google Cloud project and all its resources, run the following command:

```bash
gcloud projects delete $PROJECT_ID
```

> Note:
Finally, open MongoDB Atlas on Google Cloud and delete the `Cluster0` cluster you created to ensure no dangling free-tier usage.


## Congratulations

Duration: 01:00

Congratulations! You've successfully built a cross-cloud Multidb architecture.

You demonstrated how the MCP Toolbox serves as the architectural glue for a
modern, specialized application. By matching the right database to the right
job, you achieved:

-   **Flexible Data Writes**: MongoDB for event logs.
-   **Transactional Consistency**: AlloyDB for core integrity.
-   **High-Performance Analytics**: BigQuery for business intelligence.
-   **Unified Development**: A single Python backend abstracting all complexity
  using the MCP Toolbox.

### Reference docs

Learn more about related Google Cloud products and explore these codelabs:

- AlloyDB AI: [Getting started with Vector Embeddings with AlloyDB AI](https://codelabs.developers.google.com/getting-started-vector-embeddings-alloydb-ai)
- [AlloyDB AI: Multimodal Embeddings in AlloyDB](https://codelabs.developers.google.com/multimodal-embeddings-alloydb)
- MCP Toolbox: [Installing and Setting-up MCP Toolbox for Databases on AlloyDB](https://codelabs.developers.google.com/installing-and-setting-up-mcp-toolbox-for-databases-on-alloydb)

For more information on the products used in this codelab, see:

- [AlloyDB for PostgreSQL Documentation](https://cloud.google.com/alloydb/docs)
- [MongoDB Atlas on Google Cloud Documentation](https://www.mongodb.com/docs/atlas/)
- [BigQuery Documentation](https://cloud.google.com/bigquery/docs)
- [Cloud Storage Documentation](https://cloud.google.com/storage/docs)
- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud Build Documentation](https://cloud.google.com/build/docs)
- [MCP Toolbox Implementation](https://mcp-toolbox.dev/documentation/)


