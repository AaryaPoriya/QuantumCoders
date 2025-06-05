from flask import Blueprint, jsonify
from app.models import (
    FoodtypesCategoriesResponse, FoodType as FoodTypeModel, Category as CategoryModel,
    StoreSection as StoreSectionModel, ErrorResponse
)
from app.db import execute_query
from app.auth import jwt_required # Decide if these are public or need auth
from app.utils import serialize_rows # Using serialize_rows for direct conversion
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('misc', __name__, url_prefix='/misc')

# API 4: Fetch All Foodtypes and Categories
@bp.route('/foodtypes-categories', methods=['GET'])
# @jwt_required # Make this public or protected based on requirements
def get_foodtypes_and_categories():
    foodtypes = []
    categories = []
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Fetch Foodtypes
            cur.execute("SELECT foodtype_id, foodtype_name FROM public.foodtype ORDER BY foodtype_name;")
            ft_rows = cur.fetchall()
            if ft_rows:
                serialized_ft = serialize_rows(ft_rows, cur.description)
                foodtypes = [FoodTypeModel(**ft) for ft in serialized_ft]
            
            # Fetch Categories
            cur.execute("SELECT category_id, category_name FROM public.category ORDER BY category_name;")
            cat_rows = cur.fetchall()
            if cat_rows:
                serialized_cat = serialize_rows(cat_rows, cur.description)
                categories = [CategoryModel(**cat) for cat in serialized_cat]
        close_conn(conn)
        return jsonify(FoodtypesCategoriesResponse(foodtypes=foodtypes, categories=categories).dict()), 200
    except Exception as e:
        logger.error(f"Error fetching foodtypes/categories: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 16: Get Store Sections
@bp.route('/store-sections', methods=['GET'])
# @jwt_required # Make this public or protected based on requirements
def get_store_sections():
    sections = []
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT section_id, section_name, x1, y1, x2, y2, floor_level FROM public.store_sections ORDER BY section_name;")
            rows = cur.fetchall()
            if rows:
                serialized_sections = serialize_rows(rows, cur.description)
                sections = [StoreSectionModel(**s) for s in serialized_sections]
        close_conn(conn)
        return jsonify([s.dict() for s in sections]), 200 # Returning a list of sections
    except Exception as e:
        logger.error(f"Error fetching store sections: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500 