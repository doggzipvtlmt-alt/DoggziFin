import os
from io import BytesIO
from uuid import uuid4
from datetime import datetime, timezone

import pandas as pd
from bson import ObjectId
from flask import Flask, jsonify, render_template, request, send_file
from pymongo.errors import DuplicateKeyError
from pymongo import MongoClient, ReturnDocument

app = Flask(__name__)

MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
DEFAULT_MONGO_URI = (
    f"mongodb+srv://doggzipvtlmt_db_user:{MONGO_PASSWORD}@cluster1.a3voff.mongodb.net/?retryWrites=true&w=majority"
    if MONGO_PASSWORD
    else None
)
MONGO_URI = os.getenv("MONGO_URI") or DEFAULT_MONGO_URI

_client = None
_db = None

REQUIRED_EXPENSE_FIELDS = ["category", "description", "amount", "department", "date", "approved_by"]
ALLOWED_TRANSACTION_TYPES = {"inbound", "outbound"}
ALLOWED_TRANSACTION_STATUS = {"completed", "pending", "failed", "refunded"}
ALLOWED_ISSUE_STATUS = {"open", "investigating", "resolved"}


def get_db():
    global _client, _db
    if _db is None:
        if not MONGO_URI:
            raise RuntimeError("MongoDB configuration missing. Set MONGO_URI or MONGO_PASSWORD.")
        _client = MongoClient(MONGO_URI)
        _db = _client["doggzi_finance"]
        init_collections(_db)
    return _db


def init_collections(db):
    existing = set(db.list_collection_names())
    for name in ["capex_expenses", "opex_expenses", "transactions", "transaction_issues", "system_logs", "id_counters"]:
        if name not in existing:
            db.create_collection(name)

    db.capex_expenses.create_index("capex_id", unique=True, partialFilterExpression={"capex_id": {"$exists": True}})
    db.opex_expenses.create_index("opex_id", unique=True, partialFilterExpression={"opex_id": {"$exists": True}})
    db.transactions.create_index("transaction_id", unique=True, partialFilterExpression={"transaction_id": {"$exists": True}})
    db.transactions.create_index("internal_transaction_key", unique=True, partialFilterExpression={"internal_transaction_key": {"$exists": True}})
    db.transaction_issues.create_index("issue_id", unique=True, partialFilterExpression={"issue_id": {"$exists": True}})
    db.system_logs.create_index("log_id", unique=True, partialFilterExpression={"log_id": {"$exists": True}})


def generate_readable_id(counter_key, prefix):
    counter = get_db().id_counters.find_one_and_update(
        {"_id": counter_key},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"{prefix}-{counter['seq']:04d}"


def create_system_log(action_type, module_name, user_id, details, download_type="", file_name="", deleted_record_id="", reason=""):
    get_db().system_logs.insert_one(
        {
            "log_id": generate_readable_id("system_log", "LOG"),
            "action_type": action_type,
            "module_name": module_name,
            "user_id": user_id or "unknown",
            "download_type": download_type,
            "file_name": file_name,
            "deleted_record_id": deleted_record_id,
            "reason": reason,
            "details": details,
            "timestamp": datetime.now(timezone.utc),
            "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr or "unknown"),
        }
    )


def serialize_doc(doc):
    if not doc:
        return doc
    serialized = dict(doc)
    if "_id" in serialized:
        serialized["id"] = str(serialized.pop("_id"))
    for key, value in list(serialized.items()):
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
    return serialized


def parse_amount(value):
    try:
        amount = float(value)
    except (ValueError, TypeError):
        return None
    return amount if amount > 0 else None


def validate_expense(data):
    errors = []
    for field in REQUIRED_EXPENSE_FIELDS:
        if not str(data.get(field, "")).strip():
            errors.append(f"{field} is required")
    if parse_amount(data.get("amount")) is None:
        errors.append("amount must be a valid number greater than 0")
    return errors


def validate_transaction(data):
    required = [
        "amount",
        "payment_method",
        "transaction_type",
        "transaction_category",
        "transaction_status",
    ]
    errors = []
    for field in required:
        if not str(data.get(field, "")).strip():
            errors.append(f"{field} is required")

    if parse_amount(data.get("amount")) is None:
        errors.append("amount must be a valid number greater than 0")

    if data.get("transaction_type") not in ALLOWED_TRANSACTION_TYPES:
        errors.append("transaction_type must be inbound or outbound")

    if data.get("transaction_status") not in ALLOWED_TRANSACTION_STATUS:
        errors.append("transaction_status must be completed, pending, failed, or refunded")

    return errors


def _find_expense_entries(collection_name):
    db = get_db()
    id_field = "capex_id" if collection_name == "capex_expenses" else "opex_id"
    entries = list(db[collection_name].find({}, {"_id": 1, id_field: 1, "category": 1, "description": 1, "amount": 1, "department": 1, "date": 1, "approved_by": 1, "notes": 1}).sort("date", -1))
    return [serialize_doc(entry) for entry in entries]


@app.route("/")
def dashboard():
    db = get_db()

    capex_entries = list(db.capex_expenses.find({}, {"amount": 1, "date": 1, "description": 1}))
    opex_entries = list(db.opex_expenses.find({}, {"amount": 1, "date": 1, "description": 1}))

    total_capex = sum(float(row.get("amount", 0)) for row in capex_entries)
    total_opex = sum(float(row.get("amount", 0)) for row in opex_entries)

    transactions = list(db.transactions.find({}, {"amount": 1, "transaction_type": 1, "transaction_status": 1, "transaction_category": 1, "created_at": 1, "notes": 1, "transaction_id": 1}).sort("created_at", -1))
    total_inbound_revenue = sum(float(t.get("amount", 0)) for t in transactions if t.get("transaction_type") == "inbound")
    total_outbound_expenses = sum(float(t.get("amount", 0)) for t in transactions if t.get("transaction_type") == "outbound")

    today = datetime.now(timezone.utc).date()
    todays_inbound_revenue = 0
    todays_outbound_payments = 0
    for t in transactions:
        created_at = t.get("created_at")
        if not isinstance(created_at, datetime) or created_at.date() != today:
            continue
        if t.get("transaction_type") == "inbound":
            todays_inbound_revenue += float(t.get("amount", 0))
        if t.get("transaction_type") == "outbound":
            todays_outbound_payments += float(t.get("amount", 0))

    net_revenue_today = todays_inbound_revenue - todays_outbound_payments

    pending_transactions = sum(1 for t in transactions if t.get("transaction_status") == "pending")
    failed_transactions = sum(1 for t in transactions if t.get("transaction_status") == "failed")
    refunds_issued = sum(
        float(t.get("amount", 0))
        for t in transactions
        if t.get("transaction_category") == "refund" and t.get("transaction_status") == "refunded"
    )

    recent = []
    for row in capex_entries:
        recent.append({"type": "CAPEX", "description": row.get("description", ""), "amount": float(row.get("amount", 0)), "date": row.get("date", "")})
    for row in opex_entries:
        recent.append({"type": "OPEX", "description": row.get("description", ""), "amount": float(row.get("amount", 0)), "date": row.get("date", "")})
    for row in transactions[:10]:
        recent.append(
            {
                "type": row.get("transaction_type", "transaction").upper(),
                "description": row.get("notes") or row.get("transaction_id", "Transaction"),
                "amount": float(row.get("amount", 0)),
                "date": row.get("created_at").strftime("%Y-%m-%d") if isinstance(row.get("created_at"), datetime) else "",
            }
        )
    recent = sorted(recent, key=lambda x: x.get("date", ""), reverse=True)[:10]

    monthly_map = {}
    for row in capex_entries:
        month = (row.get("date") or "")[:7]
        if month:
            monthly_map.setdefault(month, {"month": month, "capex": 0, "opex": 0})["capex"] += float(row.get("amount", 0))
    for row in opex_entries:
        month = (row.get("date") or "")[:7]
        if month:
            monthly_map.setdefault(month, {"month": month, "capex": 0, "opex": 0})["opex"] += float(row.get("amount", 0))
    monthly = [monthly_map[k] for k in sorted(monthly_map.keys())][-6:]

    return render_template(
        "index.html",
        total_capex=total_capex,
        total_opex=total_opex,
        total_inbound_revenue=total_inbound_revenue,
        total_outbound_expenses=total_outbound_expenses,
        todays_inbound_revenue=todays_inbound_revenue,
        todays_outbound_payments=todays_outbound_payments,
        net_revenue_today=net_revenue_today,
        pending_transactions=pending_transactions,
        failed_transactions=failed_transactions,
        refunds_issued=refunds_issued,
        recent=recent,
        monthly=monthly,
    )


@app.route("/capex")
def capex_page():
    entries = _find_expense_entries("capex_expenses")
    total = sum(float(e.get("amount", 0)) for e in entries)
    return render_template("capex.html", entries=entries, total=total)


@app.route("/opex")
def opex_page():
    entries = _find_expense_entries("opex_expenses")
    total = sum(float(e.get("amount", 0)) for e in entries)
    return render_template("opex.html", entries=entries, total=total)


@app.route("/logs")
def logs_page():
    return render_template("logs.html")


@app.route("/inbound-transactions")
def inbound_transactions_page():
    return render_template("inbound_transactions.html")


@app.route("/outbound-transactions")
def outbound_transactions_page():
    return render_template("outbound_transactions.html")


@app.route("/transaction-issues")
def transaction_issues_page():
    return render_template("transaction_issues.html")


@app.route("/org-chart")
def org_chart_page():
    return render_template("org_chart.html")


@app.route("/api/add_capex", methods=["POST"])
def add_capex():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in (request.json or {}).items()}
    errors = validate_expense(data)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    amount = parse_amount(data.get("amount"))
    capex_id = data.get("capex_id", "")
    if not capex_id:
        return jsonify({"success": False, "errors": ["capex_id is required. Use Generate ID."]}), 400

    try:
        get_db().capex_expenses.insert_one(
            {
                "capex_id": capex_id,
                "internal_record_id": f"ICR-{uuid4().hex[:12].upper()}",
                "category": data["category"],
                "description": data["description"],
                "amount": amount,
                "department": data["department"],
                "date": data["date"],
                "approved_by": data["approved_by"],
                "notes": data.get("notes", ""),
                "created_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        return jsonify({"success": False, "errors": ["capex_id already exists. Generate a new ID."]}), 409
    return jsonify({"success": True, "message": "CAPEX entry added successfully", "capex_id": capex_id})


@app.route("/api/add_opex", methods=["POST"])
def add_opex():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in (request.json or {}).items()}
    errors = validate_expense(data)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    amount = parse_amount(data.get("amount"))
    opex_id = data.get("opex_id", "")
    if not opex_id:
        return jsonify({"success": False, "errors": ["opex_id is required. Use Generate ID."]}), 400
    try:
        get_db().opex_expenses.insert_one(
            {
                "opex_id": opex_id,
                "internal_record_id": f"IOR-{uuid4().hex[:12].upper()}",
                "category": data["category"],
                "description": data["description"],
                "amount": amount,
                "department": data["department"],
                "date": data["date"],
                "approved_by": data["approved_by"],
                "notes": data.get("notes", ""),
                "created_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        return jsonify({"success": False, "errors": ["opex_id already exists. Generate a new ID."]}), 409
    return jsonify({"success": True, "message": "OPEX entry added successfully", "opex_id": opex_id})


@app.route("/api/get_capex")
def get_capex():
    return jsonify(_find_expense_entries("capex_expenses"))


@app.route("/api/get_opex")
def get_opex():
    return jsonify(_find_expense_entries("opex_expenses"))


def _delete_expense_entry(entry_id, collection_name, entry_type):
    data = request.json or {}
    password = data.get("password", "")
    deleted_by = (data.get("deleted_by") or "").strip()

    if not deleted_by:
        return jsonify({"success": False, "message": "Name is required to delete an entry"}), 400

    if password != "3344":
        return jsonify({"success": False, "message": "Incorrect password"}), 403

    db = get_db()
    try:
        object_id = ObjectId(entry_id)
    except Exception:
        return jsonify({"success": False, "message": f"{entry_type} entry not found"}), 404

    entry = db[collection_name].find_one({"_id": object_id})
    if not entry:
        return jsonify({"success": False, "message": f"{entry_type} entry not found"}), 404

    create_system_log(
        action_type="delete",
        module_name=entry_type,
        user_id=deleted_by,
        deleted_record_id=entry.get(f"{entry_type.lower()}_id", str(entry["_id"])),
        reason=data.get("reason", ""),
        details=f"Deleted {entry_type} record {entry.get('description', '')}",
    )
    db[collection_name].delete_one({"_id": object_id})

    return jsonify({"success": True, "message": f"{entry_type} entry deleted successfully"})


@app.route("/api/delete_capex/<entry_id>", methods=["DELETE"])
def delete_capex(entry_id):
    return _delete_expense_entry(entry_id, "capex_expenses", "CAPEX")


@app.route("/api/delete_opex/<entry_id>", methods=["DELETE"])
def delete_opex(entry_id):
    return _delete_expense_entry(entry_id, "opex_expenses", "OPEX")


@app.route("/api/generate_id/<module_name>")
def generate_id(module_name):
    mapping = {
        "capex": ("capex", "CAPEX", "capex_id"),
        "opex": ("opex", "OPEX", "opex_id"),
        "issue": ("transaction_issue", "ISSUE", "issue_id"),
        "outbound": ("outbound_transaction", "OUT", "transaction_id"),
    }
    if module_name not in mapping:
        return jsonify({"success": False, "message": "Unsupported module"}), 400
    counter_key, prefix, field_name = mapping[module_name]
    return jsonify({"success": True, "field": field_name, "value": generate_readable_id(counter_key, prefix)})


@app.route("/api/add_transaction", methods=["POST"])
def add_transaction():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in (request.json or {}).items()}
    errors = validate_transaction(data)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    if data.get("transaction_type") == "inbound":
        transaction_id = data.get("payment_gateway_transaction_id", "")
        if not transaction_id:
            return jsonify({"success": False, "errors": ["payment_gateway_transaction_id is required for inbound transactions"]}), 400
    else:
        transaction_id = data.get("transaction_id", "")
        if not transaction_id:
            return jsonify({"success": False, "errors": ["transaction_id is required. Use Generate ID."]}), 400

    document = {
        "transaction_id": transaction_id,
        "internal_transaction_key": generate_readable_id("internal_transaction_key", "INB" if data.get("transaction_type") == "inbound" else "OUT"),
        "order_id": data.get("order_id", ""),
        "customer_id": data.get("customer_id", ""),
        "vendor_id": data.get("vendor_id", ""),
        "amount": parse_amount(data.get("amount")),
        "payment_method": data["payment_method"],
        "gateway_reference": data.get("gateway_reference", ""),
        "transaction_type": data["transaction_type"],
        "transaction_category": data["transaction_category"],
        "transaction_status": data["transaction_status"],
        "refund_reference": data.get("refund_reference", ""),
        "created_at": datetime.now(timezone.utc),
        "notes": data.get("notes", ""),
    }
    try:
        get_db().transactions.insert_one(document)
    except DuplicateKeyError:
        return jsonify({"success": False, "errors": ["transaction_id already exists"]}), 409

    return jsonify({"success": True, "message": "Transaction added successfully", "transaction_id": transaction_id})


@app.route("/api/get_transactions")
def get_transactions():
    tx_type = request.args.get("transaction_type", "").strip().lower()
    query = {}
    if tx_type in ALLOWED_TRANSACTION_TYPES:
        query["transaction_type"] = tx_type

    rows = list(get_db().transactions.find(query).sort("created_at", -1))
    return jsonify([serialize_doc(r) for r in rows])


@app.route("/api/update_transaction_status/<transaction_id>", methods=["PUT"])
def update_transaction_status(transaction_id):
    data = request.json or {}
    new_status = (data.get("transaction_status") or "").strip().lower()
    if new_status not in ALLOWED_TRANSACTION_STATUS:
        return jsonify({"success": False, "message": "Invalid transaction_status"}), 400

    result = get_db().transactions.update_one(
        {"transaction_id": transaction_id},
        {"$set": {"transaction_status": new_status}},
    )
    if result.matched_count == 0:
        return jsonify({"success": False, "message": "Transaction not found"}), 404

    return jsonify({"success": True, "message": "Transaction status updated"})


@app.route("/api/record_refund", methods=["POST"])
def record_refund():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in (request.json or {}).items()}
    original_transaction_id = data.get("original_transaction_id", "")
    refund_transaction_id = data.get("transaction_id", "") or generate_readable_id("outbound_transaction", "OUT")
    amount = parse_amount(data.get("amount"))

    if not original_transaction_id or amount is None:
        return jsonify({"success": False, "message": "original_transaction_id and valid amount are required"}), 400

    original = get_db().transactions.find_one({"transaction_id": original_transaction_id})
    if not original:
        return jsonify({"success": False, "message": "Original transaction not found"}), 404

    get_db().transactions.insert_one(
        {
            "transaction_id": refund_transaction_id,
            "order_id": original.get("order_id", ""),
            "customer_id": original.get("customer_id", ""),
            "vendor_id": "",
            "amount": amount,
            "payment_method": data.get("payment_method") or original.get("payment_method", ""),
            "gateway_reference": data.get("gateway_reference", ""),
            "transaction_type": "outbound",
            "transaction_category": "refund",
            "transaction_status": "refunded",
            "refund_reference": original_transaction_id,
            "created_at": datetime.now(timezone.utc),
            "notes": data.get("notes", "Refund issued"),
        }
    )

    get_db().transactions.update_one(
        {"transaction_id": original_transaction_id},
        {"$set": {"transaction_status": "refunded"}},
    )

    return jsonify({"success": True, "message": "Refund recorded successfully"})


@app.route("/api/add_transaction_issue", methods=["POST"])
def add_transaction_issue():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in (request.json or {}).items()}
    required = ["transaction_id", "issue_type", "description", "reported_by"]
    errors = [f"{field} is required" for field in required if not str(data.get(field, "")).strip()]
    status = (data.get("status") or "open").strip().lower()
    if status not in ALLOWED_ISSUE_STATUS:
        errors.append("status must be open, investigating, or resolved")

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    issue_id = data.get("issue_id", "")
    if not issue_id:
        return jsonify({"success": False, "errors": ["issue_id is required. Use Generate ID."]}), 400
    try:
        get_db().transaction_issues.insert_one(
            {
                "issue_id": issue_id,
                "internal_record_id": f"IIS-{uuid4().hex[:12].upper()}",
                "transaction_id": data["transaction_id"],
                "issue_type": data["issue_type"],
                "description": data["description"],
                "reported_by": data["reported_by"],
                "status": status,
                "created_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        return jsonify({"success": False, "errors": ["issue_id already exists. Generate a new ID."]}), 409
    return jsonify({"success": True, "message": "Transaction issue created", "issue_id": issue_id})


@app.route("/api/export/<module_name>")
def export_module(module_name):
    collection_map = {
        "capex": ("capex_expenses", {"_id": 0, "internal_record_id": 0}),
        "opex": ("opex_expenses", {"_id": 0, "internal_record_id": 0}),
        "inbound": ("transactions", {"_id": 0, "internal_transaction_key": 0}),
        "outbound": ("transactions", {"_id": 0, "internal_transaction_key": 0}),
    }
    if module_name not in collection_map:
        return jsonify({"success": False, "message": "Unsupported export module"}), 400

    collection_name, projection = collection_map[module_name]
    query = {}
    if module_name in {"inbound", "outbound"}:
        query["transaction_type"] = module_name

    rows = list(get_db()[collection_name].find(query, projection).sort("created_at", -1))
    if not rows:
        rows = [{"message": "No data available"}]

    df = pd.DataFrame(rows)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=module_name.upper())
    output.seek(0)

    filename = f"{module_name}_records_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    create_system_log(
        action_type="download",
        module_name=module_name.upper(),
        user_id=request.args.get("user_id", "unknown"),
        download_type="excel",
        file_name=filename,
        details=f"Downloaded {module_name.upper()} Excel export",
    )
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/system_logs")
def system_logs():
    query = {}
    module_name = (request.args.get("module_name") or "").strip()
    action_type = (request.args.get("action_type") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    if module_name:
        query["module_name"] = module_name
    if action_type:
        query["action_type"] = action_type
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = datetime.fromisoformat(f"{start_date}T00:00:00+00:00")
        if end_date:
            query["timestamp"]["$lte"] = datetime.fromisoformat(f"{end_date}T23:59:59+00:00")

    rows = list(get_db().system_logs.find(query).sort("timestamp", -1))
    return jsonify([serialize_doc(r) for r in rows])


@app.route("/api/get_transaction_issues")
def get_transaction_issues():
    rows = list(get_db().transaction_issues.find({}).sort("created_at", -1))
    return jsonify([serialize_doc(r) for r in rows])


@app.route("/api/update_transaction_issue_status/<issue_id>", methods=["PUT"])
def update_transaction_issue_status(issue_id):
    status = (request.json or {}).get("status", "").strip().lower()
    if status not in ALLOWED_ISSUE_STATUS:
        return jsonify({"success": False, "message": "Invalid status"}), 400

    result = get_db().transaction_issues.update_one({"issue_id": issue_id}, {"$set": {"status": status}})
    if result.matched_count == 0:
        return jsonify({"success": False, "message": "Issue not found"}), 404
    return jsonify({"success": True, "message": "Issue status updated"})


if __name__ == "__main__":
    get_db()
    app.run(debug=True)
