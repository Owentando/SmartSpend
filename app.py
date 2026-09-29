from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file
import sqlite3
import os
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from collections import Counter

# PDF generation
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

app = Flask(__name__)
ON_RENDER = bool(os.environ.get("RENDER"))


def _require_env(name, dev_default):
    """Required on Render; falls back to a dev value when running locally."""
    value = os.environ.get(name)
    if value:
        return value
    if ON_RENDER:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return dev_default


app.secret_key = _require_env("SECRET_KEY", "dev-only-secret-change-me")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "smartshop.db"))



ADMIN_INVITE_CODE = _require_env("ADMIN_INVITE_CODE", "dev-admin-code")



app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)
app.config["SESSION_COOKIE_SECURE"] = ON_RENDER  # HTTPS-only cookies on Render
app.config["CSRF_DISABLED"] = os.environ.get("CSRF_DISABLED") == "1"



@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https:; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' https:; "
        "font-src 'self' https:;"
    )
    return response



def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def validate_csrf_token(token_from_form):
    expected = session.get("_csrf_token", "")
    if not expected or not token_from_form:
        return False
    return secrets.compare_digest(expected, token_from_form)


app.jinja_env.globals["csrf_token"] = generate_csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        if app.config.get("CSRF_DISABLED"):
            return None
        if request.path.startswith("/api/"):
            return None
        token = (
            request.form.get("_csrf_token", "")
            or request.headers.get("X-CSRF-Token", "")
        )
        if not validate_csrf_token(token):
            flash("Your session expired. Please try again.", "danger")
            return redirect(request.referrer or url_for("home"))
    return None



login_attempts = {}

def is_rate_limited(key, max_attempts=5, window_seconds=300):
    now = datetime.now()
    attempts = login_attempts.get(key, [])
    attempts = [t for t in attempts if (now - t).total_seconds() < window_seconds]
    login_attempts[key] = attempts
    return len(attempts) >= max_attempts


def record_attempt(key):
    login_attempts.setdefault(key, []).append(datetime.now())



@app.errorhandler(404)
def not_found_error(error):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("errors/500.html"), 500



FREE_DISTANCE_KM = 10

DISTANCE_FEES = {
    5: 0,
    10: 0,
    25: 10,
    50: 20,
    100: 35,
}


def get_distance_fee(radius, product_distance):
    try:
        product_distance = float(product_distance)
    except (TypeError, ValueError):
        return 0

    if product_distance <= FREE_DISTANCE_KM:
        return 0

    try:
        radius = int(float(radius))
    except (TypeError, ValueError):
        return 0

    keys = sorted(DISTANCE_FEES.keys())
    chosen = keys[-1]
    for k in keys:
        if radius <= k:
            chosen = k
            break
    return DISTANCE_FEES.get(chosen, 0)



SHOP_DISTANCES = {
    "Shoprite":      {"steve_biko": 2,  "ml_sultan": 5, "ritson": 6, "berea": 3, "glenwood": 7, "umbilo": 8, "pinetown": 15, "chatsworth": 22, "south_beach": 6},
    "Checkers":      {"steve_biko": 3,  "ml_sultan": 4, "ritson": 5, "berea": 2, "glenwood": 6, "umbilo": 9, "pinetown": 14, "chatsworth": 21, "south_beach": 5},
    "Pick n Pay":    {"steve_biko": 5,  "ml_sultan": 3, "ritson": 4, "berea": 4, "glenwood": 5, "umbilo": 7, "pinetown": 12, "chatsworth": 20, "south_beach": 4},
    "Clicks":        {"steve_biko": 1,  "ml_sultan": 3, "ritson": 4, "berea": 2, "glenwood": 4, "umbilo": 6, "pinetown": 13, "chatsworth": 18, "south_beach": 5},
    "Dis-Chem":      {"steve_biko": 2,  "ml_sultan": 4, "ritson": 5, "berea": 3, "glenwood": 5, "umbilo": 7, "pinetown": 14, "chatsworth": 19, "south_beach": 6},
    "Edgars":        {"steve_biko": 3,  "ml_sultan": 2, "ritson": 3, "berea": 4, "glenwood": 6, "umbilo": 8, "pinetown": 13, "chatsworth": 20, "south_beach": 7},
    "Mr Price":      {"steve_biko": 2,  "ml_sultan": 3, "ritson": 3, "berea": 3, "glenwood": 5, "umbilo": 7, "pinetown": 12, "chatsworth": 18, "south_beach": 5},
    "Mr Price Home": {"steve_biko": 2,  "ml_sultan": 3, "ritson": 3, "berea": 3, "glenwood": 5, "umbilo": 7, "pinetown": 12, "chatsworth": 18, "south_beach": 5},
    "Jet":           {"steve_biko": 3,  "ml_sultan": 4, "ritson": 4, "berea": 5, "glenwood": 7, "umbilo": 8, "pinetown": 14, "chatsworth": 20, "south_beach": 6},
    "SportScene":    {"steve_biko": 5,  "ml_sultan": 3, "ritson": 4, "berea": 5, "glenwood": 6, "umbilo": 8, "pinetown": 15, "chatsworth": 21, "south_beach": 5},
    "CNA":           {"steve_biko": 4,  "ml_sultan": 2, "ritson": 3, "berea": 4, "glenwood": 6, "umbilo": 8, "pinetown": 13, "chatsworth": 20, "south_beach": 6},
    "DUT Bookshop":  {"steve_biko": 1,  "ml_sultan": 2, "ritson": 2, "berea": 3, "glenwood": 5, "umbilo": 7, "pinetown": 12, "chatsworth": 19, "south_beach": 5},
}

AREAS = [
    {"key": "steve_biko",  "name": "DUT Steve Biko Campus"},
    {"key": "ml_sultan",   "name": "DUT ML Sultan Campus"},
    {"key": "ritson",      "name": "DUT Ritson Campus"},
    {"key": "berea",       "name": "Berea"},
    {"key": "glenwood",    "name": "Glenwood"},
    {"key": "umbilo",      "name": "Umbilo"},
    {"key": "pinetown",    "name": "Pinetown"},
    {"key": "chatsworth",  "name": "Chatsworth"},
    {"key": "south_beach", "name": "South Beach"},
]


def get_shop_distance(store_name, area_key):
    if not store_name or not area_key:
        return 5
    shop = SHOP_DISTANCES.get(store_name)
    if not shop:
        return 5
    return shop.get(area_key, 5)



def format_datetime(value):
    if not value:
        return ""
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            return str(value)
    return dt.strftime("%d %b %Y, %I:%M %p")


app.jinja_env.filters['format_datetime'] = format_datetime



def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def get_unique_products():
    unique_products = []
    seen_names = set()
    for product in PRODUCTS:
        if product["name"] not in seen_names:
            unique_products.append(product)
            seen_names.add(product["name"])
    return unique_products



PRODUCTS = [
    {"id": 1, "name": "Aunt Caroline Rice 2kg", "category": "food", "item": "rice", "brand": "Aunt Caroline", "size": "2kg", "store": "Shoprite", "price": 52, "shipping": 0, "distance": 2, "rating": 4.7, "image_url": "/static/images/Rice/Aunt_caroline_2kg.jpg"},
    {"id": 2, "name": "Spekko Rice 2kg", "category": "food", "item": "rice", "brand": "Spekko", "size": "2kg", "store": "Checkers", "price": 55, "shipping": 0, "distance": 3, "rating": 4.6, "image_url": "/static/images/Rice/Spekko_2kg.jpg"},
    {"id": 3, "name": "Golden Delight Rice 2kg", "category": "food", "item": "rice", "brand": "Golden Delight", "size": "2kg", "store": "Pick n Pay", "price": 49, "shipping": 5, "distance": 5, "rating": 4.5, "image_url": "/static/images/Rice/Golden_delight_2kg.jpg"},
    {"id": 4, "name": "Spekko Rice 5kg", "category": "food", "item": "rice", "brand": "Spekko", "size": "5kg", "store": "Checkers", "price": 125, "shipping": 10, "distance": 3, "rating": 4.7, "image_url": "/static/images/Rice/spekko_5kg.jpg"},
    {"id": 5, "name": "Tastic Rice 2kg", "category": "food", "item": "rice", "brand": "Tastic", "size": "2kg", "store": "Shoprite", "price": 48, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/Rice/tastic_2kg.jpg"},
    {"id": 6, "name": "Sasko White Bread Loaf", "category": "food", "item": "bread", "brand": "Sasko", "size": "700g", "store": "Shoprite", "price": 18, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/bread/Sasko_White_Bread_loaf.jpg"},
    {"id": 7, "name": "Albany Bread Loaf", "category": "food", "item": "bread", "brand": "Albany", "size": "700g", "store": "Checkers", "price": 19, "shipping": 0, "distance": 3, "rating": 4.4, "image_url": "/static/images/bread/Albany_bread.jpg"},
    {"id": 8, "name": "Blue Ribbon Bread Loaf", "category": "food", "item": "bread", "brand": "Blue Ribbon", "size": "700g", "store": "Pick n Pay", "price": 18, "shipping": 5, "distance": 5, "rating": 4.3, "image_url": "/static/images/bread/Blue_Ribbon_Bread_loaf.jpg"},
    {"id": 9, "name": "Sasko Brown Bread Loaf", "category": "food", "item": "bread", "brand": "Sasko", "size": "700g", "store": "Shoprite", "price": 20, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/bread/Sasko_Brown_Bread_loaf.jpg"},
    {"id": 10, "name": "Sunflower Oil 750ml", "category": "food", "item": "oil", "brand": "Sunflower", "size": "750ml", "store": "Pick n Pay", "price": 22, "shipping": 0, "distance": 5, "rating": 4.4, "image_url": "/static/images/oil/Sunflower_oil_750ml.jpg"},
    {"id": 11, "name": "Sunflower Oil 2L", "category": "food", "item": "oil", "brand": "Sunflower", "size": "2L", "store": "Shoprite", "price": 35, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/oil/Sunflower_Oil_2L.jpg"},
    {"id": 12, "name": "Delight Oil 750ml", "category": "food", "item": "oil", "brand": "Delight", "size": "750ml", "store": "Checkers", "price": 21, "shipping": 0, "distance": 3, "rating": 4.3, "image_url": "/static/images/oil/Delight_oil_750ml.jpg"},
    {"id": 13, "name": "Delight Oil 2L", "category": "food", "item": "oil", "brand": "Delight", "size": "2L", "store": "Pick n Pay", "price": 34, "shipping": 0, "distance": 5, "rating": 4.4, "image_url": "/static/images/oil/Delight_oil_2l.jpg"},
    {"id": 14, "name": "Aces Maize Meal 2.5kg", "category": "food", "item": "maize meal", "brand": "Aces", "size": "2.5kg", "store": "Pick n Pay", "price": 42, "shipping": 0, "distance": 5, "rating": 4.3, "image_url": "/static/images/Maize_Meal/Aces_Maize_meal_2.5kg.jpg"},
    {"id": 15, "name": "White Star Maize Meal 2.5kg", "category": "food", "item": "maize meal", "brand": "White Star", "size": "2.5kg", "store": "Shoprite", "price": 45, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/Maize_Meal/White_star_maize_meal_2.5kg.jpg"},
    {"id": 16, "name": "White Star Maize Meal 5kg", "category": "food", "item": "maize meal", "brand": "White Star", "size": "5kg", "store": "Checkers", "price": 75, "shipping": 10, "distance": 3, "rating": 4.7, "image_url": "/static/images/Maize_Meal/White_star_maize_meal_5kg.jpg"},
    {"id": 17, "name": "Iwisa Maize Meal 5kg", "category": "food", "item": "maize meal", "brand": "Iwisa", "size": "5kg", "store": "Shoprite", "price": 78, "shipping": 10, "distance": 2, "rating": 4.6, "image_url": "/static/images/Maize_Meal/Iwisa_maize_meal_5kg.jpg"},
    {"id": 18, "name": "Clover Milk 1L", "category": "food", "item": "milk", "brand": "Clover", "size": "1L", "store": "Checkers", "price": 22, "shipping": 0, "distance": 3, "rating": 4.6, "image_url": "/static/images/Milk/Clover_milk_1l.jpg"},
    {"id": 19, "name": "Parmalat Milk 1L", "category": "food", "item": "milk", "brand": "Parmalat", "size": "1L", "store": "Shoprite", "price": 23, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/Milk/Parmalat_milk_1L.jpg"},
    {"id": 20, "name": "Clover Milk 2L", "category": "food", "item": "milk", "brand": "Clover", "size": "2L", "store": "Pick n Pay", "price": 38, "shipping": 0, "distance": 5, "rating": 4.6, "image_url": "/static/images/Milk/Clover_milk_2L.jpg"},
    {"id": 21, "name": "Parmalat Milk 2L", "category": "food", "item": "milk", "brand": "Parmalat", "size": "2L", "store": "Checkers", "price": 40, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/Milk/Parmalat_milk_2L.jpg"},
    {"id": 22, "name": "Selati Sugar 2kg", "category": "food", "item": "sugar", "brand": "Selati", "size": "2kg", "store": "Pick n Pay", "price": 39, "shipping": 0, "distance": 5, "rating": 4.5, "image_url": "/static/images/Sugar/Selati_Sugar_2kg.jpg"},
    {"id": 23, "name": "Huletts Sugar 2kg", "category": "food", "item": "sugar", "brand": "Huletts", "size": "2kg", "store": "Shoprite", "price": 41, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/Sugar/Hulletts_sugar_2kg.jpg"},
    {"id": 24, "name": "Selati Sugar 5kg", "category": "food", "item": "sugar", "brand": "Selati", "size": "5kg", "store": "Checkers", "price": 89, "shipping": 10, "distance": 3, "rating": 4.5, "image_url": "/static/images/Sugar/Selati_sugar_5kg.jpg"},
    {"id": 25, "name": "Chicken Breast 1kg", "category": "food", "item": "chicken", "brand": "Country Bird", "size": "1kg", "store": "Shoprite", "price": 89, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/Meat/Chicken Breast_1kg.jpg"},
    {"id": 26, "name": "Chicken Breast 2kg", "category": "food", "item": "chicken", "brand": "Country Bird", "size": "2kg", "store": "Checkers", "price": 165, "shipping": 0, "distance": 3, "rating": 4.6, "image_url": "/static/images/Meat/chicken_breast_2kg.jpg"},
    {"id": 27, "name": "Beef Mince 500g", "category": "food", "item": "beef", "brand": "Farm Fresh", "size": "500g", "store": "Pick n Pay", "price": 55, "shipping": 0, "distance": 5, "rating": 4.6, "image_url": "/static/images/Meat/Beef_mince_500g.jpg"},
    {"id": 28, "name": "Beef Mince 1kg", "category": "food", "item": "beef", "brand": "Farm Fresh", "size": "1kg", "store": "Shoprite", "price": 99, "shipping": 0, "distance": 2, "rating": 4.7, "image_url": "/static/images/Meat/Beef_mince_1kg.jpg"},
    {"id": 29, "name": "Pork Sausages 500g", "category": "food", "item": "pork", "brand": "Farm Fresh", "size": "500g", "store": "Checkers", "price": 45, "shipping": 5, "distance": 3, "rating": 4.3, "image_url": "/static/images/Meat/Pork_sausages_500g.jpg"},
    {"id": 30, "name": "Lamb Chops 1kg", "category": "food", "item": "lamb", "brand": "Farm Fresh", "size": "1kg", "store": "Pick n Pay", "price": 159, "shipping": 0, "distance": 5, "rating": 4.8, "image_url": "/static/images/Meat/lamb_chops_1kg.jpg"},
    {"id": 31, "name": "Chicken Thighs 1kg", "category": "food", "item": "chicken", "brand": "Country Bird", "size": "1kg", "store": "Shoprite", "price": 75, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/Meat/chicken_thighs_1kg.jpg"},
    {"id": 32, "name": "Beef Steak 500g", "category": "food", "item": "beef", "brand": "Farm Fresh", "size": "500g", "store": "Checkers", "price": 85, "shipping": 0, "distance": 3, "rating": 4.7, "image_url": "/static/images/Meat/beef_steak_500g.jpg"},
    {"id": 33, "name": "Fresh Tomatoes 250g", "category": "food", "item": "tomatoes", "brand": "Fresh Pick", "size": "250g", "store": "Shoprite", "price": 12, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/tomatoes/Fresh_tomatoes_250g.jpg"},
    {"id": 34, "name": "Fresh Tomatoes 500g", "category": "food", "item": "tomatoes", "brand": "Fresh Pick", "size": "500g", "store": "Checkers", "price": 22, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/tomatoes/fresh_tomatoes_500g.jpg"},
    {"id": 35, "name": "Fresh Tomatoes 1kg", "category": "food", "item": "tomatoes", "brand": "Fresh Pick", "size": "1kg", "store": "Pick n Pay", "price": 39, "shipping": 0, "distance": 5, "rating": 4.6, "image_url": "/static/images/tomatoes/fresh_tomatoes_1kg.jpg"},
    {"id": 36, "name": "Cherry Tomatoes 250g", "category": "food", "item": "tomatoes", "brand": "Fresh Pick", "size": "250g", "store": "Checkers", "price": 18, "shipping": 5, "distance": 3, "rating": 4.6, "image_url": "/static/images/tomatoes/cherry_tomatoes_250g.jpg"},
    {"id": 37, "name": "Potatoes 2kg", "category": "food", "item": "potatoes", "brand": "Fresh Pick", "size": "2kg", "store": "Shoprite", "price": 29, "shipping": 0, "distance": 2, "rating": 4.3, "image_url": "/static/images/potatoes/potatoes_2kg.jpg"},
    {"id": 38, "name": "Potatoes 5kg", "category": "food", "item": "potatoes", "brand": "Fresh Pick", "size": "5kg", "store": "Pick n Pay", "price": 59, "shipping": 10, "distance": 5, "rating": 4.4, "image_url": "/static/images/potatoes/potatoes_5kg.jpg"},
    {"id": 39, "name": "Sweet Potatoes 1kg", "category": "food", "item": "potatoes", "brand": "Fresh Pick", "size": "1kg", "store": "Checkers", "price": 22, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/potatoes/sweet_potatoes_1kg.jpg"},
    {"id": 40, "name": "Onions 2kg", "category": "food", "item": "onions", "brand": "Fresh Pick", "size": "2kg", "store": "Shoprite", "price": 25, "shipping": 0, "distance": 2, "rating": 4.2, "image_url": "/static/images/onions/onions_2kg.jpg"},
    {"id": 41, "name": "Onions 5kg", "category": "food", "item": "onions", "brand": "Fresh Pick", "size": "5kg", "store": "Checkers", "price": 55, "shipping": 0, "distance": 3, "rating": 4.3, "image_url": "/static/images/onions/onions_5kg.jpg"},
    {"id": 42, "name": "Cabbage 1kg", "category": "food", "item": "cabbage", "brand": "Fresh Pick", "size": "1kg", "store": "Shoprite", "price": 15, "shipping": 0, "distance": 2, "rating": 4.2, "image_url": "/static/images/vegetables/cabbage_1kg.jpg"},
    {"id": 43, "name": "Spinach Bunch 250g", "category": "food", "item": "spinach", "brand": "Fresh Pick", "size": "250g", "store": "Checkers", "price": 12, "shipping": 0, "distance": 3, "rating": 4.4, "image_url": "/static/images/vegetables/spinach_bunch_250g.jpg"},
    {"id": 44, "name": "Carrots 1kg", "category": "food", "item": "carrots", "brand": "Fresh Pick", "size": "1kg", "store": "Pick n Pay", "price": 18, "shipping": 5, "distance": 5, "rating": 4.3, "image_url": "/static/images/vegetables/carrots_1kg.jpg"},
    {"id": 45, "name": "Broccoli 250g", "category": "food", "item": "broccoli", "brand": "Fresh Pick", "size": "250g", "store": "Checkers", "price": 22, "shipping": 0, "distance": 3, "rating": 4.6, "image_url": "/static/images/vegetables/broccoli_250g.jpg"},
    {"id": 46, "name": "Cauliflower 500g", "category": "food", "item": "cauliflower", "brand": "Fresh Pick", "size": "500g", "store": "Shoprite", "price": 25, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/vegetables/cauliflower_500g.jpg"},
    {"id": 47, "name": "Bananas 1kg", "category": "food", "item": "bananas", "brand": "Fresh Pick", "size": "1kg", "store": "Shoprite", "price": 18, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/fruits/banana_1kg.jpg"},
    {"id": 48, "name": "Apples 1kg", "category": "food", "item": "apples", "brand": "Fresh Pick", "size": "1kg", "store": "Checkers", "price": 22, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/fruits/apples_1kg.jpg"},
    {"id": 49, "name": "Oranges 1.5kg", "category": "food", "item": "oranges", "brand": "Fresh Pick", "size": "1.5kg", "store": "Pick n Pay", "price": 25, "shipping": 5, "distance": 5, "rating": 4.3, "image_url": "/static/images/fruits/oranges_1.5kg.jpg"},
    {"id": 50, "name": "Grapes 500g", "category": "food", "item": "grapes", "brand": "Fresh Pick", "size": "500g", "store": "Checkers", "price": 28, "shipping": 0, "distance": 3, "rating": 4.6, "image_url": "/static/images/fruits/grapes_500g.jpg"},
    {"id": 51, "name": "Strawberries 250g", "category": "food", "item": "strawberries", "brand": "Fresh Pick", "size": "250g", "store": "Shoprite", "price": 35, "shipping": 0, "distance": 2, "rating": 4.7, "image_url": "/static/images/fruits/strawberries_250g.jpg"},
    {"id": 52, "name": "Eggs 6 Pack", "category": "food", "item": "eggs", "brand": "Fresh Farm", "size": "6 Pack", "store": "Shoprite", "price": 18, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/Eggs/Eggs_6.jpg"},
    {"id": 53, "name": "Eggs 12 Pack", "category": "food", "item": "eggs", "brand": "Fresh Farm", "size": "12 Pack", "store": "Checkers", "price": 32, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/Eggs/eggs_12.jpg"},
    {"id": 54, "name": "Eggs 30 Pack", "category": "food", "item": "eggs", "brand": "Fresh Farm", "size": "30 Pack", "store": "Pick n Pay", "price": 72, "shipping": 10, "distance": 5, "rating": 4.3, "image_url": "/static/images/Eggs/eggs_30.jpg"},
    {"id": 55, "name": "Gouda Cheese 250g", "category": "food", "item": "cheese", "brand": "Fresh Farm", "size": "250g", "store": "Checkers", "price": 35, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/cheese/gouda_cheese_250g.jpg"},
    {"id": 56, "name": "Gouda Cheese 500g", "category": "food", "item": "cheese", "brand": "Fresh Farm", "size": "500g", "store": "Shoprite", "price": 62, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/cheese/gouda_cheese_500g.jpg"},
    {"id": 57, "name": "Cheddar Cheese 250g", "category": "food", "item": "cheese", "brand": "Fresh Farm", "size": "250g", "store": "Pick n Pay", "price": 38, "shipping": 5, "distance": 5, "rating": 4.4, "image_url": "/static/images/cheese/chedda_cheese_250g.jpg"},
    {"id": 58, "name": "Butter 250g", "category": "food", "item": "butter", "brand": "Clover", "size": "250g", "store": "Shoprite", "price": 28, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/butter _margarine/butter_250g.jpg"},
    {"id": 59, "name": "Margarine 500g", "category": "food", "item": "butter", "brand": "Clover", "size": "500g", "store": "Checkers", "price": 45, "shipping": 0, "distance": 3, "rating": 4.3, "image_url": "/static/images/butter _margarine/margarine_500g.jpg"},
    {"id": 60, "name": "Cake Flour 2.5kg", "category": "food", "item": "flour", "brand": "Snowflake", "size": "2.5kg", "store": "Pick n Pay", "price": 35, "shipping": 0, "distance": 5, "rating": 4.5, "image_url": "/static/images/flour/cake_flour_2.5kg.jpg"},
    {"id": 61, "name": "Bread Flour 2.5kg", "category": "food", "item": "flour", "brand": "Snowflake", "size": "2.5kg", "store": "Shoprite", "price": 38, "shipping": 5, "distance": 2, "rating": 4.4, "image_url": "/static/images/flour/bread_flour_2.5kg.jpg"},
    {"id": 62, "name": "All Purpose Flour 5kg", "category": "food", "item": "flour", "brand": "Snowflake", "size": "5kg", "store": "Checkers", "price": 62, "shipping": 10, "distance": 3, "rating": 4.5, "image_url": "/static/images/flour/all_purpose_flour_5kg.jpg"},
    {"id": 63, "name": "Baked Beans 410g", "category": "food", "item": "tinned", "brand": "KOO", "size": "410g", "store": "Shoprite", "price": 15, "shipping": 0, "distance": 2, "rating": 4.3, "image_url": "/static/images/tinned _food/baked_beans_410g.jpg"},
    {"id": 64, "name": "Tuna 185g", "category": "food", "item": "tinned", "brand": "Ocean", "size": "185g", "store": "Checkers", "price": 22, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/tinned _food/tuna_185g.jpg"},
    {"id": 65, "name": "Sweetcorn 410g", "category": "food", "item": "tinned", "brand": "KOO", "size": "410g", "store": "Pick n Pay", "price": 12, "shipping": 5, "distance": 5, "rating": 4.2, "image_url": "/static/images/tinned _food/sweetcorn_210g.jpg"},
    {"id": 66, "name": "Tomato Paste 70g", "category": "food", "item": "tinned", "brand": "KOO", "size": "70g", "store": "Shoprite", "price": 8, "shipping": 0, "distance": 2, "rating": 4.3, "image_url": "/static/images/tinned _food/tomato_paste_70g.jpg"},
    {"id": 67, "name": "Spaghetti 500g", "category": "food", "item": "pasta", "brand": "Golden Cloud", "size": "500g", "store": "Pick n Pay", "price": 18, "shipping": 0, "distance": 5, "rating": 4.4, "image_url": "/static/images/noodles/spaghetti_500g.jpg"},
    {"id": 68, "name": "Macaroni 500g", "category": "food", "item": "pasta", "brand": "Golden Cloud", "size": "500g", "store": "Shoprite", "price": 18, "shipping": 0, "distance": 2, "rating": 4.3, "image_url": "/static/images/noodles/macaroni_500g.jpg"},
    {"id": 69, "name": "Ramen Noodles 70g", "category": "food", "item": "pasta", "brand": "Indomie", "size": "70g", "store": "Checkers", "price": 5, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/noodles/Ramen_noodles_70g.jpg"},
    {"id": 70, "name": "Ramen Noodles 5 Pack", "category": "food", "item": "pasta", "brand": "Indomie", "size": "5 Pack", "store": "Shoprite", "price": 22, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/noodles/Ramen_noodles_5Pack.jpg"},
    {"id": 71, "name": "Dettol Bath Soap", "category": "toiletries", "item": "soap", "brand": "Dettol", "store": "Clicks", "price": 25, "shipping": 0, "distance": 1, "rating": 4.7, "image_url": "/static/images/toiletries/dettol_bath_soap.jpg"},
    {"id": 72, "name": "Sunlight Bath Soap", "category": "toiletries", "item": "soap", "brand": "Sunlight", "store": "Dis-Chem", "price": 22, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/toiletries/sunlight_bath_soap.jpg"},
    {"id": 73, "name": "Dove Bath Soap", "category": "toiletries", "item": "soap", "brand": "Dove", "store": "Clicks", "price": 32, "shipping": 5, "distance": 1, "rating": 4.6, "image_url": "/static/images/toiletries/dove_bath_soap.jpg"},
    {"id": 74, "name": "Lifebuoy Bath Soap", "category": "toiletries", "item": "soap", "brand": "Lifebuoy", "store": "Dis-Chem", "price": 24, "shipping": 0, "distance": 2, "rating": 4.3, "image_url": "/static/images/toiletries/lifebuoy_bath_soap.jpg"},
    {"id": 75, "name": "Colgate Toothpaste", "category": "toiletries", "item": "toothpaste", "brand": "Colgate", "store": "Clicks", "price": 29, "shipping": 0, "distance": 1, "rating": 4.7, "image_url": "/static/images/toiletries/colgate_toothpaste.jpg"},
    {"id": 76, "name": "Aquafresh Toothpaste", "category": "toiletries", "item": "toothpaste", "brand": "Aquafresh", "store": "Dis-Chem", "price": 27, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/toiletries/Aquafresh_toothpaste.jpg"},
    {"id": 77, "name": "Sensodyne Toothpaste", "category": "toiletries", "item": "toothpaste", "brand": "Sensodyne", "store": "Clicks", "price": 55, "shipping": 5, "distance": 1, "rating": 4.8, "image_url": "/static/images/toiletries/sensodyne_toothpaste.jpg"},
    {"id": 78, "name": "Twinsaver Toilet Paper 9 Pack", "category": "toiletries", "item": "toilet paper", "brand": "Twinsaver", "size": "9 Pack", "store": "Shoprite", "price": 65, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/toiletries/twinsaver_toilet_paper_9pack.jpg"},
    {"id": 79, "name": "Baby Soft Toilet Paper 9 Pack", "category": "toiletries", "item": "toilet paper", "brand": "Baby Soft", "size": "9 Pack", "store": "Checkers", "price": 59, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/toiletries/baby_soft_toilet_paper_9Pack.jpg"},
    {"id": 80, "name": "Twinsaver Toilet Paper 12 Pack", "category": "toiletries", "item": "toilet paper", "brand": "Twinsaver", "size": "12 Pack", "store": "Pick n Pay", "price": 85, "shipping": 10, "distance": 5, "rating": 4.6, "image_url": "/static/images/toiletries/Twinsaver_toilet_paper_12pack.jpg"},
    {"id": 81, "name": "OMO Washing Powder 2kg", "category": "toiletries", "item": "washing powder", "brand": "OMO", "size": "2kg", "store": "Shoprite", "price": 79, "shipping": 0, "distance": 2, "rating": 4.7, "image_url": "/static/images/toiletries/OMO_washing_powder_2kg.jpg"},
    {"id": 82, "name": "OMO Washing Powder 5kg", "category": "toiletries", "item": "washing powder", "brand": "OMO", "size": "5kg", "store": "Checkers", "price": 179, "shipping": 15, "distance": 3, "rating": 4.8, "image_url": "/static/images/toiletries/OMO_washing_powder_5kg.jpg"},
    {"id": 83, "name": "Ariel Washing Powder 2kg", "category": "toiletries", "item": "washing powder", "brand": "Ariel", "size": "2kg", "store": "Pick n Pay", "price": 82, "shipping": 5, "distance": 5, "rating": 4.7, "image_url": "/static/images/toiletries/Ariel_washing_powder_2kg.jpg"},
    {"id": 84, "name": "Dishwashing Liquid 500ml", "category": "toiletries", "item": "dishwashing", "brand": "Sunlight", "size": "500ml", "store": "Shoprite", "price": 28, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/toiletries/Dishwashing_liquid_500ml.jpg"},
    {"id": 85, "name": "Dishwashing Liquid 1L", "category": "toiletries", "item": "dishwashing", "brand": "Sunlight", "size": "1L", "store": "Checkers", "price": 48, "shipping": 0, "distance": 3, "rating": 4.5, "image_url": "/static/images/toiletries/dishwashing_liquid_1l.jpg"},
    {"id": 86, "name": "Hand Sanitizer 500ml", "category": "toiletries", "item": "sanitizer", "brand": "Dettol", "size": "500ml", "store": "Clicks", "price": 35, "shipping": 0, "distance": 1, "rating": 4.6, "image_url": "/static/images/toiletries/hand_sanitizer_500ml.jpg"},
    {"id": 87, "name": "Hand Sanitizer 1L", "category": "toiletries", "item": "sanitizer", "brand": "Dettol", "size": "1L", "store": "Dis-Chem", "price": 59, "shipping": 5, "distance": 2, "rating": 4.6, "image_url": "/static/images/toiletries/hand_sanitizer_1l.jpg"},
    {"id": 88, "name": "Clere Body Lotion 250ml", "category": "personal_care", "item": "lotion", "brand": "Clere", "size": "250ml", "store": "Clicks", "price": 55, "shipping": 0, "distance": 1, "rating": 4.6, "image_url": "/static/images/personal_care/clere_body_lotion_250ml.jpg"},
    {"id": 89, "name": "Clere Body Lotion 500ml", "category": "personal_care", "item": "lotion", "brand": "Clere", "size": "500ml", "store": "Dis-Chem", "price": 85, "shipping": 5, "distance": 2, "rating": 4.7, "image_url": "/static/images/personal_care/clere_body_lotion_500ml.jpg"},
    {"id": 90, "name": "Nivea Body Lotion 250ml", "category": "personal_care", "item": "lotion", "brand": "Nivea", "size": "250ml", "store": "Clicks", "price": 69, "shipping": 5, "distance": 1, "rating": 4.7, "image_url": "/static/images/personal_care/nivea_body_lotion_250ml.jpg"},
    {"id": 91, "name": "Vaseline Body Lotion 250ml", "category": "personal_care", "item": "lotion", "brand": "Vaseline", "size": "250ml", "store": "Dis-Chem", "price": 59, "shipping": 0, "distance": 2, "rating": 4.6, "image_url": "/static/images/personal_care/vaseline_body_lotion_250ml.jpg"},
    {"id": 92, "name": "Pantene Shampoo", "category": "personal_care", "item": "shampoo", "brand": "Pantene", "store": "Clicks", "price": 69, "shipping": 10, "distance": 1, "rating": 4.5, "image_url": "/static/images/personal_care/pentene_shampoo.jpg"},
    {"id": 93, "name": "Tresemme Shampoo", "category": "personal_care", "item": "shampoo", "brand": "Tresemme", "store": "Dis-Chem", "price": 75, "shipping": 5, "distance": 2, "rating": 4.6, "image_url": "/static/images/personal_care/tresemme_shampoo.jpg"},
    {"id": 94, "name": "Dove Shampoo", "category": "personal_care", "item": "shampoo", "brand": "Dove", "store": "Clicks", "price": 65, "shipping": 0, "distance": 1, "rating": 4.5, "image_url": "/static/images/personal_care/dove_shampoo.jpg"},
    {"id": 95, "name": "Head & Shoulders Shampoo", "category": "personal_care", "item": "shampoo", "brand": "Head & Shoulders", "store": "Dis-Chem", "price": 79, "shipping": 0, "distance": 2, "rating": 4.7, "image_url": "/static/images/personal_care/head&shoulders_shampoo.jpg"},
    {"id": 96, "name": "Dove Deodorant Roll On", "category": "personal_care", "item": "deodorant", "brand": "Dove", "store": "Clicks", "price": 35, "shipping": 0, "distance": 1, "rating": 4.5, "image_url": "/static/images/personal_care/dove_deodorant_roll_on.jpg"},
    {"id": 97, "name": "Shield Deodorant Roll On", "category": "personal_care", "item": "deodorant", "brand": "Shield", "store": "Dis-Chem", "price": 32, "shipping": 0, "distance": 2, "rating": 4.4, "image_url": "/static/images/personal_care/shied_deodorant_roll_on.jpg"},
    {"id": 98, "name": "Skechers Sneakers", "category": "clothing", "item": "shoes", "brand": "Skechers", "size": "3", "colour": "Black", "store": "Edgars", "price": 399, "shipping": 0, "distance": 3, "rating": 4.7, "style": "Sporty", "image_url": "/static/images/clothing/skechers_sneakers.jpg"},
    {"id": 99, "name": "Nike Sneakers", "category": "clothing", "item": "shoes", "brand": "Nike", "size": "4", "colour": "White", "store": "SportScene", "price": 699, "shipping": 20, "distance": 5, "rating": 4.8, "style": "Sporty", "image_url": "/static/images/clothing/nike_sneakers.jpg"},
    {"id": 100, "name": "Adidas Sneakers", "category": "clothing", "item": "shoes", "brand": "Adidas", "size": "5", "colour": "Black", "store": "Edgars", "price": 599, "shipping": 20, "distance": 3, "rating": 4.7, "style": "Sporty", "image_url": "/static/images/clothing/Addidas_sneakers.jpg"},
    {"id": 121, "name": "Skechers Runner", "category": "clothing", "item": "shoes", "brand": "Skechers", "size": "6", "colour": "Grey", "store": "SportScene", "price": 449, "shipping": 10, "distance": 2, "rating": 4.8, "style": "Sporty", "image_url": "/static/images/clothing/skechers_runner.jpg"},
    {"id": 122, "name": "Nike Air Zoom", "category": "clothing", "item": "shoes", "brand": "Nike", "size": "7", "colour": "Red", "store": "Edgars", "price": 749, "shipping": 15, "distance": 4, "rating": 4.9, "style": "Sporty", "image_url": "/static/images/clothing/nike_air_zoom.jpg"},
    {"id": 123, "name": "Adidas Street", "category": "clothing", "item": "shoes", "brand": "Adidas", "size": "8", "colour": "White", "store": "Mr Price", "price": 549, "shipping": 10, "distance": 2, "rating": 4.6, "style": "Streetwear", "image_url": "/static/images/clothing/addidas_street.jpg"},
    {"id": 124, "name": "Puma Classic", "category": "clothing", "item": "shoes", "brand": "Puma", "size": "9", "colour": "Navy", "store": "SportScene", "price": 499, "shipping": 0, "distance": 3, "rating": 4.7, "style": "Sporty", "image_url": "/static/images/clothing/puma_classic.jpg"},
    {"id": 101, "name": "Student Jacket", "category": "clothing", "item": "jacket", "brand": "Urban Wear", "size": "M", "colour": "Black", "store": "Mr Price", "price": 399, "shipping": 20, "distance": 2, "rating": 4.5, "style": "Casual", "image_url": "/static/images/clothing/student_jacket.jpg"},
    {"id": 102, "name": "Student Hoodie", "category": "clothing", "item": "hoodie", "brand": "Urban Wear", "size": "L", "colour": "Grey", "store": "Jet", "price": 349, "shipping": 20, "distance": 3, "rating": 4.6, "style": "Streetwear", "image_url": "/static/images/clothing/student_hoodie.jpg"},
    {"id": 103, "name": "Basic T-Shirt", "category": "clothing", "item": "t-shirt", "brand": "Campus Fashion", "size": "M", "colour": "Black", "store": "Mr Price", "price": 149, "shipping": 20, "distance": 2, "rating": 4.4, "style": "Casual", "image_url": "/static/images/clothing/basic_T-shirt.jpg"},
    {"id": 104, "name": "Graphic T-Shirt", "category": "clothing", "item": "t-shirt", "brand": "Campus Fashion", "size": "L", "colour": "White", "store": "Jet", "price": 169, "shipping": 20, "distance": 3, "rating": 4.5, "style": "Streetwear", "image_url": "/static/images/clothing/graphic_T-shirt.jpg"},
    {"id": 105, "name": "Jeans", "category": "clothing", "item": "jeans", "brand": "Campus Fashion", "size": "32", "colour": "Blue", "store": "Edgars", "price": 299, "shipping": 20, "distance": 3, "rating": 4.5, "style": "Casual", "image_url": "/static/images/clothing/jeans.jpg"},
    {"id": 106, "name": "Slim Fit Jeans", "category": "clothing", "item": "jeans", "brand": "Campus Fashion", "size": "30", "colour": "Black", "store": "Mr Price", "price": 279, "shipping": 20, "distance": 2, "rating": 4.6, "style": "Trendy", "image_url": "/static/images/clothing/slim_fit_jeans.jpg"},
    {"id": 107, "name": "Student Dress", "category": "clothing", "item": "dress", "brand": "Urban Wear", "size": "M", "colour": "Pink", "store": "Jet", "price": 249, "shipping": 20, "distance": 3, "rating": 4.4, "style": "Trendy", "image_url": "/static/images/clothing/student_dress.jpg"},
    {"id": 108, "name": "Winter Scarf", "category": "clothing", "item": "scarf", "brand": "Urban Wear", "store": "Edgars", "price": 89, "shipping": 10, "distance": 3, "rating": 4.3, "style": "Smart", "image_url": "/static/images/clothing/winter_scarf.jpg"},
    {"id": 109, "name": "Casio Scientific Calculator", "category": "study_materials", "item": "calculator", "brand": "Casio", "store": "CNA", "price": 249, "shipping": 20, "distance": 4, "rating": 4.8, "image_url": "/static/images/study_meterials/casio_scientific_calculator.jpg"},
    {"id": 110, "name": "Sharp Scientific Calculator", "category": "study_materials", "item": "calculator", "brand": "Sharp", "store": "Edgars", "price": 229, "shipping": 10, "distance": 3, "rating": 4.7, "image_url": "/static/images/study_meterials/sharp_scientific_calculator.jpg"},
    {"id": 111, "name": "Exercise Book", "category": "study_materials", "item": "exercise book", "brand": "Student Choice", "size": "72 pages", "store": "CNA", "price": 15, "shipping": 0, "distance": 4, "rating": 4.5, "image_url": "/static/images/study_meterials/exercise_book.jpg"},
    {"id": 112, "name": "Exercise Book 96 pages", "category": "study_materials", "item": "exercise book", "brand": "Student Choice", "size": "96 pages", "store": "Mr Price Home", "price": 18, "shipping": 0, "distance": 2, "rating": 4.5, "image_url": "/static/images/study_meterials/exercise_book_96pages.jpg"},
    {"id": 113, "name": "A4 Student Notebook", "category": "study_materials", "item": "notebook", "brand": "Student Choice", "size": "A4", "store": "CNA", "price": 35, "shipping": 0, "distance": 4, "rating": 4.7, "image_url": "/static/images/study_meterials/A4_student_Notebook.jpg"},
    {"id": 114, "name": "Programming Textbook", "category": "study_materials", "item": "textbook", "brand": "DUT Bookshop", "store": "DUT Bookshop", "price": 450, "shipping": 30, "distance": 1, "rating": 4.8, "image_url": "/static/images/study_meterials/programming_textbook.jpg"},
    {"id": 115, "name": "Mathematics Textbook", "category": "study_materials", "item": "textbook", "brand": "DUT Bookshop", "store": "DUT Bookshop", "price": 380, "shipping": 30, "distance": 1, "rating": 4.7, "image_url": "/static/images/study_meterials/mathematics_textbook.jpg"},
    {"id": 116, "name": "Pack of Student Pens", "category": "study_materials", "item": "pens", "brand": "Student Choice", "size": "Pack", "store": "CNA", "price": 25, "shipping": 0, "distance": 4, "rating": 4.5, "image_url": "/static/images/study_meterials/pack_of_students_pens.jpg"},
    {"id": 117, "name": "Highlighters Set", "category": "study_materials", "item": "pens", "brand": "Student Choice", "size": "6 Pack", "store": "Edgars", "price": 35, "shipping": 0, "distance": 3, "rating": 4.6, "image_url": "/static/images/study_meterials/highlighters_set.jpg"},
    {"id": 118, "name": "Geometry Set", "category": "study_materials", "item": "geometry", "brand": "Student Choice", "store": "CNA", "price": 45, "shipping": 5, "distance": 4, "rating": 4.4, "image_url": "/static/images/study_meterials/geometry_set.jpg"},
    {"id": 119, "name": "Student Backpack", "category": "study_materials", "item": "bag", "brand": "Student Choice", "store": "Mr Price", "price": 199, "shipping": 20, "distance": 2, "rating": 4.6, "image_url": "/static/images/study_meterials/student_backpack.jpg"},
    {"id": 120, "name": "Laptop Bag", "category": "study_materials", "item": "bag", "brand": "Student Choice", "store": "Edgars", "price": 249, "shipping": 20, "distance": 3, "rating": 4.7, "image_url": "/static/images/study_meterials/laptop_bag.jpg"},
]



STUDENT_CATEGORIES = [
    {"key": "food", "name": "Food", "emoji": "🍎", "description": "Rice, bread, oil and more",
     "image_url": "images/food.jpg"},
    {"key": "toiletries", "name": "Toiletries", "emoji": "🧻", "description": "Soap, toothpaste and more",
     "image_url": "images/toiletries.jpg"},
    {"key": "personal_care", "name": "Personal Care", "emoji": "🧴", "description": "Lotion, shampoo and more",
     "image_url": "images/personal_care.jpg"},
    {"key": "clothing", "name": "Clothing", "emoji": "👕", "description": "Shoes, jackets and clothes",
     "image_url": "images/clothing.jpg"},
    {"key": "study_materials", "name": "Study Materials", "emoji": "📚", "description": "Calculators and exercise books",
     "image_url": "images/study_materials.jpg"},
]



KNOWN_ITEMS = {
    "food": ["rice", "bread", "oil", "maize meal", "milk", "sugar", "chicken",
             "beef", "pork", "lamb", "tomatoes", "potatoes", "onions",
             "cabbage", "spinach", "carrots", "broccoli", "cauliflower",
             "bananas", "apples", "oranges", "grapes", "strawberries",
             "eggs", "cheese", "butter", "flour", "tinned", "pasta"],
    "toiletries": ["soap", "toothpaste", "toilet paper", "washing powder",
                   "dishwashing", "sanitizer"],
    "personal_care": ["lotion", "shampoo", "deodorant"],
    "clothing": ["shoes", "jacket", "hoodie", "t-shirt", "jeans", "dress", "scarf"],
    "study_materials": ["calculator", "exercise book", "notebook", "textbook",
                        "pens", "geometry", "bag"],
}

VARIANT_WORDS = ["white", "brown", "whole wheat", "low fat", "full cream", "skim"]


def get_budget_list():
    return session.get("budget_list", [])


def get_budget_list_details():
    budget_ids = get_budget_list()
    budget_products = [product for product in PRODUCTS if product["id"] in budget_ids]
    total_cost = 0
    for product in budget_products:
        distance = get_shop_distance(product.get("store", ""), "steve_biko")
        fee = get_distance_fee(25, distance)
        shipping = fee if fee > 0 else product.get("shipping", 0)
        total_cost += product["price"] + shipping
    return budget_products, total_cost



INITIAL_PRODUCTS = list(PRODUCTS)


def seed_products_if_empty():
    connection = get_db()
    count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    if count == 0:
        for p in INITIAL_PRODUCTS:
            connection.execute(
                """INSERT INTO products
                   (id, name, category, item, brand, size, store,
                    price, shipping, distance, rating, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["id"], p["name"], p["category"], p["item"],
                    p.get("brand", ""), p.get("size", ""), p.get("store", ""),
                    p["price"], p.get("shipping", 0), p.get("distance", 0),
                    p.get("rating", 0), p.get("image_url", "")
                )
            )
        connection.commit()
        print(f"✅ Seeded {len(INITIAL_PRODUCTS)} products into the database.")

    connection.close()


def load_products_from_db():
    global PRODUCTS
    connection = get_db()
    rows = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
    connection.close()
    PRODUCTS = [dict(row) for row in rows]


def save_product_to_db(product):
    connection = get_db()
    connection.execute(
        """INSERT OR REPLACE INTO products
           (id, name, category, item, brand, size, store,
            price, shipping, distance, rating, image_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product["id"], product["name"], product["category"], product["item"],
            product.get("brand", ""), product.get("size", ""), product.get("store", ""),
            product["price"], product.get("shipping", 0), product.get("distance", 0),
            product.get("rating", 0), product.get("image_url", "")
        )
    )
    connection.commit()
    connection.close()


def delete_product_from_db(product_id):
    connection = get_db()
    connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
    connection.commit()
    connection.close()



def init_db():
    connection = get_db()
    connection.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, surname TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, budget REAL DEFAULT 0, role TEXT DEFAULT 'student', colour TEXT DEFAULT 'Any', style TEXT DEFAULT '', preferred_brands TEXT DEFAULT '', preferred_colours TEXT DEFAULT '', preferred_stores TEXT DEFAULT '', hobbies TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, query TEXT, budget REAL, colour TEXT, product_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS shopping_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, product_id INTEGER NOT NULL, product_name TEXT NOT NULL, price REAL NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS product_status (product_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'In Stock', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS stock_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, product_id INTEGER NOT NULL, product_name TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))""")

    connection.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT,
        item TEXT,
        brand TEXT,
        size TEXT,
        store TEXT,
        price REAL NOT NULL,
        shipping REAL DEFAULT 0,
        distance REAL DEFAULT 0,
        rating REAL DEFAULT 0,
        image_url TEXT
    )""")

    connection.execute("""CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL UNIQUE,
        discount_percent REAL NOT NULL,
        starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ends_at TIMESTAMP,
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    )""")

    connection.commit()
    connection.close()
    print("Database initialized successfully.")

    connection = get_db()
    existing = connection.execute("SELECT product_id FROM product_status WHERE product_id = 6").fetchone()
    if not existing:
        connection.execute(
            "INSERT INTO product_status (product_id, status) VALUES (?, 'Out of Stock')",
            (6,)
        )
        connection.commit()
        print("Seeded: Sasko White Bread Loaf (ID 6) set to Out of Stock.")
    connection.close()



STATUS_OPTIONS = ["In Stock", "Low Stock", "Out of Stock"]


def get_product_statuses():
    connection = get_db()
    rows = connection.execute("SELECT product_id, status FROM product_status").fetchall()
    connection.close()
    return {row["product_id"]: row["status"] for row in rows}



def get_active_sales():
    connection = get_db()
    rows = connection.execute(
        """SELECT product_id, discount_percent, ends_at
           FROM sales
           WHERE (ends_at IS NULL OR datetime(ends_at) >= datetime('now'))"""
    ).fetchall()
    connection.close()
    return {
        row["product_id"]: {
            "discount_percent": float(row["discount_percent"] or 0),
            "ends_at": row["ends_at"],
        }
        for row in rows
    }


def apply_sale(product, active_sales=None):
    if active_sales is None:
        active_sales = get_active_sales()

    enriched = dict(product)
    sale = active_sales.get(product["id"])

    if not sale or sale["discount_percent"] <= 0:
        enriched["original_price"] = product["price"]
        enriched["on_sale"] = False
        enriched["sale_percent"] = 0
        enriched["sale_ends_at"] = None
        return enriched

    discount = sale["discount_percent"]
    new_price = round(product["price"] * (1 - discount / 100), 2)

    enriched["original_price"] = product["price"]
    enriched["price"] = new_price
    enriched["on_sale"] = True
    enriched["sale_percent"] = discount
    enriched["sale_ends_at"] = sale["ends_at"]
    return enriched


def pick_in_stock_alternative(out_product, pool, budget=0):
    def total(p):
        return p["price"] + p.get("shipping", 0)

    candidates = [p for p in pool
                  if p["id"] != out_product["id"] and p.get("item") == out_product.get("item")]
    if not candidates:
        return None
    if budget > 0:
        affordable = [p for p in candidates if total(p) <= budget]
        if affordable:
            candidates = affordable

    candidates.sort(key=lambda p: (
        p.get("size") != out_product.get("size"),
        p.get("brand") != out_product.get("brand"),
        total(p),
    ))
    return candidates[0]


def record_stock_alert(user_id, product_id, product_name):
    connection = get_db()
    existing = connection.execute(
        "SELECT id FROM stock_alerts WHERE user_id = ? AND product_id = ? AND status = 'pending' LIMIT 1",
        (user_id, product_id)
    ).fetchone()
    if not existing:
        connection.execute(
            "INSERT INTO stock_alerts (user_id, product_id, product_name) VALUES (?, ?, ?)",
            (user_id, product_id, product_name)
        )
        connection.commit()
    connection.close()


def count_back_in_stock(user_id):
    if not user_id:
        return 0
    connection = get_db()
    count = connection.execute(
        "SELECT COUNT(*) FROM stock_alerts WHERE user_id = ? AND status = 'ready'",
        (user_id,)
    ).fetchone()[0] or 0
    connection.close()
    return count


def flash_out_of_stock(names, alternative):
    names = list(dict.fromkeys(names))
    verb = "is" if len(names) == 1 else "are"
    flash(f"⚠️ {', '.join(names)} {verb} currently out of stock.", "danger")
    if alternative:
        alt_total = alternative["price"] + alternative.get("shipping", 0)
        flash(f"💡 We recommend {alternative['name']} at {alternative['store']} "
              f"for R{alt_total:.2f} instead. It is in stock.", "danger")
    else:
        flash("We have no similar products in stock right now. Please check back later.", "danger")


def get_favourites():
    favourites = session.get("favourites", [])
    cleaned_favourites = []
    for product_id in favourites:
        try:
            product_id = int(product_id)
            if product_id not in cleaned_favourites:
                cleaned_favourites.append(product_id)
        except (ValueError, TypeError):
            pass
    return cleaned_favourites



def get_real_image_url(product):
    local_url = product.get("image_url", "")
    if local_url:
        if local_url.startswith("/static/"):
            disk_path = os.path.join(BASE_DIR, local_url.lstrip("/"))
            if os.path.exists(disk_path):
                return local_url
        else:
            return local_url

    keyword = (
        product.get("item")
        or product.get("category")
        or product.get("name", "product")
    ).replace(" ", "+")

    return f"https://loremflickr.com/400/400/{keyword}"



def build_basket(max_amount, area_key=None, max_items=40):
    if max_amount <= 0:
        return {
            "basket_items": [],
            "grouped_stores": [],
            "total": 0.0,
            "product_total": 0.0,
            "travel_fee": 0.0,
            "stores": [],
            "remaining": max_amount,
            "budget": max_amount,
            "area": area_key,
        }

    statuses = get_product_statuses()
    active_sales = get_active_sales()

    candidates = []
    for p in PRODUCTS:
        if statuses.get(p["id"], "In Stock") == "Out of Stock":
            continue

        enriched = enrich_product(
            p,
            budget=max_amount,
            radius=25,
            active_sales=active_sales,
        )

        # Product price alone must fit in the budget
        if enriched["price"] > max_amount:
            continue

        enriched["status"] = statuses.get(p["id"], "In Stock")
        enriched["image_url"] = get_real_image_url(p)
        candidates.append(enriched)

    if not candidates:
        return {
            "basket_items": [],
            "grouped_stores": [],
            "total": 0.0,
            "product_total": 0.0,
            "travel_fee": 0.0,
            "stores": [],
            "remaining": max_amount,
            "budget": max_amount,
            "area": area_key,
        }

    candidates.sort(key=lambda x: x["price"])

    # Pass 1 — one item per item-type for diversity
    basket = []
    used_item_types = set()

    for p in candidates:
        if len(basket) >= max_items:
            break
        item_key = (p.get("item") or p.get("name") or "").strip().lower()
        if item_key in used_item_types:
            continue
        basket.append(p)
        used_item_types.add(item_key)

    # Pass 2 — fill remaining slots (allow multiple from same type now)
    while len(basket) < max_items:
        added = False
        for p in candidates:
            if p in basket:
                continue
            basket.append(p)
            added = True
            break
        if not added:
            break

    # Helper — compute totals (products + travel per store)
    def calculate_totals(items):
        product_total = sum(p["price"] for p in items)

        store_distances = {}
        for p in items:
            store = p.get("store", "")
            if store not in store_distances:
                store_distances[store] = get_shop_distance(store, area_key)

        travel_fee = 0
        for store, distance in store_distances.items():
            if distance > FREE_DISTANCE_KM:
                travel_fee += get_distance_fee(25, distance)

        return product_total, travel_fee, store_distances

    # Trim until products + travel fits inside budget
    while basket:
        product_total, travel_fee, store_distances = calculate_totals(basket)
        if product_total + travel_fee <= max_amount:
            break
        basket.sort(key=lambda x: x["price"])
        basket.pop()

    product_total, travel_fee, store_distances = calculate_totals(basket)
    grand_total = product_total + travel_fee
    remaining = round(max_amount - grand_total, 2)

    # Group items by store
    grouped = {}
    for p in basket:
        store = p.get("store", "")
        distance = store_distances.get(store, 5)
        fee = 0 if distance <= FREE_DISTANCE_KM else get_distance_fee(25, distance)

        if store not in grouped:
            grouped[store] = {
                "store": store,
                "distance": distance,
                "fee": fee,
                "items": [],
            }

        p["distance"] = distance
        grouped[store]["items"].append(p)

    grouped_stores = sorted(grouped.values(), key=lambda s: s["distance"])

    for g in grouped_stores:
        g["items"].sort(key=lambda x: x["price"])

    return {
        "basket_items": basket,
        "grouped_stores": grouped_stores,
        "total": round(grand_total, 2),
        "product_total": round(product_total, 2),
        "travel_fee": round(travel_fee, 2),
        "stores": [(g["store"], g["distance"]) for g in grouped_stores],
        "remaining": remaining,
        "budget": max_amount,
        "area": area_key,
    }


@app.context_processor
def inject_favourites_count():
    if "user_id" in session:
        return {
            "favourites_count": len(get_favourites()),
            "back_in_stock_count": count_back_in_stock(session["user_id"]),
        }
    return {"favourites_count": 0, "back_in_stock_count": 0}



def login_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login", next=request.path if request.method == "GET" else None))
        return function(*args, **kwargs)
    return decorated_function


def admin_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login", next=request.path if request.method == "GET" else None))
        connection = get_db()
        user = connection.execute("SELECT role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        connection.close()
        if not user or user["role"] != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return function(*args, **kwargs)
    return decorated_function


def store_manager_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login", next=request.path if request.method == "GET" else None))
        connection = get_db()
        user = connection.execute("SELECT role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        connection.close()
        if not user or user["role"] != "store_manager":
            flash("Only Store Managers can manage products.", "danger")
            if user and user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("dashboard"))
        return function(*args, **kwargs)
    return decorated_function



@app.route("/")
def home():
    return render_template("landing.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    surname = request.form.get("surname", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "student").strip()

    if not name or not surname or not email or not password:
        flash("Please complete all required fields.", "danger")
        return redirect(url_for("register"))

    if len(name) < 2 or len(name) > 50:
        flash("Name must be between 2 and 50 characters.", "danger")
        return redirect(url_for("register"))

    if len(surname) < 2 or len(surname) > 50:
        flash("Surname must be between 2 and 50 characters.", "danger")
        return redirect(url_for("register"))

    allowed_name_chars = set("abcdefghijklmnopqrstuvwxyz"
                             "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                             " -'")
    if not all(ch in allowed_name_chars for ch in name):
        flash("Name can only contain letters, spaces, hyphens and apostrophes.", "danger")
        return redirect(url_for("register"))

    if not all(ch in allowed_name_chars for ch in surname):
        flash("Surname can only contain letters, spaces, hyphens and apostrophes.", "danger")
        return redirect(url_for("register"))

    if len(email) > 100:
        flash("Email is too long (max 100 characters).", "danger")
        return redirect(url_for("register"))

    if email.count("@") != 1:
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("register"))

    local_part, domain_part = email.split("@")

    if not local_part:
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("register"))

    if "." not in domain_part:
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("register"))

    if domain_part.startswith(".") or domain_part.endswith("."):
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("register"))

    if len(domain_part.split(".")[-1]) < 2:
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("register"))

    if len(password) < 8:
        flash("Password must be at least 8 characters.", "danger")
        return redirect(url_for("register"))

    if len(password) > 100:
        flash("Password is too long (max 100 characters).", "danger")
        return redirect(url_for("register"))

    if not any(ch.isdigit() for ch in password):
        flash("Password must contain at least one number.", "danger")
        return redirect(url_for("register"))

    if not any(ch.isalpha() for ch in password):
        flash("Password must contain at least one letter.", "danger")
        return redirect(url_for("register"))

    valid_roles = ["student", "admin", "store_manager"]
    if role not in valid_roles:
        flash("Invalid account type.", "danger")
        return redirect(url_for("register"))

    if request.form.get("accept_terms") != "yes":
        flash("You must accept the Terms & Conditions to register.", "danger")
        return redirect(url_for("register"))

    if role == "admin":
        provided_code = request.form.get("admin_code", "").strip()
        if provided_code != ADMIN_INVITE_CODE:
            flash("Invalid admin invite code. Please try again.", "danger")
            return redirect(url_for("register"))

    budget = 0

    connection = get_db()
    existing_user = connection.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    if existing_user:
        connection.close()
        flash("This email is already registered. Please login.", "danger")
        return redirect(url_for("login"))

    connection.execute(
        "INSERT INTO users (name, surname, email, password, budget, role) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, surname, email, generate_password_hash(password), budget, role)
    )
    connection.commit()
    connection.close()

    flash("Registration successful! Please login.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    rate_key = f"{email}|{request.remote_addr}"
    if is_rate_limited(rate_key, max_attempts=5, window_seconds=300):
        flash("Too many failed login attempts. Please wait 5 minutes.", "danger")
        return redirect(url_for("login"))

    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    connection.close()

    if user and check_password_hash(user["password"], password):
        login_attempts.pop(rate_key, None)

        session.clear()

        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["surname"] = user["surname"]
        session["email"] = user["email"]
        session["role"] = user["role"]
        session.setdefault("favourites", [])
        session.setdefault("budget_list", [])
        session.permanent = True

        flash("Login successful!", "success")

        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)

        if user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        elif user["role"] == "store_manager":
            return redirect(url_for("store_dashboard"))
        else:
            return redirect(url_for("dashboard"))

    record_attempt(rate_key)
    flash("Incorrect email or password.", "danger")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))



@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "store_manager":
        return redirect(url_for("store_dashboard"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    selected_category = request.args.get("category", "").strip()

    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    search_history = connection.execute(
        "SELECT * FROM search_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (session["user_id"],)
    ).fetchall()
    purchase_history = connection.execute(
        "SELECT * FROM shopping_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (session["user_id"],)
    ).fetchall()
    total_spent = connection.execute(
        "SELECT SUM(price) FROM shopping_history WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0] or 0
    connection.close()

    total_budget = user["budget"]
    remaining_budget = total_budget - total_spent

    low_budget = False
    if total_budget > 0 and remaining_budget <= total_budget * 0.15:
        low_budget = True

    connection = get_db()
    back_in_stock_alerts = connection.execute(
        "SELECT * FROM stock_alerts WHERE user_id = ? AND status = 'ready' ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()
    connection.close()

    return render_template(
        "dashboard.html",
        user=user,
        history=purchase_history,
        search_history=search_history,
        products=get_unique_products(),
        categories=STUDENT_CATEGORIES,
        areas=AREAS,
        total_spent=total_spent,
        remaining_budget=remaining_budget,
        total_savings=max(0, remaining_budget),
        cart_count=len(get_budget_list()),
        low_budget=low_budget,
        selected_category=selected_category,
        back_in_stock_alerts=back_in_stock_alerts,
    )



@app.route("/affordable-products")
@login_required
def affordable_products():
    budget_arg = request.args.get("budget", "").strip()
    area_key = request.args.get("area", "").strip()

    if budget_arg:
        try:
            budget = float(budget_arg)
        except (ValueError, TypeError):
            budget = 0
    else:
        connection = get_db()
        user_row = connection.execute(
            "SELECT budget FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        connection.close()
        budget = user_row["budget"] if user_row else 0

    if budget <= 0:
        flash("Please enter a budget greater than zero.", "warning")
        return redirect(url_for("dashboard"))

    connection = get_db()
    connection.execute(
        "UPDATE users SET budget = ? WHERE id = ?",
        (budget, session["user_id"])
    )
    connection.commit()
    connection.close()

    basket = build_basket(budget, area_key=area_key)

    friendly_area = "your area"
    for a in AREAS:
        if a["key"] == area_key:
            friendly_area = a["name"]
            break

    if basket["basket_items"]:
        item_count = len(basket["basket_items"])
        store_count = len(basket["grouped_stores"])
        recommendation_message = (
            f"✅ With R{budget:.2f} near {friendly_area} you can get these "
            f"{item_count} item{'s' if item_count != 1 else ''} "
            f"from {store_count} mall{'s' if store_count != 1 else ''}. "
            f"Products: R{basket['product_total']:.2f}. "
            f"Travel: R{basket['travel_fee']:.2f}. "
            f"Total: R{basket['total']:.2f}."
        )
    else:
        recommendation_message = (
            f"❌ Nothing in the catalogue fits inside R{budget:.2f} near "
            f"{friendly_area}. Try increasing your budget."
        )

    return render_template(
        "affordable_basket.html",
        basket=basket,
        budget=budget,
        area=area_key,
        area_name=friendly_area,
        recommendation_message=recommendation_message,
        cart_count=len(get_budget_list())
    )


@app.route("/affordable-products/accept", methods=["POST"])
@login_required
def accept_affordable_basket():
    budget_arg = request.form.get("budget", "").strip()
    area_key = request.form.get("area", "").strip()

    try:
        budget = float(budget_arg)
    except (ValueError, TypeError):
        budget = 0

    if budget <= 0:
        flash("Invalid budget.", "danger")
        return redirect(url_for("dashboard"))

    basket = build_basket(budget, area_key=area_key)

    if not basket["basket_items"]:
        flash("Nothing to add — the basket is empty.", "warning")
        return redirect(url_for("affordable_products", budget=budget, area=area_key))

    connection = get_db()
    saved = 0
    skipped = 0

    for product in basket["basket_items"]:
        existing = connection.execute(
            "SELECT id FROM shopping_history WHERE user_id = ? AND product_name = ? LIMIT 1",
            (session["user_id"], product["name"])
        ).fetchone()

        if existing:
            skipped += 1
            continue

        connection.execute(
            "INSERT INTO shopping_history (user_id, product_id, product_name, price) "
            "VALUES (?, ?, ?, ?)",
            (session["user_id"], product["id"], product["name"], product["price"])
        )
        saved += 1

    # Add the travel fee as a single line item
    if basket["travel_fee"] > 0:
        connection.execute(
            "INSERT INTO shopping_history (user_id, product_id, product_name, price) "
            "VALUES (?, ?, ?, ?)",
            (session["user_id"], 0, "Travel (malls visit)", basket["travel_fee"])
        )

    connection.commit()
    connection.close()

    if saved and skipped:
        flash(f"✅ Added {saved} items to your budget plan. {skipped} were already there.", "success")
    elif saved:
        flash(f"✅ Added {saved} items to your budget plan.", "success")
    else:
        flash("All items were already in your budget plan.", "info")

    return redirect(url_for("history"))



@app.route("/spending-insights")
@login_required
def spending_insights():
    if session.get("role") == "store_manager":
        return redirect(url_for("store_dashboard"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    connection = get_db()
    rows = connection.execute(
        """SELECT sh.product_id, sh.price
           FROM shopping_history sh
           WHERE sh.user_id = ?""",
        (session["user_id"],)
    ).fetchall()

    category_totals = {
        "food": 0,
        "toiletries": 0,
        "personal_care": 0,
        "clothing": 0,
        "study_materials": 0,
    }

    for row in rows:
        pid = row["product_id"]
        price = float(row["price"] or 0)
        product = next((p for p in PRODUCTS if p["id"] == pid), None)
        if product:
            cat = product.get("category", "")
            if cat in category_totals:
                category_totals[cat] += price

    connection.close()

    return render_template(
        "spending_insights.html",
        category_labels=["Food", "Toiletries", "Personal Care", "Clothing", "Study Materials"],
        category_values=[
            round(category_totals["food"], 2),
            round(category_totals["toiletries"], 2),
            round(category_totals["personal_care"], 2),
            round(category_totals["clothing"], 2),
            round(category_totals["study_materials"], 2),
        ],
        cart_count=len(get_budget_list()),
    )


@app.route("/update-budget", methods=["POST"])
@login_required
def update_budget():
    new_budget = request.form.get("budget", "").strip()
    try:
        new_budget = float(new_budget)
        if new_budget <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Please enter a valid positive budget.", "danger")
        return redirect(url_for("dashboard"))
    connection = get_db()
    connection.execute("UPDATE users SET budget = ? WHERE id = ?", (new_budget, session["user_id"]))
    connection.commit()
    connection.close()
    flash(f"Your monthly budget has been updated to R{new_budget:.2f}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/clear-budget-plan", methods=["POST"])
@login_required
def clear_budget_plan():
    connection = get_db()
    connection.execute("DELETE FROM shopping_history WHERE user_id = ?", (session["user_id"],))
    connection.commit()
    connection.close()
    flash("Your budget plan has been cleared.", "success")
    return redirect(url_for("dashboard"))


@app.route("/clear-search-history", methods=["POST"])
@login_required
def clear_search_history():
    connection = get_db()
    connection.execute("DELETE FROM search_history WHERE user_id = ?", (session["user_id"],))
    connection.commit()
    connection.close()
    flash("Your recent searches have been cleared.", "success")
    return redirect(url_for("dashboard"))


@app.route("/dismiss-stock-alerts", methods=["POST"])
@login_required
def dismiss_stock_alerts():
    connection = get_db()
    connection.execute(
        "UPDATE stock_alerts SET status = 'seen' WHERE user_id = ? AND status = 'ready'",
        (session["user_id"],)
    )
    connection.commit()
    connection.close()
    return redirect(url_for("dashboard"))



@app.route("/store-dashboard")
@login_required
@store_manager_required
def store_dashboard():
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close()
    all_products = PRODUCTS
    total_products = len(all_products)
    avg_rating = sum(p["rating"] for p in all_products) / total_products if total_products > 0 else 0
    return render_template(
        "store_dashboard.html",
        user=user,
        total_products=total_products,
        avg_rating=avg_rating,
        cart_count=0
    )


@app.route("/store/inventory")
@login_required
@store_manager_required
def store_inventory():
    statuses = get_product_statuses()
    all_products = [dict(p, status=statuses.get(p["id"], "In Stock")) for p in PRODUCTS]
    total_products = len(all_products)
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close()
    return render_template("store_inventory.html", user=user, products=all_products, total_products=total_products, status_options=STATUS_OPTIONS, cart_count=0)


@app.route("/store/update-status/<int:product_id>", methods=["POST"])
@login_required
@store_manager_required
def update_product_status(product_id):
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if product is None:
        flash("Product not found.", "danger")
        return redirect(url_for("store_inventory"))
    new_status = request.form.get("status", "").strip()
    if new_status not in STATUS_OPTIONS:
        flash("Invalid status.", "danger")
        return redirect(url_for("store_inventory"))
    connection = get_db()
    connection.execute(
        "INSERT OR REPLACE INTO product_status (product_id, status, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (product_id, new_status)
    )
    if new_status == "In Stock":
        connection.execute(
            "UPDATE stock_alerts SET status = 'ready' WHERE product_id = ? AND status = 'pending'",
            (product_id,)
        )
    connection.commit()
    connection.close()
    flash(f"{product['name']} status updated to {new_status}.", "success")
    return redirect(url_for("store_inventory"))


@app.route("/store/quality")
@login_required
@store_manager_required
def store_quality():
    all_products = PRODUCTS
    low_rated = sorted([p for p in all_products if p.get("rating", 0) < 4.3], key=lambda p: p["rating"])
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close()
    return render_template("store_quality.html", user=user, low_rated=low_rated, total_low=len(low_rated), cart_count=0)


@app.route("/store/insights")
@login_required
@store_manager_required
def store_insights():
    all_products = PRODUCTS
    total_products = len(all_products)
    category_counts = Counter(p["category"] for p in all_products)
    category_data = [
        {"name": cat.replace("_", " ").title(), "count": count, "pct": round(count / total_products * 100, 1) if total_products > 0 else 0}
        for cat, count in category_counts.items()
    ]
    category_data.sort(key=lambda x: x["count"], reverse=True)
    category_prices = {}
    for p in all_products:
        category_prices.setdefault(p["category"], []).append(p["price"])
    avg_price_data = [{"name": cat.replace("_", " ").title(), "avg": sum(vals) / len(vals)} for cat, vals in category_prices.items()]
    avg_price_data.sort(key=lambda x: x["avg"], reverse=True)
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close()
    return render_template("store_insights.html", user=user, total_products=total_products, category_data=category_data, avg_price_data=avg_price_data, cart_count=0)



@app.route("/store/sales")
@login_required
@store_manager_required
def store_sales():
    connection = get_db()
    user = connection.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    connection.close()

    active_sales = get_active_sales()

    products_with_sales = []
    for p in PRODUCTS:
        sale = active_sales.get(p["id"])
        on_sale = bool(sale)
        sale_price = (
            round(p["price"] * (1 - sale["discount_percent"] / 100), 2)
            if on_sale else None
        )
        products_with_sales.append({
            **p,
            "on_sale": on_sale,
            "discount_percent": sale["discount_percent"] if on_sale else 0,
            "sale_price": sale_price,
            "sale_ends_at": sale["ends_at"] if on_sale else None,
        })

    return render_template(
        "store_sales.html",
        user=user,
        products=products_with_sales,
        cart_count=0,
    )


@app.route("/store/sales/set/<int:product_id>", methods=["POST"])
@login_required
@store_manager_required
def store_set_sale(product_id):
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("store_sales"))

    discount_str = request.form.get("discount_percent", "").strip()
    ends_at = request.form.get("ends_at", "").strip() or None

    try:
        discount = float(discount_str)
    except (ValueError, TypeError):
        flash("Please enter a valid discount percentage.", "danger")
        return redirect(url_for("store_sales"))

    if discount <= 0 or discount >= 100:
        flash("Discount must be between 1 and 99.", "danger")
        return redirect(url_for("store_sales"))

    connection = get_db()
    connection.execute("DELETE FROM sales WHERE product_id = ?", (product_id,))
    connection.execute(
        """INSERT INTO sales (product_id, discount_percent, ends_at, created_by)
           VALUES (?, ?, ?, ?)""",
        (product_id, discount, ends_at, session["user_id"])
    )
    connection.commit()
    connection.close()

    flash(f"✅ {product['name']} is now {discount:.0f}% off.", "success")
    return redirect(url_for("store_sales"))


@app.route("/store/sales/remove/<int:product_id>", methods=["POST"])
@login_required
@store_manager_required
def store_remove_sale(product_id):
    connection = get_db()
    connection.execute("DELETE FROM sales WHERE product_id = ?", (product_id,))
    connection.commit()
    connection.close()
    flash("Sale removed.", "success")
    return redirect(url_for("store_sales"))



@app.route("/admin/view-products")
@login_required
@admin_required
def admin_view_products():
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close()

    active_sales = get_active_sales()
    statuses = get_product_statuses()

    all_products = []
    for p in PRODUCTS:
        sale = active_sales.get(p["id"])
        on_sale = bool(sale)
        sale_price = (
            round(p["price"] * (1 - sale["discount_percent"] / 100), 2)
            if on_sale else None
        )
        all_products.append({
            **p,
            "status": statuses.get(p["id"], "In Stock"),
            "on_sale": on_sale,
            "discount_percent": sale["discount_percent"] if on_sale else 0,
            "sale_price": sale_price,
            "sale_ends_at": sale["ends_at"] if on_sale else None,
        })

    total_products = len(all_products)
    avg_rating = sum(p["rating"] for p in all_products) / total_products if total_products > 0 else 0
    low_rated = sorted([p for p in all_products if p.get("rating", 0) < 4.3], key=lambda p: p["rating"])[:5]
    category_counts = Counter(p["category"] for p in all_products)
    category_data = [
        {"name": cat.replace("_", " ").title(), "count": count, "pct": round(count / total_products * 100, 1) if total_products > 0 else 0}
        for cat, count in category_counts.items()
    ]
    category_data.sort(key=lambda x: x["count"], reverse=True)
    category_prices = {}
    for p in all_products:
        category_prices.setdefault(p["category"], []).append(p["price"])
    avg_price_data = [{"name": cat.replace("_", " ").title(), "avg": sum(vals) / len(vals)} for cat, vals in category_prices.items()]
    avg_price_data.sort(key=lambda x: x["avg"], reverse=True)

    return render_template(
        "admin_view_products.html",
        user=user,
        products=all_products,
        total_products=total_products,
        avg_rating=avg_rating,
        low_rated=low_rated,
        category_data=category_data,
        avg_price_data=avg_price_data,
        cart_count=0
    )



@app.route("/compare")
@login_required
def compare():
    selected_item = request.args.get("item", "").strip().lower()
    item_types = {}
    for p in PRODUCTS:
        key = p.get("item", "other")
        if key not in item_types:
            item_types[key] = {"key": key, "label": key.title(), "image_url": "", "category": p.get("category", "")}
        if not item_types[key]["image_url"] and p.get("image_url"):
            item_types[key]["image_url"] = p["image_url"]
    item_types = dict(sorted(item_types.items(), key=lambda x: x[1]["label"]))
    matching_products = [p for p in PRODUCTS if p.get("item", "").lower() == selected_item] if selected_item else []
    ids_param = request.args.get("ids", "")
    product_ids = [int(c.strip()) for c in ids_param.split(",") if c.strip().isdigit()][:3]
    selected = [p for p in matching_products if p["id"] in product_ids]
    highlights = {}
    if len(selected) >= 2:
        prices = [p["price"] + p.get("shipping", 0) for p in selected]
        highlights["cheapest_index"] = prices.index(min(prices))
        highlights["cheapest_total"] = min(prices)
        highlights["most_expensive_total"] = max(prices)
        highlights["best_rating_index"] = max(range(len(selected)), key=lambda i: selected[i].get("rating", 0))
        highlights["closest_index"] = min(range(len(selected)), key=lambda i: selected[i].get("distance", 999))
        highlights["max_savings"] = max(prices) - min(prices)
    return render_template("compare.html", item_types=item_types, selected_item=selected_item, matching_products=matching_products, products=selected, highlights=highlights, cart_count=len(get_budget_list()))



@app.route("/download-budget-pdf")
@login_required
def download_budget_pdf():
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    history_items = connection.execute("SELECT product_id, product_name, price, created_at FROM shopping_history WHERE user_id = ? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    total_spent = connection.execute("SELECT SUM(price) FROM shopping_history WHERE user_id = ?", (session["user_id"],)).fetchone()[0] or 0
    connection.close()
    if not history_items:
        flash("Your budget plan is empty. Add some items first.", "warning")
        return redirect(url_for("dashboard"))
    remaining = user["budget"] - total_spent
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="SmartSpend - Budget Plan", author="SmartSpend AI")
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle("CustomTitle", parent=styles["Heading1"], fontSize=22, textColor=colors.HexColor("#1a73e8"), spaceAfter=6)
    subtitle_style = ParagraphStyle("CustomSubtitle", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#666666"), spaceAfter=20)
    section_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#333333"), spaceBefore=12, spaceAfter=8)
    story.append(Paragraph("SmartSpend AI - Budget Plan", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%d %B %Y at %H:%M')}", subtitle_style))
    story.append(Paragraph("Student Information", section_style))
    user_data = [["Name", f"{user['name']} {user['surname']}"], ["Email", user["email"]], ["Monthly Budget", f"R{user['budget']:.2f}"], ["Total Spent", f"R{total_spent:.2f}"], ["Remaining Budget", f"R{remaining:.2f}"]]
    user_table = Table(user_data, colWidths=[5 * cm, 12 * cm])
    user_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef5ff")), ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a73e8")), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0"))]))
    story.append(user_table)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Your Budget Plan Items", section_style))
    table_data = [["#", "Product", "Amount", "Date Added"]]
    for i, item in enumerate(history_items, 1):
        table_data.append([str(i), item["product_name"], f"R{item['price']:.2f}", format_datetime(item["created_at"])])
    table_data.append(["", "", "GRAND TOTAL:", f"R{total_spent:.2f}"])
    items_table = Table(table_data, colWidths=[1 * cm, 8 * cm, 3 * cm, 5 * cm])
    items_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")), ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fff3cd")), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story.append(items_table)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Summary", section_style))
    summary_data = [["Total Spent", f"R{total_spent:.2f}"], ["Monthly Budget", f"R{user['budget']:.2f}"], ["Remaining Budget", f"R{remaining:.2f}"]]
    summary_table = Table(summary_data, colWidths=[9 * cm, 8 * cm])
    summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eefaf1")), ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1e7e34")), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 10), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c3e6cb"))]))
    story.append(summary_table)
    story.append(Spacer(1, 1 * cm))
    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#999999"), alignment=1)
    story.append(Paragraph("Generated by SmartSpend AI - Your student budgeting assistant", footer_style))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"SmartSpend_Budget_Plan_{datetime.now().strftime('%Y%m%d')}.pdf", mimetype="application/pdf")


@app.route("/download-budget-list-pdf")
@login_required
def download_budget_list_pdf():
    budget_products, cart_total = get_budget_list_details()
    if not budget_products:
        flash("Your budget list is empty. Add some items first.", "warning")
        return redirect(url_for("view_budget_list"))
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    total_spent = connection.execute("SELECT SUM(price) FROM shopping_history WHERE user_id = ?", (session["user_id"],)).fetchone()[0] or 0
    connection.close()
    remaining = user["budget"] - total_spent
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="SmartSpend - Budget List", author="SmartSpend AI")
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle("CustomTitle", parent=styles["Heading1"], fontSize=22, textColor=colors.HexColor("#1a73e8"), spaceAfter=6)
    subtitle_style = ParagraphStyle("CustomSubtitle", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#666666"), spaceAfter=20)
    section_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#333333"), spaceBefore=12, spaceAfter=8)
    story.append(Paragraph("SmartSpend AI - Budget List", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%d %B %Y at %H:%M')}", subtitle_style))
    story.append(Paragraph("Student Information", section_style))
    user_data = [["Name", f"{user['name']} {user['surname']}"], ["Email", user["email"]], ["Monthly Budget", f"R{user['budget']:.2f}"], ["Already Allocated", f"R{total_spent:.2f}"], ["Available Budget", f"R{remaining:.2f}"]]
    user_table = Table(user_data, colWidths=[5 * cm, 12 * cm])
    user_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef5ff")), ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a73e8")), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0"))]))
    story.append(user_table)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Items in Your Budget List", section_style))
    table_data = [["#", "Product", "Store", "Price", "Transport", "Total"]]
    for i, p in enumerate(budget_products, 1):
        distance = get_shop_distance(p.get("store", ""), "steve_biko")
        fee = get_distance_fee(25, distance)
        transport = fee if fee > 0 else p.get("shipping", 0)
        total_item = p["price"] + transport
        table_data.append([str(i), p["name"], p["store"], f"R{p['price']:.2f}", f"R{transport:.2f}" if transport else "Free", f"R{total_item:.2f}"])
    table_data.append(["", "", "", "", "GRAND TOTAL:", f"R{cart_total:.2f}"])
    items_table = Table(table_data, colWidths=[1 * cm, 6.5 * cm, 3 * cm, 2 * cm, 2 * cm, 2.5 * cm])
    items_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")), ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fff3cd")), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story.append(items_table)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Budget Summary", section_style))
    summary_data = [["Budget List Total", f"R{cart_total:.2f}"], ["Monthly Budget", f"R{user['budget']:.2f}"], ["Already Allocated", f"R{total_spent:.2f}"], ["Remaining After This List", f"R{remaining - cart_total:.2f}"]]
    summary_table = Table(summary_data, colWidths=[9 * cm, 8 * cm])
    summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eefaf1")), ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1e7e34")), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 10), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c3e6cb"))]))
    story.append(summary_table)
    story.append(Spacer(1, 1 * cm))
    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#999999"), alignment=1)
    story.append(Paragraph("Generated by SmartSpend AI - Your student budgeting assistant", footer_style))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"SmartSpend_Budget_List_{datetime.now().strftime('%Y%m%d')}.pdf", mimetype="application/pdf")



@app.route("/favourite/<int:product_id>", methods=["POST"])
@login_required
def favourite(product_id):
    product = next((product for product in PRODUCTS if product["id"] == product_id), None)
    if product is None:
        flash("Product not found.", "danger")
        return redirect(request.referrer or url_for("home"))
    favourites = list(get_favourites())
    if product_id in favourites:
        favourites.remove(product_id)
        flash(f"{product['name']} removed from favourites.", "info")
    else:
        favourites.append(product_id)
        flash(f"{product['name']} added to favourites!", "success")
    session["favourites"] = list(dict.fromkeys(favourites))
    session.modified = True
    return redirect(request.referrer or url_for("home"))


@app.route("/favourites")
def favourites():
    favourite_ids = get_favourites()
    favourite_products = [product for product in PRODUCTS if product["id"] in favourite_ids]
    return render_template("favourites.html", products=favourite_products, favourites=favourite_ids, cart_count=len(get_budget_list()))


@app.route("/profile")
@login_required
def profile():
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close()
    return render_template("profile.html", user=user, cart_count=len(get_budget_list()))


@app.route("/update-profile", methods=["POST"])
@login_required
def update_profile():
    new_budget = request.form.get("budget", "").strip()
    new_name = request.form.get("name", "").strip()
    new_surname = request.form.get("surname", "").strip()
    if not new_name or not new_surname:
        flash("Name and surname cannot be empty.", "danger")
        return redirect(url_for("profile"))
    try:
        new_budget = float(new_budget)
        if new_budget < 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Please enter a valid budget.", "danger")
        return redirect(url_for("profile"))
    connection = get_db()
    connection.execute("UPDATE users SET name = ?, surname = ?, budget = ? WHERE id = ?", (new_name, new_surname, new_budget, session["user_id"]))
    connection.commit()
    connection.close()
    session["name"] = new_name
    session["surname"] = new_surname
    flash("Profile updated successfully!", "success")
    return redirect(url_for("profile"))


@app.route("/history")
@login_required
def history():
    connection = get_db()
    history_records = connection.execute("SELECT product_id, product_name, price, created_at FROM shopping_history WHERE user_id = ? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    connection.close()
    return render_template("history.html", history=history_records, cart_count=len(get_budget_list()))


@app.route("/save-plan/<int:product_id>", methods=["POST"])
@login_required
def save_to_spending_plan(product_id):
    product = next((product for product in PRODUCTS if product["id"] == product_id), None)
    if not product:
        flash("Product not found.", "danger")
        return redirect(request.referrer or url_for("home"))

    statuses = get_product_statuses()
    if statuses.get(product_id, "In Stock") == "Out of Stock":
        record_stock_alert(session["user_id"], product["id"], product["name"])
        in_stock_pool = [p for p in PRODUCTS if statuses.get(p["id"], "In Stock") != "Out of Stock"]
        flash_out_of_stock([product["name"]], pick_in_stock_alternative(product, in_stock_pool))
        return redirect(request.referrer or url_for("home"))

    distance = get_shop_distance(product.get("store", ""), "steve_biko")
    fee = get_distance_fee(25, distance)
    transport = fee if fee > 0 else product.get("shipping", 0)
    purchase_total = product["price"] + transport

    connection = get_db()
    user = connection.execute("SELECT budget FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    total_spent = connection.execute(
        "SELECT COALESCE(SUM(price), 0) FROM shopping_history WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0] or 0

    last_search = session.get("last_search", {})
    try:
        search_budget = float(last_search.get("budget", 0))
    except (ValueError, TypeError):
        search_budget = 0

    profile_remaining = (user["budget"] - total_spent) if user else 0
    effective_remaining = profile_remaining
    if search_budget > 0:
        effective_remaining = min(profile_remaining, search_budget)

    if purchase_total > effective_remaining:
        connection.close()
        flash(
            f"❌ Cannot add {product['name']}. "
            f"It costs R{purchase_total:.2f}, but you only have R{effective_remaining:.2f} available "
            f"based on your search budget.",
            "danger"
        )
        return redirect(request.referrer or url_for("home"))

    existing = connection.execute(
        "SELECT id FROM shopping_history WHERE user_id = ? AND product_name = ? LIMIT 1",
        (session["user_id"], product["name"])
    ).fetchone()
    if existing:
        connection.execute("UPDATE shopping_history SET created_at = CURRENT_TIMESTAMP WHERE id = ?", (existing["id"],))
        connection.commit()
        connection.close()
        flash(f"{product['name']} is already in your budget plan.", "info")
        return redirect(url_for("history"))

    connection.execute(
        "INSERT INTO shopping_history (user_id, product_id, product_name, price) VALUES (?, ?, ?, ?)",
        (session["user_id"], product["id"], product["name"], purchase_total)
    )
    connection.commit()
    connection.close()
    flash(f"✅ {product['name']} saved to your spending plan!", "success")
    return redirect(url_for("history"))


@app.route("/add-to-budget-list/<int:product_id>", methods=["POST"])
@login_required
def add_to_budget_list(product_id):
    product = next((product for product in PRODUCTS if product["id"] == product_id), None)
    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("home"))
    statuses = get_product_statuses()
    if statuses.get(product_id, "In Stock") == "Out of Stock":
        record_stock_alert(session["user_id"], product["id"], product["name"])
        in_stock_pool = [p for p in PRODUCTS if statuses.get(p["id"], "In Stock") != "Out of Stock"]
        flash_out_of_stock([product["name"]], pick_in_stock_alternative(product, in_stock_pool))
        return redirect(request.referrer or url_for("home"))
    budget_list = list(get_budget_list())
    if product_id not in budget_list:
        budget_list.append(product_id)
        session["budget_list"] = budget_list
        session.modified = True
        flash(f"{product['name']} added to your budget list!", "success")
    else:
        flash(f"{product['name']} is already in your budget list.", "info")
    return redirect(url_for("view_budget_list"))


@app.route("/budget-list")
@login_required
def view_budget_list():
    budget_products, cart_total = get_budget_list_details()
    connection = get_db()
    user = connection.execute("SELECT budget FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    total_spent = connection.execute("SELECT SUM(price) FROM shopping_history WHERE user_id = ?", (session["user_id"],)).fetchone()[0] or 0
    connection.close()
    remaining_budget = user["budget"] - total_spent
    return render_template("budget_list.html", products=budget_products, cart_total=cart_total, remaining_budget=remaining_budget, cart_count=len(get_budget_list()))


@app.route("/remove-from-budget-list/<int:product_id>", methods=["POST"])
@login_required
def remove_from_budget_list(product_id):
    budget_list = list(get_budget_list())
    if product_id in budget_list:
        budget_list.remove(product_id)
        session["budget_list"] = budget_list
        session.modified = True
        flash("Item removed from budget list.", "info")
    return redirect(url_for("view_budget_list"))


@app.route("/finalize-budget-plan", methods=["POST"])
@login_required
def finalize_budget_plan():
    budget_products, budget_total = get_budget_list_details()
    if not budget_products:
        flash("Your budget list is empty.", "warning")
        return redirect(url_for("view_budget_list"))

    connection = get_db()
    user = connection.execute("SELECT budget FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    total_spent = connection.execute(
        "SELECT COALESCE(SUM(price), 0) FROM shopping_history WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0] or 0

    last_search = session.get("last_search", {})
    try:
        search_budget = float(last_search.get("budget", 0))
    except (ValueError, TypeError):
        search_budget = 0

    profile_remaining = user["budget"] - total_spent
    effective_remaining = profile_remaining
    if search_budget > 0:
        effective_remaining = min(profile_remaining, search_budget)

    if budget_total > effective_remaining:
        connection.close()
        over_by = budget_total - effective_remaining
        flash(
            f"❌ Cannot finalize. Your budget list totals R{budget_total:.2f}, "
            f"but you only have R{effective_remaining:.2f} available. "
            f"You're R{over_by:.2f} over budget.",
            "danger"
        )
        return redirect(url_for("view_budget_list"))

    saved_count = 0
    skipped_count = 0
    for product in budget_products:
        distance = get_shop_distance(product.get("store", ""), "steve_biko")
        fee = get_distance_fee(25, distance)
        transport = fee if fee > 0 else product.get("shipping", 0)
        purchase_total = product["price"] + transport
        existing = connection.execute(
            "SELECT id FROM shopping_history WHERE user_id = ? AND product_name = ? LIMIT 1",
            (session["user_id"], product["name"])
        ).fetchone()
        if existing:
            connection.execute("UPDATE shopping_history SET created_at = CURRENT_TIMESTAMP WHERE id = ?", (existing["id"],))
            skipped_count += 1
        else:
            connection.execute(
                "INSERT INTO shopping_history (user_id, product_id, product_name, price) VALUES (?, ?, ?, ?)",
                (session["user_id"], product["id"], product["name"], purchase_total)
            )
            saved_count += 1
    connection.commit()
    connection.close()
    session["budget_list"] = []
    if skipped_count and saved_count:
        flash(f"Added {saved_count} new item(s). {skipped_count} were already in your plan.", "success")
    elif saved_count:
        flash("Budget plan finalized! Your items have been saved to your spending plan.", "success")
    else:
        flash("All items were already in your spending plan.", "info")
    return redirect(url_for("history"))


def get_user_preferences(user_id):
    connection = get_db()
    user = connection.execute("SELECT preferred_brands, preferred_colours, preferred_stores, hobbies, style FROM users WHERE id = ?", (user_id,)).fetchone()
    connection.close()
    if user:
        return {
            "brands": [x.strip() for x in user["preferred_brands"].split(",") if x.strip()] if user["preferred_brands"] else [],
            "colours": [x.strip() for x in user["preferred_colours"].split(",") if x.strip()] if user["preferred_colours"] else [],
            "stores": [x.strip() for x in user["preferred_stores"].split(",") if x.strip()] if user["preferred_stores"] else [],
            "hobbies": [x.strip() for x in user["hobbies"].split(",") if x.strip()] if user["hobbies"] else [],
            "styles": [x.strip() for x in user["style"].split(",") if x.strip()] if user["style"] else []
        }
    return {"brands": [], "colours": [], "stores": [], "hobbies": [], "styles": []}


def update_user_preferences(user_id, preferences):
    connection = get_db()
    connection.execute("UPDATE users SET preferred_brands = ?, preferred_colours = ?, preferred_stores = ?, hobbies = ?, style = ? WHERE id = ?", (",".join(preferences.get("brands", [])), ",".join(preferences.get("colours", [])), ",".join(preferences.get("stores", [])), ",".join(preferences.get("hobbies", [])), ",".join(preferences.get("styles", [])), user_id))
    connection.commit()
    connection.close()


@app.route("/preferences")
@login_required
def preferences():
    return render_template("preferences.html", preferences=get_user_preferences(session["user_id"]), cart_count=len(get_budget_list()))


@app.route("/update-preferences", methods=["POST"])
@login_required
def update_preferences():
    preferences = {"brands": request.form.getlist("brands"), "colours": request.form.getlist("colours"), "stores": request.form.getlist("stores"), "hobbies": request.form.getlist("hobbies"), "styles": request.form.getlist("styles")}
    update_user_preferences(session["user_id"], preferences)
    flash("Your preferences have been saved! SmartSpend AI will use them for better recommendations.", "success")
    return redirect(url_for("preferences"))



@app.route("/api/products")
def api_products():
    return jsonify(PRODUCTS)


def product_matches_text(product, query):
    if not query:
        return True
    searchable_text = " ".join([str(product.get("name", "")), str(product.get("item", "")), str(product.get("brand", "")), str(product.get("size", "")), str(product.get("category", "")), str(product.get("store", ""))]).lower()
    return all(word in searchable_text for word in query.lower().split())


def valid_colour_filter(product, colour):
    if not colour or colour.lower() == "any":
        return True
    if product.get("category") != "clothing":
        return True
    return product.get("colour", "").lower() == colour.lower()


def enrich_product(product, budget=0, preferred_brands=None, preferred_stores=None,
                   preferred_colours=None, preferred_styles=None, radius=25,
                   active_sales=None):
    preferred_brands = preferred_brands or []
    preferred_stores = preferred_stores or []
    preferred_colours = preferred_colours or []
    preferred_styles = preferred_styles or []

    product = apply_sale(product, active_sales)

    distance_fee = get_distance_fee(radius, product.get("distance", 0))
    if distance_fee > 0:
        product_shipping = distance_fee
    else:
        product_shipping = product.get("shipping", 0)

    total_price = product["price"] + product_shipping

    match_score = 70

    if product.get("on_sale"):
        match_score += 15

    if budget > 0:
        if total_price <= budget * 0.5:
            match_score += 20
        elif total_price <= budget * 0.75:
            match_score += 15
        elif total_price <= budget:
            match_score += 10
    if product_shipping == 0:
        match_score += 20
    elif product_shipping <= 10:
        match_score += 10
    if product.get("distance", 0) <= 2:
        match_score += 15
    elif product.get("distance", 0) <= 5:
        match_score += 10
    if preferred_brands and product.get("brand", "").lower() in preferred_brands:
        match_score += 10
    if preferred_stores and any(s in product.get("store", "").lower() for s in preferred_stores):
        match_score += 10
    if product.get("category") == "clothing" and preferred_colours and product.get("colour", "").lower() in preferred_colours:
        match_score += 10
    if product.get("category") == "clothing" and preferred_styles and product.get("style", "").lower() in preferred_styles:
        match_score += 10
    if product.get("rating", 0) >= 4.5:
        match_score += 5
    match_score = min(99, round(match_score))

    enriched = dict(product)
    enriched["shipping"] = product_shipping
    enriched["total_price"] = total_price
    enriched["savings"] = max(0, round(budget - total_price, 2)) if budget > 0 else 0
    enriched["match"] = match_score

    enriched["original_price"] = product.get("original_price", product["price"])
    enriched["on_sale"] = product.get("on_sale", False)
    enriched["sale_percent"] = product.get("sale_percent", 0)
    enriched["sale_ends_at"] = product.get("sale_ends_at")

    return enriched


@app.route("/search-products", methods=["GET", "POST"])
@login_required
def search_products():
    if request.method == "POST":
        form = request.form
        session["last_search"] = request.form.to_dict()
        session.modified = True
    else:
        form = session.get("last_search")
        if not form:
            return redirect(url_for("dashboard"))

    product_category = form.get("product_category", "").strip().lower()
    category_aliases = {
        "clothes": "clothing", "sneakers": "clothing",
        "study": "study_materials", "study materials": "study_materials",
        "personal care": "personal_care"
    }
    product_category = category_aliases.get(product_category, product_category)
    valid_categories = {category["key"] for category in STUDENT_CATEGORIES}
    if product_category and product_category not in valid_categories:
        flash("Please choose one of the available student budgeting categories.", "warning")
        return redirect(url_for("dashboard"))

    product_name = form.get("product_name", "").strip()
    selected_brand = form.get("brand", "").strip()
    selected_size = form.get("product_size", "").strip()
    clothing_size = form.get("clothing_size", "").strip()
    colour = form.get("colour", "").strip()

    if not clothing_size and product_category == "clothing":
        clothing_size = selected_size

    budget_text = form.get("budget", "0").strip()
    radius_text = form.get("radius", "25").strip()
    shipping = form.get("shipping", "any").strip()
    sort = form.get("sort", "low_to_high").strip()

    only_sale = form.get("only_sale", "").strip().lower() in ("1", "true", "on", "yes")

    try:
        budget = float(budget_text)
    except (ValueError, TypeError):
        budget = 0
    try:
        radius = float(radius_text)
    except (ValueError, TypeError):
        radius = 25

    product_name_lower = product_name.lower()
    searched_item = ""

    if product_category and product_category in KNOWN_ITEMS:
        for item_keyword in KNOWN_ITEMS[product_category]:
            if item_keyword in product_name_lower:
                searched_item = item_keyword
                break

    if not searched_item:
        for cat, items in KNOWN_ITEMS.items():
            for item_keyword in items:
                if item_keyword in product_name_lower:
                    searched_item = item_keyword
                    if not product_category:
                        product_category = cat
                    break
            if searched_item:
                break

    variant_word = ""
    for word in VARIANT_WORDS:
        if word in product_name_lower:
            variant_word = word
            break

    preferences = get_user_preferences(session["user_id"])
    preferred_brands = [brand.lower() for brand in preferences["brands"]]
    preferred_colours = [c.lower() for c in preferences["colours"]]
    preferred_stores = [s.lower() for s in preferences["stores"]]
    preferred_styles = [st.lower() for st in preferences["styles"]]

    strict_results = []
    same_item_fallback = []
    out_of_stock_requested = []
    statuses = get_product_statuses()
    brand_requested = bool(selected_brand) and selected_brand.lower() != "any"

    active_sales = get_active_sales()

    for product in PRODUCTS:
        if only_sale and product["id"] not in active_sales:
            continue

        if product_category and product["category"] != product_category:
            continue
        if selected_size and product_category != "clothing":
            if str(product.get("size", "")) != str(selected_size):
                continue
        if clothing_size and product_category == "clothing":
            if str(product.get("size", "")) != str(clothing_size):
                continue
        if not valid_colour_filter(product, colour):
            continue
        if product.get("distance", 0) > radius:
            continue
        product_shipping = product.get("shipping", 0)
        if shipping == "free" and product_shipping != 0:
            continue
        if shipping == "low" and product_shipping > 50:
            continue

        enriched = enrich_product(
            product,
            budget=budget,
            preferred_brands=preferred_brands,
            preferred_stores=preferred_stores,
            preferred_colours=preferred_colours,
            preferred_styles=preferred_styles,
            radius=radius,
            active_sales=active_sales,
        )

        total_price = enriched["total_price"]
        within_budget = (budget <= 0) or (total_price <= budget)

        brand_matches = True
        if selected_brand and selected_brand.lower() != "any":
            if product.get("brand", "").lower() != selected_brand.lower():
                brand_matches = False

        product_name_check = product["name"].lower()
        if variant_word:
            same_item = (variant_word in product_name_check)
        elif searched_item:
            product_item = product.get("item", "").lower()
            same_item = (product_item == searched_item) or (searched_item in product_name_check)
        else:
            if product_name:
                query_words = product_name.lower().split()
                product_text = " ".join([
                    str(product.get("name", "")), str(product.get("item", "")),
                    str(product.get("brand", "")), str(product.get("category", ""))
                ]).lower()
                same_item = any(word in product_text for word in query_words)
            else:
                same_item = True

        enriched["status"] = statuses.get(product["id"], "In Stock")
        is_out_of_stock = enriched["status"] == "Out of Stock"

        if not same_item:
            continue

        if is_out_of_stock:
            if brand_requested:
                was_requested = brand_matches
            else:
                product_brand = product.get("brand", "").lower()
                was_requested = (bool(product_brand) and product_brand in product_name_lower) or \
                                (product_name_check in product_name_lower) or \
                                (product_name_lower in product_name_check)
            if was_requested:
                out_of_stock_requested.append(enriched)
            continue

        if brand_matches and within_budget:
            strict_results.append(enriched)
        else:
            same_item_fallback.append(enriched)

    used_fallback = False
    brand_warning = ""
    results = []
    recommended_product = None
    recommendation_message = ""

    if out_of_stock_requested:
        used_fallback = True
        out_names = list(dict.fromkeys(p["name"] for p in out_of_stock_requested))
        out_verb = "is" if len(out_names) == 1 else "are"
        recommended_product = pick_in_stock_alternative(
            out_of_stock_requested[0], PRODUCTS, budget
        )

        if recommended_product:
            brand_warning = (
                f"⚠️ OUT OF STOCK: {', '.join(out_names)} {out_verb} currently out of stock. "
                f"✅ IN STOCK: We recommend {recommended_product['name']} at "
                f"{recommended_product['store']} for "
                f"R{recommended_product['price'] + recommended_product.get('shipping', 0):.2f}."
            )
            recommended_product = enrich_product(
                recommended_product, budget=budget, radius=radius,
                active_sales=active_sales,
            )
            recommended_product["status"] = statuses.get(recommended_product["id"], "In Stock")
            results = [recommended_product]
        else:
            brand_warning = (
                f"⚠️ OUT OF STOCK: {', '.join(out_names)} {out_verb} currently out of stock "
                f"and we have no similar products in stock right now."
            )
            results = []

        for p in out_of_stock_requested:
            record_stock_alert(session["user_id"], p["id"], p["name"])

        flash_out_of_stock(out_names, recommended_product)

    elif strict_results:
        results = strict_results
        recommended_product = results[0] if results else None

    elif same_item_fallback:
        used_fallback = True
        same_item_fallback.sort(key=lambda p: p.get("total_price", p.get("price", 0)))

        fitting_options = (
            [p for p in same_item_fallback if p["total_price"] <= budget]
            if budget > 0 else same_item_fallback
        )

        item_label = searched_item or product_name or "that item"

        if fitting_options:
            recommended_product = fitting_options[0]

            if searched_item and selected_brand and budget > 0:
                brand_warning = (
                    f"⚠️ OVER BUDGET: We don't have {selected_brand} "
                    f"{searched_item.title()} for R{budget:.2f} in any shop. "
                    f"✅ WITHIN BUDGET: But with your budget you can get "
                    f"{recommended_product['name']} at {recommended_product['store']} "
                    f"for R{recommended_product['total_price']:.2f}."
                )
            elif searched_item and budget > 0:
                brand_warning = (
                    f"⚠️ OVER BUDGET: We don't have the exact {searched_item} "
                    f"you asked for at R{budget:.2f}. "
                    f"✅ WITHIN BUDGET: The cheapest {searched_item} that fits your budget is "
                    f"{recommended_product['name']} at {recommended_product['store']} "
                    f"for R{recommended_product['total_price']:.2f}."
                )
            else:
                brand_warning = (
                    f"✅ WITHIN BUDGET: Here's the closest match that fits your budget: "
                    f"{recommended_product['name']} at {recommended_product['store']} "
                    f"for R{recommended_product['total_price']:.2f}."
                )

            results = [recommended_product]

        else:
            cheapest_overall = same_item_fallback[0]
            recommended_product = None
            rec_over_by = cheapest_overall["total_price"] - budget

            brand_warning = (
                f"❌ We don't have any {item_label} for R{budget:.2f}. "
                f"The cheapest {item_label} we have is "
                f"{cheapest_overall['name']} at {cheapest_overall['store']} "
                f"for R{cheapest_overall['total_price']:.2f} "
                f"(R{rec_over_by:.2f} over your budget). "
                f"Try increasing your budget or searching for something else."
            )

            results = []

    else:
        results = []
        recommendation_message = (
            f"❌ We don't have any {searched_item or product_name or 'matching products'} "
            f"in stock within R{budget:.2f}. "
            f"Try increasing your budget or changing your search."
        )
        flash(recommendation_message, "warning")

    if used_fallback and brand_warning:
        recommendation_message = brand_warning
    elif results:
        best = results[0]
        reasons = []
        actually_within_budget = (budget <= 0) or (best["total_price"] <= budget)

        if actually_within_budget:
            if budget > 0 and best["total_price"] <= budget * 0.5:
                reasons.append(f"it's well within your R{budget:.0f} budget")
            elif budget > 0:
                reasons.append(f"it fits your R{budget:.0f} budget")

        if best.get("shipping", 0) == 0:
            reasons.append("it has FREE transport")
        elif best.get("shipping", 0) <= 10:
            reasons.append(f"transport is only R{best['shipping']:.0f}")

        if best.get("category") == "clothing" and preferred_styles and best.get("style", "").lower() in preferred_styles:
            reasons.append("it matches your preferred style")
        if best.get("category") == "clothing" and preferred_colours and best.get("colour", "").lower() in preferred_colours:
            reasons.append("it matches your favourite colour")
        if preferred_stores and best.get("store", "").lower() in preferred_stores:
            reasons.append("it's from one of your preferred stores")

        if best.get("on_sale"):
            reasons.insert(0, f"it's on sale ({best['sale_percent']:.0f}% off)")

        if actually_within_budget:
            recommendation_message = (
                f"✅ WITHIN BUDGET: Based on your criteria, you should consider budgeting for "
                f"{best['name']} at {best['store']} because " + ", ".join(reasons) + "."
            )
        else:
            over_by = best["total_price"] - budget
            recommendation_message = (
                f"⚠️ OVER BUDGET: We couldn't find any {searched_item or 'product'} "
                f"within R{budget:.2f}. The closest match is {best['name']} at "
                f"{best['store']} for R{best['total_price']:.2f} "
                f"(R{over_by:.2f} over your budget)."
            )

    final_results = []
    if used_fallback:
        if recommended_product:
            final_results.append(recommended_product)
    else:
        final_results = results

    if not final_results:
        final_results = results

    if request.method == "POST":
        connection = get_db()
        existing = connection.execute(
            "SELECT id FROM search_history WHERE user_id = ? AND query = ? ORDER BY created_at DESC LIMIT 1",
            (session["user_id"], product_name)
        ).fetchone()

        if existing:
            connection.execute(
                """UPDATE search_history
                   SET created_at = CURRENT_TIMESTAMP, budget = ?, colour = ?, product_id = ?
                   WHERE id = ?""",
                (budget, colour if product_category == "clothing" else "",
                 final_results[0]["id"] if final_results else None, existing["id"])
            )
        else:
            connection.execute(
                "INSERT INTO search_history (user_id, query, budget, colour, product_id) VALUES (?, ?, ?, ?, ?)",
                (session["user_id"], product_name, budget,
                 colour if product_category == "clothing" else "",
                 final_results[0]["id"] if final_results else None)
            )
        connection.commit()
        connection.close()

    return render_template(
        "results.html",
        products=final_results,
        favourites=get_favourites(),
        query=product_name,
        budget=budget,
        colour=colour,
        radius=radius,
        shipping=shipping,
        sort=sort,
        recommendation_message=recommendation_message,
        categories=STUDENT_CATEGORIES,
        cart_count=len(get_budget_list())
    )



@app.route("/admin/products")
@login_required
@store_manager_required
def admin_products():
    return render_template("admin_products.html", products=PRODUCTS, cart_count=len(get_budget_list()))


@app.route("/store/add-product", methods=["GET", "POST"])
@login_required
@store_manager_required
def store_add_product():
    if request.method == "GET":
        return render_template("store_add_product.html", categories=STUDENT_CATEGORIES, cart_count=len(get_budget_list()))

    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    item = request.form.get("item", "").strip()
    brand = request.form.get("brand", "").strip()
    size = request.form.get("size", "").strip()
    store = request.form.get("store", "").strip()
    price = request.form.get("price", 0)
    shipping = request.form.get("shipping", 0)
    distance = request.form.get("distance", 5)
    rating = request.form.get("rating", 4.0)
    image_url = request.form.get("image_url", "").strip()

    try:
        price = float(price)
        shipping = float(shipping)
        distance = float(distance)
        rating = float(rating)
    except (ValueError, TypeError):
        flash("Please enter valid numbers.", "danger")
        return redirect(url_for("store_add_product"))

    new_id = max([p["id"] for p in PRODUCTS]) + 1

    new_product = {
        "id": new_id,
        "name": name,
        "category": category,
        "item": item,
        "brand": brand,
        "size": size,
        "store": store,
        "price": price,
        "shipping": shipping,
        "distance": distance,
        "rating": rating,
        "image_url": image_url if image_url else f"/static/images/{name.lower().replace(' ', '_')}.jpg"
    }

    PRODUCTS.append(new_product)
    save_product_to_db(new_product)

    flash(f"Product '{name}' added successfully!", "success")
    return redirect(url_for("admin_products"))


@app.route("/store/delete-product/<int:product_id>", methods=["POST"])
@login_required
@store_manager_required
def store_delete_product(product_id):
    global PRODUCTS
    PRODUCTS = [p for p in PRODUCTS if p["id"] != product_id]
    delete_product_from_db(product_id)
    flash("Product deleted successfully.", "success")
    return redirect(request.referrer or url_for("store_dashboard"))



@app.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    connection = get_db()
    users = connection.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    total_users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0
    total_students = connection.execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0] or 0
    total_admins = connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] or 0
    total_store_managers = connection.execute("SELECT COUNT(*) FROM users WHERE role = 'store_manager'").fetchone()[0] or 0
    total_allocated = connection.execute("SELECT SUM(budget) FROM users").fetchone()[0] or 0
    total_spent = connection.execute("SELECT SUM(price) FROM shopping_history").fetchone()[0] or 0
    total_products = len(PRODUCTS)
    recent_searches = connection.execute("SELECT sh.*, u.name, u.surname, u.role FROM search_history sh LEFT JOIN users u ON sh.user_id = u.id ORDER BY sh.created_at DESC LIMIT 10").fetchall()

    spending_students = connection.execute(
        "SELECT COUNT(DISTINCT user_id) FROM shopping_history"
    ).fetchone()[0] or 0
    avg_spent = (total_spent / spending_students) if spending_students > 0 else 0

    connection.close()
    return render_template(
        "admin_dashboard.html",
        users=users,
        total_users=total_users,
        total_students=total_students,
        total_admins=total_admins,
        total_store_managers=total_store_managers,
        total_allocated=total_allocated,
        total_spent=total_spent,
        total_budgeted=total_spent,
        total_products=total_products,
        recent_searches=recent_searches,
        spending_students=spending_students,
        avg_spent=avg_spent,
        cart_count=len(get_budget_list())
    )


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    connection = get_db()
    users_raw = connection.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()

    users = []
    for u in users_raw:
        planned = connection.execute(
            "SELECT COALESCE(SUM(price), 0) FROM shopping_history WHERE user_id = ?",
            (u["id"],)
        ).fetchone()[0] or 0

        users.append({
            "id": u["id"],
            "name": u["name"],
            "surname": u["surname"],
            "email": u["email"],
            "role": u["role"],
            "budget": u["budget"] or 0,
            "created_at": u["created_at"],
            "planned": planned,
            "remaining": (u["budget"] or 0) - planned,
        })

    connection.close()
    return render_template("admin_users.html", users=users, cart_count=len(get_budget_list()))


@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_users"))
    connection = get_db()
    connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    connection.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))
    connection.execute("DELETE FROM shopping_history WHERE user_id = ?", (user_id,))
    connection.execute("DELETE FROM stock_alerts WHERE user_id = ?", (user_id,))
    connection.commit()
    connection.close()
    flash("User deleted successfully.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/change-role/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_change_role(user_id):
    if user_id == session["user_id"]:
        flash("You cannot change your own role.", "danger")
        return redirect(url_for("admin_users"))
    new_role = request.form.get("role")
    valid_roles = ["student", "admin", "store_manager"]
    if new_role not in valid_roles:
        flash("Invalid role.", "danger")
        return redirect(url_for("admin_users"))
    connection = get_db()
    connection.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    connection.commit()
    connection.close()
    flash(f"User role changed to {new_role}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/edit-user/<int:user_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    connection = get_db()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    connection.close()
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin_users"))
    if request.method == "GET":
        return render_template("admin_edit_user.html", user=user, cart_count=len(get_budget_list()))
    name = request.form.get("name", "").strip()
    surname = request.form.get("surname", "").strip()
    email = request.form.get("email", "").strip().lower()
    budget = request.form.get("budget", 2000)
    role = request.form.get("role", "student")
    try:
        budget = float(budget)
    except:
        budget = 2000
    connection = get_db()
    connection.execute("UPDATE users SET name = ?, surname = ?, email = ?, budget = ?, role = ? WHERE id = ?", (name, surname, email, budget, role, user_id))
    connection.commit()
    connection.close()
    flash("User updated successfully!", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/stats")
@login_required
@admin_required
def admin_stats():
    connection = get_db()
    daily_spending = connection.execute("SELECT DATE(created_at) as date, SUM(price) as total FROM shopping_history GROUP BY DATE(created_at) ORDER BY DATE(created_at) DESC LIMIT 30").fetchall()
    top_searches = connection.execute("SELECT query, COUNT(*) as count FROM search_history WHERE query IS NOT NULL AND query != '' GROUP BY query ORDER BY count DESC LIMIT 10").fetchall()
    top_spent = connection.execute("SELECT product_name, SUM(price) as total FROM shopping_history GROUP BY product_name ORDER BY total DESC LIMIT 10").fetchall()
    connection.close()
    return render_template("admin_stats.html", daily_spending=daily_spending, top_searches=top_searches, top_spent=top_spent, cart_count=len(get_budget_list()))



init_db()

seed_products_if_empty()
load_products_from_db()

if __name__ == "__main__":
    app.run(debug=False)