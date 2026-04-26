import os
import io
import csv
import sqlite3
from datetime import datetime,timedelta
from flask import Flask,render_template,request,redirect,url_for,session,send_file,jsonify,flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash,check_password_hash

app=Flask(__name__)
app.secret_key=os.getenv("SECRET_KEY")
os.makedirs('instance', exist_ok=True)
instance_dir = os.path.join(os.path.dirname(__file__), 'instance')
os.makedirs(instance_dir, exist_ok=True)

db_path = os.path.join(instance_dir, 'users.db')

app.config['SQLALCHEMY_DATABASE_URI']=f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False

def migrate_database():
    """Add new columns to existing database if they don't exist"""
    try:
        os.makedirs(os.path.dirname(db_path),exist_ok=True)
        conn=sqlite3.connect(db_path)
        cursor=conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
        table_exists=cursor.fetchone()
        if table_exists:
            cursor.execute("PRAGMA table_info(user)")
            columns=[column[1]for column in cursor.fetchall()]
            if 'is_admin'not in columns:
                print("Adding is_admin column...")
                cursor.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                conn.commit()
                print("is_admin column added successfully")
            if 'created_at'not in columns:
                print("Adding created_at column...")
                cursor.execute("ALTER TABLE user ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
                conn.commit()
                print("created_at column added successfully")
            if 'virtual_bank_balance'not in columns:
                print("Adding virtual_bank_balance column...")
                cursor.execute("ALTER TABLE user ADD COLUMN virtual_bank_balance INTEGER DEFAULT 10000")
                conn.commit()
                print("virtual_bank_balance column added successfully")
        else:
            print("User table doesn't exist yet, will be created by SQLAlchemy")
        conn.close()
        return True
    except Exception as e:
        print(f"Migration error: {e}")
        return False

print("🔄 Checking database migration...")
migrate_database()

db=SQLAlchemy(app)

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(100))
    email=db.Column(db.String(120),unique=True,nullable=False)
    password=db.Column(db.String(128),nullable=False)
    status=db.Column(db.String(10),default='free')
    pro_expiry=db.Column(db.DateTime)
    time_remaining=db.Column(db.Integer,default=7200)
    last_usage_reset=db.Column(db.String(20),default=datetime.now().strftime("%Y-%m-%d"))
    is_admin=db.Column(db.Boolean,default=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    virtual_bank_balance=db.Column(db.Integer,default=10000)

class Purchase(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    months=db.Column(db.Integer,nullable=False)
    amount=db.Column(db.Integer,nullable=False)
    purchase_date=db.Column(db.DateTime,default=datetime.utcnow)

def update_user_status():
    """Downgrade to free if pro plan expired."""
    if "user_id"in session:
        user=User.query.get(session["user_id"])
        if user and user.status=="pro"and user.pro_expiry and user.pro_expiry<datetime.now():
            user.status="free"
            user.pro_expiry=None
            db.session.commit()

def reset_usage_if_needed(user):
    """Resets free usage time if a new day has started."""
    today_str=datetime.now().strftime("%Y-%m-%d")
    if user.last_usage_reset!=today_str:
        user.time_remaining=7200
        user.last_usage_reset=today_str
        db.session.commit()

def admin_required(f):
    """Decorator to require admin access."""
    def decorated_function(*args,**kwargs):
        if "user_id"not in session:
            return redirect(url_for("login"))
        user=User.query.get(session["user_id"])
        if not user or not user.is_admin:
            flash("Access denied. Admin privileges required.","error")
            return redirect(url_for("dashboard"))
        return f(*args,**kwargs)
    decorated_function.__name__=f.__name__
    return decorated_function

def calculate_plan_price(months):
    """Calculate price based on months"""
    prices={1:50,3:120,6:200,12:350}
    return prices.get(months,50)

@app.route('/')
def home():
    update_user_status()
    return render_template("home.html")

@app.route('/login',methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form["email"]
        password=request.form["password"]
        user=User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password,password):
            session["user_id"]=user.id
            session["is_admin"]=user.is_admin
            reset_usage_if_needed(user)
            flash(f"Welcome back, {user.name}!","success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password. Please try again.","error")
    return render_template("login.html")

@app.route('/register',methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form["name"]
        email=request.form["email"]
        password=request.form["password"]
        confirm=request.form["confirm"]
        if password!=confirm:
            flash("Passwords do not match. Please try again.","error")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.","error")
            return render_template("register.html")
        hashed_pw=generate_password_hash(password)
        new_user=User(
            name=name,
            email=email,
            password=hashed_pw,
            status='free',
            time_remaining=7200,
            last_usage_reset=datetime.now().strftime("%Y-%m-%d"),
            is_admin=(email=="admin@signtrack.com"),
            created_at=datetime.utcnow(),
            virtual_bank_balance=10000
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully! Please log in.","success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out successfully.","info")
    return redirect(url_for("home"))

@app.route('/dashboard')
def dashboard():
    if "user_id"not in session:
        return redirect(url_for("login"))
    update_user_status()
    user=User.query.get(session["user_id"])
    return render_template("dashboard.html",user=user)

@app.route('/buy',methods=["GET","POST"])
def buy():
    if "user_id"not in session:
        return redirect(url_for("login"))
    user=User.query.get(session["user_id"])
    if request.method=="POST":
        months=int(request.form["months"])
        amount=calculate_plan_price(months)
        if user.virtual_bank_balance<amount:
            flash(f"Insufficient funds. Your current balance is ₹{user.virtual_bank_balance}. You need ₹{amount}.","error")
            return render_template("buy.html")
        user.virtual_bank_balance-=amount
        print(f"User {user.email} purchased {months} months for ₹{amount}. New virtual bank balance: ₹{user.virtual_bank_balance}")
        if user.status=="pro"and user.pro_expiry and user.pro_expiry>datetime.now():
            expiry=user.pro_expiry+timedelta(days=30*months)
        else:
            expiry=datetime.now()+timedelta(days=30*months)
        user.status="pro"
        user.pro_expiry=expiry
        purchase=Purchase(
            user_id=user.id,
            months=months,
            amount=amount,
            purchase_date=datetime.utcnow()
        )
        db.session.add(purchase)
        db.session.commit()
        flash(f"Pro plan activated! Valid until {expiry.strftime('%B %d, %Y')}","success")
        return redirect(url_for("dashboard"))
    return render_template("buy.html")

@app.route('/download')
def download():
    if "user_id"not in session:
        flash("Please log in to download the app.","error")
        return redirect(url_for("login"))
    file_path="SignTrackInstaller.exe"
    if os.path.exists(file_path):
        return send_file(file_path,as_attachment=True)
    flash("Installer not found. Please contact support.","error")
    return redirect(url_for("dashboard"))

@app.route('/admin')
@admin_required
def admin_dashboard():
    users=User.query.all()
    total_users=len(users)
    pro_users=len([u for u in users if u.status=='pro'])
    free_users=total_users-pro_users
    total_revenue=db.session.query(db.func.sum(Purchase.amount)).scalar()or 0
    today=datetime.now().date()
    new_users_today=len([u for u in users if u.created_at and u.created_at.date()==today])
    active_pro_users=len([u for u in users if u.status=='pro'and u.pro_expiry and u.pro_expiry>datetime.now()])
    week_from_now=datetime.now()+timedelta(days=7)
    expiring_soon=len([u for u in users if u.status=='pro'and u.pro_expiry and u.pro_expiry<=week_from_now])
    current_month=datetime.now().replace(day=1)
    monthly_revenue=db.session.query(db.func.sum(Purchase.amount)).filter(
        Purchase.purchase_date>=current_month
    ).scalar()or 0
    stats={
        'total_users':total_users,
        'pro_users':pro_users,
        'free_users':free_users,
        'total_revenue':total_revenue,
        'new_users_today':new_users_today,
        'active_pro_users':active_pro_users,
        'expiring_soon':expiring_soon,
        'monthly_revenue':monthly_revenue
    }
    return render_template("admin_dashboard.html",users=users,stats=stats)

@app.route('/admin/update_user',methods=['POST'])
@admin_required
def admin_update_user():
    data=request.get_json()
    user=User.query.get(data['id'])
    if user:
        user.name=data['name']
        user.email=data['email']
        user.status=data['status']
        db.session.commit()
        return jsonify({'success':True})
    return jsonify({'success':False,'message':'User not found'})

@app.route('/admin/toggle_status',methods=['POST'])
@admin_required
def admin_toggle_status():
    data=request.get_json()
    user=User.query.get(data['id'])
    if user:
        if user.status=='pro':
            user.status='free'
            user.pro_expiry=None
        else:
            user.status='pro'
            user.pro_expiry=datetime.now()+timedelta(days=30)
        db.session.commit()
        return jsonify({'success':True})
    return jsonify({'success':False,'message':'User not found'})

@app.route('/admin/delete_user',methods=['POST'])
@admin_required
def admin_delete_user():
    data=request.get_json()
    user=User.query.get(data['id'])
    if user and not user.is_admin:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success':True})
    return jsonify({'success':False,'message':'Cannot delete this user'})

@app.route('/admin/export_users')
@admin_required
def admin_export_users():
    users=User.query.all()
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['ID','Name','Email','Status','Pro Expiry','Time Remaining','Created At'])
    for user in users:
        writer.writerow([
            user.id,
            user.name,
            user.email,
            user.status,
            user.pro_expiry.strftime('%Y-%m-%d')if user.pro_expiry else 'N/A',
            f"{user.time_remaining//60}m",
            user.created_at.strftime('%Y-%m-%d')if user.created_at else 'N/A'
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'signtrack_users_{datetime.now().strftime("%Y%m%d")}.csv'
    )

@app.route('/admin/bulk_email',methods=['POST'])
@admin_required
def admin_bulk_email():
    data=request.get_json()
    message=data.get('message','')
    users=User.query.all()
    return jsonify({
        'success':True,
        'message':f'Email sent to {len(users)} users: "{message}"'
    })

@app.route('/admin/cleanup_expired',methods=['POST'])
@admin_required
def admin_cleanup_expired():
    expired_users=User.query.filter(
        User.status=='pro',
        User.pro_expiry<datetime.now()
    ).all()
    count=0
    for user in expired_users:
        user.status='free'
        user.pro_expiry=None
        count+=1
    db.session.commit()
    return jsonify({
        'success':True,
        'message':f'Cleaned up {count} expired pro accounts'
    })

@app.route('/make_admin/<email>')
def make_admin(email):
    """Temporary route to make a user admin - REMOVE IN PRODUCTION!"""
    user=User.query.filter_by(email=email).first()
    if user:
        user.is_admin=True
        db.session.commit()
        return f"User {email} is now an admin!"
    return "User not found"


with app.app_context():
    db.create_all()
    print("Database tables created/verified on function initialization")
    admin=User.query.filter_by(email="admin@signtrack.com").first()
    if not admin:
        admin_user=User(
            name="Admin",
            email="admin@signtrack.com",
            password=generate_password_hash("admin123"),
            status="pro",
            is_admin=True,
            pro_expiry=datetime.now()+timedelta(days=365),
            created_at=datetime.utcnow(),
            virtual_bank_balance=10000
        )
        db.session.add(admin_user)
        db.session.commit()
        print("Admin user created: admin@signtrack.com / admin123")
    else:
        if not admin.is_admin:
            admin.is_admin=True
        if admin.virtual_bank_balance is None:
            admin.virtual_bank_balance=10000
        db.session.commit()
        print("Existing admin user updated with admin privileges and virtual bank balance")
        app.run(debug=False)