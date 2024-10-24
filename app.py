from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

client = anthropic.Anthropic()

def verify_and_increment_api_key(api_key):
    """Verify API key and increment its request count"""
    try:
        keys_ref = db.collection('api_keys').document('key')
        requests_ref = db.collection('api_keys').document('requests')
        
        @firestore.transactional
        def increment_in_transaction(transaction):
            keys_doc = keys_ref.get(transaction=transaction)
            
            if not keys_doc.exists:
                return False
            
            data = keys_doc.to_dict()
            if api_key not in data or not data[api_key]:
                return False
            
            requests_doc = requests_ref.get(transaction=transaction)
            request_data = requests_doc.to_dict() if requests_doc.exists else {}
            
            current_time = datetime.now()
            
            if api_key in request_data and isinstance(request_data[api_key], dict):
                existing_data = request_data[api_key]
                existing_data['count'] = (existing_data.get('count', 0) + 1)
                existing_data['last_used'] = current_time
                
                transaction.update(requests_ref, {
                    api_key: existing_data
                })
            else:
                new_data = {
                    'count': 1,
                    'created_at': current_time,
                    'last_used': current_time
                }
                
                transaction.update(requests_ref, {
                    api_key: new_data
                })
            
            return True
            
        transaction = db.transaction()
        return increment_in_transaction(transaction)
    except Exception as e:
        print(f"Error verifying and incrementing API key: {e}")
        return False

@app.route('/api/send_to_claude', methods=['POST'])
def send_to_claude():
    try:
        data = request.json
        if not data or 'text' not in data or 'apiKey' not in data:
            return jsonify({"error": "Invalid input. 'text' and 'apiKey' fields are required."}), 400

        if not verify_and_increment_api_key(data['apiKey']):
            return jsonify({"error": "Invalid API key."}), 401

        text = data['text']
        
        enhanced_prompt = f"""Generate executable code solution for this problem:

{text}

The code must:
1. Include ALL necessary imports at the top
2. Be complete and runnable without modifications
3. Use proper indentation and formatting
4. Include any required helper functions
5. Include example usage in 'if __name__ == "__main__":' block if appropriate
6. Use type hints for clarity
7. Handle basic error cases
8. Have no markdown formatting
9. Include no explanations or additional text
10. Only include docstrings if crucial for functionality

RETURN ONLY THE CODE WITH NO OTHER TEXT OR FORMATTING."""

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            temperature=0.1,
            system="You are a code generator that ONLY outputs raw code. Never include explanations, markdown formatting, or phrases like 'here's the code'. Return nothing but the actual code that solves the problem.",
            messages=[{
                "role": "user",
                "content": enhanced_prompt
            }]
        )

        if hasattr(message, 'content') and isinstance(message.content, list):
            generated_text = '\n'.join([block.text for block in message.content if hasattr(block, 'text')])
            return jsonify({"response": generated_text.strip()})
        else:
            print("Message Structure:", message)
            return jsonify({"error": "Content not found or is not in expected format."}), 500

    except Exception as e:
        print("Error:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
