from google import genai
from dotenv import load_dotenv
import os
from flask import Flask, request, jsonify, render_template
import groq
from duckduckgo_search import DDGS
import re
from datetime import datetime

load_dotenv()

app = Flask("VyntrAI")
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

@app.route("/chat", methods=["POST"])
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
