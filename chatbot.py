import random
import json
import numpy as np
import pickle
import nltk
from nltk.stem import WordNetLemmatizer
from keras.models import load_model
from nltk.sentiment import SentimentIntensityAnalyzer
from openai import OpenAI

lemmatizer = WordNetLemmatizer()
sia = SentimentIntensityAnalyzer()

# --- LOAD MODELS & DATA ---
model = load_model(r'D:\mental heath\models\chatbot_model.h5')
words = pickle.load(open(r'D:\mental heath\models\words.pkl', 'rb'))
classes = pickle.load(open(r'D:\mental heath\models\classes.pkl', 'rb'))
intents_json_data = json.loads(open(r'D:\mental heath\config\intents1.json', encoding='utf-8').read())

# --- LLM SETUP (Make sure LM Studio is running!) ---
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="not-needed")
llm_history = [
    {"role": "system", "content": "You are Aura, a highly empathetic mental health assistant. Keep responses brief, warm, and supportive. Do not diagnose or give medical advice."}
]

# --- THE MEMORY TRACKER ---
chat_memory = {
    "last_intent": None
}

def clean_up_sentence(sentence):
    sentence_words = nltk.word_tokenize(sentence)
    sentence_words = [lemmatizer.lemmatize(word.lower()) for word in sentence_words]
    return sentence_words

def bow(sentence, words):
    sentence_words = clean_up_sentence(sentence)
    bag = [0] * len(words)
    for s in sentence_words:
        for i, w in enumerate(words):
            if w == s:
                bag[i] = 1
    return np.array(bag)

def predict_intent(sentence):
    p = bow(sentence, words)
    res = model.predict(np.array([p]), verbose=0)[0]
    ERROR_THRESHOLD = 0.65
    results = [[i, r] for i, r in enumerate(res) if r > ERROR_THRESHOLD]
    results.sort(key=lambda x: x[1], reverse=True)
    if results:
        return classes[results[0][0]], results[0][1]
    return "unknown", 0



def get_response(user_input, db_last_intent): # <--- Now accepts the DB memory!
    intent, confidence = predict_intent(user_input)
    
    sentiment_dict = sia.polarity_scores(user_input)
    compound_score = sentiment_dict['compound']
    
    if compound_score <= -0.5:
        risk_level, mood, suggestion = "High", "Severely Distressed", "Please consider reaching out to a professional. Call 1800-599-0019."
    elif compound_score < -0.1:
        risk_level, mood, suggestion = "Moderate", "Anxious / Down", "Try the 4-7-8 breathing exercise to ground yourself."
    elif compound_score < 0.2:
        risk_level, mood, suggestion = "Low", "Neutral", "I'm here to listen. Take your time."
    else:
        risk_level, mood, suggestion = "Minimal", "Positive / Calm", "It sounds like you're in a decent space. Keep it up!"

    intent_to_save = intent # By default, save whatever they just said to the DB
    
    # ROUTE A: Emergency
    if intent == "emergency_self_harm" and confidence > 0.70:
        bot_reply = "<strong>[SAFETY TRIGGER ACTIVATED]</strong><br><br>I am so sorry you are in pain. You are not alone. Please reach out right now:<br> Kiran Helpline: 1800-599-0019<br> AASRA: +91-9820466726"
        intent_to_save = "emergency"
        risk_level, mood = "CRITICAL", "Emergency"
        
    # ROUTE B: User says "Yes" to the Greeting
    elif intent in ["affirmative", "yes", "okay", "sure", "yeah", "still"]:
        if db_last_intent == "anxiety":
            bot_reply = "I understand. Let's try to ease that tension. Let's do a 4-7-8 breathing exercise. Inhale for 4 seconds, hold for 7, exhale for 8."
            intent_to_save = "breathing_exercise" 
        elif db_last_intent in ["depression_sadness", "loneliness"]:
            bot_reply = "I am so sorry it is still weighing heavily on you. Can we try a small grounding activity? Name just one tiny thing you are grateful for today."
            intent_to_save = "gratitude_exercise" 
        elif db_last_intent == "stress_burnout":
            bot_reply = "Let's tackle this together. What is the absolute smallest, easiest step you can take right now to reduce the load?"
            intent_to_save = "task_breakdown"
        else:
            bot_reply = "Okay! Tell me more about what's going on."
            
        llm_history.append({"role": "user", "content": user_input})
        llm_history.append({"role": "assistant", "content": bot_reply})

    # ROUTE C: User says "No" to the Greeting
    elif intent in ["negative", "no", "nope", "nah", "not really", "feeling better"]:
        if db_last_intent in ["anxiety", "depression_sadness", "stress_burnout", "loneliness"]:
            bot_reply = "I am really glad to hear you aren't feeling that way anymore! What would you like to discuss today instead?"
        else:
            bot_reply = "Understood. What's on your mind today?"
            
        intent_to_save = "neutral_listening"
        llm_history.append({"role": "user", "content": user_input})
        llm_history.append({"role": "assistant", "content": bot_reply})

    # ROUTE D: Normal Chat via LLM
    else:
        llm_history.append({"role": "user", "content": user_input})
        try:
            response = client.chat.completions.create(
                model="local-model", messages=llm_history, temperature=0.6 
            )
            bot_reply = response.choices[0].message.content
            llm_history.append({"role": "assistant", "content": bot_reply})
        except Exception as e:
            bot_reply = "I'm having trouble connecting to my deeper thoughts. Is the local AI server running?"

    return {
        "reply": bot_reply,
        "mood": mood,
        "score": round(compound_score, 2),
        "risk_level": risk_level,
        "suggestion": suggestion,
        "intent_to_save": intent_to_save # <--- Passes this back to app.py to save in the DB
    }