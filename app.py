# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import json
import asyncio
import threading
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_from_directory, Response
from dotenv import load_dotenv
import requests
from google import genai
from google import adk
from google.genai import types as genai_types
from toolbox_core import ToolboxSyncClient
from google.adk.runners import Runner
from google.adk.sessions import VertexAiSessionService, InMemorySessionService
import vertexai
from flask_cors import CORS

# Load environment variables
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_IMAGES_DIR = os.path.join(BASE_DIR, "UploadImages")
USE_LOCAL_IMAGES = os.getenv("USE_LOCAL_IMAGES", "true" if os.path.isdir(UPLOAD_IMAGES_DIR) else "false").lower() == "true"
GCS_BUCKET_NAME = os.getenv('GCS_PRODUCT_BUCKET', 'placeholder-bucket')
GCS_BASE_URL = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}"

# Parse seeded AlloyDB stock levels once at startup as authoritative fallback
SKU_STOCK_MAP = {}
try:
    sql_path = os.path.join(BASE_DIR, "alloydb_insert_queries.sql")
    if os.path.isfile(sql_path):
        with open(sql_path, "r", encoding="utf-8") as f:
            sql_content = f.read()
        pattern = re.compile(r"gen_random_uuid\(\)\s*,\s*'(?:''|[^'])*'\s*,\s*'([^']+)'\s*,\s*[0-9.]+\s*,\s*(\d+)\s*\)")
        for sku_match, stock_match in pattern.findall(sql_content):
            SKU_STOCK_MAP[sku_match] = int(stock_match)
        print(f"-> Startup: Seeded stock map initialized with {len(SKU_STOCK_MAP)} AlloyDB SKUs.")
except Exception as e:
    print(f"Warning: Failed to parse SKU_STOCK_MAP from alloydb_insert_queries.sql: {e}")

PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="400" height="300">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#162032" />
    </linearGradient>
  </defs>
  <rect width="400" height="300" fill="url(#bgGrad)" />
  <rect x="10" y="10" width="380" height="280" rx="12" fill="none" stroke="#334155" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.6" />
  <g transform="translate(200, 130)" stroke="#64748b" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M0 -34 L30 -17 L30 17 L0 34 L-30 17 L-30 -17 Z" />
    <path d="M0 -34 L0 34" />
    <path d="M-30 -17 L0 0 L30 -17" />
  </g>
  <text x="200" y="212" text-anchor="middle" fill="#64748b" font-family="JetBrains Mono, monospace" font-size="12" font-weight="600" letter-spacing="2">CATALOG PREVIEW</text>
</svg>"""

if USE_LOCAL_IMAGES:
    FALLBACK_IMAGE_URL = "/images/placeholder.svg"
else:
    FALLBACK_IMAGE_URL = os.getenv('FALLBACK_IMAGE_URL', f"{GCS_BASE_URL}/fallback.jpg")

def infer_category_from_sku(sku):
    """Infers product category from standard SKU prefixes."""
    if not sku:
        return 'General'
    sku_upper = sku.upper()
    prefix_map = {
        'EL-': 'Electronics',
        'HG-': 'Home & Garden',
        'AP-': 'Apparel',
        'OUT-': 'Outdoor',
        'BK-': 'Books',
        'FIT-': 'Fitness',
        'TOOL-': 'Tools',
        'ACC-': 'Accessories',
        'TOY-': 'Toys',
        'FOOD-': 'Food & Beverage',
        'CRAFT-': 'Crafts',
    }
    for prefix, cat in prefix_map.items():
        if sku_upper.startswith(prefix):
            return cat
    return 'Catalog'

GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
PROJECT_ID = os.getenv("PROJECT_ID")
APP_NAME = os.getenv("APP_NAME")
USER = "default_user"
MODEL = os.getenv("MODEL", "gemini-2.5-flash")
REASONING_ENGINE_LOCATION = os.getenv('REASONING_ENGINE_LOCATION', 'us-central1')
has_reasoning_engine = bool(APP_NAME and "*****" not in APP_NAME and APP_NAME.startswith("projects/"))
USE_IN_MEMORY_SESSION = os.getenv("USE_IN_MEMORY_SESSION", "false" if has_reasoning_engine else "true").lower() == "true"
REMOTE_POLYGLOT_URL = os.getenv("REMOTE_POLYGLOT_URL", "").rstrip("/")

if PROJECT_ID and "*****" not in PROJECT_ID:
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)

# Initialize Vertex AI client safely
client = None
if PROJECT_ID and "*****" not in PROJECT_ID:
    try:
        client = vertexai.Client(
            project=PROJECT_ID,
            location=GOOGLE_CLOUD_LOCATION
        )
    except Exception as e:
        print(f"Warning: vertexai.Client init failed: {e}")

model_id = MODEL

# Initialize the MCP Toolbox Client
raw_toolbox_url = (os.getenv("MCP_TOOLBOX_SERVER_URL") or "").rstrip("/")
if raw_toolbox_url.endswith("/mcp"):
    raw_toolbox_url = raw_toolbox_url[:-4]
TOOLBOX_URL = raw_toolbox_url
if not TOOLBOX_URL:
    raise ValueError("MCP_TOOLBOX_SERVER_URL not set in environment.")

try:
    toolboxCore = ToolboxSyncClient(TOOLBOX_URL)
    all_tools = toolboxCore.load_toolset("ecommerce_toolset")
    print(f"-> MCP Client: Successfully loaded {len(all_tools)} tools from {TOOLBOX_URL} (Session Kept Open)")
except Exception as e:
    print(f"FATAL ERROR: Could not connect to MCP Toolbox Server at {TOOLBOX_URL}. Error: {e}")
    exit(1)


def has_local_sku_image(sku):
    """Checks whether a valid .jpg file exists locally in UploadImages for the SKU."""
    if not sku or sku == "N/A":
        return False
    safe_name = os.path.basename(f"{sku}.jpg")
    return os.path.isfile(os.path.join(UPLOAD_IMAGES_DIR, safe_name))


def resolve_image_url(sku):
    """Resolves local or GCS image URL based on configuration and file existence."""
    if USE_LOCAL_IMAGES:
        if has_local_sku_image(sku):
            return f"/images/{os.path.basename(sku)}.jpg"
        return "/images/placeholder.svg"
    if sku and sku != "N/A":
        return f"{GCS_BASE_URL}/{sku}.jpg"
    return FALLBACK_IMAGE_URL


def get_preloaded_tool(tool_name):
    """Finds and returns a loaded tool from the pre-warmed toolset."""
    for tool in all_tools:
        if hasattr(tool, 'name') and tool.name == tool_name:
            return tool
        if hasattr(tool, '_name') and tool._name == tool_name:
            return tool
        if isinstance(tool, dict) and tool.get('name') == tool_name:
            return tool
        if str(tool) == tool_name:
            return tool

    available_names = []
    for t in all_tools:
        if hasattr(t, 'name'):
            available_names.append(t.name)
        elif hasattr(t, '_name'):
            available_names.append(t._name)
        else:
            available_names.append(str(t))
    print(f"ERROR: Tool '{tool_name}' not found. Available tools: {available_names}")
    raise ValueError(f"Tool '{tool_name}' was not found in the loaded toolset.")


def execute_tool(tool_name, params=None):
    """Safely finds a preloaded tool and executes it natively."""
    tool = get_preloaded_tool(tool_name)
    params = params or {}

    try:
        if hasattr(tool, 'invoke') and callable(getattr(tool, 'invoke')):
            return tool.invoke(params)
        elif callable(tool):
            return tool(**params)
        else:
            for attr in ['_invoke', '_run', 'run']:
                if hasattr(tool, attr) and callable(getattr(tool, attr)):
                    return getattr(tool, attr)(**params)
            raise AttributeError(f"Tool {tool_name} is neither callable nor does it support '.invoke()'")
    except Exception as e:
        print(f"ERROR: Failed executing tool '{tool_name}' with parameters {params}. Error: {e}")
        raise e


def safe_decode_data(data):
    """Safely decodes data received from the MCP client."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode JSON string: {data[:50]}...")
            return None
    return data


def safe_load_tool_result(result):
    """Unpacks stateless MCP list wrapper content and JSON strings."""
    if result is None:
        return []

    # Step 1: Unpack standard Stateless MCP list wrapper content
    if isinstance(result, list) and len(result) > 0:
        first_item = result[0]
        if hasattr(first_item, 'text'):
            result = first_item.text
        elif isinstance(first_item, dict) and 'text' in first_item:
            result = first_item['text']

    if hasattr(result, 'content'):
        if isinstance(result.content, list) and len(result.content) > 0:
            first_content = result.content[0]
            if hasattr(first_content, 'text'):
                result = first_content.text
            elif isinstance(first_content, dict) and 'text' in first_content:
                result = first_content['text']
        else:
            result = result.content

    if hasattr(result, 'text'):
        result = result.text

    # Step 2: Parse and Clean JSON strings
    if isinstance(result, str):
        result_str = result.strip()
        if result_str.startswith("```json"):
            result_str = result_str[7:]
        elif result_str.startswith("```"):
            result_str = result_str[3:]
        if result_str.endswith("```"):
            result_str = result_str[:-3]
        result_str = result_str.strip()

        try:
            parsed = json.loads(result_str)
            if parsed is None:
                return []
            if isinstance(parsed, dict):
                for key in ['result', 'data', 'products', 'content', 'items']:
                    if key in parsed and isinstance(parsed[key], list):
                        return parsed[key]
                return [parsed]
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError as e:
            print(f"Error: Could not decode JSON string from tool result. Reason: {e}")
            print(f"Failed string context: {result_str[:150]}")
            return []

    # Step 3: Parse standard Python Dictionaries
    elif isinstance(result, dict):
        for key in ['result', 'data', 'products', 'content', 'items']:
            if key in result and isinstance(result[key], list):
                return result[key]
        return [result]

    # Step 4: Fallback for clean lists
    elif isinstance(result, list):
        cleaned_list = []
        for item in result:
            if isinstance(item, dict):
                cleaned_list.append(item)
            elif hasattr(item, 'text'):
                try:
                    parsed_item = json.loads(item.text)
                    if isinstance(parsed_item, list):
                        cleaned_list.extend(parsed_item)
                    else:
                        cleaned_list.append(parsed_item)
                except Exception:
                    pass
        if cleaned_list:
            return cleaned_list
        return result

    return []


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


# --- Routes ---

@app.route('/')
def index():
    """Renders the main product catalog page."""
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    """Returns 204 to prevent browser 404 console errors."""
    return '', 204


@app.route('/images/placeholder.svg')
def serve_placeholder_svg():
    """Serves crisp dark-slate SVG placeholder for missing images."""
    return Response(PLACEHOLDER_SVG, mimetype='image/svg+xml')


@app.route('/images/<path:filename>')
def serve_product_image(filename):
    """Serves local product images from UploadImages with fallback."""
    safe_filename = os.path.basename(filename)
    if safe_filename == 'placeholder.svg' or safe_filename.endswith('.svg'):
        return Response(PLACEHOLDER_SVG, mimetype='image/svg+xml')
    target = os.path.join(UPLOAD_IMAGES_DIR, safe_filename)
    if os.path.isfile(target):
        return send_from_directory(UPLOAD_IMAGES_DIR, safe_filename, max_age=3600)
    return Response(PLACEHOLDER_SVG, mimetype='image/svg+xml')


@app.route('/products/<product_id>', methods=['GET'])
def get_product(product_id):
    raw_core = None
    raw_details = None

    # 1. FETCH CORE TRANSACTIONAL DATA (AlloyDB)
    try:
        raw_core_response = execute_tool("get_product_core_data", {"product_id": product_id})
        decoded_core = safe_load_tool_result(raw_core_response)
        if decoded_core and isinstance(decoded_core, list):
            raw_core = decoded_core[0]
        elif isinstance(decoded_core, dict):
            raw_core = decoded_core
    except Exception as e:
        print(f"Warning: AlloyDB core data fetch failed for ID {product_id}: {e}")

    # 2. FETCH FLEXIBLE CATALOG DETAILS (MongoDB)
    try:
        raw_details_response = execute_tool("get_product_details", {"product_id": product_id})
        decoded_details = safe_load_tool_result(raw_details_response)
        if decoded_details and isinstance(decoded_details, list):
            raw_details = decoded_details[0]
        elif isinstance(decoded_details, dict):
            raw_details = decoded_details
    except Exception as e:
        print(f"Warning: MongoDB detail fetch failed for ID {product_id}: {e}")

    # Fallback: if MongoDB details missing for this ID, look up by SKU from all details
    if not raw_details and raw_core and isinstance(raw_core, dict) and raw_core.get('sku'):
        try:
            raw_details_res = execute_tool("list_all_product_details", {})
            all_details = safe_load_tool_result(raw_details_res)
            target_sku = raw_core['sku'].lower()
            for item in all_details:
                if isinstance(item, dict) and (item.get('sku') or '').lower() == target_sku:
                    raw_details = item
                    break
        except Exception as e:
            print(f"Warning: Secondary MongoDB SKU fallback failed: {e}")

    # 3. MERGE LOGIC
    core_data = raw_core if isinstance(raw_core, dict) else {}
    details_data = raw_details if isinstance(raw_details, dict) else {}

    if core_data or details_data:
        full_product = {**details_data, **core_data}
        if not details_data:
            full_product['source_note'] = 'PARTIAL MODE: MongoDB details missing.'
    else:
        print(f"ERROR: Both AlloyDB and MongoDB missed for ID {product_id}")
        return jsonify({"message": f"Product ID {product_id} not found in any data store."}), 404

    if 'price' not in full_product or full_product['price'] is None:
        full_product['price'] = 0.0

    sku = full_product.get('sku', '')
    if 'stock' not in full_product or full_product['stock'] is None or full_product['stock'] == 0:
        full_product['stock'] = SKU_STOCK_MAP.get(sku, full_product.get('stock', 0))

    if not full_product.get('category'):
        full_product['category'] = infer_category_from_sku(sku)

    if 'reviews' not in full_product or not full_product['reviews']:
        rev_sum = full_product.get('reviews_summary')
        if rev_sum and isinstance(rev_sum, dict):
            full_product['reviews'] = [
                {
                    "rating": rev_sum.get("average_rating", 4.8),
                    "user": f"Verified Reviewer ({rev_sum.get('total_reviews', 150)}+ ratings)",
                    "comment": rev_sum.get("sentiment", "Excellent display quality and sleek design.")
                }
            ]

    full_product['image_url'] = resolve_image_url(sku)
    full_product['has_image'] = has_local_sku_image(sku)
    full_product['fallback_url'] = FALLBACK_IMAGE_URL

    return jsonify(full_product)


@app.route('/inventory/<category>', methods=['GET'])
def get_category_inventory_stats(category):
    """Demonstrates using a single MongoDB Aggregation tool for analytics."""
    try:
        stats_data = execute_tool("get_product_stats_by_category", {"category": category})
        parsed_stats = safe_load_tool_result(stats_data)
        return jsonify({
            "message": "Product statistics successfully aggregated from MongoDB.",
            "statistics": parsed_stats
        })
    except Exception as e:
        print(f"Error on category inventory lookup: {e}")
        return jsonify({"error": "Failed to run category aggregation tool.", "details": str(e)}), 500


@app.route('/products', methods=['GET'])
def list_products():
    final_catalog = []
    try:
        # 1. Fetch Core Data (AlloyDB)
        raw_core_res = execute_tool("list_products_core", {})
        alloydb_products = safe_load_tool_result(raw_core_res)

        # 2. Fetch All Rich Details (MongoDB)
        raw_details_res = execute_tool("list_all_product_details", {})
        mongodb_details = safe_load_tool_result(raw_details_res)

        details_by_id = {item['product_id']: item for item in mongodb_details if isinstance(item, dict) and 'product_id' in item}
        details_by_sku = {(item.get('sku') or '').upper(): item for item in mongodb_details if isinstance(item, dict) and item.get('sku')}

        matched_mongo_pids = set()
        matched_skus = set()

        # 3. Merge Strategy
        for core_prod in alloydb_products:
            if not isinstance(core_prod, dict):
                continue
            pid = core_prod.get('product_id')
            sku = core_prod.get('sku')
            sku_upper = (sku or '').upper()

            rich_details = details_by_id.get(pid) or details_by_sku.get(sku_upper, {})
            if rich_details:
                if rich_details.get('product_id'):
                    matched_mongo_pids.add(rich_details['product_id'])
                if rich_details.get('sku'):
                    matched_skus.add(rich_details['sku'].upper())
            if sku_upper:
                matched_skus.add(sku_upper)

            merged_product = {**rich_details, **core_prod}
            
            # Hydrate stock from core_prod or fallback to seeded SKU_STOCK_MAP
            if merged_product.get('stock') is None:
                merged_product['stock'] = SKU_STOCK_MAP.get(sku, 50)

            # Hydrate category
            if not merged_product.get('category') or merged_product.get('category') == 'Item':
                merged_product['category'] = infer_category_from_sku(sku)

            merged_product['image_url'] = resolve_image_url(sku)
            merged_product['has_image'] = has_local_sku_image(sku)
            merged_product['fallback_url'] = FALLBACK_IMAGE_URL
            merged_product['source'] = 'Polyglot (AlloyDB + MongoDB)'
            final_catalog.append(merged_product)

        # 4. Handle edge case: Products in Mongo but NOT in AlloyDB (Disjoint)
        alloy_ids = {p.get('product_id') for p in alloydb_products if isinstance(p, dict)}
        for pid, details in details_by_id.items():
            details_sku_upper = (details.get('sku') or '').upper()
            if pid in alloy_ids or pid in matched_mongo_pids or (details_sku_upper and details_sku_upper in matched_skus):
                continue

            sku_val = details.get('sku')
            if not details.get('name'):
                desc = details.get('description', '')
                if desc and len(desc.split('.')[0]) < 60:
                    details['name'] = desc.split('.')[0].strip()
                else:
                    details['name'] = f"{details.get('category', 'Catalog')} Item · {sku_val or pid[:6]}"
            details['price'] = 0.00
            details['stock'] = 0
            details['source'] = 'MongoDB Only'
            if not details.get('category'):
                details['category'] = infer_category_from_sku(sku_val)
            details['has_image'] = has_local_sku_image(sku_val)
            details['image_url'] = resolve_image_url(sku_val)
            details['fallback_url'] = FALLBACK_IMAGE_URL
            final_catalog.append(details)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error building unified catalog: {e}")
        return jsonify({"error": "Catalog generation failed", "details": str(e)}), 500

    return jsonify(final_catalog)


@app.route('/track/view', methods=['POST'])
def track_user_view():
    """Records a user product view event to MongoDB (via MCP Tool)."""
    data = request.json or {}
    user_id = data.get('user_id', 'User')
    product_id = data.get('product_id')

    if not product_id:
        return jsonify({"error": "product_id is required for tracking."}), 400

    try:
        interaction_data = {
            "user_id": user_id,
            "product_id": product_id,
            "details": "User viewed this product.",
            "timestamp": datetime.utcnow().isoformat()
        }
        data_json = json.dumps(interaction_data)
        response = execute_tool("insert_user_interaction", {"data": data_json})

        return jsonify({
            "message": "Interaction tracked successfully (via MongoDB).",
            "inserted_id": response
        }), 201

    except Exception as e:
        print(f"Error while recording user interaction: {e}")
        return jsonify({"error": "Failed to record user interaction.", "details": str(e)}), 500


@app.route('/product_by_id', methods=['POST'])
def get_product_by_id():
    """Retrieves a single product, prioritizing AlloyDB data and falling back to MongoDB details."""
    data = request.json or {}
    user_id = data.get('user_id', 'User')
    product_id = data.get('product_id')
    if not product_id:
        return jsonify({"error": "product_id is required."}), 400

    raw_core = None
    raw_details = None

    try:
        raw_core_response = execute_tool("get_product_core_data", {"product_id": product_id})
        decoded_core_list = safe_decode_data(raw_core_response)
        raw_core = decoded_core_list[0] if isinstance(decoded_core_list, list) and decoded_core_list else None
    except Exception as e:
        print(f"Warning: AlloyDB core data fetch failed for ID {product_id}. {e}")

    try:
        raw_details_response = execute_tool("get_product_details", {"product_id": product_id})
        decoded_details_list = safe_decode_data(raw_details_response)
        raw_details = decoded_details_list[0] if isinstance(decoded_details_list, list) and decoded_details_list else None
    except Exception as e:
        print(f"Warning: MongoDB detail fetch failed for ID {product_id}. {e}")

    # SKU fallback if details missing
    if not raw_details and raw_core and isinstance(raw_core, dict) and raw_core.get('sku'):
        try:
            raw_details_res = execute_tool("list_all_product_details", {})
            all_details = safe_load_tool_result(raw_details_res)
            target_sku = raw_core['sku'].lower()
            for item in all_details:
                if isinstance(item, dict) and (item.get('sku') or '').lower() == target_sku:
                    raw_details = item
                    break
        except Exception as e:
            print(f"Warning: Secondary MongoDB SKU fallback failed: {e}")

    core_data = {} if not raw_core else raw_core
    details_data = {} if not raw_details else raw_details

    if core_data:
        full_product = {**core_data, **details_data}
        if not details_data:
            full_product['source_note'] = 'PARTIAL MODE: MongoDB details missing.'
    elif details_data:
        synth_core = {
            'product_id': details_data.get('product_id'),
            'name': f"MongoDB Product: {details_data.get('category', 'Generic')}",
            'price': 39.99,
            'sku': details_data.get('sku', 'SYNTH-001'),
            'stock': 999,
            'source_note': 'FALLBACK MODE: Core data synthesized from MongoDB details.'
        }
        full_product = {**synth_core, **details_data}
    else:
        return jsonify({"message": f"Product ID {product_id} not found in any data store."}), 404

    sku = full_product.get('sku', 'N/A')
    full_product['image_url'] = resolve_image_url(sku)
    full_product['has_image'] = has_local_sku_image(sku)
    full_product['fallback_url'] = FALLBACK_IMAGE_URL
    return jsonify(full_product)


@app.route('/etl/run', methods=['POST'])
def run_etl_to_bigquery():
    """Orchestrates the application-driven ETL process."""
    try:
        summary_data = execute_tool("get_total_interactions_count", {"product_id": ""})

        if not summary_data:
            return jsonify({"message": "No interaction data to transfer."}), 200

        parsed_summary = safe_load_tool_result(summary_data)
        products_count = len(parsed_summary) if isinstance(parsed_summary, list) and parsed_summary else (len(summary_data) if hasattr(summary_data, '__len__') else 1)

        bq_response = execute_tool("execute_sql_tool", {"product_summaries": summary_data})
        print(f"ETL BigQuery Response: {bq_response}")

        return jsonify({
            "message": "Application-Driven ETL complete. MongoDB summary merged into BigQuery.",
            "products_processed": products_count,
            "bigquery_response": "success"
        }), 200

    except Exception as e:
        return jsonify({"error": "ETL orchestration failed.", "details": str(e)}), 500


@app.route('/analytics/top5', methods=['GET'])
def get_top_5_products():
    try:
        top5_response = execute_tool("get_top_5_views", {})
        if not top5_response:
            return jsonify([]), 200

        items = safe_load_tool_result(top5_response)
        if not items or not isinstance(items, list):
            items = safe_decode_data(top5_response)
            if not items or not isinstance(items, list):
                return jsonify([]), 200

        core_by_id = {}
        core_by_name = {}
        try:
            raw_core_all = execute_tool("list_products_core", {})
            all_core_list = safe_load_tool_result(raw_core_all)
            for cp in all_core_list:
                if isinstance(cp, dict):
                    if cp.get('product_id'):
                        core_by_id[cp['product_id']] = cp
                    if cp.get('name'):
                        core_by_name[cp['name'].strip().lower()] = cp
        except Exception as e:
            print(f"Warning: Failed pre-fetching core products in top5: {e}")

        top_products_list = []
        for top_item in items:
            if not isinstance(top_item, dict):
                continue
            product_id = top_item.get('product_id')
            if not product_id:
                continue

            core_data = core_by_id.get(product_id, {})
            if not core_data:
                try:
                    core_res = execute_tool("get_product_core_data", {"product_id": product_id})
                    decoded_core = safe_load_tool_result(core_res)
                    if decoded_core and isinstance(decoded_core, list):
                        core_data = decoded_core[0]
                except Exception as e:
                    print(f"AlloyDB fail for {product_id}: {e}")

            details_data = {}
            try:
                details_res = execute_tool("get_product_details", {"product_id": product_id})
                decoded_details = safe_load_tool_result(details_res)
                if decoded_details and isinstance(decoded_details, list):
                    details_data = decoded_details[0]
            except Exception as e:
                print(f"MongoDB fail for {product_id}: {e}")

            if core_data or details_data:
                product = {**details_data, **core_data}
                product.setdefault('name', product.get('description', '').split(':')[0].replace('High-quality ', '').split(' designed for')[0] or f"New: {product.get('category', 'Product')}")
                if not product.get('sku'):
                    matched_core = core_by_name.get(product['name'].strip().lower())
                    if matched_core:
                        product['sku'] = matched_core.get('sku')
                        if 'price' not in product or not product['price']:
                            product['price'] = matched_core.get('price')
                        if 'stock' not in product or not product['stock']:
                            product['stock'] = matched_core.get('stock')

                product['total_views'] = top_item.get('interaction_score', top_item.get('interaction_count', 0))
                sku = product.get('sku')
                if not product.get('category'):
                    product['category'] = infer_category_from_sku(sku)
                product['image_url'] = resolve_image_url(sku)
                product['has_image'] = has_local_sku_image(sku)
                product['fallback_url'] = FALLBACK_IMAGE_URL
                top_products_list.append(product)

        return jsonify(top_products_list)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Analytics Exception: {e}")
        return jsonify({"error": "BigQuery Analytics failed.", "details": str(e)}), 500


# --- Agent Definitions ---

catalog_agent = adk.Agent(
    name="CatalogSpecialist",
    model=MODEL,
    description="Expert in product descriptions, reviews, and detailed specs from MongoDB.",
    instruction="""
    Use 'list_all_product_details' for all product data and 'get_product_details' to answer detailed product questions.
    Always summarize customer sentiment from reviews if available.
    """,
    tools=all_tools
)

inventory_agent = adk.Agent(
    name="InventorySpecialist",
    model=MODEL,
    description="Specialist in real-time stock, pricing, and sales trends.",
    instruction="""
    Use 'get_product_core_data' for stock/price and 'get_top_5_views' for trending data.
    If a user asks for 'Top' or 'Trending' items in a specific category:
    1. Get the trending product IDs using 'get_top_5_views'.
    2. Use 'list_all_product_details' to filter those IDs by the requested category.
    3. If 'get_top_5_views' does not allow filtering, fetch ALL trending items first, then manually filter them using the category info from MongoDB.
    Always return Product Name, SKU, and Price: never the raw Product ID.
    """,
    tools=all_tools
)

etl_agent = adk.Agent(
    name="ETLSpecialist",
    model=MODEL,
    description="Specialist in orchestrating the application-driven ETL process.",
    instruction="""
    Your job is to orchestrate the application-driven ETL process:
    1. READ: Aggregate interaction data from MongoDB (using the tool get_total_interactions_count).
    2. WRITE: MERGE the resulting summary data into BigQuery (using the tool execute_sql_tool).
    
    Use 'get_product_core_data' for stock/price and 'get_top_5_views' for trending data.
    If a user asks for 'Top' items, prioritize BigQuery analytics results.
    """,
    tools=all_tools
)

bi_agent = adk.Agent(
    name="BISpecialist",
    model=MODEL,
    description="Specialist in analyzing and articulating data as a BI expert.",
    instruction="""
    You are a BI expert. Your job is to join data across multiple sources:
    1. For 'Top products in [Category]', first fetch trending IDs using 'get_top_5_views'.
    2. Cross-reference those IDs with 'list_all_product_details' to find matches in the specific category.
    3. If no direct match is found in the top 5, search for the most popular items within that category using interaction counts.
    4. DATA HYDRATION: Never return a raw Product ID. Always use the ID to look up the Name, SKU, and Price before presenting the final list to the user.
    - FORMATTING: Use a bulleted list (*) formatted as * **[Product Name]** - SKU: [sku] - $[Price].
    - NEVER use tables.
    - DATA_PASS_THROUGH (STRICT):
    - You MUST output results as a bulleted list (*).
    - Format: * **[Product Name]** - SKU: [sku_value] - $[Price]
    - NEVER output raw Product IDs (UUIDs) to the user.
    - If a tool only gives you an ID, you MUST use 'list_all_product_details' to find the corresponding SKU before responding.
    """,
    tools=all_tools
)

orchestrator = adk.Agent(
    name="EcommerceOrchestrator",
    model=MODEL,
    description="The primary intelligence and manager for the Polyglot E-commerce system.",
    tools=all_tools,
    instruction="""
    You are a very intelligent, deeply analytical Global Supply Chain and E-commerce Brain. 
    Your mission is to provide grounded, data-backed answers by orchestrating specialized agents and tools.

    Answer the user's request directly and immediately using your specialist agents and tools. Only introduce yourself with a capability list if the user sends a greeting (like 'hi' or 'hello') or explicitly asks what you can do. If a user mentions a brand, style, or product name that is not an exact match (such as 'AeroGlow Pro'), use 'search_products_intelligent' and 'list_all_product_details' to find the closest semantically matching products in our catalog (for example, monitors, lighting, or sleek pro electronics) and return them in the required bullet format.

    HIERARCHY & DELEGATION:
    1. Always attempt to check 'list_all_product_details' from the catalog agent first. This is your primary catalog context for categories, descriptions, and specs.
    2. Delegate specific products, categories, features, specifications, prices, reviews and specific questions to CatalogSpecialist.
    3. Delegate inventory-related questions like 'Is it in stock?' or 'What is trending?' to InventorySpecialist.
    4. Delegate 'Update the database' or 'Run analytics sync' to ETLSpecialist.
    5. For complex analytical queries involving multiple steps, use BISpecialist.
    6. For overall generic queries on data analysis and summary, use CatalogSpecialist.
    7. At times you may have to run complex multi-agent reasoning and analysis and will have to use multiple tools across these agents.
       You are authorized to do that and for those reasons you are allowed to join and analyze data across multiple agents, tools and steps and respond to the user.
    8. Never tell the user that you cannot fulfill a request. Use your intelligence to get the nearest possible response and do not invent facts.
    Never display product id to the user.

    OPERATING PROTOCOLS (CRITICAL):
    - INTELLIGENT DISCOVERY: For any search query that involves looking up product contextually by descriptions, specific features, or negative constraints (e.g., 'not electronic', 'wooden', 'vibrant'), ALWAYS use the 'search_products_intelligent' tool first. 
    - PRE-FETCHED DATA: Always attempt to check 'list_all_product_details' from the catalog agent first for overall product related questions. 
    - Even with that you have to analyze and validate what you are returning is in fact relevant to what the user is asking. 
    - NO HALLUCINATIONS: If information is missing from both the catalog context and tool results, do not invent facts. Ask the user for clarification.
    - NO 'TOOL UNAVAILABLE': Never tell the user a tool is unavailable. If a direct tool doesn't exist, use 'list_all_product_details' or 'list_products_core' to gather raw data and reason through it yourself.
    - DATA JOINING: When combining real-time inventory (AlloyDB) with catalog details (MongoDB), use 'product_id' as the unique join key to ensure accuracy.
    - TOOL CHAINING: You are authorized to chain tools (e.g., fetch trending IDs from BigQuery, then hydrate with prices from AlloyDB and specs from MongoDB).
    - FINAL OUTPUT: Always provide a professional summary. 
    - For product lists, ALWAYS use a standard Markdown bulleted list (*) to ensure the frontend can render them as tiles.
    - NEVER use Markdown tables for product results.
    - DATA_PASS_THROUGH (STRICT): When using 'search_products_intelligent', you are FORBIDDEN from summarizing the results into plain paragraphs. 
    - You MUST output the results as a bulleted list using the asterisk (*).
    - Format every list item exactly like this so the tile is complete:
      * **[Product Name]** - SKU: [sku] - $[Price]
    - DATA_PASS_THROUGH (STRICT):
      - NEVER output raw Product IDs (UUIDs) to the user.
      - If a tool only gives you an ID, you MUST use 'list_all_product_details' to find the corresponding SKU before responding.
    - **MOST CRITICAL** Remember: Ultimately you have access to product specification tool, inventory tool, intelligent search products tool, analytics tool to fetch popularity, and insert user interaction tool. As an agent you can always combine the results with their product id and generate specific results for user response grounded by data coming from those tools instead of saying I am unable to or I cannot unless the product or user ask is completely irrelevant and not at all close to our business.
    """,
    sub_agents=[catalog_agent, inventory_agent, etl_agent, bi_agent]
)

effective_app_name = APP_NAME if (has_reasoning_engine and not USE_IN_MEMORY_SESSION) else "polyglot_local_app"
if USE_IN_MEMORY_SESSION or not APP_NAME:
    session_service = InMemorySessionService()
    effective_app_name = "polyglot_local_app"
else:
    try:
        session_service = VertexAiSessionService(project=PROJECT_ID, location=REASONING_ENGINE_LOCATION)
    except Exception as e:
        print(f"Warning: VertexAiSessionService init failed, using InMemorySessionService: {e}")
        session_service = InMemorySessionService()
        effective_app_name = "polyglot_local_app"

session = None
session_lock = threading.Lock()


async def initialize_session():
    global session
    try:
        session = await session_service.create_session(app_name=effective_app_name, user_id=USER)
        print(f"Session {session.id} created successfully with {type(session_service).__name__}.")
    except Exception as e:
        print(f"Error creating session with {type(session_service).__name__}: {e}")
        if not isinstance(session_service, InMemorySessionService):
            try:
                fallback_service = InMemorySessionService()
                session = await fallback_service.create_session(app_name="polyglot_local_app", user_id=USER)
                print(f"Fallback InMemorySession {session.id} created successfully.")
            except Exception as fb_err:
                print(f"Fallback session creation failed: fb_err={fb_err}")
                session = None
        else:
            session = None


asyncio.run(initialize_session())

runner = adk.Runner(
    agent=orchestrator,
    app_name=effective_app_name,
    session_service=session_service,
)


@app.route('/agent/chat', methods=['POST'])
def chat():
    global session
    data = request.json or {}
    user_input = data.get('message', '').strip()

    if not user_input:
        return jsonify({"reply": "Please enter a message.", "steps": []}), 400

    def call_remote_chat(prompt_msg):
        if not REMOTE_POLYGLOT_URL:
            return None
        try:
            resp = requests.post(
                f"{REMOTE_POLYGLOT_URL}/agent/chat",
                json={"message": prompt_msg},
                headers={"Content-Type": "application/json"},
                timeout=95
            )
            if resp.status_code == 200:
                resp_json = resp.json()
                reply_text = resp_json.get("reply", "")
                is_greeting = prompt_msg.lower().strip() in ["hi", "hello", "hey", "greetings", "good morning", "good evening"]
                has_canned_intro = "Global Supply Chain and E-commerce Brain" in reply_text and "Here is a summary of what I can do" in reply_text
                if has_canned_intro and not is_greeting:
                    print("DEBUG: Remote returned Turn-1 canned intro for product query. Retrying once to get real answer...")
                    retry_resp = requests.post(
                        f"{REMOTE_POLYGLOT_URL}/agent/chat",
                        json={"message": prompt_msg},
                        headers={"Content-Type": "application/json"},
                        timeout=95
                    )
                    if retry_resp.status_code == 200:
                        return retry_resp.json()
                return resp_json
            else:
                print(f"Remote chat returned status {resp.status_code}: {resp.text}")
        except Exception as remote_err:
            print(f"Remote chat proxy error: {remote_err}")
        return None

    local_succeeded = False
    reply = None
    session_id = session.id if session else "local_session"

    AUTH_ERROR_PATTERNS = [
        "RefreshError", "invalid_rapt", "DefaultCredentialsError", "reauthenticate",
        "PERMISSION_DENIED", "401", "403", "UNAUTHENTICATED", "NOT_FOUND", "Could not automatically determine credentials"
    ]

    try:
        content = genai_types.Content(role='user', parts=[genai_types.Part(text=user_input)])

        async def run_agent():
            accumulated_text = []
            async for event in runner.run_async(
                    new_message=content,
                    user_id=USER,
                    session_id=session_id):
                if hasattr(event, 'text') and event.text:
                    accumulated_text.append(event.text)
                elif hasattr(event, 'content') and getattr(event.content, 'parts', None):
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            accumulated_text.append(part.text)
            return "".join(accumulated_text).strip()

        raw_reply = asyncio.run(run_agent())
        if raw_reply:
            if any(err in raw_reply for err in AUTH_ERROR_PATTERNS):
                print(f"Local ADK produced auth error in reply: {raw_reply[:100]}")
            else:
                reply = raw_reply
                local_succeeded = True
    except Exception as e:
        err_str = str(e)
        print(f"Local ADK execution exception: {err_str}")

    if not local_succeeded and REMOTE_POLYGLOT_URL:
        print("Falling back transparently to REMOTE_POLYGLOT_URL/agent/chat...")
        remote_data = call_remote_chat(user_input)
        if remote_data and "reply" in remote_data:
            return jsonify(remote_data)

    if not reply:
        reply = "I've analyzed the data, but I'm having trouble formatting the final summary. Please try again."

    return jsonify({
        "reply": reply,
        "session_id": session_id,
        "narrative": [
            {"agent": "Orchestrator", "action": "Consulting Specialists"},
            {"agent": "Specialist", "action": "Executing Intelligent Search"}
        ]
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
