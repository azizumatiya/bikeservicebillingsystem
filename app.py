from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_this_in_production_2025'  # Production માં બદલી નાખજો

client = MongoClient('mongodb://localhost:27017/')
db = client['bike_service_db']
users = db['users']
services = db['services']

# ────────────────────────────────────────────────
# Index
# ────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

# ────────────────────────────────────────────────
# Register
# ────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        mobile = request.form.get('mobile', '').strip()
        password = request.form.get('password', '').strip()
        if not mobile or not password:
            return 'Mobile number and password required.', 400
        if users.find_one({'mobile': mobile}):
            return 'User already exists. Please login.'
        users.insert_one({'mobile': mobile, 'password': password})
        session['user'] = mobile
        return redirect(url_for('home'))
    return render_template('register.html')

# ────────────────────────────────────────────────
# Login
# ────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        mobile = request.form.get('mobile', '').strip()
        password = request.form.get('password', '').strip()
        user = users.find_one({'mobile': mobile, 'password': password})
        if user:
            session['user'] = mobile
            return redirect(url_for('home'))
        return 'Invalid mobile number or password.'
    return render_template('login.html')

# ────────────────────────────────────────────────
# Logout
# ────────────────────────────────────────────────
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# ────────────────────────────────────────────────
# Home
# ────────────────────────────────────────────────
@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))

    user_mobile = session['user']
    user_services = list(services.find({'user_mobile': user_mobile}).sort('created_at', -1))

    monthly_services = defaultdict(list)
    for s in user_services:
        if 'created_at' in s:
            month_key = s['created_at'].strftime('%Y-%m')
            monthly_services[month_key].append(s)

    sorted_months = sorted(monthly_services.keys(), reverse=True)

    years_cursor = services.distinct('created_at', {'user_mobile': user_mobile})
    years = sorted(set(y.year for y in years_cursor if y), reverse=True)
    if not years:
        years = [datetime.now().year]

    return render_template('home.html',
                           monthly_services=monthly_services,
                           sorted_months=sorted_months,
                           years=years)

# ────────────────────────────────────────────────
# Monthly Report Data (AJAX)
# ────────────────────────────────────────────────
@app.route('/monthly_report_data', methods=['GET'])
def monthly_report_data():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_mobile = session['user']
    from_date_str = request.args.get('from')
    to_date_str   = request.args.get('to')
    year_str      = request.args.get('year')
    month_str     = request.args.get('month')

    if from_date_str and to_date_str:
        try:
            start = datetime.strptime(from_date_str, '%Y-%m-%d')
            end   = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        except ValueError:
            return jsonify({'error': 'Invalid date format (use YYYY-MM-DD)'}), 400
        match_stage = {'user_mobile': user_mobile, 'created_at': {'$gte': start, '$lte': end}}
        is_custom_range = True
    else:
        try:
            year = int(year_str or datetime.now().year)
        except:
            year = datetime.now().year
        start = datetime(year, 1, 1)
        end   = datetime(year + 1, 1, 1)
        if month_str:
            try:
                month = int(month_str)
                start = datetime(year, month, 1)
                end   = datetime(year, month + 1, 1) if month < 12 else datetime(year + 1, 1, 1)
            except:
                pass
        match_stage = {'user_mobile': user_mobile, 'created_at': {'$gte': start, '$lt': end}}
        is_custom_range = False

    # Date-wise aggregation
    day_pipeline = [
        {'$match': match_stage},
        {'$group': {
            '_id': {
                'date': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}},
                'mode': '$payment_mode'
            },
            'total_paid': {'$sum': '$paid'},
            'count': {'$sum': 1}
        }},
        {'$sort': {'_id.date': 1}}
    ]

    day_results = list(services.aggregate(day_pipeline))
    day_dict = defaultdict(lambda: {'online': 0.0, 'offline': 0.0, 'total': 0.0, 'count': 0})

    for r in day_results:
        d = r['_id']['date']
        mode = r['_id']['mode']
        paid = float(r['total_paid'] or 0)
        cnt  = int(r['count'] or 0)
        day_dict[d]['count'] += cnt
        if mode == 'Online':
            day_dict[d]['online'] += paid
        elif mode == 'Offline':
            day_dict[d]['offline'] += paid
        day_dict[d]['total'] += paid

    date_wise = []
    for date_str, vals in sorted(day_dict.items()):
        date_wise.append({
            'date': date_str,
            'online': round(vals['online'], 2),
            'offline': round(vals['offline'], 2),
            'total': round(vals['total'], 2),
            'count': vals['count']
        })

    total_online  = sum(item['online']  for item in date_wise)
    total_offline = sum(item['offline'] for item in date_wise)
    total_all     = sum(item['total']   for item in date_wise)

    response = {
        'selected': {'online': total_online, 'offline': total_offline, 'total': total_all},
        'date_wise': date_wise
    }

    if not is_custom_range:
        gujarati_months = ['જાન્યુઆરી','ફેબ્રુઆરી','માર્ચ','એપ્રિલ','મે','જૂન','જુલાઈ','ઓગસ્ટ','સપ્ટેમ્બર','ઓક્ટોબર','નવેમ્બર','ડિસેમ્બર']
        monthly_pipeline = [
            {'$match': match_stage},
            {'$group': {
                '_id': {'month': {'$month': '$created_at'}, 'mode': '$payment_mode'},
                'total_paid': {'$sum': '$paid'}
            }},
            {'$sort': {'_id.month': 1}}
        ]
        monthly_results = list(services.aggregate(monthly_pipeline))
        online_monthly  = [0.0] * 12
        offline_monthly = [0.0] * 12
        for r in monthly_results:
            m = r['_id']['month'] - 1
            paid = float(r['total_paid'] or 0)
            if r['_id']['mode'] == 'Online':
                online_monthly[m] = paid
            elif r['_id']['mode'] == 'Offline':
                offline_monthly[m] = paid
        response.update({
            'months': gujarati_months,
            'online': online_monthly,
            'offline': offline_monthly
        })

    return jsonify(response)

# ─── Garage Routes ────────────────────────────────────────────────
@app.route('/garage1', methods=['GET', 'POST'])
def garage1():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST': return handle_add_service('garage1')
    slist = list(services.find({'user_mobile': session['user'], 'section': 'garage1'}))
    return render_template('section.html', section='Garage 1', services=slist)

@app.route('/garage2', methods=['GET', 'POST'])
def garage2():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST': return handle_add_service('garage2')
    slist = list(services.find({'user_mobile': session['user'], 'section': 'garage2'}))
    return render_template('section.html', section='Garage 2', services=slist)

@app.route('/showroom', methods=['GET', 'POST'])
def showroom():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST': return handle_add_service('showroom')
    slist = list(services.find({'user_mobile': session['user'], 'section': 'showroom'}))
    return render_template('section.html', section='Showroom', services=slist)

def handle_add_service(section):
    try:
        customer_name   = request.form.get('customer_name', '')
        customer_number = request.form.get('customer_number', '')
        bike_name       = request.form.get('bike_name', '')
        bike_number     = request.form.get('bike_number', '')
        payment_mode    = request.form.get('payment_mode', 'Offline')
        paid            = float(request.form.get('paid', '0'))
        total           = float(request.form.get('total', '0'))
        pending         = total - paid

        services_list = []
        i = 1
        while True:
            desc = request.form.get(f'service_desc_{i}')
            if not desc: break
            price = float(request.form.get(f'price_{i}', '0'))
            services_list.append({'desc': desc, 'price': price})
            i += 1

        doc = {
            'user_mobile': session['user'],
            'section': section,
            'customer_name': customer_name,
            'customer_number': customer_number,
            'bike_name': bike_name,
            'bike_number': bike_number,
            'services': services_list,
            'total': total,
            'payment_mode': payment_mode,
            'paid': paid,
            'pending': pending,
            'created_at': datetime.utcnow()
        }
        services.insert_one(doc)
        return redirect(url_for(section))
    except Exception as e:
        return f"Error adding service: {str(e)}", 500

# ─── Edit Service ────────────────────────────────────────────────
@app.route('/edit_service/<id>', methods=['GET', 'POST'])
def edit_service(id):
    if 'user' not in session:
        return redirect(url_for('login'))
    
    try:
        entry = services.find_one({'_id': ObjectId(id), 'user_mobile': session['user']})
        if not entry:
            return 'સર્વિસ મળી નથી અથવા તમારી નથી', 404
    except:
        return 'આઈડી ખોટી છે', 400
    
    if request.method == 'GET':
        return render_template('edit_service.html', entry=entry)
    
    # POST - Update
    if request.method == 'POST':
        try:
            customer_name   = request.form.get('customer_name', '').strip()
            customer_number = request.form.get('customer_number', '').strip()
            bike_name       = request.form.get('bike_name', '').strip()
            bike_number     = request.form.get('bike_number', '').strip()
            payment_mode    = request.form.get('payment_mode', 'Offline')

            paid_str  = request.form.get('paid', '0')
            total_str = request.form.get('total', '0')
            paid  = float(paid_str)  if paid_str.replace('.', '', 1).replace('-', '', 1).isdigit() else 0.0
            total = float(total_str) if total_str.replace('.', '', 1).replace('-', '', 1).isdigit() else 0.0
            pending = total - paid

            services_list = []
            i = 1
            while True:
                desc_key = f'service_desc_{i}'
                price_key = f'price_{i}'
                if desc_key not in request.form:
                    break
                desc = request.form.get(desc_key, '').strip()
                price_str = request.form.get(price_key, '0')
                price = float(price_str) if price_str.replace('.', '', 1).replace('-', '', 1).isdigit() else 0.0
                if desc:
                    services_list.append({'desc': desc, 'price': price})
                i += 1

            result = services.update_one(
                {'_id': ObjectId(id), 'user_mobile': session['user']},
                {'$set': {
                    'customer_name':   customer_name,
                    'customer_number': customer_number,
                    'bike_name':       bike_name,
                    'bike_number':     bike_number,
                    'services':        services_list,
                    'total':           total,
                    'payment_mode':    payment_mode,
                    'paid':            paid,
                    'pending':         pending
                }}
            )

            if result.modified_count == 1:
                return redirect(url_for('home'))
            else:
                return redirect(url_for('home'))  # કોઈ ફેરફાર ન હોય તો પણ પાછા જાઓ

        except Exception as e:
            return f"અપડેટ થયું નહીં: {str(e)}", 500

# ─── Delete Service ────────────────────────────────────────────────
@app.route('/delete_service/<id>', methods=['POST'])
def delete_service(id):
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        result = services.delete_one({
            '_id': ObjectId(id),
            'user_mobile': session['user']
        })
        if result.deleted_count == 1:
            return jsonify({'success': True, 'message': 'Deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Not found or not yours'}), 404
    except:
        return jsonify({'success': False, 'message': 'Delete error'}), 500

# ─── Search ────────────────────────────────────────────────
@app.route('/search', methods=['POST'])
def search():
    if 'user' not in session: return redirect(url_for('login'))
    query = request.form.get('query', '').strip()
    if not query: return redirect(url_for('home'))

    results = list(services.find({
        'user_mobile': session['user'],
        '$or': [
            {'customer_name':   {'$regex': query, '$options': 'i'}},
            {'customer_number': {'$regex': query, '$options': 'i'}},
            {'bike_number':     {'$regex': query, '$options': 'i'}}
        ]
    }).sort('created_at', -1))

    return render_template('search.html', results=results)

# ─── Pending Payments ────────────────────────────────────────────────
@app.route('/pending')
def pending():
    if 'user' not in session:
        return redirect(url_for('login'))

    user_mobile = session['user']
    pending_services = list(services.find({
        'user_mobile': user_mobile,
        'pending': {'$gt': 0}
    }).sort('created_at', -1))

    monthly_pending = defaultdict(list)
    total_pending = 0.0

    for s in pending_services:
        if 'created_at' in s:
            month_key = s['created_at'].strftime('%Y-%m')
            monthly_pending[month_key].append(s)
            total_pending += s['pending']

    sorted_months = sorted(monthly_pending.keys(), reverse=True)

    return render_template('pending.html',
                           pending_services=pending_services,
                           monthly_pending=monthly_pending,
                           sorted_months=sorted_months,
                           total_pending=round(total_pending, 2))

# ────────────────────────────────────────────────
# All Bills / All Services Page
# ────────────────────────────────────────────────
# ────────────────────────────────────────────────
# All Bills / All Services Page
# ────────────────────────────────────────────────
@app.route('/all_bills')
def all_bills():
    if 'user' not in session:
        return redirect(url_for('login'))

    user_mobile = session['user']

    # બધી સર્વિસ લાવો (નવીથી જૂની તરફ)
    all_services = list(services.find({'user_mobile': user_mobile})
                        .sort('created_at', -1))

    # મહિના વાઇઝ ગ્રુપિંગ અને ટોટલ ગણતરી
    monthly_services = defaultdict(list)
    monthly_totals = defaultdict(lambda: {'income': 0.0, 'pending': 0.0})
    
    total_income = 0.0
    total_pending = 0.0

    for s in all_services:
        if 'created_at' in s:
            month_key = s['created_at'].strftime('%Y-%m')
            monthly_services[month_key].append(s)
            
            # મહિના મુજબ સરવાળો
            monthly_totals[month_key]['income'] += s.get('total', 0)
            monthly_totals[month_key]['pending'] += s.get('pending', 0)
            
            # આખા વર્ષનો સરવાળો
            total_income += s.get('total', 0)
            total_pending += s.get('pending', 0)

    sorted_months = sorted(monthly_services.keys(), reverse=True)

    return render_template('all_bills.html',
                           all_services=all_services,
                           monthly_services=monthly_services,
                           monthly_totals=monthly_totals, # આ નવું ઉમેર્યું
                           sorted_months=sorted_months,
                           total_income=round(total_income, 2),
                           total_pending=round(total_pending, 2))
# ─── Bill View ────────────────────────────────────────────────
@app.route('/bill/<id>')
def bill(id):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        entry = services.find_one({'_id': ObjectId(id), 'user_mobile': session['user']})
        if not entry:
            return 'Bill not found', 404
        return render_template('bill.html', entry=entry)
    except:
        return 'Invalid bill ID', 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)  