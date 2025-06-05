from flask import Blueprint, request, jsonify, current_app
from pydantic import ValidationError
from app.models import (
    VerifyMobileRequest, VerifyOTPRequest, ProfileCompleteRequest, 
    UserResponse, TokenResponse, MessageResponse, ErrorResponse
)
from app.db import execute_query # Still needed for direct DB calls
from app.auth import (
    generate_otp_for_mobile, 
    verify_otp_for_mobile, 
    generate_jwt_token,
    get_current_user_id,
    jwt_required
)
from app.utils import handle_pydantic_error, serialize_row
import logging
import psycopg2

logger = logging.getLogger(__name__)
bp = Blueprint('auth', __name__, url_prefix='/auth')

# API 1: Verify or Save Mobile Number (and create/update profile status)
@bp.route('/verify_mobile', methods=['POST'])
def verify_mobile_number_route():
    try:
        data = VerifyMobileRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, user_name, is_profile_complete FROM public.user_details WHERE mobilenum = %s;", (data.mobile_number,))
            user_info_row = cur.fetchone()

            if user_info_row:
                # User exists
                user_id, user_name_db, is_profile_complete_db = user_info_row
                if not is_profile_complete_db and user_name_db is not None:
                    # Profile has a name but flag is false. Correct it.
                    logger.info(f"User {user_id} ({data.mobile_number}) has a name but is_profile_complete is false. Updating to true.")
                    cur.execute("UPDATE public.user_details SET is_profile_complete = TRUE WHERE user_id = %s;", (user_id,))
                # else: User exists and their profile complete status is already correct or they have no name yet.
            else:
                # User does not exist, create a minimal profile
                cur.execute("""
                    INSERT INTO public.user_details (mobilenum, is_profile_complete)
                    VALUES (%s, FALSE) RETURNING user_id;
                    """, (data.mobile_number,))
                new_user_minimal_row = cur.fetchone()
                if not new_user_minimal_row:
                    conn.rollback()
                    logger.error(f"Failed to create minimal profile for {data.mobile_number}")
                    return jsonify(ErrorResponse(detail='Failed to initialize user profile.').dict()), 500
                logger.info(f"Minimal profile created for {data.mobile_number}, user_id: {new_user_minimal_row[0]}")
            conn.commit() 
        close_conn(conn)
        conn = None 
        
        generate_otp_for_mobile(data.mobile_number)
        return jsonify(MessageResponse(message=f'OTP sent to {data.mobile_number}').dict()), 200

    except psycopg2.Error as db_err:
        logger.error(f"Database error in /verify_mobile for {data.mobile_number}: {db_err}")
        if conn: conn.rollback()
        return jsonify(ErrorResponse(detail=f'Database error: {str(db_err)}').dict()), 500
    except Exception as e:
        logger.error(f"Error in /verify_mobile for {data.mobile_number}: {e}")
        if conn: conn.rollback()
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn and not conn.closed: close_conn(conn)

# API 2: Verify OTP & Get Token with Profile Status
@bp.route('/verify_otp', methods=['POST'])
def verify_otp_route():
    try:
        data = VerifyOTPRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    if not verify_otp_for_mobile(data.mobile_number, data.otp):
        return jsonify(ErrorResponse(detail='Invalid OTP or OTP expired.').dict()), 400

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Fetch user_id and their definitive is_profile_complete status
            cur.execute("SELECT user_id, is_profile_complete FROM public.user_details WHERE mobilenum = %s;", (data.mobile_number,))
            user_details_row = cur.fetchone()
        close_conn(conn)
        conn = None 

        if not user_details_row:
            logger.error(f"User not found for {data.mobile_number} after OTP verification.")
            return jsonify(ErrorResponse(detail='User record not found. Please try mobile verification again.').dict()), 404
        
        user_id, is_profile_complete = user_details_row[0], user_details_row[1]
        token = generate_jwt_token({'user_id': user_id})
        
        return jsonify(TokenResponse(token=token, user_id=user_id, is_profile_complete=is_profile_complete).dict()), 200
        
    except psycopg2.Error as db_err:
        logger.error(f"Database error in /verify_otp for {data.mobile_number}: {db_err}")
        return jsonify(ErrorResponse(detail=f'Database error: {str(db_err)}').dict()), 500
    except Exception as e:
        logger.error(f"Error in /verify_otp for {data.mobile_number}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error during OTP verification.').dict()), 500
    finally:
        if conn and not conn.closed: close_conn(conn)

# API 3: Complete User Profile (was Create User Profile)
@bp.route('/complete_profile', methods=['POST'])
@jwt_required
def complete_user_profile_route():
    user_id = get_current_user_id()
    if not user_id: 
        return jsonify(ErrorResponse(detail='Authentication token invalid or missing user_id.').dict()), 401

    try:
        profile_data = ProfileCompleteRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            update_query = """
            UPDATE public.user_details 
            SET user_name = %s, email = %s, user_foodtype_id = %s, user_allergy_id = %s, is_profile_complete = TRUE
            WHERE user_id = %s
            RETURNING user_id, user_name, mobilenum, email, user_foodtype_id, user_allergy_id, is_profile_complete;
            """
            params = (
                profile_data.user_name,
                profile_data.email,
                profile_data.user_foodtype_id,
                profile_data.user_allergy_id,
                user_id
            )
            cur.execute(update_query, params)
            updated_user_raw = cur.fetchone()
            conn.commit()

        if not updated_user_raw:
            close_conn(conn)
            conn = None # Set to None after close
            logger.warning(f"Failed to update profile for user_id: {user_id}. User not found or no update occurred.")
            return jsonify(ErrorResponse(detail='Failed to complete user profile. User not found.').dict()), 404
        
        user_dict_from_db = {
            'user_id': updated_user_raw[0],
            'user_name': updated_user_raw[1],
            'mobilenum': updated_user_raw[2],
            'email': updated_user_raw[3],
            'user_foodtype_id': updated_user_raw[4],
            'user_allergy_id': updated_user_raw[5],
            'is_profile_complete': updated_user_raw[6]
        }
        completed_user = UserResponse(**user_dict_from_db)
        close_conn(conn)
        conn = None # Set to None after successful close
        return jsonify(completed_user.dict()), 200

    except psycopg2.IntegrityError as e:
        if conn: conn.rollback()
        logger.error(f"Database integrity error in /complete_profile for user_id {user_id}: {e}")
        detail = 'Error completing profile. This email might already be in use by another account.'
        if "user_details_email_key" in str(e).lower():
            detail = "This email address is already registered by another user."
        return jsonify(ErrorResponse(detail=detail).dict()), 409
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Error in /complete_profile for user_id {user_id}: {e}")
        return jsonify(ErrorResponse(detail=f'Internal server error: {str(e)}').dict()), 500
    finally:
        if conn and not conn.closed: close_conn(conn) 
