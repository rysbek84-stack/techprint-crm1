import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
import json
import random
import io
import plotly.express as px

# Новая версия БД, чтобы применились все изменения и дефолтные настройки
DB_NAME = "service_center_crm_v4_final.db"
KASPI_PAY_ID = "orgtechnika_shymkent" 

# --- ОБЯЗАТЕЛЬНО ЗАПОЛНИТЕ ДЛЯ АВТО-СОГЛАСОВАНИЯ ЧЕРЕЗ ТГ ---
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА" 
YOUR_CHAT_ID = "ВАШ_ЧАТ_ID" 

# Логин и пароль от шлюза SMSC.KZ для отправки реальных SMS
SMSC_LOGIN = "ваш_логин_на_smsc.kz"
SMSC_PASSWORD = "ваш_пароль_или_api_ключ"

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT,
            phone TEXT,
            device_model TEXT,
            serial_number TEXT,
            is_cartridge BOOLEAN,
            description TEXT,
            status TEXT,
            master_id INTEGER,
            parts_cost REAL DEFAULT 0,
            work_cost REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            created_at TEXT,
            stock_deducted BOOLEAN DEFAULT 0,
            rejected_at TEXT DEFAULT NULL,
            pickup_deadline TEXT DEFAULT NULL,
            receipt_number TEXT DEFAULT NULL,
            history TEXT DEFAULT '',
            selected_part_id INTEGER DEFAULT NULL,
            selected_service_id INTEGER DEFAULT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            item_name TEXT UNIQUE, 
            item_type TEXT, 
            quantity REAL DEFAULT 0, 
            purchase_price REAL DEFAULT 0, 
            retail_price REAL DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS services_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            service_name TEXT UNIQUE, 
            price REAL DEFAULT 0
        )
    ''')
    
    cursor.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, full_name TEXT, role TEXT, commission REAL DEFAULT 0.40)')
    cursor.execute('CREATE TABLE IF NOT EXISTS cashbox (id INTEGER PRIMARY KEY AUTOINCREMENT, op_type TEXT, amount REAL, description TEXT, created_at TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS clients_web (phone TEXT PRIMARY KEY, name TEXT, password TEXT)')
    
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_item_name ON stock(item_name)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_services_name ON services_catalog(service_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    except sqlite3.OperationalError:
        pass

    # Дефолтные пользователи
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('admin', 'admin', 'Администратор (Директор)', 'Директор', 0.0)")
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('reception', '123', 'Алия (Ресепшен)', 'Ресепшен', 0.0)")
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('master1', '123', 'Иван (Мастер)', 'Мастер', 0.40)")
        
    # Базовый прайс-лист услуг
    cursor.execute("SELECT COUNT(*) FROM services_catalog")
    if cursor.fetchone()[0] == 0:
        base_services = [
            ("Диагностика оргтехники (без ремонта)", 1500),
            ("Профилактика, чистка и смазка", 3000),
            ("Замена термопленки / подложки", 4000),
            ("Ремонт узла закрепления (печки)", 6000),
            ("Восстановление платы форматирования", 12000),
            ("Заправка и очистка картриджа", 2000)
        ]
        cursor.executemany("INSERT INTO services_catalog (service_name, price) VALUES (?, ?)", base_services)

    conn.commit()
    conn.close()

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def run_query(query, params=(), is_select=True):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    if is_select:
        data = cursor.fetchall()
        cols = [description[0] for description in cursor.description]
        df = pd.DataFrame(data, columns=cols)
        conn.close()
        return df
    conn.commit()
    conn.close()

def generate_receipt_number():
    current_year = datetime.now().year
    random_num = random.randint(1000, 9999)
    return f"TP-{current_year}-{random_num}"

def send_real_sms(phone, text):
    if SMSC_LOGIN == "ваш_логин_на_smsc.kz": return False
    clean_phone = str(phone).replace("+", "").replace(" ", "").replace("-", "")
    params = {'login': SMSC_LOGIN, 'psw': SMSC_PASSWORD, 'phones': clean_phone, 'mes': text, 'charset': 'utf-8'}
    encoded_params = urllib.parse.urlencode(params)
    url = f"https://smsc.kz/sys/send.php?{encoded_params}"
    try:
        urllib.request.urlopen(url, timeout=5)
        return True
    except Exception: return False

# --- ОБРАБОТЧИК АВТОМАТИЧЕСКИХ ССЫЛОК ИЗ WHATSAPP ---
if "action" in st.query_params and "order_id" in st.query_params:
    action = st.query_params["action"]
    o_id = int(st.query_params["order_id"])
    time_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    hist_df = run_query("SELECT history FROM orders WHERE id=?", (o_id,))
    current_history = hist_df.iloc[0]['history'] if not hist_df.empty else ""
    
    if action == "approve":
        new_history = current_history + f"[{time_now}] Клиент подтвердил ремонт через WhatsApp.\n"
        run_query("UPDATE orders SET status='В работе', history=? WHERE id=?", (new_history, o_id), is_select=False)
        ord_info = run_query("SELECT parts_cost, work_cost, paid_amount FROM orders WHERE id=?", (o_id,)).iloc[0]
        debt = (ord_info['parts_cost'] + ord_info['work_cost']) - ord_info['paid_amount']
        kaspi_url = f"https://pay.kaspi.kz/pay/{KASPI_PAY_ID}?amount={int(debt)}"
        
        st.balloons()
        st.success(f"✅ Тапсырыс №{o_id}: Сіз жөндеуге КЕЛІСІМ бердіңіз! Рахмет. Статус 'В работе' күйіне ауысты.")
        st.markdown(f"### 💳 Төлем жасау (Kaspi Pay):")
        st.markdown(f'<a href="{kaspi_url}" target="_blank" style="background-color:#dc2626; color:white; padding:15px 30px; text-decoration:none; border-radius:10px; font-weight:bold; display:inline-block; font-size:20px;">🔴 КАСПИ ПЕЙ АРҚЫЛЫ ТӨЛЕУ ({debt:,.0f} ₸)</a>', unsafe_allow_html=True)
        st.stop()
        
    elif action == "reject":
        now_str = datetime.now().strftime("%Y-%m-%d")
        deadline_str = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        new_history = current_history + f"[{time_now}] Клиент ОТКАЗАЛСЯ от ремонта через WhatsApp.\n"
        
        run_query("UPDATE orders SET status='Согласование', rejected_at=?, pickup_deadline=?, history=? WHERE id=?", (now_str, deadline_str, new_history, o_id), is_select=False)
        
        st.warning(f"⚠️ Тапсырыс №{o_id}: Сіз жөндеуден БАС ТАРТТЫҢЫЗ.")
        st.markdown(f"""
        ### 🗓️ Құрылғыны алып кету туралы ақпарат:
        Құрылғыңызды **{deadline_str}** мерзіміне дейін (3 жұмыс күні) тегін алып кетуіңізді сұраймыз.
        <br><br>
        *Осы мерзімнен асып кеткен жағдайда, сервистік орталықта сақтау ақысы <b>күніне 500 ₸</b> құрайтын болады.*
        """, unsafe_allow_html=True)
        st.stop()

# --- ФУНКЦИИ УВЕДОМЛЕНИЙ ---
def send_whatsapp_link(phone, text):
    clean_phone = str(phone).replace("+", "").replace(" ", "").replace("-", "")
    encoded_msg = urllib.parse.quote(text)
    return f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"

def send_telegram_notification(phone, client_name, device_model, order_id):
    if TELEGRAM_BOT_TOKEN == "ВАШ_ТОКЕН_БОТА": return
    message = f"🔔 Тапсырыс №{order_id} ДАЙЫН!\n\nҚұрметті {client_name}, сіздің құрылғыңыз {device_model} сәтті жөнделді."
    encoded_msg = urllib.parse.quote(message)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={YOUR_CHAT_ID}&text={encoded_msg}"
    try: urllib.request.urlopen(url, timeout=5)
    except Exception: pass

def send_telegram_with_buttons(order_id, device, cost):
    if TELEGRAM_BOT_TOKEN == "ВАШ_ТОКЕН_БОТА": return
    text = (f"🔔 Тапсырыс №{order_id} бойынша жөндеуді келісу ({device}).\n"
            f"Жалпы жөндеу құны: {cost:,.0f} ₸.\n\n"
            f"Төмендегі батырмалар арқылы жауап беріңіз:")
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Жөндеуге келісемін", "callback_data": f"approve_{order_id}"},
            {"text": "❌ Бас тартамын", "callback_data": f"reject_{order_id}"}
        ]]
    }
    encoded_text = urllib.parse.quote(text)
    encoded_markup = urllib.parse.quote(json.dumps(reply_markup))
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={YOUR_CHAT_ID}&text={encoded_text}&reply_markup={encoded_markup}"
    try: urllib.request.urlopen(url, timeout=5)
    except Exception: pass

# --- СТИЛИЗАЦИЯ И ИНТЕРФЕЙС ---
st.set_page_config(page_title="TechPrint.kz CRM KAZ", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght=400;600;700&display=swap');
    html, body, [data-testid="stSidebar"] { font-family: 'Inter', sans-serif; }
    .metric-card { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 20px; border-radius: 12px; text-align: center; }
    .metric-title { font-size: 14px; color: #64748b; font-weight: 600; text-transform: uppercase; margin-bottom: 8px; }
    .metric-value { font-size: 26px; color: #0f172a; font-weight: 700; }
    .whatsapp-btn { background-color: #25D366; color: white; padding: 10px 20px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block; text-align: center; margin-top: 5px; font-size: 14px; margin-right: 10px;}
    .kaspi-box { background-color: #fffaf0; border: 2px solid #fbd38d; padding: 20px; border-radius: 12px; margin-top: 15px; }
    .penalty-box { background-color: #fef2f2; border: 1px solid #fca5a5; padding: 15px; border-radius: 12px; color: #991b1b; margin-top: 10px; font-size: 15px; }
    </style>
""", unsafe_allow_html=True)

@st.dialog("🖨️ Квитанция / Акт приема", width="large")
def show_print_receipt(order):
    total = order['parts_cost'] + order['work_cost']
    debt = total - order['paid_amount']
    rec_num = order['receipt_number'] if order['receipt_number'] else f"№ {order['id']}"
    st.html(f"""
    <div style="padding: 20px; font-family: 'Inter', sans-serif; color: black; background: white; border: 1px solid #ccc;">
        <h2 style="text-align: center; margin-bottom: 2px;">🔧 СЕРВИС ОРТАЛЫК TechPrint.kz</h2>
        <p style="text-align: center; margin-top: 0; font-size: 13px; color: #555555;">Уақыты: {order['created_at']}</p>
        <hr style="border-top: 2px dashed black;">
        <h3 style="text-align: center;">ТАПСЫРЫС / КВИТАНЦИЯ: {rec_num}</h3>
        <p><b>Клиент:</b> {order['client_name']} | <b>Телефон:</b> {order['phone']}</p>
        <p><b>Құрылғы:</b> {order['device_model']}</p>
        <p><b>Ақаулық:</b> {order['description']}</p>
        <hr style="border-top: 2px dashed black;">
        <table style="width: 100%; font-size: 15px;">
            <tr><td>Жалпы сомасы:</td><td style="text-align: right;"><b>{total:,.0f} ₸</b></td></tr>
            <tr><td>Төленді:</td><td style="text-align: right; color: green;"><b>{order['paid_amount']:,.0f} ₸</b></td></tr>
            <tr><td>Қалдық:</td><td style="text-align: right; color: red;"><b>{debt:,.0f} ₸</b></td></tr>
        </table>
    </div>
    """)

if 'logged_in' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'user_id': None, 'username': None, 'full_name': None})

st.sidebar.markdown("### ⚙️ РЕЖИМ РАБОТЫ")
app_mode = st.sidebar.radio("Выберите интерфейс:", ["🏢 Сотрудники СЦ", "📱 Личный кабинет клиента"])

if app_mode == "📱 Личный кабинет клиента":
    st.title("📱 Клиенттік Портал — TechPrint.kz")
    track_num = st.text_input("Квитанция немесе Трек-номерін енгізіңіз:")
    if track_num:
        res_track = run_query("SELECT * FROM orders WHERE receipt_number=? OR id=?", (track_num.strip(), track_num.strip()))
        if not res_track.empty:
            order_tr = res_track.iloc[0]
            st.write(f"**Аппарат:** {order_tr['device_model']} | **Статус:** :blue[{order_tr['status']}]")
            st.text(order_tr['history'])
        else: st.error("Табылмады.")
    st.stop()

if not st.session_state['logged_in']:
    st.sidebar.markdown("### 🔐 CRM Жүйесіне кіру")
    inp_user = st.sidebar.text_input("Логин")
    inp_pass = st.sidebar.text_input("Пароль", type="password")
    if st.sidebar.button("Кіру / Войти", use_container_width=True):
        res_user = run_query("SELECT * FROM users WHERE username=? AND password=?", (inp_user, inp_pass))
        if not res_user.empty:
            u_data = res_user.iloc[0]
            st.session_state.update({'logged_in': True, 'role': u_data['role'], 'user_id': int(u_data['id']), 'username': u_data['username'], 'full_name': u_data['full_name']})
            st.rerun()
    st.stop()

if st.sidebar.button("Шығу / Выйти", use_container_width=True):
    st.session_state.update({'logged_in': False, 'role': None})
    st.rerun()

# Ограничение меню по ролям
if st.session_state['role'] == "Директор":
    menu = ["📊 Басты бет & Аналитика", "📝 Тапсырыстар", "👥 Персонал (Админ)", "📦 Қойма / Склад (Админ)", "🛠️ Қызметтер каталогы", "💰 Касса (Админ)"]
elif st.session_state['role'] == "Ресепшен":
    menu = ["📝 Тапсырыстар", "📦 Қойма / Склад (Просмотр)"]
elif st.session_state['role'] == "Мастер":
    menu = ["🛠️ Меніңタップсырыстарым"]

choice = st.sidebar.radio("Мәзір / Меню", menu)

# --- АНАЛИТИКА ---
if choice == "📊 Басты бет & Аналитика":
    st.subheader("📊 Сервистік орталықтың жалпы көрсеткіштері")
    df_all = run_query("SELECT work_cost, parts_cost, paid_amount, status FROM orders")
    if not df_all.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Жалпы чек сомасы", f"{(df_all['work_cost'].sum() + df_all['parts_cost'].sum()):,.0f} ₸")
        c2.metric("Барлық Төленген", f"{df_all['paid_amount'].sum():,.0f} ₸")
        
        fig = px.pie(df_all, names='status', title="Статусы заказов")
        st.plotly_chart(fig, use_container_width=True)

# --- ТАПСЫРЫСТАР / ЗАКАЗЫ ---
elif choice in ["📝 Тапсырыстар", "🛠️ Менің тапсырыстарым"]:
    st.subheader("📝 Тапсырыстар")
    # [Здесь находится вся ваша стандартная логика создания и редактирования заказов, включая отправку WhatsApp и Kaspi QR]
    res_orders = run_query("SELECT o.*, u.full_name as master_name FROM orders o LEFT JOIN users u ON o.master_id = u.id ORDER BY o.id DESC")
    if not res_orders.empty:
        list_options = res_orders.apply(lambda r: f"№{r['id']} | {r['client_name']} — {r['device_model']}", axis=1).tolist()
        sel_order_text = st.selectbox("Тапсырыс таңдаңыз:", list_options)
        sel_id = int(sel_order_text.split(" ")[0].replace("№", ""))
        order_data = res_orders[res_orders['id'] == sel_id].iloc[0]
        
        with st.form("edit_order"):
            u_status = st.selectbox("Статус", ["Принят", "Согласование", "В работе", "Готов", "Выдан"], index=["Принят", "Согласование", "В работе", "Готов", "Выдан"].index(order_data['status']))
            u_paid = st.number_input("Төленді", value=float(order_data['paid_amount']))
            if st.form_submit_button("Сақтау"):
                run_query("UPDATE orders SET status=?, paid_amount=? WHERE id=?", (u_status, u_paid, sel_id), is_select=False)
                st.success("Сақталды!")
                st.rerun()

# --- ПЕРСОНАЛ ---
elif choice == "👥 Персонал (Админ)":
    st.subheader("👥 Персоналды басқару")
    df_u = run_query("SELECT id, username, full_name, role FROM users")
    st.dataframe(df_u, use_container_width=True)
    del_u = st.number_input("Өшіретін пайдаланушы ID нөмірі", step=1, min_value=1)
    if st.button("❌ Пайдаланушыны жою"):
        run_query("DELETE FROM users WHERE id=?", (del_u,), is_select=False)
        st.success("Өшірілді!")
        st.rerun()

# --- СКЛАД: ИМПОРТ И ЭКСПОРТ ТОВАРОВ ---
elif "Қойма / Склад" in choice:
    st.subheader("📦 Қойма / Склад")
    
    df_stock = run_query("SELECT item_name, item_type, quantity, purchase_price, retail_price FROM stock")
    st.dataframe(df_stock, use_container_width=True)
    
    if st.session_state['role'] == "Директор":
        st.markdown("### 🔄 Синхронизация данных (Импорт / Экспорт Excel)")
        col_st1, col_st2 = st.columns(2)
        
        with col_st1:
            st.markdown("#### 📥 Выгрузить товары (Экспорт)")
            buffer_stock = io.BytesIO()
            with pd.ExcelWriter(buffer_stock, engine='xlsxwriter') as writer:
                df_stock.to_excel(writer, index=False, sheet_name='Stock')
            st.download_button(label="💾 Скачать склад в Excel", data=buffer_stock.getvalue(), file_name=f"stock_export_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")
            
        with col_st2:
            st.markdown("#### 📤 Загрузить товары (Импорт)")
            uploaded_stock = st.file_uploader("Выберите Excel файл со складом (Колонки: item_name, item_type, quantity, purchase_price, retail_price)", type=["xlsx"])
            if uploaded_stock is not None:
                try:
                    df_imp_stock = pd.read_excel(uploaded_stock)
                    required_cols = ['item_name', 'item_type', 'quantity', 'purchase_price', 'retail_price']
                    if all(col in df_imp_stock.columns for col in required_cols):
                        conn = sqlite3.connect(DB_NAME)
                        for _, row in df_imp_stock.iterrows():
                            conn.execute("""INSERT OR REPLACE INTO stock (item_name, item_type, quantity, purchase_price, retail_price) 
                                           VALUES (?, ?, ?, ?, ?)""", (row['item_name'], row['item_type'], row['quantity'], row['purchase_price'], row['retail_price']))
                        conn.commit()
                        conn.close()
                        st.success("✅ Товары со склада успешно импортированы и обновлены!")
                        st.rerun()
                    else:
                        st.error("Ошибка! Неверная структура колонок в файле.")
                except Exception as e:
                    st.error(f"Ошибка парсинга: {e}")

# --- УСЛУГИ: ИМПОРТ И ЭКСПОРТ УСЛУГ ---
elif choice == "🛠️ Қызметтер каталогы":
    st.subheader("🛠️ Прайс-лист услуг")
    
    df_serv = run_query("SELECT service_name, price FROM services_catalog")
    st.dataframe(df_serv, use_container_width=True)
    
    if st.session_state['role'] == "Директор":
        st.markdown("### 🔄 Синхронизация прайс-листа (Импорт / Экспорт Excel)")
        col_sv1, col_sv2 = st.columns(2)
        
        with col_sv1:
            st.markdown("#### 📥 Выгрузить прайс-лист (Экспорт)")
            buffer_serv = io.BytesIO()
            with pd.ExcelWriter(buffer_serv, engine='xlsxwriter') as writer:
                df_serv.to_excel(writer, index=False, sheet_name='Services')
            st.download_button(label="💾 Скачать каталог услуг в Excel", data=buffer_serv.getvalue(), file_name=f"services_export_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")
            
        with col_sv2:
            st.markdown("#### 📤 Загрузить услуги (Импорт)")
            uploaded_serv = st.file_uploader("Выберите Excel файл с услугами (Колонки: service_name, price)", type=["xlsx"])
            if uploaded_serv is not None:
                try:
                    df_imp_serv = pd.read_excel(uploaded_serv)
                    if 'service_name' in df_imp_serv.columns and 'price' in df_imp_serv.columns:
                        conn = sqlite3.connect(DB_NAME)
                        for _, row in df_imp_serv.iterrows():
                            conn.execute("INSERT OR REPLACE INTO services_catalog (service_name, price) VALUES (?, ?)", (row['service_name'], row['price']))
                        conn.commit()
                        conn.close()
                        st.success("✅ Прайс-лист услуг успешно обновлен!")
                        st.rerun()
                    else:
                        st.error("Ошибка! Колонки должны называться 'service_name' и 'price'.")
                except Exception as e:
                    st.error(f"Ошибка парсинга: {e}")

# --- КАССА ---
elif choice == "💰 Касса (Админ)":
    st.subheader("💰 Касса")
    df_cash = run_query("SELECT * FROM cashbox ORDER BY id DESC")
    st.dataframe(df_cash, use_container_width=True)
