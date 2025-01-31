import json
import boto3
import time
from botocore.exceptions import BotoCoreError, ClientError
from datetime import datetime, timedelta
import uuid
import os
import re

s3 = boto3.client('s3')
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('CONVERSATION_TABLE', 'JaymartConversations'))

BUCKET_NAME = 'jaymart-data'
CATALOG_KEY = 'products/test.json'
PAYMENTS_KEY = 'payments/test2.json'  # New S3 key for payments data

def get_product_catalog():
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=CATALOG_KEY)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching catalog from S3: {e}")
        return {}

def get_payments_data():
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=PAYMENTS_KEY)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching payments data from S3: {e}")
        return {}

BASE_CONTEXT = """
# Jaymart Chatbot Instructions

Core Rules:
1. READ THE QUESTION CAREFULLY and answer EXACTLY what was latest asked .
2. Answer ONLY what is asked From Bot: onwards, no need to send it.
3. Keep responses short and DIRECT ,If it's not necessary, don't ask back.
4. NO greeting or small talk
5. NO follow-up questions
6. NO additional suggestions
7. No greetings or "Bot:"/"Assistant:" prefixes
8. Don't answer yourself. You have to wait for the user to reply first.

Response Format (REQUIRED):
All responses must use this exact format:

For Product Lists:
Budget: XX,XXX bath

1. [Product Name] - XX,XXX bath
  - Feature 1
  - Feature 2

2. [Product Name] - XX,XXX bath
  - Feature 1
  - Feature 2

For Product Details:
[Product Name] - XX,XXX bath

Specifications:
- Feature 1
- Feature 2
- Feature 3

Payment Options:
- Full payment: XX,XXX bath
- Installment: XX months at XXX bath/month

Format Rules:
1. Use proper line breaks between sections
2. Start each feature on new line with indent
3. Use bullet points consistently
4. Add blank line between different products
5. Present prices clearly with currency symbol

## Store Locations
1. Big C Bangplee Branch
   - Address: 1st Floor, 89 Moo 9, Theparak Rd., Km.13, Bangplee Yai Subdistrict, Bangplee District, Samut Prakan
   - Tel: 02-312-2437
2. Central Rama 3 Branch
   - Address: 3rd floor, 79 Sathu Pradit Rd., Chong Nonsi Subdistrict, Yan Nawa District, Bangkok
   - Tel: 020290455

"""

class ConversationManager:
    def __init__(self, table):
        self.table = table
        self.max_history_length = 5
        self.session_timeout = 30

    def get_conversation_history(self, session_id):
        try:
            response = self.table.get_item(Key={'session_id': session_id})
            if 'Item' not in response:
                return []
            
            last_updated = datetime.fromisoformat(response['Item']['last_updated'])
            if datetime.utcnow() - last_updated > timedelta(minutes=self.session_timeout):
                return []
                
            return response['Item']['history']
        except Exception as e:
            print(f"Error retrieving conversation history: {e}")
            return []

    def update_conversation_history(self, session_id, user_message, bot_response):
        try:
            history = self.get_conversation_history(session_id)
            
            history.append({
                'user': user_message,
                'bot': bot_response,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            if len(history) > self.max_history_length:
                history = history[-self.max_history_length:]
            
            self.table.put_item(Item={
                'session_id': session_id,
                'history': history,
                'last_updated': datetime.utcnow().isoformat()
            })
            
            return history
        except Exception as e:
            print(f"Error updating conversation history: {e}")
            return []

def contains_thai(text):
    return re.search(r'[\u0E00-\u0E7F]', text) is not None

def prepare_prompt(user_prompt, conversation_history):
    catalog = get_product_catalog()
    payments = get_payments_data()
    full_context = BASE_CONTEXT + "\n\n## Product Catalog\n" + json.dumps(catalog, indent=2)
    full_context += "\n\n## Payment Data\n" + json.dumps(payments, indent=2)
    if conversation_history:
        full_context += "\n\nPrevious conversation:\n\n"
        for exchange in conversation_history:
            full_context += f"User: {exchange['user']}\n"
            
    full_context += f"User: {user_prompt}\nAssistant:"
    
    return full_context

def format_response(response_body):
    """Format the response text with proper line breaks"""
    if 'results' not in response_body or not response_body['results']:
        raise ValueError("Unexpected response format from Bedrock")
    
    bot_response = response_body['results'][0]['outputText']
    
    # Clean up formatting
    formatted = bot_response.encode().decode('unicode_escape')
    formatted = formatted.replace('฿', 'THB')
    
    lines = formatted.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('-'):
            cleaned_lines.append('  ' + line.strip())
        else:
            cleaned_lines.append(line.strip())
    
    formatted = '\n'.join(line for line in cleaned_lines if line)
    
    # Add proper spacing between sections
    formatted = formatted.replace('\nSpecifications:', '\n\nSpecifications:')
    formatted = formatted.replace('\nPayment Options:', '\n\nPayment Options:')
    
    return formatted

def call_bedrock(prompt):
    return bedrock.invoke_model(
        modelId='amazon.titan-text-premier-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps({
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": 1000,
                "stopSequences": ["User:"],
                "temperature": 0.6,
                "topP": 1
            }
        })
    )

def lambda_handler(event, context):
    start_time = time.time()
    conversation_manager = ConversationManager(table)
    
    try:
        body = json.loads(event['body']) if isinstance(event.get('body'), str) else event.get('body', event)
        if 'prompt' not in body:
            raise ValueError("No 'prompt' found in the request body")
        
        session_id = body.get('session_id', str(uuid.uuid4()))
        user_prompt = body['prompt']
        
        if contains_thai(user_prompt):
            bot_response = "Sorry, I don't understand. Please answer again."
            conversation_manager.update_conversation_history(session_id, user_prompt, bot_response)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'response': bot_response,
                    'session_id': session_id,
                    'execution_time': round(time.time() - start_time, 2)
                }, ensure_ascii=False),
                'headers': {
                    'Content-Type': 'application/json; charset=utf-8',
                    'Access-Control-Allow-Origin': '*'
                }
            }
        
        conversation_history = conversation_manager.get_conversation_history(session_id)
        
        if context.get_remaining_time_in_millis() < 5000:
            raise TimeoutError("Not enough time to process request")
        
        full_prompt = prepare_prompt(user_prompt, conversation_history)
        response = call_bedrock(full_prompt)
        
        response_body = json.loads(response['body'].read())
        formatted_response = format_response(response_body)
        
        conversation_manager.update_conversation_history(
            session_id, 
            user_prompt, 
            formatted_response
        )
        
        execution_time = round(time.time() - start_time, 2)
        print(f"Request processed in {execution_time} seconds")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'response': formatted_response,
                'session_id': session_id,
                'execution_time': execution_time
            }, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json; charset=utf-8',
                'Access-Control-Allow-Origin': '*'
            }
        }
        
    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f"{error_type}: {error_message}",
                'execution_time': round(time.time() - start_time, 2)
            }),
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
        }