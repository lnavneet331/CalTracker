# filepath: d:\Programs\Projects\CalTracker\app.py
import streamlit as st
import requests
import datetime
import gspread
from google.oauth2.service_account import Credentials
import json

# Streamlit UI
st.title("Calorie Tracker")

# Input for Gemini API key (stored in Streamlit secrets)
gemini_api_key = st.secrets["gemini_api_key"] if "gemini_api_key" in st.secrets else st.text_input("Enter Gemini API Key", type="password")

# Input for food entry
food_entry = st.text_input("What did you eat?")

# --- Gemini API Call Function ---
def get_nutrition_from_gemini(food, api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    prompt = f"""Give me the nutritional information for: {food}.
    
    Respond in this exact JSON format:
    {{
      "food_items": [
        {{
          "item": "FOOD_NAME",
          "quantity": "QUANTITY",
          "calories": "NUMBER",
          "protein": "NUMBER",
          "carbs": "NUMBER",
          "fat": "NUMBER"
        }}
      ]
    }}
    
    If there are multiple items, include each as a separate object in the food_items array.
    For ranges like '35-45', use the average value. Don't include any markdown or text outside the JSON.
    """
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    params = {"key": api_key}
    response = requests.post(url, headers=headers, params=params, json=data)
    if response.status_code == 200:
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return text
        except Exception as e:
            return f"Error parsing Gemini response: {e}"
    else:
        return f"Gemini API error: {response.text}"

# --- Google Sheets Logging Function ---
def log_to_google_sheets(food, nutrition_json, timestamp):
    # Check if running on Streamlit Cloud (with secrets)
    if "gcp_service_account" in st.secrets:
        # Use service account info from secrets
        service_account_info = st.secrets["gcp_service_account"]
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
    else:
        # Fallback to local file for development
        creds_path = "service_account.json"
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
    
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1Oo-ZlGXV2gioSCmp_x8s_cqJDDKR4shXjWzJqacZYxA/edit?usp=sharing")
    worksheet = sheet.sheet1

    # Remove code block markers if present
    cleaned = nutrition_json.strip()
    # Remove triple backticks and optional 'json' after them
    if cleaned.startswith('```'):
        cleaned = cleaned.lstrip('`')
        if cleaned.startswith('json'):
            cleaned = cleaned[4:].strip()
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3].strip()

    # Remove any leading/trailing quotes
    cleaned = cleaned.strip('"')
    
    try:
        nutrition = json.loads(cleaned)
        
        # Handle different Gemini response formats
        food_items = []
        
        # Format 1 (preferred): food_items array
        if 'food_items' in nutrition:
            for item in nutrition.get("food_items", []):
                food_items.append({
                    "item": item.get("item", ""),
                    "quantity": item.get("quantity", ""),
                    "calories": item.get("calories", ""),
                    "protein": item.get("protein", ""),
                    "carbs": item.get("carbs", ""),
                    "fat": item.get("fat", ""),
                    "notes": item.get("notes", "")
                })
                
        # Format 2: dishes array
        elif 'dishes' in nutrition:
            for dish in nutrition.get('dishes', []):
                food_items.append({
                    "item": dish.get("dish", ""),
                    "quantity": nutrition.get("serving_size", ""),
                    "calories": dish.get("calories", ""),
                    "protein": dish.get("protein", ""),
                    "carbs": dish.get("carbs", ""),
                    "fat": dish.get("fat", ""),
                    "notes": dish.get("notes", "")
                })
                
        # Format 3: nutritional_information with multiple food items
        elif 'nutritional_information' in nutrition:
            serving_size = nutrition.get("serving_size", "")
            ni = nutrition.get("nutritional_information", {})
            
            # Process each food item in nutritional_information
            for food_name, food_details in ni.items():
                # Clean up food name
                display_name = food_name.replace('_', ' ').title()
                
                # Handle range values (e.g., "35-45") by extracting average
                def extract_numeric_value(value):
                    if isinstance(value, (int, float)):
                        return str(value)
                    if not value:
                        return ""
                    
                    # If it's a string that might contain a range like "35-45"
                    if isinstance(value, str) and "-" in value:
                        try:
                            parts = value.split("-")
                            # Extract numeric part if units are included
                            num1 = float(''.join(c for c in parts[0] if c.isdigit() or c == '.'))
                            num2 = float(''.join(c for c in parts[1] if c.isdigit() or c == '.'))
                            return str(round((num1 + num2) / 2, 1))
                        except:
                            return value
                    return value
                
                calories = extract_numeric_value(food_details.get("calories", ""))
                protein = extract_numeric_value(food_details.get("protein", ""))
                carbs = extract_numeric_value(food_details.get("carbohydrates", "") or food_details.get("carbs", ""))
                fat = extract_numeric_value(food_details.get("fat", ""))
                
                food_items.append({
                    "item": display_name,
                    "quantity": serving_size,
                    "calories": calories,
                    "protein": protein,
                    "carbs": carbs,
                    "fat": fat,
                    "notes": food_details.get("description", "")
                })
                
        # If no recognized format but has direct nutrition info, treat as single item
        elif any(key in nutrition for key in ['calories', 'protein', 'carbs', 'fat', 'carbohydrates']):
            food_items.append({
                "item": food,
                "quantity": nutrition.get("serving_size", ""),
                "calories": nutrition.get("calories", ""),
                "protein": nutrition.get("protein", ""),
                "carbs": nutrition.get("carbs", "") or nutrition.get("carbohydrates", ""),
                "fat": nutrition.get("fat", ""),
                "notes": ""
            })
            
        # Log data to worksheet
        if food_items:
            for item in food_items:
                worksheet.append_row([
                    timestamp,
                    item["item"],
                    item["quantity"],
                    item["calories"],
                    item["protein"],
                    item["carbs"],
                    item["fat"],
                    item["notes"]
                ])
        else:
            # Unknown format, log the raw data
            worksheet.append_row([timestamp, food, "", "", "", "", "", f"Unknown format: {cleaned}"])
    except Exception as e:
        worksheet.append_row([timestamp, food, nutrition_json, "", "", "", "", f"Error parsing nutrition JSON: {e}"])

# Button to submit
if st.button("Log Food"):
    if not gemini_api_key:
        st.error("Please enter your Gemini API key.")
    elif not food_entry:
        st.error("Please enter what you ate.")
    else:
        st.info("Fetching nutritional information...")
        nutrition = get_nutrition_from_gemini(food_entry, gemini_api_key)
        st.write("Nutritional Info:", nutrition)
        st.info("Logging to Google Sheets...")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            log_to_google_sheets(food_entry, nutrition, now)
            st.success("Entry logged!")
        except Exception as e:
            st.error(f"Failed to log to Google Sheets: {e}")
