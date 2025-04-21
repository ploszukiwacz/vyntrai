from google import genai
from dotenv import load_dotenv
import os
from flask import Flask, request, jsonify, render_template
import groq

load_dotenv()

app = Flask("VyntrAI")
google_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))

with open("system_prompt.txt", "r") as f:
    system_prompt = f.read()
# chat = client.chats.create(model="gemini-2.0-pro-exp")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    messages = [system_prompt, data.get("message", "")]
    api_choice = data.get("api", "google")

    try:
        if api_choice == "google":
            response = google_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=messages
            )
            model_response = response.text if hasattr(response, 'text') else "No response text available"
        else:  # groq
            completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": data.get("message", "")}
                ],
                model="gemma2-9b-it",
                temperature=0.7,
                max_tokens=1024,
            )
            model_response = completion.choices[0].message.content

        return jsonify({"response": model_response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(port=5000)

# for model in client.models.list():
#     print(model)

# r = client.models.generate_content(
#     model="gemini-2.0-pro-exp",
#     contents=["Hello"]
# )
# print(r.text)
