from flask_cors import CORS
from google import genai
from dotenv import load_dotenv
import os
from flask import Flask, request, jsonify, render_template
import groq
from duckduckgo_search import DDGS
import re
from datetime import datetime
from functools import wraps
from collections import defaultdict
import time

load_dotenv()

app = Flask("VyntrAI")
CORS(app, resources={
    r"/chat": {
        "origins": [
            "http://localhost:5000",
            f"http://localhost:{os.getenv('PORT')}",
            "https://vai.ploszukiwacz.hackclub.app"
        ],
        "methods": ["GET", "POST"],
        "allow_headers": ["Content-Type"]
    }
})

MINUTE_RATE_LIMIT = 5
DAILY_RATE_LIMIT = 1000
STATUS_RATE_LIMIT = 2
RATE_LIMIT_STORAGE = {
    'minute': defaultdict(list),
    'day': defaultdict(list),
    'status': defaultdict(list)
}

def get_remote_address():
    """Get the client's IP address"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr
def rate_limit(minute_limit=MINUTE_RATE_LIMIT, daily_limit=DAILY_RATE_LIMIT):
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                ip = get_remote_address()
                now = time.time()

                stats = get_rate_limit_stats(ip)
                minute_requests = stats['minute']['current']
                daily_requests = stats['day']['current']

                # Prepare headers
                response_headers = {
                    'X-RateLimit-Limit-Minute': str(minute_limit),
                    'X-RateLimit-Remaining-Minute': str(max(0, minute_limit - minute_requests)),
                    'X-RateLimit-Limit-Daily': str(daily_limit),
                    'X-RateLimit-Remaining-Daily': str(max(0, daily_limit - daily_requests))
                }

                # Check if limits are exceeded
                if minute_requests >= minute_limit:
                    reset_time = stats['minute']['reset']
                    response_headers['Retry-After'] = str(int(reset_time))
                    return jsonify({
                        'error': 'Rate limit exceeded',
                        'reset_in_seconds': int(reset_time),
                        'type': 'minute'
                    }), 429, response_headers

                if daily_requests >= daily_limit:
                    reset_time = stats['day']['reset']
                    response_headers['Retry-After'] = str(int(reset_time))
                    return jsonify({
                        'error': 'Daily rate limit exceeded',
                        'reset_in_seconds': int(reset_time),
                        'type': 'day'
                    }), 429, response_headers

                # Add current request timestamp
                RATE_LIMIT_STORAGE['minute'][ip].append(now)
                RATE_LIMIT_STORAGE['day'][ip].append(now)

                # Call the original route function
                response = f(*args, **kwargs)

                # Add rate limit headers to response
                if isinstance(response, tuple):
                    response_obj, status_code = response
                    return response_obj, status_code, response_headers
                return response, 200, response_headers

            return decorated_function
        return decorator
def check_status_rate_limit(ip):
            """Check rate limit for status endpoint"""
            now = time.time()
            second_ago = now - 1

            # Clean old status checks
            RATE_LIMIT_STORAGE['status'][ip] = [
                t for t in RATE_LIMIT_STORAGE['status'][ip] if t > second_ago
            ]

            # Check if limit exceeded
            if len(RATE_LIMIT_STORAGE['status'][ip]) >= STATUS_RATE_LIMIT:
                return True

            # Add current check
            RATE_LIMIT_STORAGE['status'][ip].append(now)
            return False

def get_rate_limit_stats(ip):
            """Get current rate limit statistics without modifying counts"""
            now = time.time()
            minute_ago = now - 60
            day_ago = now - 86400

            # Clean up old entries
            RATE_LIMIT_STORAGE['minute'][ip] = [
                t for t in RATE_LIMIT_STORAGE['minute'][ip] if t > minute_ago
            ]
            RATE_LIMIT_STORAGE['day'][ip] = [
                t for t in RATE_LIMIT_STORAGE['day'][ip] if t > day_ago
            ]

            minute_requests = len(RATE_LIMIT_STORAGE['minute'][ip])
            daily_requests = len(RATE_LIMIT_STORAGE['day'][ip])

            return {
                'minute': {
                    'current': minute_requests,
                    'reset': min(RATE_LIMIT_STORAGE['minute'][ip]) + 60 - now if RATE_LIMIT_STORAGE['minute'][ip] else 60
                },
                'day': {
                    'current': daily_requests,
                    'reset': min(RATE_LIMIT_STORAGE['day'][ip]) + 86400 - now if RATE_LIMIT_STORAGE['day'][ip] else 86400
                }
            }


google_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))

with open("system_prompt.txt", "r") as f:
    system_prompt = f.read()
# chat = client.chats.create(model="gemini-2.0-pro-exp")

def should_search(query):
    # Keywords that suggest current information is needed
    current_info_keywords = [
        'latest', 'recent', 'current', 'news', 'today', 'now',
        'update', 'happening', 'weather', 'price', 'stock',
        'score', 'latest', 'trending'
    ]

    # Time-related patterns
    time_patterns = [
        r'\b\d{4}\b',  # Year
        r'this (week|month|year)',
        r'last (week|month|year)',
        r'latest',
        r'current',
    ]

    # Question patterns that often require current information
    question_patterns = [
        r'what.*happening',
        r'how much.*cost',
        r'where.*find',
        r'who.*is',
        r'when.*will',
        r'why.*is',
    ]

    query = query.lower()

    # Check for current info keywords
    if any(keyword in query for keyword in current_info_keywords):
        return True

    # Check for time patterns
    if any(re.search(pattern, query, re.IGNORECASE) for pattern in time_patterns):
        return True

    # Check for question patterns
    if any(re.search(pattern, query, re.IGNORECASE) for pattern in question_patterns):
        return True

    # Check for queries about specific dates
    if re.search(r'\b(today|tomorrow|yesterday)\b', query):
        return True

    # Check for queries about real-time information
    if re.search(r'\b(live|real[-\s]time|current)\b', query):
        return True

    return False

def perform_web_search(query, num_results=5):
    current_year = datetime.now().year
    # Add current year to query if it might need current information
    if should_search(query) and str(current_year) not in query:
        query = f"{query} {current_year}"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("link", ""),
                    "snippet": result.get("body", "")
                })
            return formatted_results
    except Exception as e:
        print(f"Search error: {e}")
        return []

@app.route("/rate-limit-status")
def rate_limit_status():
    ip = get_remote_address()

    # Check status endpoint rate limit
    if check_status_rate_limit(ip):
        return jsonify({
            'error': 'Status check rate limit exceeded',
            'retry_after': 1
        }), 429

    stats = get_rate_limit_stats(ip)

    return jsonify({
        'minute_limit': {
            'limit': MINUTE_RATE_LIMIT,
            'remaining': max(0, MINUTE_RATE_LIMIT - stats['minute']['current']),
            'reset': int(stats['minute']['reset'])
        },
        'daily_limit': {
            'limit': DAILY_RATE_LIMIT,
            'remaining': max(0, DAILY_RATE_LIMIT - stats['day']['current']),
            'reset': int(stats['day']['reset'])
        }
    })

@app.route("/chat", methods=["POST"])
@rate_limit(minute_limit=MINUTE_RATE_LIMIT, daily_limit=DAILY_RATE_LIMIT)
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        api_choice = data.get("api", "google")
        chat_history = data.get("history", [])  # Get history from request

        search_context = ""
        if should_search(user_message):
            search_results = perform_web_search(user_message)
            if search_results:
                search_context = "\n\nRelevant information from the web:\n"
                for idx, result in enumerate(search_results, 1):
                    search_context += f"\n{idx}. {result['title']}\n{result['snippet']}\nSource: {result['url']}\n"

        # Format the conversation history for the AI
        conversation_context = "Previous conversation:\n"
        for msg in chat_history[:-1]:  # Exclude the current message
            role = "User" if msg["isUser"] else "Assistant"
            conversation_context += f"{role}: {msg['content']}\n"

        combined_message = f"{conversation_context}\nCurrent user message: {user_message}\nSearch results:\n{search_context}"

        if api_choice == "google":
            response = google_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[system_prompt, combined_message]
            )
            model_response = response.text if hasattr(response, 'text') else "No response text available"
        else:  # groq
            completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": combined_message}
                ],
                model="gemma2-9b-it",
                temperature=0.7,
                max_tokens=1024,
            )
            model_response = completion.choices[0].message.content

        return jsonify({"response": model_response})
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        return jsonify({"error": "An error occurred while processing your request"}), 500

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5000)))

# for model in client.models.list():
#     print(model)

# r = client.models.generate_content(
#     model="gemini-2.0-pro-exp",
#     contents=["Hello"]
# )
# print(r.text)
