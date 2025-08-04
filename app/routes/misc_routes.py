from flask import Blueprint, jsonify, send_from_directory, current_app
import os
from app.models import (
    FoodtypesCategoriesResponse, FoodType as FoodTypeModel, Category as CategoryModel,
    StoreSection as StoreSectionModel, ErrorResponse
)
from app.db import execute_query
from app.auth import jwt_required
from app.utils import serialize_rows, serialize_row
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('misc', __name__, url_prefix='/misc')

# API 4: Fetch All Foodtypes and Categories
@bp.route('/foodtypes-categories', methods=['GET'])
def get_foodtypes_and_categories():
    query = """
    SELECT 
        (
            SELECT json_agg(
                json_build_object('foodtype_id', ft.foodtype_id, 'foodtype_name', ft.foodtype_name)
                ORDER BY ft.foodtype_name
            ) 
            FROM public.foodtype ft
        ) as foodtypes,
        (
            SELECT json_agg(
                json_build_object('category_id', c.category_id, 'category_name', c.category_name)
                ORDER BY c.category_name
            ) 
            FROM public.category c
        ) as categories;
    """
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            
            data = serialize_row(row, cur.description) if row else {}
            foodtypes_list = data.get('foodtypes') or []
            categories_list = data.get('categories') or []
            
            response = FoodtypesCategoriesResponse(
                foodtypes=[FoodTypeModel(**ft) for ft in foodtypes_list],
                categories=[CategoryModel(**cat) for cat in categories_list]
            )
            
        close_conn(conn)
        return jsonify(response.dict()), 200
    except Exception as e:
        logger.error(f"Error fetching foodtypes/categories: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 16: Get Store Sections
@bp.route('/store-sections', methods=['GET'])
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

@bp.route('/images/<path:filename>')
def serve_image(filename):
    # Construct the absolute path to the images directory.
    # 'current_app.root_path' points to the 'app' folder.
    # '..' goes one level up to the project root ('QuantumCoders').
    # This creates a reliable path to QuantumCoders/images/.
    images_dir = os.path.abspath(os.path.join(current_app.root_path, '..', 'images'))
    return send_from_directory(images_dir, filename)
