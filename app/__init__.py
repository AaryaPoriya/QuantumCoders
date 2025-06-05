from flask import Flask
from flask_cors import CORS
import os
from .db import init_app as init_db

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    CORS(app) # Enable CORS for all routes

    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev'), # Fallback for dev, ensure it's set in .env
        DATABASE_URL=os.environ.get('DATABASE_URL'),
        JWT_SECRET_KEY=os.environ.get('JWT_SECRET_KEY', 'jwt-dev'),
        FIXED_OTP=os.environ.get('FIXED_OTP', '123456')
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # Initialize database
    init_db(app)

    # Register blueprints
    from .routes import auth_routes, cart_routes, product_routes, user_routes, order_routes, misc_routes
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(cart_routes.bp)
    app.register_blueprint(product_routes.bp)
    app.register_blueprint(user_routes.bp)
    app.register_blueprint(order_routes.bp)
    app.register_blueprint(misc_routes.bp)

    @app.route('/hello')
    def hello():
        return 'Hello, Smart Cart User!'

    return app 