from pydantic import BaseModel, EmailStr, constr, conint, confloat, Field
from typing import List, Optional, Union, Dict, Any
from datetime import date, datetime

# --- Generic Models ---
class MessageResponse(BaseModel):
    message: str

class ErrorResponse(BaseModel):
    detail: Union[str, List[Dict[str, Any]]]

# --- Auth Models ---
class VerifyMobileRequest(BaseModel):
    mobile_number: constr(min_length=10, max_length=15)

class VerifyOTPRequest(BaseModel):
    mobile_number: constr(min_length=10, max_length=15)
    otp: constr(min_length=4, max_length=10)

class TokenResponse(BaseModel):
    token: str
    user_id: int
    is_profile_complete: bool

class ProfileCompleteRequest(BaseModel):
    user_name: str
    email: Optional[EmailStr] = None
    user_foodtype_id: Optional[int] = None
    user_allergy_id: Optional[int] = None

class UserResponse(BaseModel):
    user_id: int
    user_name: Optional[str] = None
    mobilenum: str
    email: Optional[EmailStr] = None
    user_foodtype_id: Optional[int] = None
    user_allergy_id: Optional[int] = None
    is_profile_complete: bool

    class Config:
        from_attributes = True


# --- Data Fetch Models ---
class FoodType(BaseModel):
    foodtype_id: int
    foodtype_name: str
    class Config:
        from_attributes = True

class Category(BaseModel):
    category_id: int
    category_name: str
    class Config:
        from_attributes = True

class FoodtypesCategoriesResponse(BaseModel):
    foodtypes: List[FoodType]
    categories: List[Category]

# --- Product Models ---
class ProductBase(BaseModel):
    product_name: str
    price: confloat(gt=0)
    discounted_price: Optional[confloat(ge=0)] = None
    barcode: str
    weight: Optional[confloat(ge=0)] = None
    expiry: Optional[date] = None
    category_id: Optional[int] = None
    offer_name: Optional[str] = None

class Product(ProductBase):
    product_id: int
    class Config:
        from_attributes = True

class ProductFoodTypeDetail(BaseModel):
    foodtype_id: int
    foodtype_name: str

class ProductAllergyDetail(BaseModel):
    allergy_id: int
    allergy_name: str

class ProductDetailResponse(Product):
    foodtypes: List[ProductFoodTypeDetail] = []
    allergies: List[ProductAllergyDetail] = []


# --- Checklist Models ---
class ChecklistItemBase(BaseModel):
    product_id: int
    quantity: conint(gt=0)

class ChecklistItemCreate(ChecklistItemBase):
    pass

class ChecklistItemResponse(ChecklistItemBase):
    checklist_id: int
    user_id: int
    product: Product
    class Config:
        from_attributes = True

class ChecklistResponse(BaseModel):
    items: List[ChecklistItemResponse]


# --- Recipe Models ---
class Recipe(BaseModel):
    recipe_id: int
    recipe_name: str
    product_id: int
    product: Optional[Product] = None
    class Config:
        from_attributes = True

class RecipeDetailResponse(BaseModel):
    recipe_id: int
    recipe_name: str
    products: List[Product]

# --- Offer Models ---
class OfferResponse(BaseModel):
    offers: List[Product]

# --- Search Models ---
class SearchQuery(BaseModel):
    query: str

class SearchResponse(BaseModel):
    results: List[Product]


# --- Cart Models ---
class ConnectCartRequest(BaseModel):
    cart_id: int

class CartConnectionResponse(BaseModel):
    cart_id: int
    user_id: int
    message: str

class CartItemBase(BaseModel):
    product_id: int
    quantity: conint(gt=0)

class CartItem(CartItemBase):
    cart_items_id: int
    cart_id: int
    product: Product
    class Config:
        from_attributes = True
        
class CartItemAddRequest(BaseModel):
    product_id: int

class CartItemRemoveRequest(BaseModel):
    product_id: int

class CartViewResponse(BaseModel):
    cart_id: int
    items: List[CartItem]
    total_weight: Optional[float] = None

class CartLocation(BaseModel):
    cart_id: int
    x_coord: float
    y_coord: float
    section_id: Optional[int] = None
    updated_at: datetime
    class Config:
        from_attributes = True

class Esp32CartUpdateRequest(BaseModel):
    cart_id: int
    product_id: int
    weight: float

class CartWeightUpdateRequest(BaseModel):
    cart_id: int
    cart_weight: float


# --- Location Models ---
class StoreSection(BaseModel):
    section_id: int
    section_name: str
    x1: float
    y1: float
    x2: float
    y2: float
    floor_level: int
    class Config:
        from_attributes = True

class ProductLocation(BaseModel):
    product_id: int
    section_id: int
    aisle_num: int
    shelf_num: int
    x_coord: float
    y_coord: float
    section: Optional[StoreSection] = None
    class Config:
        from_attributes = True

class DestinationRequest(BaseModel):
    product_id: int

class ShortestPathRequest(BaseModel):
    destinations: List[DestinationRequest]

class PathSegment(BaseModel):
    x: float
    y: float
    section_id: Optional[int] = None
    instruction: Optional[str] = None

class ShortestPathResponse(BaseModel):
    path: List[PathSegment]

# --- Order Models ---
class CheckoutResponse(BaseModel):
    order_id: int
    user_id: int
    total_products: int
    total_price: float
    discounted_price: float
    message: str

class DetailOrderItemResponse(BaseModel):
    product_id: int
    quantity: int
    price: float
    discounted_price: float
    product_name: str

class OrderResponse(BaseModel):
    order_id: int
    user_id: int
    total_products: int
    total_price: float
    discounted_price: float
    items: List[DetailOrderItemResponse]

    class Config:
        from_attributes = True

# --- Misc ---
class Allergy(BaseModel):
    allergy_id: int
    allergy_name: str
    class Config:
        from_attributes = True 
