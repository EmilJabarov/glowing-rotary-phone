import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required
)
from flask_caching import Cache
from flask_migrate import Migrate
from dotenv import load_dotenv
from serpapi import google_search  # Correct import based on your setup
import openai
from werkzeug.security import generate_password_hash, check_password_hash  # For password hashing
from difflib import SequenceMatcher

# ---------------------------
# Configuration and Setup
# ---------------------------

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_default_secret_key')  # Replace with a strong secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'  # SQLite database
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # Redirect to 'login' page if not authenticated

# Configure Logging
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,  # Set to DEBUG for detailed logs during development
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)

# Load API Keys
openai.api_key = os.getenv('OPENAI_API_KEY')  # Ensure this is set in your .env file
serpapi_api_key = os.getenv('SERPAPI_API_KEY')  # Ensure this is set in your .env file

if not serpapi_api_key:
    raise ValueError("SERPAPI_API_KEY not found in environment variables.")

# ---------------------------
# Database Models
# ---------------------------

class User(UserMixin, db.Model):
    __tablename__ = 'user'  # Explicitly define table name to avoid conflicts
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)  # Hashed password
    preferences = db.Column(db.Text, nullable=True)  # User preferences

    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check hashed password."""
        return check_password_hash(self.password_hash, password)

class Search(db.Model):
    __tablename__ = 'search'  # Explicitly define table name
    id = db.Column(db.Integer, primary_key=True)
    search_query = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref=db.backref('searches', lazy='dynamic'))

# ---------------------------
# Create the Database Tables
# ---------------------------

with app.app_context():
    db.create_all()

# ---------------------------
# User Loader for Flask-Login
# ---------------------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------------------
# Helper Functions
# ---------------------------

def compare_queries(query1, query2):
    return SequenceMatcher(None, query1, query2).ratio()

def get_user_preferences(user):
    """
    Analyze the user's past searches to infer preferences.
    """
    search_counts = {}
    for search in user.searches:
        query = search.search_query.lower()
        words = query.split()
        for word in words:
            search_counts[word] = search_counts.get(word, 0) + 1

    sorted_words = sorted(search_counts.items(), key=lambda item: item[1], reverse=True)
    top_preferences = [word for word, count in sorted_words[:10]]  # Top 10 preferences

    preferences = ', '.join(top_preferences)
    logging.debug(f"Inferred Preferences for User {user.username}: {preferences}")
    return preferences

def modify_query_with_preferences(query, preferences):
    """
    Modify the original query based on user preferences by applying personalization only when relevant.
    If no preferences are relevant, return the original query.
    """
    logging.debug(f"Modifying query: '{query}' with preferences: '{preferences}'")

    try:
        preferences_list = [pref.strip().lower() for pref in preferences.split(',')]
        query_parts = query.lower().split()

        # Contextual map to identify relevant preferences based on query words
        contextual_map = {
            "gaming": ["headset", "mouse", "monitor", "controller", "games"],
            "music": ["headphones", "speakers", "playlist"],
            "coding": ["keyboard", "programming", "tools", "laptops"],
            "sports": ["basketball", "football", "shoes"],
            "english teacher": ["teaching", "curriculum", "lesson", "resources"],
            # Add more mappings as needed
        }

        relevant_preferences = []
        for pref in preferences_list:
            if pref in contextual_map:
                for word in query_parts:
                    if word in contextual_map[pref]:
                        relevant_preferences.append(pref)
                        break

        if not relevant_preferences:
            logging.debug("No relevant preferences found. Returning original query.")
            return query

        system_prompt = (
            "You are an assistant that personalizes search queries based on user preferences. "
            "Only apply preferences if they are relevant to the query. If no preferences are relevant, "
            "return the query unchanged. Do not include any prefixes, labels, or additional text."
        )

        examples = (
            "Examples:\n"
            "- Preferences: gaming, music\n"
            "  Original Query: cooking recipes\n"
            "  Output: cooking recipes\n"
            "- Preferences: coding, gaming\n"
            "  Original Query: wireless headphones\n"
            "  Output: gaming wireless headphones\n"
            "- Preferences: sports\n"
            "  Original Query: basketball equipment\n"
            "  Output: sports basketball equipment\n"
            "- Preferences: english teacher\n"
            "  Original Query: teaching resources\n"
            "  Output: english teacher teaching resources\n"
        )

        messages = [
            {"role": "system", "content": system_prompt + "\n\n" + examples},
            {"role": "user", "content": f"Preferences: {', '.join(relevant_preferences)}"},
            {"role": "user", "content": f"Original Query: {query}"},
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=100,
        )

        gpt_modified_query = response['choices'][0]['message']['content'].strip()

        # Remove possible prefixes
        prefixes_to_remove = ["output:", "modified query:", "result:"]
        for prefix in prefixes_to_remove:
            if gpt_modified_query.lower().startswith(prefix):
                gpt_modified_query = gpt_modified_query[len(prefix):].strip()

        logging.debug(f"GPT modified query after cleaning: '{gpt_modified_query}'")

        similarity = compare_queries(query, gpt_modified_query)
        if similarity > 0.9 or gpt_modified_query == query:
            logging.debug("Modified query is very similar to the original. Using original query.")
            return query

        return gpt_modified_query
    except Exception as e:
        logging.error(f"Error modifying query: {e}", exc_info=True)
        return query  # Fallback to original query

def serpapi_search(query, page):
    """
    Perform a search using SerpApi's Google Search API.
    """
    params = {
        "q": query,
        "api_key": serpapi_api_key,
        "engine": "google",
        "start": (page - 1) * 10,
        "num": 10,
        "hl": "en",  # Language
        "gl": "us",  # Country
        "google_domain": "google.com"
    }
    try:
        search = google_search.GoogleSearch(params)  # Correct class instantiation
        results_json = search.get_dict()
        logging.debug(f"SerpApi response: {results_json}")

        results = [
            {
                'name': item.get('title', ''),
                'url': item.get('link', ''),
                'snippet': item.get('snippet', '')
            }
            for item in results_json.get('organic_results', [])
        ]

        # Parse total results
        total_results = results_json.get('search_information', {}).get('total_results', 0)
        total = int(total_results) if isinstance(total_results, int) else 0

        logging.debug(f"Total results: {total} (type: {type(total)})")

        return results, total
    except Exception as e:
        logging.error(f"Error during search: {e}", exc_info=True)
        return [], 0

# ---------------------------
# Routes
# ---------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    User registration route.
    """
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        if not username or not password:
            flash('Username and password are required.', 'warning')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))

        new_user = User(username=username)
        new_user.set_password(password)  # Hash the password
        db.session.add(new_user)
        db.session.commit()

        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    User login route.
    """
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):  # Check hashed password
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('search'))

        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """
    User logout route.
    """
    logout_user()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('login'))

@app.route('/profile')
@login_required
def profile():
    """
    User profile route.
    """
    return render_template('profile.html', user=current_user)

@app.route('/set_preferences', methods=['GET', 'POST'])
@login_required
def set_preferences():
    """
    Route to set user search preferences.
    """
    if request.method == 'POST':
        preferences = request.form['preferences'].strip()
        current_user.preferences = preferences
        db.session.commit()
        flash('Preferences updated!', 'success')
        return redirect(url_for('profile'))
    return render_template('set_preferences.html', preferences=current_user.preferences or '')

@app.route('/clear_learning')
@login_required
def clear_learning():
    """
    Route to clear user search preferences.
    """
    current_user.preferences = None
    db.session.commit()
    flash('Preferences cleared!', 'info')
    return redirect(url_for('profile'))

@app.route('/search_history')
@login_required
def search_history():
    """
    Route to display user's search history.
    """
    history = current_user.searches.order_by(Search.timestamp.desc()).all()
    return render_template('search_history.html', history=history)

@app.route('/', methods=['GET', 'POST'])
def search():
    """
    Home route displaying the search form.
    """
    logging.debug("Entered '/' route with method: %s", request.method)
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        logging.debug("Received POST request with query: '%s'", query)
        if not query:
            flash('Please enter a search query.', 'warning')
            return redirect(url_for('search'))

        if current_user.is_authenticated:
            preferences = current_user.preferences
            if not preferences:
                # Infer preferences from search history if not set
                preferences = get_user_preferences(current_user)
                current_user.preferences = preferences
                db.session.commit()
                logging.debug(f"Inferred preferences: {preferences}")

            if preferences:
                logging.debug(f"User preferences found: {preferences}")
                query = modify_query_with_preferences(query, preferences)
                logging.debug(f"Final query after modification: {query}")

        return redirect(url_for('results', query=query))
    logging.debug("Rendering 'index.html' for GET request.")
    return render_template('index.html')

@app.route('/results')
def results():
    """
    Route to display search results.
    """
    query = request.args.get('query', '').strip()
    logging.debug("Entered '/results' route with query: '%s'", query)
    if not query:
        flash('No query provided.', 'warning')
        return redirect(url_for('search'))

    page = request.args.get('page', 1, type=int)
    results, total = serpapi_search(query, page)

    if current_user.is_authenticated:
        search_entry = Search(search_query=query, author=current_user)
        db.session.add(search_entry)
        db.session.commit()

    return render_template('results.html', results=results, query=query, page=page, total=total)

# ---------------------------
# Error Handlers
# ---------------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return render_template('405.html'), 405

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return render_template('500.html'), 500

# ---------------------------
# Run the Application
# ---------------------------

if __name__ == '__main__':
    app.run(debug=True)
