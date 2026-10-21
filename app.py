#RESPONSAVEL PELA APLICAÇÃO FLASK
#E PELOS ENDPOINTS
import os
from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from db import db
load_dotenv()
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
migrate = Migrate(app, db)