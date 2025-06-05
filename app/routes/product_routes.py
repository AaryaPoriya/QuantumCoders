from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from app.models import (
    Product as ProductModel, ProductDetailResponse, 
    ProductFoodTypeDetail, ProductAllergyDetail,
    OfferResponse, SearchQuery, SearchResponse, ErrorResponse
)
from app.db import execute_query
from app.auth import jwt_required # Some product routes might be public, some protected
from app.utils import handle_pydantic_error, serialize_row, serialize_rows
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('product', __name__, url_prefix='/products')

# API 10: Offers
@bp.route('/offers', methods=['GET'])
# @jwt_required # Decide if offers should be public or require auth
def get_offers():
    # Query products with non-null offer_name and valid discount.
    # Assuming discounted_price being set and less than price implies an offer, 
    # or offer_name is not null.
    query = """
    SELECT product_id, product_name, price, discounted_price, barcode, weight, expiry, category_id, offer_name
    FROM public.product 
    WHERE offer_name IS NOT NULL OR (discounted_price IS NOT NULL AND discounted_price < price);
    """
    try:
        conn = None
        offer_products = []
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            if rows:
                serialized_products = serialize_rows(rows, cur.description)
                offer_products = [ProductModel(**p) for p in serialized_products]
        
        return jsonify(OfferResponse(offers=offer_products).dict()), 200
    except Exception as e:
        logger.error(f"Error fetching offers: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn: close_conn(conn)

# API 11: Search
@bp.route('/search', methods=['GET'])
# @jwt_required # Decide if search should be public or require auth
def search_products():
    search_term = request.args.get('query')
    if not search_term:
        return jsonify(ErrorResponse(detail='Search query parameter is required.').dict()), 400
    
    # Using ILIKE for case-insensitive search
    # Searching in product_name and barcode
    query = """
    SELECT product_id, product_name, price, discounted_price, barcode, weight, expiry, category_id, offer_name
    FROM public.product 
    WHERE product_name ILIKE %s OR barcode ILIKE %s;
    """
    like_pattern = f'%{search_term}%'
    try:
        conn = None
        search_results = []
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, (like_pattern, like_pattern))
            rows = cur.fetchall()
            if rows:
                serialized_results = serialize_rows(rows, cur.description)
                search_results = [ProductModel(**p) for p in serialized_results]

        return jsonify(SearchResponse(results=search_results).dict()), 200
    except Exception as e:
        logger.error(f"Error during product search for term '{search_term}': {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn: close_conn(conn)

# API 12: Get Product Details
@bp.route('/<int:product_id>', methods=['GET'])
# @jwt_required # Decide if product details are public or require auth
def get_product_details(product_id):
    product_query = """
    SELECT p.product_id, p.product_name, p.price, p.discounted_price, 
           p.barcode, p.weight, p.expiry, p.category_id, p.offer_name,
           c.category_name
    FROM public.product p
    LEFT JOIN public.category c ON p.category_id = c.category_id
    WHERE p.product_id = %s;
    """
    
    foodtypes_query = """
    SELECT ft.foodtype_id, ft.foodtype_name 
    FROM public.product_foodtype pft
    JOIN public.foodtype ft ON pft.foodtype_id = ft.foodtype_id
    WHERE pft.product_id = %s;
    """

    allergies_query = """
    SELECT a.allergy_id, a.allergy_name
    FROM public.food_allergy fa
    JOIN public.allergy a ON fa.allergy_id = a.allergy_id
    WHERE fa.product_id = %s;
    """
    
    try:
        conn = None
        product_data = None
        foodtype_list = []
        allergy_list = []
        from app.db import get_conn, close_conn
        
        # Fetch main product details
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(product_query, (product_id,))
            row = cur.fetchone()
            if not row:
                close_conn(conn)
                return jsonify(ErrorResponse(detail=f'Product with id {product_id} not found.').dict()), 404
            product_data_raw = serialize_row(row, cur.description)
            # Note: category_name is fetched but not directly in ProductModel, handled in ProductDetailResponse if needed or kept separate
            product_base_data = {k: v for k, v in product_data_raw.items() if k != 'category_name'}
            product_data = ProductModel(**product_base_data)

            # Fetch foodtypes
            cur.execute(foodtypes_query, (product_id,))
            ft_rows = cur.fetchall()
            if ft_rows:
                serialized_ft = serialize_rows(ft_rows, cur.description)
                foodtype_list = [ProductFoodTypeDetail(**ft) for ft in serialized_ft]

            # Fetch allergies
            cur.execute(allergies_query, (product_id,))
            al_rows = cur.fetchall()
            if al_rows:
                serialized_al = serialize_rows(al_rows, cur.description)
                allergy_list = [ProductAllergyDetail(**al) for al in serialized_al]
        close_conn(conn)

        response = ProductDetailResponse(
            **product_data.dict(), 
            foodtypes=foodtype_list, 
            allergies=allergy_list
        )
        return jsonify(response.dict()), 200

    except Exception as e:
        logger.error(f"Error fetching product details for product_id {product_id}: {e}")
        if conn: close_conn(conn, e) # Ensure connection is closed if error occurred before explicit close_conn
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500 