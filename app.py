from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField # <-- PasswordField を追加
from wtforms.validators import DataRequired, Length, Email, EqualTo # <-- 追加のバリデーター
import os
from flask_bcrypt import Bcrypt # <-- ここを追加
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user # <-- ここを追加

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# --- ここからデータベース設定を修正 ---
# DATABASE_URL という環境変数が存在すればそれを使い（本番環境）、
# 存在しなければSQLiteを使う（開発環境）
db_url = os.environ.get('DATABASE_URL')
if db_url:
    # RenderのPostgreSQLは 'postgres://...' というURLで提供されるが、
    # SQLAlchemy 1.4以降は 'postgresql://...' を推奨するため、置換する
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url.replace("postgres://", "postgresql://", 1)
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
# --- ここまで修正 ---

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
bcrypt = Bcrypt(app) # <-- Bcryptのインスタンスを作成


# --- Flask-Loginの設定 ---
login_manager = LoginManager(app)
login_manager.login_view = 'login' # 未ログイン時にリダイレクトされるビュー（関数名）
login_manager.login_message_category = 'info' # flashメッセージのカテゴリ

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- データベースモデルの定義 ---
# UserMixin を継承することで、Flask-Loginが必要とするメソッドが追加される
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    # 'Item' モデルとの関連付け (リレーションシップ)
    # backref='author' は、Item側から User を参照するときの名前
    # lazy=True は、関連するアイテムが必要になったときに初めて読み込む設定
    items = db.relationship('Item', backref='author', lazy=True)
    
    # パスワードをハッシュ化して保存するためのプロパティ
    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    # パスワードの検証メソッド
    def verify_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"User('{self.username}', '{self.email}')"

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    complete = db.Column(db.Boolean, default=False)
    # 外部キー (Foreign Key) の設定
    # 'user.id' は、userテーブルのidカラムを参照することを示す
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# --- ここからフォームクラスを定義 ---
class ItemForm(FlaskForm):
    name = StringField('アイテム名', validators=[DataRequired(message="アイテム名を入力してください。")])
    submit = SubmitField('追加') # SubmitField: 送信ボタン

# --- ここからユーザー登録・ログイン用のフォームクラスを新しく定義 ---
class RegistrationForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('メールアドレス', validators=[DataRequired(), Email()])
    password = PasswordField('パスワード', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('パスワード（確認）', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('登録')

class LoginForm(FlaskForm):
    email = StringField('メールアドレス', validators=[DataRequired(), Email()])
    password = PasswordField('パスワード', validators=[DataRequired()])
    submit = SubmitField('ログイン')

# データベースの初期化
with app.app_context():
    pass # db.create_all() # 新しい complete カラムを持つテーブルが作成される
    # db.create_all() をコメントアウトしないこと

@app.route('/init_db')
def init_db():
    with app.app_context():
        db.create_all()
    return "Database tables created!"
# --- ここまで代替コードを追加 ---

# --- ルーティングを修正 ---
# GET（表示）とPOST（追加処理）を一つのルーティングにまとめる
@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    form = ItemForm() # フォームのインスタンスを作成
    if form.validate_on_submit():
        item_name = form.name.data # フォームから入力データを取得
        # author=current_user で、アイテムと現在ログイン中のユーザーを紐付ける
        new_item = Item(name=item_name, complete=False, author=current_user)
        db.session.add(new_item)
        db.session.commit()
        flash('アイテムが正常に追加されました。', 'success') # <-- flashメッセージを追加（任意）
        return redirect(url_for('index')) # 処理後にリダイレクト（PRGパターン）

    # GETリクエストの場合、またはバリデーションが失敗した場合
    # 現在ログイン中のユーザーのアイテムのみを取得するようにクエリを修正
    items_from_db = Item.query.filter_by(author=current_user).all()
    return render_template('index.html', 
                           title="アイテム管理アプリ",
                           items=items_from_db,
                           form=form) # フォームオブジェクトをテンプレートに渡す

# --- ここから新しいルーティングを追加 ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        # フォームのバリデーションが成功した場合
        username = form.username.data
        email = form.email.data
        password = form.password.data # パスワードはハッシュ化するので直接は使わない

        # ユーザー名とメールアドレスの重複チェック
        existing_user = User.query.filter_by(username=username).first()
        existing_email = User.query.filter_by(email=email).first()

        if existing_user:
            flash('そのユーザー名は既に使用されています。', 'danger')
        elif existing_email:
            flash('そのメールアドレスは既に使用されています。', 'danger')
        else:
            # 新しいユーザーを作成
            new_user = User(username=username, email=email, password=password)
            db.session.add(new_user)
            db.session.commit()
            flash('アカウントが作成されました！ログインしてください。', 'success')
            return redirect(url_for('login')) # ログインページへリダイレクト
    
    # GETリクエストの場合、またはバリデーションが失敗した場合
    return render_template('register.html', title='ユーザー登録', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # current_user はFlask-Loginが提供する変数で、現在ログイン中のユーザーオブジェクトを保持
    if current_user.is_authenticated:
        return redirect(url_for('index')) # 既にログイン済みの場合はトップページへ

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        
        user = User.query.filter_by(email=email).first()

        # ユーザーが存在し、かつパスワードが一致するかを検証
        if user and user.verify_password(password):
            # login_user() 関数でユーザーをログイン状態にする
            # Flask-LoginがセッションにユーザーIDを保存する
            login_user(user)
            flash('ログインに成功しました。', 'success')
            # ログイン後のリダイレクト先を取得
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('ログインに失敗しました。メールアドレスかパスワードを確認してください。', 'danger')

    return render_template('login.html', title='ログイン', form=form)

@app.route('/logout')
def logout():
    logout_user() # Flask-Loginの関数でユーザーをログアウトさせる
    flash('ログアウトしました。', 'info')
    return redirect(url_for('login')) # ログアウト後はログインページへ


@app.route('/update_item/<int:item_id>') # <int:item_id> でIDをURLから受け取る
@login_required
def update_item(item_id):
    # 指定されたIDのアイテムをデータベースから取得
    # db.session.get(モデル, 主キー) で直接取得できる
    item = db.session.get(Item, item_id) 
    if item: # アイテムが存在するか確認
        item.complete = not item.complete # completeの状態を反転させる (True -> False, False -> True)
        db.session.commit() # 変更をデータベースにコミット

    return redirect(url_for('index'))

@app.route('/delete_item/<int:item_id>') # <int:item_id> でIDをURLから受け取る
@login_required
def delete_item(item_id):
    item = db.session.get(Item, item_id)
    if item: # アイテムが存在するか確認
        db.session.delete(item) # データベースセッションからアイテムを削除対象としてマーク
        db.session.commit() # 変更をデータベースにコミット

    return redirect(url_for('index'))

# --- ここまで新しいルーティングを追加 ---

if __name__ == '__main__':
    app.run(debug=True)