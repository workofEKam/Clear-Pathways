from flask import Flask, jsonify, render_template, request, redirect, url_for
from geopy.geocoders import Nominatim
import sqlite3
import requests
from bs4 import BeautifulSoup
from google import genai
import re  # Add this at the top of app.py (after other imports) for JSON cleaning
from google.genai import types
client = genai.Client(api_key="AIzaSyCEq7JCUJu623XMDtiFRsVm-3MDa-pquW0")
import json
app = Flask(__name__)

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # Create tables if not exist
    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY, 
        name TEXT, 
        address TEXT, 
        avg_rating REAL DEFAULT 0
    )''')  # Base table (without new columns yet)

    c.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY, 
        location_id INTEGER, 
        comment TEXT, 
        rating INTEGER
    )''')

    # Add new columns if they don't exist (safe migration)
    try:
        c.execute("ALTER TABLE locations ADD COLUMN description TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists, ignore

    try:
        c.execute("ALTER TABLE locations ADD COLUMN latitude REAL")
    except sqlite3.OperationalError:
        pass  # Column already exists, ignore

    try:
        c.execute("ALTER TABLE locations ADD COLUMN longitude REAL")
    except sqlite3.OperationalError:
        pass  # Column already exists, ignore

    # Seed sample data if empty
    c.execute("SELECT COUNT(*) FROM locations")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO locations (name, address, avg_rating) VALUES (?, ?, ?)", 
                  ('Cafe Example', '123 Main St, City', 4.0))
        c.execute("INSERT INTO locations (name, address, avg_rating) VALUES (?, ?, ?)", 
                  ('Park Demo', '456 Green Ave, Town', 3.5))
        c.execute("INSERT INTO reviews (location_id, comment, rating) VALUES (?, ?, ?)", 
                  (1, 'Wheelchair accessible entrance.', 5))
        c.execute("INSERT INTO reviews (location_id, comment, rating) VALUES (?, ?, ?)", 
                  (1, 'No braille menus.', 2))

    conn.commit()
    conn.close()


init_db()
# ---------- AI FILTER FUNCTION ----------
def ai_filter_comments(comments):
    filtered = []
    try:
        for comment in comments:
            try:
                # Call Gemini with a prompt to check relevance and summarize
                response = client.models.generate_content(
                    model="gemini-1.5-flash",  # Lightweight free-tier model
                    contents=f"You are an accessibility analyzer. Determine if the following comment mentions disability access (e.g., ramps, braille, wheelchair, inclusive features). If yes, respond with 'Yes' followed by a 1-sentence summary. If no, respond with 'No'. Comment: {comment}",
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(thinking_budget=0)  # Disables thinking, as per your example
                    )
                )
                result = response.text.strip()
                
                if result.lower().startswith('yes'):
                    # Extract summary (after 'Yes')
                    summary = result.split(' ', 1)[1] if ' ' in result else result
                    filtered.append(summary)  # Add summarized version
            except Exception as e:
                # Skip individual comment errors
                continue
    
    except Exception as e:
        # Fallback to keyword filter if API setup fails (e.g., rate limit or no key)
        keywords = ['accessible', 'wheelchair', 'ramp', 'braille', 'disability', 'inclusive']
        filtered = [comment for comment in comments if any(kw in comment.lower() for kw in keywords)]
    
    return filtered if filtered else ["No accessibility reviews found."]


# ---------- SCRAPER FUNCTION ----------
def scrape_reviews(location_name):
    url = f"https://en.wikipedia.org/wiki/{location_name.replace(' ', '_')}"  # sample public URL
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        paragraphs = [p.text for p in soup.find_all('p')][:5]
        filtered = ai_filter_comments(paragraphs)
        return filtered if filtered else ["No accessibility reviews found."]
    except:
        return ["Scraping failed - fallback comment: Place has good ramps but poor lighting."]

# ---------- ROUTES ----------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/search', methods=['POST'])
def search():
    location_query = request.form['location']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT * FROM locations WHERE name LIKE ?", (f"%{location_query}%",))
    location = c.fetchone()

    db_reviews = []
    scraped_reviews = []
    gemini_suggestions = []

    if location:
        location_id = location[0]
        c.execute("SELECT * FROM reviews WHERE location_id = ?", (location_id,))
        db_reviews = c.fetchall()
        scraped_reviews = scrape_reviews(location_query.split()[0])

    conn.close()

    # Optimized Gemini call: Use DB address for precision if available
    import json
    import re  # For JSON cleaning
    try:
        # Dynamic prompt based on DB match
        if location:
            db_address = location[2]  # Use DB address for relevance
            prompt = f"Simulate a Google Maps search for wheelchair-friendly features at or near {location_query} with address {db_address}. Return a JSON array of 1-3 highly relevant objects (focus on the exact place or very similar ones, avoid duplicates with the same name unless they match the context). Each with: name, address, rating (1-5), distance (estimated in km from {db_address}), opening_hours, phone, top_review (1-sentence summary). Ensure valid JSON only."
        else:
            prompt = f"Simulate a Google Maps search for wheelchair-friendly places in {location_query}. Return a JSON array of 3-5 objects, each with: name, address, rating (1-5), distance (estimated in km), opening_hours, phone, top_review (1-sentence summary). Ensure valid JSON only."

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        result = response.text.strip()
        
        print("Raw Gemini response:", result)  # Debug (remove after testing)

        # Robust JSON parsing
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            json_str = re.sub(r"(?<!\\)'", '"', json_str)  # Single to double quotes
            json_str = re.sub(r',\s*([\]}])', r'\1', json_str)  # Remove trailing commas
            gemini_suggestions = json.loads(json_str)
        else:
            gemini_suggestions = [{"name": "Error", "top_review": "No valid JSON found in Gemini response."}]
        
        print("Parsed Gemini suggestions:", gemini_suggestions)  # Debug
    except Exception as e:
        gemini_suggestions = [{"name": "Error", "top_review": f"Gemini query failed: {str(e)}"}]
        print("Gemini error:", str(e))  # Debug

    all_reviews = [{'comment': r[2], 'rating': r[3]} for r in db_reviews] + \
                  [{'comment': rev, 'rating': 'N/A'} for rev in scraped_reviews]

    return render_template('location.html', location=location, reviews=all_reviews, gemini_suggestions=gemini_suggestions)

@app.route('/add_review', methods=['POST'])
def add_review():
    location_id = request.form['location_id']
    comment = request.form['comment']
    rating = int(request.form['rating'])

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("INSERT INTO reviews (location_id, comment, rating) VALUES (?, ?, ?)", (location_id, comment, rating))
    c.execute("SELECT AVG(rating) FROM reviews WHERE location_id = ?", (location_id,))
    avg_rating = c.fetchone()[0]
    c.execute("UPDATE locations SET avg_rating = ? WHERE id = ?", (avg_rating, location_id))

    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# ---------- ADD LOCATION FORM ----------
@app.route('/add_location', methods=['GET', 'POST'])
def add_location():
    error = None
    geolocator = Nominatim(user_agent="inclusi-rate-app")  # Required for Nominatim (fair use)

    if request.method == 'POST':
        name = request.form['name'].strip()
        address = request.form['address'].strip()
        description = request.form.get('description', '').strip()
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')

        # Convert manual inputs to float (if provided)
        manual_lat = float(latitude) if latitude else None
        manual_lon = float(longitude) if longitude else None

        # Auto-geocode if no manual coords provided
        if not manual_lat or not manual_lon:
            try:
                location = geolocator.geocode(address, timeout=10)  # Geocode the address
                if location:
                    manual_lat = location.latitude
                    manual_lon = location.longitude
                else:
                    error = "Could not find coordinates for this address. Using defaults."
            except Exception as e:
                error = f"Geocoding failed: {str(e)}. Using defaults."

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        c.execute("SELECT * FROM locations WHERE name = ? AND address = ?", (name, address))
        if c.fetchone():
            error = "Location already exists."
        else:
            c.execute('''INSERT INTO locations (name, address, avg_rating, description, latitude, longitude)
                         VALUES (?, ?, 0.0, ?, ?, ?)''',
                      (name, address, description, manual_lat, manual_lon))
            conn.commit()
            conn.close()
            return redirect(url_for('index'))

        conn.close()
    
    return render_template("add_location.html", error=error)


@app.route('/api/get_reviews', methods=['GET'])
def get_reviews():
    location_query = request.args.get('location')
    if not location_query:
        return jsonify({"error": "Location parameter is required"}), 400

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT * FROM locations WHERE name LIKE ?", (f"%{location_query}%",))
    location = c.fetchone()

    db_reviews = []
    scraped_reviews = []

    if location:
        location_id = location[0]
        c.execute("SELECT * FROM reviews WHERE location_id = ?", (location_id,))
        db_reviews = c.fetchall()
        scraped_reviews = scrape_reviews(location_query.split()[0])

    conn.close()

    # Format and return JSON (for agent webhook)
    result = {
        "location": location_query,
        "db_reviews": [{"comment": r[2], "rating": r[3]} for r in db_reviews],
        "scraped_reviews": scraped_reviews
    }
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)  
