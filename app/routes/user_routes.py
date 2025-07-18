from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from app.models import (
    ChecklistItemCreate, ChecklistItemResponse, ChecklistItemRemove, ChecklistResponse, 
    Recipe as RecipeModel, Product as ProductModel, 
    ErrorResponse, MessageResponse
)
from app.db import execute_query
from app.auth import jwt_required, get_current_user_id
from app.utils import handle_pydantic_error, serialize_row, serialize_rows
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('user', __name__, url_prefix='/user')

# API 5: Fetch User Checklist
@bp.route('/checklist', methods=['GET'])
@jwt_required
def fetch_user_checklist():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='User not found or token invalid').dict()), 401

    query = """
    SELECT c.checklist_id, c.user_id, c.product_id, c.quantity,
           p.product_name, p.price, p.discounted_price, p.barcode, p.weight, p.expiry, p.category_id, p.offer_name
    FROM public.checklist c
    JOIN public.product p ON c.product_id = p.product_id
    WHERE c.user_id = %s;
    """
    try:
        conn = None
        items = []
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, (user_id,))
            rows = cur.fetchall()
            if rows:
                for row_data in rows:
                    serialized_item = serialize_row(row_data, cur.description)
                    # Manually construct ProductModel from serialized_item fields
                    product_data = {
                        'product_id': serialized_item['product_id'],
                        'product_name': serialized_item['product_name'],
                        'price': serialized_item['price'],
                        'discounted_price': serialized_item.get('discounted_price'),
                        'barcode': serialized_item['barcode'],
                        'weight': serialized_item.get('weight'),
                        'expiry': serialized_item.get('expiry'),
                        'category_id': serialized_item.get('category_id'),
                        'offer_name': serialized_item.get('offer_name')
                    }
                    item = ChecklistItemResponse(
                        checklist_id=serialized_item['checklist_id'],
                        user_id=serialized_item['user_id'],
                        product_id=serialized_item['product_id'],
                        quantity=serialized_item['quantity'],
                        product=ProductModel(**product_data)
                    )
                    items.append(item)
        return jsonify(ChecklistResponse(items=items).dict()), 200
    except Exception as e:
        logger.error(f"Error fetching checklist for user {user_id}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn: close_conn(conn)

# API 6: Add Product in Checklist
@bp.route('/checklist/add', methods=['POST'])
@jwt_required
def add_product_in_checklist():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='User not found or token invalid').dict()), 401

    try:
        data = ChecklistItemCreate(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    # Upsert logic: If exists, update quantity; else, insert.
    # Note: The user request says "update quantity by adding".
    query_upsert = """
    INSERT INTO public.checklist (user_id, product_id, quantity)
    VALUES (%s, %s, %s)
    ON CONFLICT (user_id, product_id) 
    DO UPDATE SET quantity = checklist.quantity + EXCLUDED.quantity
    RETURNING checklist_id, user_id, product_id, quantity;
    """
    try:
        conn = None
        updated_item_dict = None
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query_upsert, (user_id, data.product_id, data.quantity))
            updated_row = cur.fetchone()
            if updated_row:
                updated_item_dict = serialize_row(updated_row, cur.description)
            conn.commit()
        
        if updated_item_dict:
            # Fetch product details to return full ChecklistItemResponse
            # This could be combined with the RETURNING if product details are joined
            product_query = "SELECT * FROM public.product WHERE product_id = %s;"
            product_conn = get_conn()
            product_details_dict = None
            with product_conn.cursor() as p_cur:
                p_cur.execute(product_query, (updated_item_dict['product_id'],))
                product_raw = p_cur.fetchone()
                if product_raw:
                    product_details_dict = serialize_row(product_raw, p_cur.description)
            close_conn(product_conn)

            if product_details_dict:
                response_item = ChecklistItemResponse(
                    **updated_item_dict,
                    product=ProductModel(**product_details_dict)
                )
                return jsonify(response_item.dict()), 200
            else:
                 return jsonify(MessageResponse(message='Checklist updated, but product details not found.').dict()), 200 # Or an error
        return jsonify(ErrorResponse(detail='Failed to add/update item in checklist').dict()), 500
    except Exception as e:
        logger.error(f"Error adding to checklist for user {user_id}: {e}")
        if conn: conn.rollback() # Ensure rollback on error
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn: close_conn(conn)

# API 7: Remove Product in Checklist
@bp.route('/checklist/remove', methods=['POST'])
@jwt_required
def remove_product_in_checklist():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='User not found or token invalid').dict()), 401
    
    try:
        # Expecting {'product_id': value} in request body
        product_id = request.json.get('product_id')
        if not isinstance(product_id, int):
            return jsonify(ErrorResponse(detail='product_id must be an integer').dict()), 400
    except Exception:
        return jsonify(ErrorResponse(detail='Invalid request body, product_id missing or malformed').dict()), 400

    query = "DELETE FROM public.checklist WHERE user_id = %s AND product_id = %s RETURNING product_id;"
    try:
        deleted_product_id_row = execute_query(query, (user_id, product_id), fetchone=True, commit=True) # commit=True for DELETE
        if deleted_product_id_row and deleted_product_id_row[0] == product_id:
            return jsonify(MessageResponse(message=f'Product {product_id} removed from checklist.').dict()), 200
        else:
            return jsonify(ErrorResponse(detail=f'Product {product_id} not found in checklist or could not be removed.').dict()), 404
    except Exception as e:
        logger.error(f"Error removing from checklist for user {user_id}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 8: Show Recipes (from cart or checklist)
@bp.route('/recipes', methods=['GET'])
@jwt_required
def show_recipes():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='User not found or token invalid').dict()), 401

    source = request.args.get('source', 'checklist').lower() # Default to checklist
    if source not in ['cart', 'checklist']:
        return jsonify(ErrorResponse(detail='Invalid source parameter. Must be "cart" or "checklist".').dict()), 400

    product_ids_query_template = """
    SELECT DISTINCT product_id FROM public.{table_name} WHERE {user_or_cart_id_column} = %s;
    """
    
    table_name = 'cart_items' if source == 'cart' else 'checklist'
    id_column = 'cart_id' if source == 'cart' else 'user_id'
    id_value = user_id # For checklist, this is user_id.

    if source == 'cart':
        # For cart, we first need to find the user's active cart_id
        cart_id_query = "SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;"
        cart_row = execute_query(cart_id_query, (user_id,), fetchone=True)
        if not cart_row:
            return jsonify(ErrorResponse(detail='User has no active cart.').dict()), 404
        id_value = cart_row[0]

    product_ids_query = product_ids_query_template.format(table_name=table_name, user_or_cart_id_column=id_column)
    
    try:
        product_id_rows = execute_query(product_ids_query, (id_value,), fetchall=True)
        if not product_id_rows:
            return jsonify({"recipes": []}), 200 # No products, so no recipes

        product_ids = [row[0] for row in product_id_rows]
        if not product_ids:
            return jsonify({"recipes": []}), 200

        # Query recipes that contain any of these products (as per schema: recipe is linked to one product)
        # This finds recipes FOR those products.
        recipes_query = """
        SELECT r.recipe_id, r.recipe_name, r.product_id,
               p.product_name as p_name, p.price, p.discounted_price, p.barcode, p.weight, p.expiry, p.category_id, p.offer_name
        FROM public.recipe r
        JOIN public.product p ON r.product_id = p.product_id
        WHERE r.product_id = ANY(%s);
        """
        
        conn = None
        recipes_data = []
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(recipes_query, (product_ids,))
            raw_recipes = cur.fetchall()
            if raw_recipes:
                for rec_row in raw_recipes:
                    serialized_recipe = serialize_row(rec_row, cur.description)
                    product_details = {
                        'product_id': serialized_recipe['product_id'],
                        'product_name': serialized_recipe['p_name'],
                        'price': serialized_recipe['price'],
                        'discounted_price': serialized_recipe.get('discounted_price'),
                        'barcode': serialized_recipe['barcode'],
                        'weight': serialized_recipe.get('weight'),
                        'expiry': serialized_recipe.get('expiry'),
                        'category_id': serialized_recipe.get('category_id'),
                        'offer_name': serialized_recipe.get('offer_name')
                    }
                    recipe_obj = RecipeModel(
                        recipe_id=serialized_recipe['recipe_id'],
                        recipe_name=serialized_recipe['recipe_name'],
                        product_id=serialized_recipe['product_id'],
                        product=ProductModel(**product_details)
                    )
                    recipes_data.append(recipe_obj)

        return jsonify({"recipes": [r.dict() for r in recipes_data]}), 200
    except Exception as e:
        logger.error(f"Error fetching recipes for user {user_id}, source {source}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn: close_conn(conn)

# API 9: Show Recipe Details
@bp.route('/recipes/<int:recipe_id>', methods=['GET'])
@jwt_required # Or make public if recipe details are not user-specific beyond the ID
def show_recipe_details(recipe_id):
    query = """
    SELECT r.recipe_id, r.recipe_name, r.product_id,
           p.product_name as p_name, p.price, p.discounted_price, p.barcode, p.weight, p.expiry, p.category_id, p.offer_name
    FROM public.recipe r
    JOIN public.product p ON r.product_id = p.product_id
    WHERE r.recipe_id = %s;
    """
    try:
        conn = None
        recipe_obj = None
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, (recipe_id,))
            row = cur.fetchone()
            if row:
                serialized_recipe = serialize_row(row, cur.description)
                product_details = {
                    'product_id': serialized_recipe['product_id'],
                    'product_name': serialized_recipe['p_name'],
                    'price': serialized_recipe['price'],
                    'discounted_price': serialized_recipe.get('discounted_price'),
                    'barcode': serialized_recipe['barcode'],
                    'weight': serialized_recipe.get('weight'),
                    'expiry': serialized_recipe.get('expiry'),
                    'category_id': serialized_recipe.get('category_id'),
                    'offer_name': serialized_recipe.get('offer_name')
                }
                recipe_obj = RecipeModel(
                    recipe_id=serialized_recipe['recipe_id'],
                    recipe_name=serialized_recipe['recipe_name'],
                    product_id=serialized_recipe['product_id'],
                    product=ProductModel(**product_details)
                )
        if recipe_obj:
            return jsonify(recipe_obj.dict()), 200
        else:
            return jsonify(ErrorResponse(detail=f'Recipe with id {recipe_id} not found.').dict()), 404
    except Exception as e:
        logger.error(f"Error fetching recipe details for recipe_id {recipe_id}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn: close_conn(conn) 
