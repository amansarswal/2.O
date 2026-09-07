"""FarmConnect: a small farmer-to-consumer marketplace MVP."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
DEFAULT_MAX_ORDER = 20

app = Flask(__name__)
app.secret_key = "farmconnect-demo-key"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_db() -> dict:
    if not DATA_FILE.exists():
        data = {"farmers": [], "buyers": [], "products": [], "orders": [], "ratings": []}
        save_db(data)
        return data
    with DATA_FILE.open(encoding="utf-8") as file:
        data = json.load(file)
    data.setdefault("farmers", [])
    data.setdefault("buyers", [])
    data.setdefault("products", [])
    data.setdefault("orders", [])
    data.setdefault("ratings", [])
    return data


def save_db(data: dict) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def user_for_session(data: dict):
    role = session.get("role")
    uid = session.get("uid")
    people = data.get("farmers" if role == "farmer" else "buyers", [])
    return next((person for person in people if person["id"] == uid), None)


def require_user(role: str):
    data = load_db()
    user = user_for_session(data)
    if not user or session.get("role") != role:
        return data, None
    return data, user


def rating_for(data: dict, farmer_id: str) -> dict:
    reviews = [item for item in data["ratings"] if item["farmer_id"] == farmer_id]
    average = round(sum(item["stars"] for item in reviews) / len(reviews), 1) if reviews else 0
    return {"average": average, "count": len(reviews), "reviews": reviews}


def product_view(data: dict, product: dict) -> dict:
    farmer = next(item for item in data["farmers"] if item["id"] == product["farmer_id"])
    rating = rating_for(data, farmer["id"])
    return {
        **product,
        "description": product.get("description") or f"Fresh {product['name']} from {farmer.get('farm', 'our farm')}.",
        "image": product.get("image") or "https://images.unsplash.com/photo-1542838132-92c53300491e",
        "max_order": int(product.get("max_order", DEFAULT_MAX_ORDER)),
        "farmer_name": farmer["name"],
        "farm": farmer.get("farm", "Local farm"),
        "location": farmer.get("location", "India"),
        "farmer_bio": farmer.get("bio", ""),
        "rating": rating["average"],
        "rating_count": rating["count"],
    }


def order_view(data: dict, order: dict) -> dict:
    product = next((item for item in data["products"] if item["id"] == order["product_id"]), None)
    farmer = next((item for item in data["farmers"] if item["id"] == order["farmer_id"]), None)
    return {
        **order,
        "product_name": product["name"] if product else "Product",
        "image": product.get("image") if product else "",
        "price": product.get("price", 0) if product else 0,
        "unit": product.get("unit", "kg") if product else "unit",
        "farmer_name": farmer["name"] if farmer else "Farmer",
        "farm": farmer.get("farm", "") if farmer else "",
    }


@app.route("/")
def home():
    data = load_db()
    return render_template("index.html", products=[product_view(data, p) for p in data["products"] if p.get("stock", 0) > 0])


@app.route("/products")
def products_page():
    return render_template("products.html")


@app.route("/product/<product_id>")
def product_detail(product_id: str):
    data = load_db()
    product = next((p for p in data["products"] if p["id"] == product_id), None)
    if not product:
        return redirect(url_for("products_page"))
    return render_template("product_detail.html", product=product_view(data, product))


@app.route("/login")
def login():
    return render_template("login.html", mode="login", role=request.args.get("role", "consumer"))


@app.route("/register")
def register():
    return render_template("login.html", mode="register", role=request.args.get("role", "consumer"))


@app.route("/farmer")
def farmer_dashboard():
    data, user = require_user("farmer")
    if not user:
        return redirect(url_for("login", role="farmer"))
    products = [product_view(data, p) for p in data["products"] if p["farmer_id"] == user["id"]]
    for product in products:
        product["sold"] = sum(o["qty"] for o in data["orders"] if o["product_id"] == product["id"])
    return render_template("farmer.html", user=user, products=products, rating=rating_for(data, user["id"]))


@app.route("/farmer/product/new")
@app.route("/farmer/product/<product_id>/edit")
def product_form(product_id=None):
    data, user = require_user("farmer")
    if not user:
        return redirect(url_for("login", role="farmer"))
    product = next((p for p in data["products"] if p["id"] == product_id and p["farmer_id"] == user["id"]), None)
    if product_id and not product:
        return redirect(url_for("farmer_dashboard"))
    return render_template("product_form.html", product=product_view(data, product) if product else None)


@app.route("/orders")
def consumer_orders():
    data, user = require_user("consumer")
    if not user:
        return redirect(url_for("login", role="consumer"))
    orders = [order_view(data, order) for order in data["orders"] if order["buyer_id"] == user["id"]]
    eligible_farmer_ids = sorted({order["farmer_id"] for order in data["orders"] if order["buyer_id"] == user["id"]})
    eligible_farmers = [farmer for farmer in data["farmers"] if farmer["id"] in eligible_farmer_ids]
    return render_template("orders.html", orders=orders, eligible_farmers=eligible_farmers)


@app.route("/farmer/<farmer_id>/profile")
def farmer_profile(farmer_id: str):
    data = load_db()
    farmer = next((item for item in data["farmers"] if item["id"] == farmer_id), None)
    if not farmer:
        return redirect(url_for("home"))
    return render_template("profile.html", farmer=farmer, rating=rating_for(data, farmer_id))


@app.post("/api/register")
def api_register():
    data = load_db()
    body = request.get_json(force=True)
    role = body.get("role", "consumer")
    if role not in {"farmer", "consumer"}:
        return jsonify(error="Choose a valid account type."), 400
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""
    if not name or len(password) < 6:
        return jsonify(error="Name is required and password must be at least 6 characters."), 400
    key = "farmers" if role == "farmer" else "buyers"
    if any(item["name"].casefold() == name.casefold() for item in data[key]):
        return jsonify(error="An account with that name already exists."), 409
    person = {
        "id": ("f" if role == "farmer" else "b") + uuid.uuid4().hex[:8],
        "name": name,
        "password": password,
        "location": (body.get("location") or "India").strip(),
    }
    if role == "farmer":
        person.update({"farm": (body.get("farm") or "My Farm").strip(), "bio": (body.get("bio") or "").strip()})
    else:
        person["org"] = (body.get("org") or "").strip()
    data[key].append(person)
    save_db(data)
    session.update(role=role, uid=person["id"])
    return jsonify(redirect="/farmer" if role == "farmer" else "/")


@app.post("/api/login")
def api_login():
    data = load_db()
    body = request.get_json(force=True)
    role = body.get("role", "consumer")
    if role not in {"farmer", "consumer"}:
        return jsonify(error="Choose Farmer or Consumer before signing in."), 400
    key = "farmers" if role == "farmer" else "buyers"
    name = (body.get("name") or "").strip().casefold()
    person = next((item for item in data[key] if item["name"].casefold() == name and item["password"] == body.get("password")), None)
    if not person:
        return jsonify(error="Name or password did not match."), 401
    session.update(role=role, uid=person["id"])
    return jsonify(redirect="/farmer" if role == "farmer" else "/")


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def api_me():
    data = load_db()
    user = user_for_session(data)
    if not user:
        return jsonify(user=None)
    return jsonify(user={k: v for k, v in user.items() if k != "password"}, role=session["role"])


@app.get("/api/products")
def api_products():
    data = load_db()
    query = (request.args.get("q") or "").casefold()
    products = [product_view(data, p) for p in data["products"] if p.get("stock", 0) > 0]
    if query:
        products = [p for p in products if query in f"{p['name']} {p['farmer_name']} {p['location']}".casefold()]
    return jsonify(products=products)


@app.post("/api/products")
def api_save_product():
    data, user = require_user("farmer")
    if not user:
        return jsonify(error="Farmer login required."), 401
    body = request.get_json(force=True)
    try:
        price = float(body.get("price", 0))
        stock = float(body.get("stock", 0))
        max_order = int(body.get("max_order", DEFAULT_MAX_ORDER))
    except (TypeError, ValueError):
        return jsonify(error="Price, quantity, and order limit must be numbers."), 400
    if not body.get("name") or price <= 0 or stock < 0 or max_order < 1:
        return jsonify(error="Enter a name, positive price, and valid quantities."), 400
    product_id = body.get("id")
    product = next((p for p in data["products"] if p["id"] == product_id and p["farmer_id"] == user["id"]), None)
    fields = {
        "name": body["name"].strip(), "description": (body.get("description") or "").strip(),
        "image": (body.get("image") or "").strip(), "price": price, "stock": stock,
        "unit": (body.get("unit") or "kg").strip(), "max_order": max_order,
        "category": (body.get("category") or "Produce").strip(),
    }
    if product:
        product.update(fields)
    else:
        product = {"id": "p" + uuid.uuid4().hex[:8], "farmer_id": user["id"], **fields}
        data["products"].append(product)
    save_db(data)
    return jsonify(product=product)


@app.delete("/api/products/<product_id>")
def api_delete_product(product_id: str):
    data, user = require_user("farmer")
    if not user:
        return jsonify(error="Farmer login required."), 401
    product = next((p for p in data["products"] if p["id"] == product_id and p["farmer_id"] == user["id"]), None)
    if not product:
        return jsonify(error="Product not found."), 404
    data["products"].remove(product)
    save_db(data)
    return jsonify(ok=True)


@app.post("/api/orders")
def api_order():
    data, user = require_user("consumer")
    if not user:
        return jsonify(error="Consumer login required."), 401
    body = request.get_json(force=True)
    product = next((p for p in data["products"] if p["id"] == body.get("product_id")), None)
    if not product:
        return jsonify(error="Product not found."), 404
    try:
        qty = float(body.get("qty", 0))
    except (TypeError, ValueError):
        return jsonify(error="Enter a valid quantity."), 400
    max_order = int(product.get("max_order", DEFAULT_MAX_ORDER))
    if qty < 1 or qty > max_order:
        return jsonify(error=f"You can order 1–{max_order} {product.get('unit', 'units')} at a time."), 400
    if qty > product.get("stock", 0):
        return jsonify(error="That quantity is no longer available."), 400
    product["stock"] -= qty
    order = {
        "id": "o" + uuid.uuid4().hex[:8], "buyer_id": user["id"], "farmer_id": product["farmer_id"],
        "product_id": product["id"], "qty": qty, "total": round(qty * product["price"], 2),
        "status": "received", "created": now_iso(),
    }
    data["orders"].append(order)
    save_db(data)
    return jsonify(order=order)


@app.get("/api/orders")
def api_orders():
    data, user = require_user(session.get("role", "consumer"))
    if not user:
        return jsonify(error="Login required."), 401
    orders = [o for o in data["orders"] if o["buyer_id"] == user["id"]] if session["role"] == "consumer" else [o for o in data["orders"] if o["farmer_id"] == user["id"]]
    return jsonify(orders=[order_view(data, order) for order in orders])


@app.post("/api/ratings")
def api_rating():
    data, user = require_user("consumer")
    if not user:
        return jsonify(error="Consumer login required."), 401
    body = request.get_json(force=True)
    farmer_id = body.get("farmer_id")
    if not any(o["buyer_id"] == user["id"] and o["farmer_id"] == farmer_id for o in data["orders"]):
        return jsonify(error="You can rate a farmer after placing an order."), 403
    try:
        stars = int(body.get("stars", 0))
    except (TypeError, ValueError):
        stars = 0
    if not 1 <= stars <= 5:
        return jsonify(error="Choose a rating from 1 to 5 stars."), 400
    review = next((r for r in data["ratings"] if r["farmer_id"] == farmer_id and r["buyer_id"] == user["id"]), None)
    values = {"stars": stars, "comment": (body.get("comment") or "").strip()}
    if review:
        review.update(values)
    else:
        data["ratings"].append({"id": "r" + uuid.uuid4().hex[:8], "farmer_id": farmer_id, "buyer_id": user["id"], **values})
    save_db(data)
    return jsonify(rating=rating_for(data, farmer_id))


if __name__ == "__main__":
    load_db()
    app.run(debug=True, port=5050)