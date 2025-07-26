# --- Imports ---
from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import re
import os
import google.generativeai as genai
from dotenv import load_dotenv

# --- Initialization ---
app = Flask(__name__)
load_dotenv()
CORS(app)

# --- Configure the Gemini API ---
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found. Please add it to your .env file.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini API configured successfully!")
except Exception as e:
    print(f"❌ Error configuring Gemini API: {e}")
    model = None

# --- Database Loading with explicit types for stability ---
try:
    # Specifying dtypes helps prevent pandas from misinterpreting column types
    orders_df = pd.read_csv("data/orders.csv", dtype={'order_id': int, 'user_id': int})
    order_items_df = pd.read_csv("data/order_items.csv")
    products_df = pd.read_csv("data/products.csv")
    users_df = pd.read_csv("data/users.csv", dtype={'id': int})
    distribution_centers_df = pd.read_csv("data/distribution_centers.csv")
    inventory_items_df = pd.read_csv("data/inventory_items.csv")
    print("✅ All e-commerce datasets loaded successfully!")
except FileNotFoundError as e:
    print(f"❌ Error: Dataset file not found. Make sure you have a 'data' folder with all the CSV files. Details: {e}")
    exit()

# --- REWRITTEN Chatbot Logic ---

def get_top_selling_products(limit: int = 5) -> list:
    """
    Correctly calculates the most sold products using a robust pandas method.
    """
    # Count sales of each product_id
    sales_counts = order_items_df['product_id'].value_counts().reset_index()
    sales_counts.columns = ['id', 'sales']

    # Merge with products_df to get the names
    # Using a left merge to ensure we keep all our sales counts
    merged_df = pd.merge(sales_counts, products_df, on='id', how='left')

    # Sort by sales count and get the top N
    top_products = merged_df.sort_values(by='sales', ascending=False).head(limit)
    
    # Return a clean list of dictionaries for the AI
    return top_products[['name', 'sales']].to_dict('records')


def get_context_from_data(message: str) -> (str, str):
    """
    A more robust and accurate function to find context from the dataframes.
    """
    message_lower = message.lower()
    
    # Intent: Top-selling products (High Priority)
    if any(keyword in message_lower for keyword in ["top 5", "most sold", "best selling", "most popular"]):
        top_products = get_top_selling_products()
        return f"User is asking for top selling products. Data: {top_products}", "top_products_list"

    # Intent: User Information
    user_match = re.search(r"(user|customer) #?(\d+)", message_lower)
    if user_match:
        user_id = int(user_match.group(2))
        user_data = users_df[users_df['id'] == user_id]
        if not user_data.empty:
            return f"User is asking about customer #{user_id}. Data: {user_data.to_dict('records')[0]}", "user_info"
        else:
            return f"Could not find data for user ID {user_id}.", "user_info"

    # Intent: Order Tracking
    order_match = re.search(r"order #?(\d+)", message_lower)
    if order_match:
        order_id = int(order_match.group(1))
        order_data = orders_df[orders_df['order_id'] == order_id]
        if not order_data.empty:
            return f"User is asking about order #{order_id}. Data: {order_data.to_dict('records')[0]}", "track_order"
        else:
            return f"Could not find data for order ID {order_id}.", "track_order"

    # Intent: Product Information (More robust search)
    matched_product = None
    # Iterate through all products to find the best possible match in the user's query
    for _, product in products_df.iterrows():
        product_name = str(product['name']).lower()
        if product_name in message_lower:
            # This logic prefers longer, more specific matches
            if matched_product is None or len(product_name) > len(str(matched_product['name']).lower()):
                 matched_product = product
    
    if matched_product is not None:
        return f"User is asking about a product. Data: {matched_product.to_dict()}", "product_info"

    return "User is asking a general question. No specific data found.", "general_query"


def get_ai_response(message: str) -> str:
    """
    Builds a detailed prompt for the Gemini API and returns its response.
    """
    if not model:
        return "Sorry, the AI service is currently unavailable. Please check the server logs."

    context, intent = get_context_from_data(message)

    system_prompt = f"""
    You are a friendly and helpful customer support assistant for an e-commerce clothing website.
    Your goal is to answer the user's question based on the CONTEXT provided below.
    - Be conversational, clear, and polite.
    - If the CONTEXT has the data, answer the question directly and confidently. For example, if the context says an order status is 'Shipped', state that it is 'Shipped'.
    - If the CONTEXT indicates that something was not found (e.g., an invalid order ID), inform the user politely and ask them to double-check the ID.
    - If the CONTEXT contains a list of items (like top-selling products), format it as a numbered list for clarity.
    - Do not make up information. If the CONTEXT says 'No specific data found', state that you cannot answer the question and list the things you can help with (tracking orders, product info, user info, top sellers).
    - Format prices with a dollar sign and two decimal places (e.g., $45.00).
    - Keep your answers concise and to the point.

    ---
    CONTEXT: {context}
    ---
    USER'S QUESTION: {message}
    """
    
    try:
        response = model.generate_content(system_prompt)
        return response.text
    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        return "Sorry, I'm having trouble connecting to the AI service right now."

# --- Flask API Routes ---

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "API is running", "endpoints": ["/chat"]})


@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "Invalid message"}), 400
    ai_response = get_ai_response(user_message)
    return jsonify({"response": ai_response})

# --- Main Execution Block ---
if __name__ == "__main__":
    app.run(debug=True, port=5000)
