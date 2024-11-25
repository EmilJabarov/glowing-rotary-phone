# config.py
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SERPAPI_API_KEY = os.environ.get('SERPAPI_API_KEY')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///site.db'  # Update if using a different DB
    SQLALCHEMY_TRACK_MODIFICATIONS = False
