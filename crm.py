import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
import json
import random
import io

# Новая версия БД, чтобы применились все изменения и дефолтные настройки
DB_NAME = "service_center_crm_v5_pro.db"
KASPI_PAY_ID = "orgtechnika_shymkent" 

# --- ОБЯЗАТЕЛЬНО ЗАПОЛНИТЕ ДЛЯ АВТО-СОГЛАСОВАНИЯ ЧЕРЕЗ ТГ ---
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА" 
YOUR_CHAT_ID = "ВАШ_ЧАТ_ID" 

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ И SQL ИНДЕКСОВ ---
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
    
    # --- SQL ИНДЕКСЫ ДЛЯ ОПТИМИЗАЦИИ СКОРОСТИ ПОИСКА ---
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_item_name ON stock(item_name)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_services_name ON services_catalog(service_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_receipt ON orders(receipt_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(phone)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_master ON orders(master_id)")
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

# --- ИМИТАЦИЯ И СИМУЛЯЦИЯ SMS ОТПРАВКИ ---
def send_sms_notification(phone, text):
    # Логика интеграции с SMS-шлюзом (например, СМС-Центр, СМС-Групп и т.д.)
    # В рамках интерфейса выводим всплывающее окно (toast/success)
    st.toast(f"💬 SMS отправлено на {phone}: {text[:30]}...", icon="✉️")

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

def send_telegram_notification(phone, client_name, device_model, order_id, custom_msg=None):
    if TELEGRAM_BOT_TOKEN == "ВАШ_ТОКЕН_БОТА": return
    if custom_msg:
        message = custom_msg
    else:
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
        "inline_keyboard": [
            [
                {"text": "✅ Жөндеуге келісемін", "callback_data": f"approve_{order_id}"},
                {"text": "❌ Бас тартамын", "callback_data": f"reject_{order_id}"}
            ]
        ]
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
    .status-badge { background-color: #e0f2fe; color: #0369a1; padding: 6px 12px; border-radius: 20px; font-weight: bold; display: inline-block; }
    
    /* Стили для Печати и КП */
    .print-container { padding: 30px; font-family: 'Courier New', monospace; color: black; background: white; border: 3px double #333; position: relative; }
    .stamp { position: absolute; bottom: 40px; right: 60px; width: 130px; height: 130px; border: 4px dashed #1d4ed8; border-radius: 50%; opacity: 0.75; text-align: center; color: #1d4ed8; font-weight: bold; font-size: 11px; padding-top: 30px; transform: rotate(-15deg); pointer-events: none; text-transform: uppercase;}
    .signature { font-family: 'Brush Script MT', cursive; font-size: 24px; color: #1e3a8a; border-bottom: 1px solid black; display: inline-block; width: 120px; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- ОКНО ГЕНЕРАЦИИ ДОКУМЕНТОВ (КВИТАНЦИЯ И КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ) ---
@st.dialog("🖨️ Құжаттарды басып шығару (Печать документов)", width="large")
def show_print_receipt(order, doc_type="receipt"):
    total = order['parts_cost'] + order['work_cost']
    debt = total - order['paid_amount']
    rec_num = order['receipt_number'] if order['receipt_number'] else f"№ {order['id']}"
    
    if doc_type == "receipt":
        title_doc = "ТАПСЫРЫС / КВИТАНЦИЯ КВИТАНЦИЯ"
        terms_text = "Құрылғыны қабылдау кезінде сыртқы ақаулар тіркелді. Тегін сақтау мерзімі - дайын болғаннан кейін 3 күн."
    else:
        title_doc = "КОММЕРЦИЯЛЫҚ ҰСЫНЫС (Коммерческое предложение)"
        terms_text = "Бұл құжат көрсетілген қызметтер мен қосалқы бөлшектердің бағасын растайды. Төлем мерзімі — 5 жұмыс күні."

    st.html(f"""
    <div class="print-container">
        <!-- Логотип компании и контакты -->
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid black; padding-bottom: 10px;">
            <div>
                <h2 style="margin: 0; color: #111;">🖨️ TechPrint.kz</h2>
                <small>Сервистік орталық / Шымкент қ.</small>
            </div>
            <div style="text-align: right; font-size: 12px;">
                <b>Телефон:</b> +7 (707) 123-45-67<br>
                <b>Мекен-жайы:</b> Жибек Жолы көшесі, 45<br>
                <b>Трек-номер:</b> {rec_num}
            </div>
        </div>
        
        <h3 style="text-align: center; margin-top: 20px; letter-spacing: 1px;">{title_doc} {rec_num}</h3>
        <p style="text-align: center; font-size: 12px; color: #333;">Күні: {order['created_at']}</p>
        
        <div style="margin-top: 15px; font-size: 14px; line-height: 1.6;">
            <p><b>Тапсырыс беруші (Клиент):</b> {order['client_name']} | <b>Тел:</b> {order['phone']}</p>
            <p><b>Құрылғы үлгісі (Аппарат):</b> {order['device_model']} (S/N: {order['serial_number'] if order['serial_number'] else 'Бор көрсетілмеген'})</p>
            <p><b>Ақаулық сипаттамасы:</b> {order['description']}</p>
        </div>
        
        <table style="width: 100%; font-size: 14px; border-collapse: collapse; margin-top: 20px; border: 1px solid black;">
            <thead>
                <tr style="background-color: #f2f2f2; border-bottom: 1px solid black;">
                    <th style="padding: 8px; text-align: left; border-right: 1px solid black;">Атауы (Наименование)</th>
                    <th style="padding: 8px; text-align: right;">Бағасы (Цена)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid black; border-right: 1px solid black;">Пайдаланылған бөлшектер құны (Запчасти)</td>
                    <td style="padding: 8px; border-bottom: 1px solid black; text-align: right;">{order['parts_cost']:,.0f} ₸</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid black; border-right: 1px solid black;">Шебердің атқарған жұмысы (Услуги/Работа)</td>
                    <td style="padding: 8px; border-bottom: 1px solid black; text-align: right;">{order['work_cost']:,.0f} ₸</td>
                </tr>
                <tr style="font-weight: bold; font-size: 15px;">
                    <td style="padding: 8px; border-right: 1px solid black; text-align: right;">Жалпы сомасы (Итого):</td>
                    <td style="padding: 8px; text-align: right; color: blue;">{total:,.0f} ₸</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border-right: 1px solid black; text-align: right; color: green;">Алдын ала төленді (Оплачено):</td>
                    <td style="padding: 8px; text-align: right; color: green;">{order['paid_amount']:,.0f} ₸</td>
                </tr>
                <tr style="font-weight: bold; font-size: 15px; background: #fff5f5;">
                    <td style="padding: 8px; border-right: 1px solid black; text-align: right; color: red;">Қалдық қарыз (К оплате):</td>
                    <td style="padding: 8px; text-align: right; color: red;">{debt:,.0f} ₸</td>
                </tr>
            </tbody>
        </table>
        
        <p style="font-size: 11px; margin-top: 25px; color: #444; font-style: italic;"><b>Шарттар:</b> {terms_text}</p>
        
        <!-- Подписи и Имитация мокрой круглой печати -->
        <div style="margin-top: 40px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span>Менеджер: ___________</span>
            </div>
            <div style="text-align: right; padding-right: 40px;">
                <span>Директор қолтаңбасы: </span>
                <span class="signature">Т. Аманжол</span>
            </div>
        </div>
        
        <!-- Синяя печать фирмы -->
        <div class="stamp">
            TechPrint.kz<br>
            <span style="font-size:8px;">ШЫМКЕНТ Қ. БИН980745213</span><br>
            * ДИРЕКТОР *
        </div>
    </div>
    """)

if 'logged_in' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'user_id': None, 'username': None, 'full_name': None})

st.sidebar.markdown("### ⚙️ РЕЖИМ РАБОТЫ")
app_mode = st.sidebar.radio("Выберите интерфейс:", ["🏢 Сотрудники СЦ", "📱 Личный кабинет клиента"])

# =====================================================================
# РЕЖИМ 1: ЛИЧНЫЙ КАБИНЕТ КЛИЕНТА
# =====================================================================
if app_mode == "📱 Личный кабинет клиента":
    st.title("📱 Клиенттік Портал — TechPrint.kz")
    st.markdown("### 🔍 Тапсырысты квитанция/трек нөмірі бойынша жылдам тексеру")
    track_num = st.text_input("Квитанция немесе Трек-номерін енгізіңіз (мысалы: TP-2026-4521):", placeholder="TP-2026-XXXX")
    
    if track_num:
        clean_track = track_num.strip()
        res_track = run_query("SELECT * FROM orders WHERE receipt_number=? OR id=?", (clean_track, clean_track))
        if not res_track.empty:
            order_tr = res_track.iloc[0]
            total_tr = order_tr['parts_cost'] + order_tr['work_cost']
            st.markdown("#### 📊 Тапсырыс туралы ақпарат:")
            
            col_tr1, col_tr2, col_tr3 = st.columns(3)
            col_tr1.markdown(f"**Аппарат:** {order_tr['device_model']}")
            col_tr2.markdown(f"**Қабылданған уақыты:** {order_tr['created_at']}")
            col_tr3.write(f"**Қазіргі статус:** :blue[{order_tr['status']}]")
            
            st.progress({"Принят": 20, "Согласование": 40, "В работе": 60, "Готов": 80, "Выдан": 100}.get(order_tr['status'], 10))
            
            st.write(f"**Жалпы сомасы:** {total_tr:,.0f} ₸ | **Төленгені:** {order_tr['paid_amount']:,.0f} ₸")
            st.write("**📝 Соңғы өзгерістер тарихы:**")
            st.text(order_tr['history'] if order_tr['history'] else "Ақпарат жоқ.")
        else:
            st.error("⚠️ Мұндай квитанция немесе трек-номер табылмады. Қайта тексеріп көріңіз.")
            
    st.markdown("---")
    tab_web1, tab_web2 = st.tabs(["🔑 Кабинетке кіру (Полноценный вход)", "📝 Онлайн Тіркелу (Регистрация аппарата)"])
    
    with tab_web2:
        st.markdown("### 📝 Құрылғыны жөндеуге онлайн өткізу")
        c_name = st.text_input("Сіздің аты-жөніз (ФИО)*")
        c_phone = st.text_input("Telephone нөміріңіз (мысалы: 77071234567)*")
        c_device = st.text_input("Аппарат үлгісі (например: Canon LBP6030)*")
        c_desc = st.text_area("Ақаулықтың сипаттамасы (Что сломалось?)")
        c_pass = st.text_input("Кабинет үшін пароль ойлап табыңыз*", type="password")
        
        if st.button("Тіркелу и Квитанция алу", type="primary"):
            if c_name and c_phone and c_device and c_pass:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO clients_web (phone, name, password) VALUES (?, ?, ?)", (c_phone, c_name, c_pass))
                
                rec_no = generate_receipt_number()
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                initial_history = f"[{now_str}] Клиент самостоятельно зарегистрировал устройство на сайте. Статус: Принят.\n"
                
                cursor.execute('''INSERT INTO orders (client_name, phone, device_model, description, status, created_at, receipt_number, history)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (c_name, c_phone, c_device, c_desc, "Принят", now_str, rec_no, initial_history))
                conn.commit()
                conn.close()
                
                send_sms_notification(c_phone, f"TechPrint: Ваша заявка принята. Трек-номер: {rec_no}")
                st.success(f"🎉 Құттықтаймыз, {c_name}! Құрылғыңыз сәтті тіркелді.")
                st.warning(f"📋 СІЗДІҢ ТРЕК/КВИТАНЦИЯ НӨМІРІҢІЗ: {rec_no}")
                st.balloons()
            else:
                st.error("Барлық міндетті өрістерді толтырыңыз!")
                
    with tab_web1:
        st.markdown("### 🔑 Жөндеу тарихын және барлық тапсырыстарды көру")
        web_phone = st.text_input("Телефон нөмірі:")
        web_pass = st.text_input("Пароль:", type="password")
        
        if st.button("Кабинетке кіру"):
            res_client = run_query("SELECT name FROM clients_web WHERE phone=? AND password=?", (web_phone, web_pass))
            if not res_client.empty:
                st.success(f"Қош келдіңіз, {res_client.iloc[0]['name']}!")
                orders_client = run_query("SELECT id, receipt_number, device_model, status, parts_cost, work_cost, paid_amount, history FROM orders WHERE phone=?", (web_phone,))
                if not orders_client.empty:
                    for _, row in orders_client.iterrows():
                        disp_num = row['receipt_number'] if row['receipt_number'] else f"№{row['id']}"
                        total_cost = row['parts_cost'] + row['work_cost']
                        with st.expander(f"📋 Трек: {disp_num} | {row['device_model']} [{row['status']}]"):
                            st.write(f"**Аппарат статусы:** `{row['status']}`")
                            st.write(f"**Жалпы бағасы:** {total_cost:,.0f} ₸")
                            st.write(f"**Төленгені:** {row['paid_amount']:,.0f} ₸")
                            st.write("**🛠️ Жөндеудің толық тарихы (Журнал):**")
                            st.text(row['history'] if row['history'] else "Журнал бостой.")
                else: st.info("Сіздің нөміріңізге байланысты тапсырыстар табылмады.")
            else: st.error("Қате телефон нөмірі немесе пароль!")
    st.stop()

# =====================================================================
# РЕЖИМ 2: СИСТЕМА ДЛЯ СОТРУДНИКОВ
# =====================================================================
if not st.session_state['logged_in']:
    st.sidebar.markdown("### 🔐 CRM Жүйесіне кіру")
    inp_user = st.sidebar.text_input("Логин")
    inp_pass = st.sidebar.text_input("Пароль", type="password")
    if st.sidebar.button("Кіру / Войти", use_container_width=True):
        res_user = run_query("SELECT * FROM users WHERE username=? AND password=?", (inp_user, inp_pass))
        if not res_user.empty:
            u_data = res_user.iloc[0]
            st.session_state.update({
                'logged_in': True, 'role': u_data['role'], 'user_id': int(u_data['id']),
                'username': u_data['username'], 'full_name': u_data['full_name']
            })
            st.rerun()
        else: st.sidebar.error("Қате логин немесе пароль!")
    st.stop()

st.sidebar.markdown(f"👤 **{st.session_state['full_name']}**")
if st.sidebar.button("Шығу / Выйти", type="secondary", use_container_width=True):
    st.session_state.update({'logged_in': False, 'role': None, 'user_id': None})
    st.rerun()

st.sidebar.markdown("---")

if st.session_state['role'] == "Директор":
    menu = ["📊 Продвинутый Дашборд & ABC", "📝 Тапсырыстар", "👥 Персонал (Админ)", "📦 Қойма / Склад (Админ)", "🛠️ Қызметтер каталогы", "💰 Касса (Админ)"]
elif st.session_state['role'] == "Ресепшен":
    menu = ["📝 Тапсырыстар", "📦 Қойма / Склад (Просмотр)", "🛠️ Қызметтер каталогы"]
elif st.session_state['role'] == "Мастер":
    menu = ["📝 Тапсырыстар"]

choice = st.sidebar.radio("Мәзір / Меню", menu)

# --- БЛОК 1: АНАЛИТИКА, ГРАФИКИ И ABC-АНАЛИЗ ---
if choice == "📊 Продвинутый Дашборд & ABC":
    st.subheader("📊 Продвинутый Дашборд и Аналитика СЦ")
    
    df_all = run_query("SELECT o.work_cost, o.parts_cost, o.paid_amount, o.created_at, u.commission FROM orders o LEFT JOIN users u ON o.master_id = u.id")
    if not df_all.empty:
        total_rev = df_all['work_cost'].sum() + df_all['parts_cost'].sum()
        total_paid = df_all['paid_amount'].sum()
        df_all['master_share'] = df_all['work_cost'] * df_all['commission'].fillna(0.4)
        net_profit = df_all['work_cost'].sum() - df_all['master_share'].sum()
        
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f'<div class="metric-card"><div class="metric-title">Общий оборот чеков</div><div class="metric-value">{total_rev:,.0f} ₸</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="metric-card"><div class="metric-title">Всего внесено в кассу</div><div class="metric-value">{total_paid:,.0f} ₸</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="metric-card"><div class="metric-title" style="color:#16a34a;">Чистая прибыль СЦ</div><div class="metric-value" style="color:#16a34a;">{net_profit:,.0f} ₸</div></div>', unsafe_allow_html=True)

        st.markdown("### 📈 Динамика доходов по дням")
        df_all['date'] = df_all['created_at'].apply(lambda x: str(x).split(' ')[0])
        df_chart = df_all.groupby('date')[['paid_amount']].sum()
        st.line_chart(df_chart)

    # --- ABC АНАЛИЗ ЗАПЧАСТЕЙ НА СКЛАДЕ ---
    st.markdown("---")
    st.subheader("📊 ABC-анализ товарных запасов на складе")
    st.caption("Категория A — 80% выручки (критически важные), B — 15% выручки (средние), C — 5% выручки (редкие/дешевые)")
    
    df_stock_abc = run_query("SELECT item_name, quantity, retail_price FROM stock")
    if not df_stock_abc.empty:
        df_stock_abc['total_value'] = df_stock_abc['quantity'] * df_stock_abc['retail_price']
        df_stock_abc = df_stock_abc.sort_values(by='total_value', ascending=False).reset_index(drop=True)
        
        total_stock_value = df_stock_abc['total_value'].sum()
        if total_stock_value > 0:
            df_stock_abc['share'] = df_stock_abc['total_value'] / total_stock_value
            df_stock_abc['cum_share'] = df_stock_abc['share'].cumsum()
            
            def assign_abc(cum_share):
                if cum_share <= 0.80: return 'A ⭐'
                elif cum_share <= 0.95: return 'B 👍'
                else: return 'C 📦'
                
            df_stock_abc['ABC_Category'] = df_stock_abc['cum_share'].apply(assign_abc)
            st.dataframe(df_stock_abc[['item_name', 'quantity', 'retail_price', 'total_value', 'ABC_Category']], use_container_width=True)
            
            # График категорий ABC
            abc_counts = df_stock_abc.groupby('ABC_Category')['total_value'].sum()
            st.bar_chart(abc_counts)
        else:
            st.info("Ценность товаров на складе равна 0.")
    else:
        st.info("Склад пуст для выполнения ABC-анализа.")

    st.markdown("---")
    st.subheader("👨‍🔧 Зарплата мастеров (Выручка за работу)")
    df_masters_salary = run_query("""
        SELECT u.full_name as master_name, 
               u.commission,
               SUM(o.work_cost) as total_work_revenue,
               SUM(o.work_cost * u.commission) as salary_earned
        FROM orders o 
        JOIN users u ON o.master_id = u.id 
        WHERE o.status IN ('Готов', 'Выдан')
        GROUP BY u.id
    """)
    if not df_masters_salary.empty:
        st.dataframe(df_masters_salary, use_container_width=True)

# --- БЛОК 2: ТАПСЫРЫСТАР ---
elif choice == "📝 Тапсырыстар":
    st.subheader("📝 Управление заказами и печать документов")
    
    with st.expander("➕ Жаңа тапсырыс қосу (Добавить новый заказ)"):
        with st.form("add_order_form", clear_on_submit=True):
            c_name = st.text_input("Клиент аты*")
            c_phone = st.text_input("Telephone*")
            d_model = st.text_input("Аппарат үлгісі*")
            s_num = st.text_input("S/N")
            is_cart = st.checkbox("Картридж")
            
            masters_df = run_query("SELECT id, full_name FROM users WHERE role='Мастер'")
            m_options = {row['full_name']: row['id'] for _, row in masters_df.iterrows()}
            m_options["Шебер тағайындалмады"] = None
            selected_m_name = st.selectbox("Шеберді таңдаңыз", list(m_options.keys()))
            desc = st.text_area("Ақаулық сипаттамасы")
            
            if st.form_submit_button("💾 Тапсырысты сақтау"):
                if c_name and c_phone and d_model:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    rec_no = generate_receipt_number()
                    init_history = f"[{now_str}] Тапсырыс қабылданды (Ресепшен). Трек-номер: {rec_no}\n"
                    run_query('''INSERT INTO orders (client_name, phone, device_model, serial_number, is_cartridge, description, status, master_id, created_at, receipt_number, history)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (c_name, c_phone, d_model, s_num, is_cart, desc, "Принят", m_options[selected_m_name], now_str, rec_no, init_history), is_select=False)
                    
                    send_sms_notification(c_phone, f"TechPrint: Принят заказ {rec_no}, статус: Принят.")
                    st.success(f"Тапсырыс қосылды! Квитанция/Трек нөмірі: {rec_no}")
                    st.rerun()

    res_orders = run_query("SELECT o.*, u.full_name as master_name FROM orders o LEFT JOIN users u ON o.master_id = u.id ORDER BY o.id DESC")
    
    if not res_orders.empty:
        buffer_orders = io.BytesIO()
        with pd.ExcelWriter(buffer_orders, engine='xlsxwriter') as writer:
            res_orders.to_excel(writer, index=False, sheet_name='Заказы')
        st.download_button(label="📥 Барлық тапсырыстарды Excel-ге жүктеу", data=buffer_orders.getvalue(), file_name="all_orders.xlsx", mime="application/vnd.ms-excel")
        st.markdown("---")

        list_options = res_orders.apply(lambda r: f"№{r['id']} ({r['receipt_number'] if r['receipt_number'] else 'Бор'}) | {r['client_name']} — {r['device_model']} [{r['status']}]", axis=1).tolist()
        sel_order_text = st.selectbox("Өңдеу үшін тапсырысты таңдаңыз:", list_options)
        sel_id = int(sel_order_text.split(" ")[0].replace("№", ""))
        order_data = res_orders[res_orders['id'] == sel_id].iloc[0]
        
        # --- КНОПКИ ДЛЯ ПЕЧАТИ ДОКУМЕНТОВ ---
        doc_col1, doc_col2 = st.columns(2)
        with doc_col1:
            if st.button("🖨️ Квитанцияны басып шығару (С лого и контактами)"):
                show_print_receipt(order_data, doc_type="receipt")
        with doc_col2:
            if st.button("📄 Коммерциялық ұсыныс (С печатью и подписью)"):
                show_print_receipt(order_data, doc_type="commercial")
            
        penalty_amount = 0
        if order_data['pickup_deadline']:
            deadline_date = datetime.strptime(order_data['pickup_deadline'], "%Y-%m-%d").date()
            today = datetime.now().date()
            if today > deadline_date:
                overdue_days = (today - deadline_date).days
                penalty_amount = overdue_days * 500
                st.markdown(f'<div class="penalty-box">🚨 Тегін сақтау мерзімі өтіп кетті! Айыппұл: +{penalty_amount:,.0f} ₸</div>', unsafe_allow_html=True)

        db_parts = run_query("SELECT id, item_name, quantity, retail_price FROM stock WHERE quantity > 0")
        parts_list = ["Без запчасти (только работа)"]
        parts_map = {"Без запчасти (только работа)": {"id": None, "price": 0.0}}
        
        for _, row in db_parts.iterrows():
            display_name = f"{row['item_name']} (Остаток: {row['quantity']} шт) — {row['retail_price']:,.0f} ₸"
            parts_list.append(display_name)
            parts_map[display_name] = {"id": int(row['id']), "price": float(row['retail_price'])}

        db_services = run_query("SELECT id, service_name, price FROM services_catalog")
        services_list = ["Выберите услугу..."]
        services_map = {"Выберите услугу...": {"id": None, "price": 0.0}}
        
        for _, row in db_services.iterrows():
            display_name = f"{row['service_name']} — {row['price']:,.0f} ₸"
            services_list.append(display_name)
            services_map[display_name] = {"id": int(row['id']), "price": float(row['price'])}

        with st.form("edit_order_form"):
            col1, col2, col3 = st.columns(3)
            u_name = col1.text_input("Клиент аты", value=str(order_data['client_name']))
            u_phone = col2.text_input("Телефон", value=str(order_data['phone']))
            u_paid = col3.number_input("💵 ТӨЛЕНДІ (₸)", value=float(order_data['paid_amount']))
            
            st.markdown("#### 🛠️ Тауарлар мен Қызметтерді қоймадан таңдау:")
            c_part, c_serv = st.columns(2)
            sel_part = c_part.selectbox("Қосалқы бөлшек таңдау (ҚОЙМАДАН):", parts_list)
            sel_service = c_serv.selectbox("Қызмет түрін таңдау (КАТАЛОГТАН):", services_list)
            
            auto_parts_cost = parts_map[sel_part]["price"]
            auto_work_cost = services_map[sel_service]["price"]

            col4, col5, col6 = st.columns(3)
            u_status = col4.selectbox("Статус", ["Принят", "Согласование", "В работе", "Готов", "Выдан"], index=["Принят", "Согласование", "В работе", "Готов", "Выдан"].index(order_data['status']))
            
            default_p_cost = float(auto_parts_cost) if sel_part != "Без запчасти (только работа)" else float(order_data['parts_cost'])
            default_w_cost = float(auto_work_cost) if sel_service != "Выберите услугу..." else float(order_data['work_cost'])
            
            u_parts = col5.number_input("Қосалқы бөлшек құны (₸)", value=default_p_cost)
            u_work = col6.number_input("Жұмыс құны (₸)", value=default_w_cost)
            
            masters_df = run_query("SELECT id, full_name FROM users WHERE role='Мастер'")
            m_options = {row['full_name']: row['id'] for _, row in masters_df.iterrows()}
            m_options["Не назначен"] = None
            current_master_name = order_data['master_name'] if order_data['master_name'] else "Не назначен"
            
            if current_master_name not in m_options: m_options[current_master_name] = order_data['master_id']
            u_master = st.selectbox("Шеберді өзгерту", list(m_options.keys()), index=list(m_options.keys()).index(current_master_name))

            total_bill = u_parts + u_work + penalty_amount
            remaining_debt = total_bill - u_paid
            
            if u_status == "Согласование":
                st.markdown("<div class='kaspi-box'>", unsafe_allow_html=True)
                base_url = "https://crm-techprint.streamlit.app"
                msg_full = f"⚙️ TechPrint.kz\nЗаказ: {order_data['receipt_number']}\nСумма ремонта: {total_bill:,.0f} ₸.\n🟢 Согласен: {base_url}/?action=approve&order_id={sel_id}\n🔴 Отказ: {base_url}/?action=reject&order_id={sel_id}"
                
                wa_url_combined = send_whatsapp_link(u_phone, msg_full)
                st.markdown(f'<a href="{wa_url_combined}" target="_blank" class="whatsapp-btn">💬 Отправить меню согласования в WhatsApp</a>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            if st.form_submit_button("💾 Измененияны сақтау"):
                time_now = datetime.now().strftime("%Y-%m-%d %H:%M")
                p_id = parts_map[sel_part]["id"]
                s_catalog_id = services_map[sel_service]["id"]
                
                if u_status in ["В работе", "Готов", "Выдан"] and not order_data['stock_deducted'] and p_id is not None:
                    run_query("UPDATE stock SET quantity = quantity - 1 WHERE id = ?", (p_id,), is_select=False)
                    run_query("UPDATE orders SET stock_deducted = 1 WHERE id = ?", (sel_id,), is_select=False)

                log_comment = f"[{time_now}] Статус өзгерді: {order_data['status']} -> {u_status}. Төленді: {u_paid} ₸.\n"
                new_history = (order_data['history'] if order_data['history'] else "") + log_comment
                
                if u_paid != order_data['paid_amount']:
                    diff = u_paid - order_data['paid_amount']
                    run_query("INSERT INTO cashbox (op_type, amount, description, created_at) VALUES ('Доход', ?, ?, ?)", 
                              (diff, f"Оплата заказа №{sel_id}", time_now), is_select=False)
                
                if u_status != order_data['status']:
                    send_sms_notification(u_phone, f"TechPrint: Ваш заказ №{sel_id} сменил статус на {u_status}")
                    
                run_query("UPDATE orders SET client_name=?, phone=?, paid_amount=?, status=?, parts_cost=?, work_cost=?, master_id=?, history=?, selected_part_id=?, selected_service_id=? WHERE id=?", 
                          (u_name, u_phone, u_paid, u_status, u_parts, u_work, m_options[u_master], new_history, p_id, s_catalog_id, sel_id), is_select=False)
                st.success("Сақталды!")
                st.rerun()

# --- БЛОК 3: ПЕРСОНАЛ ---
elif choice == "👥 Персонал (Админ)":
    st.subheader("👥 Управление персоналом")
    # ... (Остается без изменений)

# --- БЛОК 4: СКЛАД ---
elif "Қойма / Склад" in choice:
    st.subheader("📦 Қойма / Склад")
    df_stock = run_query("SELECT id, item_name, item_type, quantity, purchase_price, retail_price FROM stock")
    st.dataframe(df_stock, use_container_width=True)
    
    if st.session_state['role'] == "Директор":
        st.markdown("### 🔄 Импорт / Экспорт Склада (Excel)")
        col_st1, col_st2 = st.columns(2)
        with col_st1:
            buffer_stock = io.BytesIO()
            with pd.ExcelWriter(buffer_stock, engine='xlsxwriter') as writer:
                df_stock[['item_name', 'item_type', 'quantity', 'purchase_price', 'retail_price']].to_excel(writer, index=False)
            st.download_button(label="📥 Складты Excel-ге жүктеу", data=buffer_stock.getvalue(), file_name="stock.xlsx", mime="application/vnd.ms-excel")
        with col_st2:
            uploaded_stock = st.file_uploader("Excel арқылы қойманы жаңарту", type=["xlsx"])
            if uploaded_stock is not None:
                df_imp = pd.read_excel(uploaded_stock)
                conn = sqlite3.connect(DB_NAME)
                for _, row in df_imp.iterrows():
                    conn.execute("INSERT OR REPLACE INTO stock (item_name, item_type, quantity, purchase_price, retail_price) VALUES (?,?,?,?,?)",
                                 (str(row['item_name']), str(row['item_type']), float(row['quantity']), float(row['purchase_price']), float(row['retail_price'])))
                conn.commit()
                conn.close()
                st.success("Қойма сәтті жаңартылды!")
                st.rerun()

# --- БЛОК 5: КАТАЛОГ УСЛУГ (ДОБАВЛЕН ИМПОРТ И ЭКСПОРТ EXCEL) ---
elif choice == "🛠️ Қызметтер каталогы":
    st.subheader("🛠️ Прайс-лист шаблон қызметтері")
    df_serv = run_query("SELECT id, service_name, price FROM services_catalog")
    st.dataframe(df_serv, use_container_width=True)
    
    if st.session_state['role'] == "Директор":
        st.markdown("### 🔄 Импорт / Экспорт Прайс-листа Услуг")
        col_sv1, col_sv2 = st.columns(2)
        with col_sv1:
            buffer_serv = io.BytesIO()
            with pd.ExcelWriter(buffer_serv, engine='xlsxwriter') as writer:
                df_serv[['service_name', 'price']].to_excel(writer, index=False)
            st.download_button(label="📥 Прайс-листті Excel-ге жүктеу", data=buffer_serv.getvalue(), file_name="services_catalog.xlsx", mime="application/vnd.ms-excel")
        with col_sv2:
            uploaded_serv = st.file_uploader("Excel арқылы қызметтерді жаңарту", type=["xlsx"])
            if uploaded_serv is not None:
                df_serv_imp = pd.read_excel(uploaded_serv)
                conn = sqlite3.connect(DB_NAME)
                for _, row in df_serv_imp.iterrows():
                    conn.execute("INSERT OR REPLACE INTO services_catalog (service_name, price) VALUES (?,?)", (str(row['service_name']), float(row['price'])))
                conn.commit()
                conn.close()
                st.success("Қызметтер каталогы жаңартылды!")
                st.rerun()

# --- БЛОК 6: КАССА ---
elif choice == "💰 Касса (Админ)":
    st.subheader("💰 Сервистік орталықтың кассасы")
    df_cash = run_query("SELECT id, op_type, amount, description, created_at FROM cashbox ORDER BY id DESC")
    st.dataframe(df_cash, use_container_width=True)
