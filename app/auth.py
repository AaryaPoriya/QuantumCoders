import jwt
from flask import request, jsonify, current_app, session, g
from functools import wraps
import datetime
from .models import ErrorResponse

# In-memory store for OTPs and pre-verified mobiles for new user registration
# For a production system, consider using Redis or another persistent store.
# Using Flask session as discussed for simplicity in dev.

FIXED_OTP = "123456" # Loaded from config in app init, accessible via current_app.config['FIXED_OTP']

def generate_otp_for_mobile(mobile_number):
    """Generates and stores OTP for a mobile number in the session."""
    otp = current_app.config['FIXED_OTP'] 
    session[f'otp_for_{mobile_number}'] = otp
    # User existence check and is_existing_for_session removed, will be handled by route
    current_app.logger.info(f"OTP {otp} stored in session for {mobile_number}")
    return otp

def verify_otp_for_mobile(mobile_number, otp_provided):
    """Verifies OTP against the one stored in session. Returns simple True/False."""
    stored_otp = session.get(f'otp_for_{mobile_number}')
    current_app.logger.info(f"Verifying OTP for {mobile_number}. Provided: {otp_provided}, Stored: {stored_otp}")
    if stored_otp == otp_provided:
        session.pop(f'otp_for_{mobile_number}', None) # Clear OTP after successful use
        # Removed is_existing_user and verified_mobile_for_creation logic
        return True
    return False

def generate_jwt_token(payload, expires_in_minutes=60):
    """Generates a JWT token."""
    payload['exp'] = datetime.datetime.utcnow() + datetime.timedelta(minutes=expires_in_minutes)
    payload['iat'] = datetime.datetime.utcnow()
    token = jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return token

def decode_jwt_token(token):
    """Decodes a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        current_app.logger.warning("JWT expired")
        return None
    except jwt.InvalidTokenError as e: # Added e for logging
        current_app.logger.warning(f"Invalid JWT token: {e}")
        return None

def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify(ErrorResponse(detail='Authorization header is missing or invalid').dict()), 401
        
        token = auth_header.split(' ')[1]
        payload = decode_jwt_token(token)
        
        if not payload or 'user_id' not in payload:
            # The previous logic for 'pending_creation_mobile' is no longer applicable 
            # as user_id is always expected in the token for protected routes.
            return jsonify(ErrorResponse(detail='Token is invalid, expired, or user_id missing').dict()), 401
        
        g.user_id = payload['user_id']
        return f(*args, **kwargs)
    return decorated_function

def get_current_user_id():
    return getattr(g, 'user_id', None)

# Removed get_pending_creation_mobile, check_verified_mobile_for_creation, clear_verified_mobile_after_creation
# as they are not needed with the new JWT-based profile completion flow.

# Helper for create_user_profile to check verified mobile
def check_verified_mobile_for_creation(mobile_number):
    if session.get('verified_mobile_for_creation') == mobile_number:
        return True
    return False

def clear_verified_mobile_after_creation(mobile_number):
    if session.get('verified_mobile_for_creation') == mobile_number:
        session.pop('verified_mobile_for_creation', None) 