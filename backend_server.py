from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import time
from datetime import datetime

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173", "http://localhost:3000", "*"])

# Configuration
WHITELIST_DIR = "whitelists"
USERS_FILE = "users.json"
ALL_REGIONS = ["ME", "IND", "ID", "VN", "TH", "BD", "PK", "TW", "EU", "CIS", "NA", "SAC", "BR"]
COIN_COST_PER_UID = 100
DEFAULT_WHITELIST_HOURS = 24

# Helper functions for file operations
def load_json_file(path, default=None):
    """Load JSON file with error handling"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return default if default is not None else {}

def save_json_file(data, path):
    """Save JSON file atomically"""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        print(f"Error saving {path}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

def get_whitelist_path(region):
    """Get path to region's whitelist file"""
    return os.path.join(WHITELIST_DIR, f"whitelist_{region.lower()}.json")

def load_whitelist(region):
    """Load whitelist for a specific region"""
    path = get_whitelist_path(region)
    data = load_json_file(path, {})
    # Convert all keys to strings and values to integers
    return {str(k): int(v) for k, v in data.items()}

def save_whitelist(region, whitelist_data):
    """Save whitelist for a specific region"""
    path = get_whitelist_path(region)
    # Ensure data is in correct format (string keys, int values)
    formatted_data = {str(k): int(v) for k, v in whitelist_data.items()}
    return save_json_file(formatted_data, path)

def load_users():
    """Load user data including coin balances"""
    return load_json_file(USERS_FILE, {})

def save_users(users_data):
    """Save user data"""
    return save_json_file(users_data, USERS_FILE)

def get_user_id():
    """Get user ID from request (simple session-based for now)"""
    # For demo purposes, using a default user
    # In production, implement proper authentication
    return request.headers.get("X-User-ID", "default_user")

def clean_expired_entries(region):
    """Remove expired entries from a region's whitelist"""
    whitelist = load_whitelist(region)
    now = int(time.time())
    expired_uids = [uid for uid, expiry in whitelist.items() if expiry <= now]
    
    for uid in expired_uids:
        del whitelist[uid]
    
    if expired_uids:
        save_whitelist(region, whitelist)
    
    return len(expired_uids)

# API Endpoints

@app.route("/api/regions", methods=["GET"])
def get_regions():
    """Get list of all supported regions"""
    regions = [
        {"code": "BD", "name": "Bangladesh"},
        {"code": "IND", "name": "India"},
        {"code": "PK", "name": "Pakistan"},
        {"code": "ID", "name": "Indonesia"},
        {"code": "VN", "name": "Vietnam"},
        {"code": "TH", "name": "Thailand"},
        {"code": "ME", "name": "Middle East"},
        {"code": "EU", "name": "Europe"},
        {"code": "NA", "name": "North America"},
        {"code": "BR", "name": "Brazil"},
        {"code": "TW", "name": "Taiwan"},
        {"code": "CIS", "name": "CIS/Russia"},
        {"code": "SAC", "name": "South America"},
    ]
    return jsonify({"success": True, "regions": regions})

@app.route("/api/whitelist/add", methods=["POST"])
def add_to_whitelist():
    """Add UID to whitelist (costs coins)"""
    data = request.json
    uid = data.get("uid", "").strip()
    region = data.get("region", "").upper()
    hours = data.get("hours", DEFAULT_WHITELIST_HOURS)
    
    # Validation
    if not uid or not uid.isdigit():
        return jsonify({"success": False, "error": "Invalid UID format"}), 400
    
    if region not in ALL_REGIONS:
        return jsonify({"success": False, "error": "Invalid region"}), 400
    
    if hours < 1 or hours > 720:
        return jsonify({"success": False, "error": "Hours must be between 1 and 720"}), 400
    
    # Check user has enough coins
    user_id = get_user_id()
    users = load_users()
    user_data = users.get(user_id, {"coins": 0, "history": []})
    
    if user_data.get("coins", 0) < COIN_COST_PER_UID:
        return jsonify({
            "success": False, 
            "error": f"Insufficient coins. Need {COIN_COST_PER_UID}, have {user_data.get('coins', 0)}"
        }), 400
    
    # Load whitelist and add UID
    whitelist = load_whitelist(region)
    expiry = int(time.time()) + (hours * 3600)
    whitelist[uid] = expiry
    
    # Save whitelist
    if not save_whitelist(region, whitelist):
        return jsonify({"success": False, "error": "Failed to save whitelist"}), 500
    
    # Deduct coins
    user_data["coins"] -= COIN_COST_PER_UID
    user_data.setdefault("history", []).append({
        "action": "whitelist_add",
        "uid": uid,
        "region": region,
        "hours": hours,
        "cost": COIN_COST_PER_UID,
        "timestamp": int(time.time())
    })
    users[user_id] = user_data
    save_users(users)
    
    return jsonify({
        "success": True,
        "uid": uid,
        "region": region,
        "expiry": expiry,
        "status": "active",
        "time_remaining": hours * 3600,
        "coins_remaining": user_data["coins"]
    })

@app.route("/api/whitelist/remove", methods=["POST"])
def remove_from_whitelist():
    """Remove UID from whitelist"""
    data = request.json
    uid = data.get("uid", "").strip()
    region = data.get("region", "").upper()
    
    if not uid:
        return jsonify({"success": False, "error": "UID is required"}), 400
    
    if region not in ALL_REGIONS:
        return jsonify({"success": False, "error": "Invalid region"}), 400
    
    # Load whitelist
    whitelist = load_whitelist(region)
    
    if uid not in whitelist:
        return jsonify({"success": False, "error": f"UID {uid} not found in {region} whitelist"}), 404
    
    # Remove UID
    del whitelist[uid]
    
    # Save whitelist
    if not save_whitelist(region, whitelist):
        return jsonify({"success": False, "error": "Failed to save whitelist"}), 500
    
    return jsonify({"success": True, "message": f"UID {uid} removed from {region} whitelist"})

@app.route("/api/whitelist/list", methods=["GET"])
def list_whitelist():
    """List all whitelisted UIDs across all regions"""
    now = int(time.time())
    all_entries = []
    
    for region in ALL_REGIONS:
        whitelist = load_whitelist(region)
        
        for uid, expiry in whitelist.items():
            time_remaining = max(0, expiry - now)
            status = "active" if expiry > now else "expired"
            
            all_entries.append({
                "uid": uid,
                "region": region,
                "expiry": expiry,
                "status": status,
                "time_remaining": time_remaining
            })
    
    # Sort by expiry time (soonest first)
    all_entries.sort(key=lambda x: x["expiry"])
    
    return jsonify({"success": True, "entries": all_entries})

@app.route("/api/whitelist/list/<region>", methods=["GET"])
def list_whitelist_by_region(region):
    """List whitelisted UIDs for a specific region"""
    region = region.upper()
    
    if region not in ALL_REGIONS:
        return jsonify({"success": False, "error": "Invalid region"}), 400
    
    whitelist = load_whitelist(region)
    now = int(time.time())
    entries = []
    
    for uid, expiry in whitelist.items():
        time_remaining = max(0, expiry - now)
        status = "active" if expiry > now else "expired"
        
        entries.append({
            "uid": uid,
            "region": region,
            "expiry": expiry,
            "status": status,
            "time_remaining": time_remaining
        })
    
    entries.sort(key=lambda x: x["expiry"])
    
    return jsonify({"success": True, "entries": entries})

@app.route("/api/whitelist/check", methods=["POST"])
def check_whitelist():
    """Check if UID is whitelisted"""
    data = request.json
    uid = data.get("uid", "").strip()
    region = data.get("region")  # Optional
    
    if not uid:
        return jsonify({"success": False, "error": "UID is required"}), 400
    
    now = int(time.time())
    
    # If region specified, check only that region
    if region:
        region = region.upper()
        if region not in ALL_REGIONS:
            return jsonify({"success": False, "error": "Invalid region"}), 400
        
        whitelist = load_whitelist(region)
        if uid in whitelist:
            expiry = whitelist[uid]
            if expiry > now:
                return jsonify({
                    "success": True,
                    "whitelisted": True,
                    "region": region,
                    "expiry": expiry,
                    "time_remaining": expiry - now
                })
    else:
        # Check all regions
        for reg in ALL_REGIONS:
            whitelist = load_whitelist(reg)
            if uid in whitelist:
                expiry = whitelist[uid]
                if expiry > now:
                    return jsonify({
                        "success": True,
                        "whitelisted": True,
                        "region": reg,
                        "expiry": expiry,
                        "time_remaining": expiry - now
                    })
    
    return jsonify({"success": True, "whitelisted": False})

@app.route("/api/coins/balance", methods=["GET"])
def get_coin_balance():
    """Get user's coin balance"""
    user_id = get_user_id()
    users = load_users()
    user_data = users.get(user_id, {"coins": 0})
    
    return jsonify({
        "success": True,
        "user_id": user_id,
        "coins": user_data.get("coins", 0)
    })

@app.route("/api/coins/add", methods=["POST"])
def add_coins():
    """Add coins to user (called after ad completion)"""
    data = request.json
    amount = data.get("amount", 0)
    reason = data.get("reason", "ad_view")
    
    if amount <= 0 or amount > 1000:
        return jsonify({"success": False, "error": "Invalid amount"}), 400
    
    user_id = get_user_id()
    users = load_users()
    user_data = users.get(user_id, {"coins": 0, "history": []})
    
    user_data["coins"] = user_data.get("coins", 0) + amount
    user_data.setdefault("history", []).append({
        "action": "coins_add",
        "amount": amount,
        "reason": reason,
        "timestamp": int(time.time())
    })
    
    users[user_id] = user_data
    save_users(users)
    
    return jsonify({
        "success": True,
        "coins": user_data["coins"],
        "added": amount,
        "reason": reason
    })

@app.route("/api/coins/history", methods=["GET"])
def get_coin_history():
    """Get user's coin transaction history"""
    user_id = get_user_id()
    users = load_users()
    user_data = users.get(user_id, {"coins": 0, "history": []})
    
    return jsonify({
        "success": True,
        "history": user_data.get("history", [])
    })

@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get overall statistics"""
    total_whitelisted = 0
    active_whitelisted = 0
    now = int(time.time())
    
    for region in ALL_REGIONS:
        whitelist = load_whitelist(region)
        total_whitelisted += len(whitelist)
        active_whitelisted += sum(1 for expiry in whitelist.values() if expiry > now)
    
    users = load_users()
    total_users = len(users)
    total_coins = sum(user.get("coins", 0) for user in users.values())
    
    return jsonify({
        "success": True,
        "stats": {
            "total_whitelisted": total_whitelisted,
            "active_whitelisted": active_whitelisted,
            "expired_whitelisted": total_whitelisted - active_whitelisted,
            "total_users": total_users,
            "total_coins": total_coins
        }
    })

@app.route("/api/cleanup", methods=["POST"])
def cleanup_expired():
    """Clean up expired entries from all regions"""
    total_removed = 0
    
    for region in ALL_REGIONS:
        removed = clean_expired_entries(region)
        total_removed += removed
    
    return jsonify({
        "success": True,
        "message": f"Cleaned up {total_removed} expired entries"
    })

@app.route("/", methods=["GET"])
def index():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "service": "UID Whitelist Backend",
        "version": "1.0.0",
        "timestamp": int(time.time())
    })

if __name__ == "__main__":
    # Create whitelists directory if it doesn't exist
    os.makedirs(WHITELIST_DIR, exist_ok=True)
    
    # Create empty whitelist files for regions that don't have them
    for region in ALL_REGIONS:
        path = get_whitelist_path(region)
        if not os.path.exists(path):
            save_whitelist(region, {})
            print(f"Created empty whitelist for {region}")
    
    # Create users file if it doesn't exist
    if not os.path.exists(USERS_FILE):
        save_users({})
        print("Created empty users file")
    
    print("Starting UID Whitelist Backend Server...")
    print(f"Whitelist directory: {WHITELIST_DIR}")
    print(f"Supported regions: {', '.join(ALL_REGIONS)}")
    print(f"Coin cost per UID: {COIN_COST_PER_UID}")
    print(f"Default whitelist hours: {DEFAULT_WHITELIST_HOURS}")
    
    # Get port from environment variable (for production deployment) or use 9046 for local
    port = int(os.environ.get("PORT", 9046))
    # Disable debug mode in production
    debug = os.environ.get("FLASK_ENV") != "production"
    
    print(f"Server running on port {port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)
