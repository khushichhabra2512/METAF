from bson.errors import InvalidId
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId # MongoDB uses special ObjectIds instead of regular numbers
from chatbot import get_response 
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'aura_super_secret_hackathon_key'

# --- MONGODB CONNECTION ---
# Connects to your local MongoDB server
client = MongoClient('mongodb://localhost:27017/') 
db = client['aura_database'] # Creates/connects to a database named 'aura_database'
users_collection = db['users'] # Creates/connects to a collection (table) named 'users'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- CUSTOM USER CLASS FOR MONGODB ---
class User(UserMixin):
    def __init__(self, user_data):
        # MongoDB stores the id as '_id', we convert it to a string for Flask-Login
        self.id = str(user_data['_id']) 
        self.username = user_data['username']
        self.password = user_data['password']
        self.last_intent = user_data.get('last_intent', None)

    def get_id(self):
        return self.id

@login_manager.user_loader
def load_user(user_id):
    try:
        # Tries to find the user in MongoDB
        user_data = users_collection.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
    except InvalidId:
        # If the browser sends an old or invalid cookie (like '1'), it safely ignores it
        return None
        
    return None

# --- AUTH ROUTES ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Check if user exists in MongoDB
        if users_collection.find_one({'username': username}):
            flash('Username already exists. Please login.')
            return redirect(url_for('signup'))
            
        
        new_user_data = {
            'username': username,
            'password': generate_password_hash(password, method='pbkdf2:sha256'),
            'last_intent': None,
            'last_active_date': None,
            'current_streak': 0,
            'longest_streak': 0
        }
        result = users_collection.insert_one(new_user_data)
        
        # Log them in immediately
        user_data = users_collection.find_one({'_id': result.inserted_id})
        login_user(User(user_data))
        return redirect(url_for('index'))
        
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Find user in MongoDB
        user_data = users_collection.find_one({'username': username})
        
        if user_data and check_password_hash(user_data['password'], password):
            login_user(User(user_data))
            return redirect(url_for('index'))
        else:
            flash('Please check your login details and try again.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- APP ROUTES ---
@app.route('/')
@login_required 
def index():
    # --- STREAK TRACKING LOGIC ---
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Fetch fresh data from MongoDB
    user_data = users_collection.find_one({'_id': ObjectId(current_user.id)})
    last_active = user_data.get('last_active_date')
    streak = user_data.get('current_streak', 0)
    longest = user_data.get('longest_streak', 0)
    
    # Check if we need to update the streak
    if last_active != today:
        if last_active == yesterday:
            streak += 1 # They came back the next day!
        else:
            streak = 1 # They missed a day, reset to 1
            
        if streak > longest:
            longest = streak # New high score!
            
        # Save the new math to MongoDB
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {
                'last_active_date': today, 
                'current_streak': streak, 
                'longest_streak': longest
            }}
        )

    # --- DYNAMIC GREETING LOGIC ---
    user_memory = current_user.last_intent
    if user_memory == "anxiety":
        greeting = f"Hi {current_user.username}. Last time we spoke, you were feeling anxious. Are you still feeling the same?"
    elif user_memory in ["depression_sadness", "loneliness"]:
        greeting = f"Hi {current_user.username}. Last time we spoke, you were feeling pretty down. Are you still feeling that way today?"
    elif user_memory == "stress_burnout":
        greeting = f"Hi {current_user.username}. Last time we spoke, you were dealing with a lot of stress. Is that still weighing on you?"
    else:
        greeting = f"Hello {current_user.username}. I'm here to listen. How are you feeling today?"
        
    # Pass the streak number to the HTML page!
    return render_template('index.html', bot_greeting=greeting, streak=streak)
# ... (all your other routes like /login and / are above this) ...

@app.route('/chat', methods=['POST'])
@login_required 
def chat():
    user_message = request.json['message']
    
    # Send the message to your AI in chatbot.py
    analysis_data = get_response(user_message, current_user.last_intent) 
    
    # UPDATE MONGODB: Save the new memory state
    users_collection.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$set': {'last_intent': analysis_data['intent_to_save']}}
    )
    
    return jsonify(analysis_data)

if __name__ == '__main__':
    app.run(debug=True)