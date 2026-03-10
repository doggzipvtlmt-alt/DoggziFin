import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, g

app = Flask(__name__)
DATABASE = os.environ.get('DATABASE_PATH', 'doggzi.db')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS capex (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                department TEXT NOT NULL,
                date TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS opex (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                department TEXT NOT NULL,
                date TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS deletion_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deleted_by TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                entry_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                department TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    db = get_db()
    total_capex = db.execute('SELECT COALESCE(SUM(amount),0) as total FROM capex').fetchone()['total']
    total_opex  = db.execute('SELECT COALESCE(SUM(amount),0) as total FROM opex').fetchone()['total']

    recent_capex = db.execute(
        'SELECT *, "CAPEX" as type FROM capex ORDER BY date DESC LIMIT 5'
    ).fetchall()
    recent_opex = db.execute(
        'SELECT *, "OPEX" as type FROM opex ORDER BY date DESC LIMIT 5'
    ).fetchall()

    recent = sorted(
        [dict(r) for r in list(recent_capex) + list(recent_opex)],
        key=lambda x: x['date'], reverse=True
    )[:10]

    # Monthly breakdown (last 6 months)
    monthly = db.execute('''
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN type='capex' THEN amount ELSE 0 END) as capex,
               SUM(CASE WHEN type='opex'  THEN amount ELSE 0 END) as opex
        FROM (
            SELECT date, amount, 'capex' as type FROM capex
            UNION ALL
            SELECT date, amount, 'opex'  as type FROM opex
        )
        GROUP BY month ORDER BY month DESC LIMIT 6
    ''').fetchall()
    monthly = [dict(m) for m in monthly][::-1]

    return render_template('index.html',
                           total_capex=total_capex,
                           total_opex=total_opex,
                           recent=recent,
                           monthly=monthly)


@app.route('/capex')
def capex_page():
    db = get_db()
    entries = db.execute('SELECT * FROM capex ORDER BY date DESC').fetchall()
    total   = db.execute('SELECT COALESCE(SUM(amount),0) as t FROM capex').fetchone()['t']
    return render_template('capex.html', entries=[dict(e) for e in entries], total=total)


@app.route('/opex')
def opex_page():
    db = get_db()
    entries = db.execute('SELECT * FROM opex ORDER BY date DESC').fetchall()
    total   = db.execute('SELECT COALESCE(SUM(amount),0) as t FROM opex').fetchone()['t']
    return render_template('opex.html', entries=[dict(e) for e in entries], total=total)


@app.route('/logs')
def logs_page():
    return render_template('logs.html')


@app.route('/org-chart')
def org_chart_page():
    return render_template('org_chart.html')


# ── API ────────────────────────────────────────────────────────────────────────

REQUIRED = ['category', 'description', 'amount', 'department', 'date', 'approved_by']


def validate(data):
    errors = []
    for field in REQUIRED:
        if not data.get(field, '').strip():
            errors.append(f'{field} is required')
    try:
        amt = float(data.get('amount', 0))
        if amt <= 0:
            errors.append('amount must be greater than 0')
    except (ValueError, TypeError):
        errors.append('amount must be a valid number')
    return errors


@app.route('/api/add_capex', methods=['POST'])
def add_capex():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in request.json.items()}
    errors = validate(data)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400
    db = get_db()
    db.execute(
        'INSERT INTO capex (category,description,amount,department,date,approved_by,notes) VALUES (?,?,?,?,?,?,?)',
        (data['category'], data['description'], float(data['amount']),
         data['department'], data['date'], data['approved_by'], data.get('notes', ''))
    )
    db.commit()
    return jsonify({'success': True, 'message': 'CAPEX entry added successfully'})


@app.route('/api/add_opex', methods=['POST'])
def add_opex():
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in request.json.items()}
    errors = validate(data)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400
    db = get_db()
    db.execute(
        'INSERT INTO opex (category,description,amount,department,date,approved_by,notes) VALUES (?,?,?,?,?,?,?)',
        (data['category'], data['description'], float(data['amount']),
         data['department'], data['date'], data['approved_by'], data.get('notes', ''))
    )
    db.commit()
    return jsonify({'success': True, 'message': 'OPEX entry added successfully'})


@app.route('/api/get_capex')
def get_capex():
    db = get_db()
    rows = db.execute('SELECT * FROM capex ORDER BY date DESC').fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/get_opex')
def get_opex():
    db = get_db()
    rows = db.execute('SELECT * FROM opex ORDER BY date DESC').fetchall()
    return jsonify([dict(r) for r in rows])


def _delete_expense_entry(entry_id, table_name, entry_type):
    data = request.json or {}
    password = data.get('password', '')
    deleted_by = (data.get('deleted_by') or '').strip()

    if not deleted_by:
        return jsonify({'success': False, 'message': 'Name is required to delete an entry'}), 400

    if password != '3344':
        return jsonify({'success': False, 'message': 'Incorrect password'}), 403

    db = get_db()
    entry = db.execute(
        f'SELECT id, category, description, amount, department, date FROM {table_name} WHERE id = ?',
        (entry_id,)
    ).fetchone()

    if not entry:
        return jsonify({'success': False, 'message': f'{entry_type} entry not found'}), 404

    db.execute(
        '''
        INSERT INTO deletion_logs (deleted_by, entry_type, entry_id, category, description, amount, department, entry_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            deleted_by,
            entry_type,
            entry['id'],
            entry['category'],
            entry['description'],
            float(entry['amount']),
            entry['department'],
            entry['date']
        )
    )
    db.execute(f'DELETE FROM {table_name} WHERE id = ?', (entry_id,))
    db.commit()

    return jsonify({'success': True, 'message': f'{entry_type} entry deleted successfully'})


@app.route('/api/delete_capex/<int:entry_id>', methods=['DELETE'])
def delete_capex(entry_id):
    return _delete_expense_entry(entry_id, 'capex', 'CAPEX')


@app.route('/api/delete_opex/<int:entry_id>', methods=['DELETE'])
def delete_opex(entry_id):
    return _delete_expense_entry(entry_id, 'opex', 'OPEX')


@app.route('/api/deletion_logs')
def deletion_logs():
    if request.args.get('password', '') != '3344':
        return jsonify({'success': False, 'message': 'Incorrect password'}), 403

    db = get_db()
    rows = db.execute('SELECT * FROM deletion_logs ORDER BY deleted_at DESC').fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == '__main__':
    init_db()
    app.run(debug=True)

init_db()
