import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
import json
import random
import io
import re

# Версия БД с поддержкой термопечати и обновлений
DB_NAME = "service_center_crm_v5_pro.db"
KASPI_PAY_ID = "orgtechnika_shymkent" 

# --- ОБЯЗАТЕЛЬНО ЗАПОЛНИТЕ ДЛЯ АВТО-СОГЛАСОВАНИЯ ЧЕРЕЗ ТГ ---
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА" 
YOUR_CHAT_ID = "ВАШ_ЧАТ_ID" 

# --- УЛУЧШЕННАЯ И ДОПОЛНЕННАЯ ФУНКЦИЯ ПАРСИНГА (КАРТОЧКА + КАТАЛОГ) ---
def parse_copyline_product(url):
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
        
        parsed_uri = urllib.parse.urlparse(url)
        base_domain = f"{parsed_uri.scheme}://{parsed_uri.netloc}"

        # Проверяем, является ли страница КАТАЛОГОМ (списком товаров)
        if 'class="product-item"' in html or 'class="product"' in html or 'class="catalog-item"' in html:
            # Поиск всех блоков товаров в каталоге
            blocks = re.findall(r'<div[^>]+class="[^"]*product-item[^"]*"[^>]*>(.*?)<!--\s*/product-item\s*-->', html, re.DOTALL)
            if not blocks:
                blocks = re.findall(r'<div[^>]+class="[^"]*product_holder[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL)
            
            products_found = []
            
            for block in blocks:
                # Извлекаем ссылку на фото
                img_m = re.search(r'<img[^>]+src="([^"]+)"', block)
                img_url = img_m.group(1) if img_m else ""
                if img_url and not img_url.startswith('http'): 
                    img_url = base_domain + img_url
                
                # Извлекаем название товара и очищаем от HTML-тегов
                name_m = re.search(r'class="name"[^>]*>(.*?)</a>', block, re.DOTALL)
                if not name_m: 
                    name_m = re.search(r'<a[^>]+href="/goods/[^"]+"[^>]*>([^<]+)</a>', block)
                
                if name_m:
                    raw_name = re.sub(r'<[^>]+>', '', name_m.group(1)).strip()
                    # Регулярное выражение для очистки от артикулов в начале и скобок в конце
                    clean_name = re.sub(r'^[A-Za-z0-9\-\.\s]{4,15}(?=\s)', '', raw_name).strip()
                    clean_name = re.sub(r'\s*\[.*?\]|\s*\(.*?\)', '', clean_name).strip()
                else:
                    continue
                    
                # Извлекаем цену товара
                price_m = re.search(r'class="price"[^>]*>([\d\s]+)', block)
                price = float(price_m.group(1).replace(" ", "").strip()) if price_m else 0.0
                
                products_found.append({
                    "title": clean_name, 
                    "price": price, 
                    "type": "Запчасти (Каталог)", 
                    "image": img_url
                })

            if products_found:
                return {"success": True, "is_list": True, "products": products_found}

        # --- СЦЕНАРИЙ ОДИНОЧНОЙ КАРТОЧКИ ТОВАРА ---
        title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else "Неизвестный товар"
        # Очистка названия карточки от артикулов
        title = re.sub(r'^[A-Za-z0-9\-\.\s]{4,15}(?=\s)', '', title).strip()
        title = re.sub(r'\s*\([^)]*\)\s*$', '', title).strip()

        price_match = re.search(r'class="price"[^>]*>([\d\s]+)', html, re.IGNORECASE)
        price = float(price_match.group(1).replace(" ", "").strip()) if price_match else 0.0

        category_match = re.findall(r'<span itemprop="name">(.*?)</span>', html)
        item_type = category_match[-2].strip() if len(category_match) >= 2 else "Запчасти"
        
        img_match = re.search(r'<a[^>]+href="([^"]+\.(?:jpg|jpeg|png))"[^>]+data-fancybox="gallery"', html, re.IGNORECASE)
        if not img_match:
            img_match = re.search(r'<img[^>]+src="([^"]+\.(?:jpg|jpeg|png))"[^>]+id="main-image"', html, re.IGNORECASE)
        
        img_url = ""
        if img_match:
            img_url = img_match.group(1).strip()
            if img_url.startswith('/'):
                img_url = f"{base_domain}{img_url}"
                
        return {
            "success": True, 
            "is_list": False, 
            "products": [{"title": title, "price": price, "type": item_type, "image": img_url}]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

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
    
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_item_name ON stock(item_name)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_services_name ON services_catalog(service_name)")
    except sqlite3.OperationalError:
        pass

    # Дефолтные пользователи
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('admin', 'admin', 'Администратор (Директор)', 'Директор', 0.0)")
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('reception', '123', 'Алия (Ресепшен)', 'Ресепшен', 0.0)")
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('master1', '123', 'Ислам (Мастер)', 'Мастер', 0.40)")
        
    # Базовый прайс-лист услуг
    cursor.execute("SELECT COUNT(*) FROM services_catalog")
    if cursor.fetchone()[0] == 0:
        base_services = [
            ("Диагностика оргтехники (без ремонта)", 1500),
            ("Профилактика, чистка и смазка", 3000),
            ("Замена термопленки / подложки", 4000),
            ("Ремонт узла закрепления (печки)", 6000),
            ("Восстановление платы форматирования", 12000),
            ("Заправка и очистка картриджа", 2000),
            ("Заправка и очистка картриджа (Эконом)", 1700),
            ("Заправка и очистка картриджа (Цветной)", 3000),
            ("Заправка и очистка картриджа (Премиум)", 2500),
            ("Ремонт А4 струйных принтеров", 15000),
            ("Ремонт А3 струйных принтеров", 20000)
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
    
    @media print {
        body * { visibility: hidden; }
        .thermal-print-area, .thermal-print-area * { visibility: visible; }
        .thermal-print-area { 
            position: absolute; 
            left: 0; 
            top: 0; 
            width: 74mm; 
            padding: 0px; 
            margin: 0px; 
            background: white !important; 
            color: black !important;
        }
        .no-print { display: none !important; }
    }
    .thermal-box-preview {
        width: 100%;
        max-width: 290px;
        margin: 0 auto;
        padding: 12px;
        background: #ffffff;
        color: #000000;
        font-family: 'Courier New', monospace;
        font-size: 13px;
        border: 1px dashed #aaaaaa;
        border-radius: 4px;
    }
    </style>
""", unsafe_allow_html=True)

@st.dialog("🖨️ Термопринтер баспасы", width="small")
def show_print_receipt(order):
    # 1. Сначала определяем все данные
    total = order['parts_cost'] + order['work_cost']
    rec_num = order['receipt_number'] if order['receipt_number'] else f"№ {order['id']}"
    
    base_url = "https://crm-techprint.streamlit.app" 
    qr_data = f"{base_url}/?track_num={rec_num}"
    # Генерируем URL картинки QR-кода
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=110x110&data={urllib.parse.quote(qr_data)}"

    # 2. Кнопка печати (используем прямой вызов JS)
    st.markdown(f"""
        <button onclick="window.print();" style="width:100%; padding:15px; background-color:#22c55e; color:white; border:none; border-radius:8px; font-weight:bold; cursor:pointer;">
            🟢 БАСЫП ШЫҒАРУ (ПЕЧАТЬ)
        </button>
    """, unsafe_allow_html=True)
    
    # 3. HTML-разметка квитанции
    st.html(f"""
    <div class="thermal-print-area" style="width: 250px; padding: 10px; font-family: 'Courier New', monospace; font-size: 13px; border: 1px dashed #ccc;">
        <div style="text-align: center;">
            <h3 style="margin: 0;">TechPrint.kz</h3>
            <p>Квитанция: <b>{rec_num}</b></p>
        </div>
        <div style="border-top: 1px dashed black; margin: 5px 0;"></div>
        <p><b>Клиент:</b> {order['client_name']}</p>
        <p><b>Аппарат:</b> {order['device_model']}</p>
        <p><b>Итого:</b> {total:,.0f} ₸</p>
        <div style="text-align: center; margin-top: 10px;">
            <img src="{qr_url}" style="width: 100px; height: 100px;" />
        </div>
    </div>
    """)
st.sidebar.markdown("### ⚙️ РЕЖИМ РАБОТЫ")
app_mode = st.sidebar.radio("Выберите interface:", ["🏢 Сотрудники СЦ", "📱 Личный кабинет клиента"])

# =====================================================================
# РЕЖИМ 1: ЛИЧНЫЙ КАБИНЕТ КЛИЕНТА
# =====================================================================
if app_mode == "📱 Личный кабинет клиента":
    st.title("📱 Клиенттік Портал — TechPrint.kz")
    st.markdown("### 🔍 Тапсырысты квитанция/трек нөмірі бойынша жылдам тексеру")
    
    url_track = st.query_params.get("track_num", "")
    track_num = st.text_input("Квитанция немесе Трек-номерін енгізіңіз (например: TP-2026-4521):", value=url_track, placeholder="TP-2026-XXXX")
    
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
        c_name = st.text_input("Сіздің аты-жөніңіз (ФИО)*")
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
                
                st.success(f"🎉 Құттықтаймыз, {c_name}! Құрылғыңыз сәтті тіркелді.")
                st.warning(f"📋 СІЗДІҢ ТРЕК/КВИТАНЦИЯ НӨМІРІҢІЗ: {rec_no}")
                st.balloons()
            else:
                st.error("Barslyq міндетті өрістерді толтырыңыз!")
                
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
    menu = ["📊 Басты бет & Аналитика", "📝 Тапсырыстар", "👥 Персонал (Админ)", "📦 Қойма / Склад (Админ)", "🛠️ Қызметтер каталогы", "💰 Касса (Админ)"]
elif st.session_state['role'] == "Ресепшен":
    menu = ["📝 Тапсырыстар", "📦 Қойма / Склад (Просмотр)"]
elif st.session_state['role'] == "Мастер":
    menu = ["📝 Тапсырыстар"]

choice = st.sidebar.radio("Мәзір / Меню", menu)

# --- БЛОК 1: АНАЛИТИКА ---
if choice == "📊 Басты бет & Аналитика":
    st.subheader("📊 Сервистік орталықтың жалпы көрсеткіштері")
    df_all = run_query("SELECT o.work_cost, o.parts_cost, o.paid_amount, u.commission FROM orders o LEFT JOIN users u ON o.master_id = u.id")
    if not df_all.empty:
        total_rev = df_all['work_cost'].sum() + df_all['parts_cost'].sum()
        total_paid = df_all['paid_amount'].sum()
        df_all['master_share'] = df_all['work_cost'] * df_all['commission'].fillna(0.4)
        net_profit = df_all['work_cost'].sum() - df_all['master_share'].sum()
        
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f'<div class="metric-card"><div class="metric-title">Жалпы чек сомасы</div><div class="metric-value">{total_rev:,.0f} ₸</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="metric-card"><div class="metric-title">Barslyq To’lengen</div><div class="metric-value">{total_paid:,.0f} ₸</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="metric-card"><div class="metric-title" style="color:#16a34a;">Таза Пайда СЦ</div><div class="metric-value" style="color:#16a34a;">{net_profit:,.0f} ₸</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("👨‍🔧 Шеберлердің еңбекақысын есептеу (Зарплата мастеров)")
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
    else:
        st.info("Дайын немесе тапсырылған жұмыстар бойынша әлі шеберлерге есептелген еңбекақы жоқ.")

# --- БЛОК 2: ТАПСЫРЫСТАР ---
elif choice == "📝 Тапсырыстар":
    st.subheader("📝 Тапсырыстарды басқару жүйесі")
    
    with st.expander("➕ Жаңа тапсырыс қосу"):
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
        
        if st.button("🖨️ КВИТАНЦИЯНЫ ТЕРМОПРИНТЕРГЕ ШЫҒАРУ"):
            show_print_receipt(order_data)
            
        penalty_amount = 0
        if order_data['pickup_deadline']:
            deadline_date = datetime.strptime(order_data['pickup_deadline'], "%Y-%m-%d").date()
            today = datetime.now().date()
            if today > deadline_date:
                overdue_days = (today - deadline_date).days
                penalty_amount = overdue_days * 500
                st.markdown(f"""
                <div class="penalty-box">
                    🚨 <b>ТЕГІН САКТАУ МЕРЗІМІ ӨТІП КЕТТІ ({order_data['pickup_deadline']}).</b><br>
                    Мерзімінен асқан күндер: {overdue_days} күн. <br>
                    <b>Сақтау айыппұлы: +{penalty_amount:,.0f} ₸</b> (күніне 500 ₸).
                </div>
                """, unsafe_allow_html=True)

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
            
            if auto_parts_cost > 0 or auto_work_cost > 0:
                st.info(f"💡 Автоматты қойма бағасы: Бөлшек {auto_parts_cost:,.0f} ₸ | Жұмыс {auto_work_cost:,.0f} ₸")

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
            
            if current_master_name not in m_options:
                m_options[current_master_name] = order_data['master_id']
                
            u_master = st.selectbox("Шеберді өзгерту", list(m_options.keys()), index=list(m_options.keys()).index(current_master_name))

            total_bill = u_parts + u_work + penalty_amount
            remaining_debt = total_bill - u_paid
            st.write(f"**💰 Баланс: Чек: {total_bill:,.0f} ₸ | Қалдық қарыз: {remaining_debt:,.0f} ₸**")
            
            if u_status == "Согласование":
                st.markdown("<div class='kaspi-box'>", unsafe_allow_html=True)
                st.markdown("#### 📱 Клиентпен бағаны келісу және Төлем сілтемелері:")
                
                base_url = "https://crm-techprint.streamlit.app"
                link_approve_crm = f"{base_url}/?action=approve&order_id={sel_id}"
                link_reject_crm = f"{base_url}/?action=reject&order_id={sel_id}"

                disp_rec = order_data['receipt_number'] if order_data['receipt_number'] else f"№{sel_id}"
                msg_full = (
                    f"⚙️ *Сервисный Центр TechPrint.kz*\n"
                    f"Тапрысыс {disp_rec} ({order_data['device_model']})\n"
                    f"Жалпы жөндеу құны: *{total_bill:,.0f} ₸.*\n\n"
                    f"🟢 *ЖӨНДЕУГЕ КЕЛІСЕМІН (СОГЛАСЕН):*\n{link_approve_crm}\n\n"
                    f"🔴 *БАС ТАРТАМЫН (ОТКАЗЫВАЮСЬ):*\n{link_reject_crm}\n\n"
                    f"⚠️ _Ескерту: Бас тартқан жағдайда сақтау ақысы күніне 500 ₸ құрайды._"
                )
                
                wa_url_combined = send_whatsapp_link(u_phone, msg_full)
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    st.markdown(f'<a href="{wa_url_combined}" target="_blank" class="whatsapp-btn">💬 Отправить меню согласования в WhatsApp</a>', unsafe_allow_html=True)
                with col_btn2:
                    if st.form_submit_button("🤖 ТГ Авто-Келісу жолдау"):
                        send_telegram_with_buttons(sel_id, order_data['device_model'], total_bill)
                        st.success("Жіберілді!")

                if remaining_debt > 0:
                    kaspi_url = f"https://pay.kaspi.kz/pay/{KASPI_PAY_ID}?amount={int(remaining_debt)}"
                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=130x130&data={urllib.parse.quote(kaspi_url)}"
                    st.image(qr_url, caption=f"Внутренний Kaspi QR: {remaining_debt:,.0f} ₸")
                st.markdown("</div>", unsafe_allow_html=True)

            if st.form_submit_button("💾 Измененияны сақтау"):
                time_now = datetime.now().strftime("%Y-%m-%d %H:%M")
                p_id = parts_map[sel_part]["id"]
                s_catalog_id = services_map[sel_service]["id"]
                
                if u_status in ["В работе", "Готов", "Выдан"] and not order_data['stock_deducted'] and p_id is not None:
                    run_query("UPDATE stock SET quantity = quantity - 1 WHERE id = ?", (p_id,), is_select=False)
                    run_query("UPDATE orders SET stock_deducted = 1 WHERE id = ?", (sel_id,), is_select=False)
                    st.toast(f"📦 Товар списан со склада (1 шт)!")

                log_comment = f"[{time_now}] Статус өзгерді: {order_data['status']} -> {u_status}. Төленді: {u_paid} ₸. Қосалқы бөлшек: {sel_part}, Қызмет: {sel_service}.\n"
                new_history = (order_data['history'] if order_data['history'] else "") + log_comment
                
                if u_paid != order_data['paid_amount']:
                    diff = u_paid - order_data['paid_amount']
                    run_query("INSERT INTO cashbox (op_type, amount, description, created_at) VALUES ('Доход', ?, ?, ?)", 
                              (diff, f"Оплата заказа №{sel_id}", time_now), is_select=False)
                
                if u_status != order_data['status']:
                    custom_msg = f"🔔 Тапсырыс №{sel_id} статусы өзгерді!\nАппарат: {order_data['device_model']}\nЖаңа статус: *{u_status}*"
                    send_telegram_notification(u_phone, u_name, order_data['device_model'], sel_id, custom_msg=custom_msg)
                    
                run_query("UPDATE orders SET client_name=?, phone=?, paid_amount=?, status=?, parts_cost=?, work_cost=?, master_id=?, history=?, selected_part_id=?, selected_service_id=? WHERE id=?", 
                          (u_name, u_phone, u_paid, u_status, u_parts, u_work, m_options[u_master], new_history, p_id, s_catalog_id, sel_id), is_select=False)
                st.success("Сақталды!")
                st.rerun()

# --- БЛОК 3: ПЕРСОНАЛ ---
elif choice == "👥 Персонал (Админ)":
    st.subheader("👥 Персоналды басқару")
    tab1, tab2 = st.tabs(["➕ Жаңа қызметкер қосу", "📋 Тізім және Өшіру"])
    
    with tab1:
        with st.form("add_user"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")
            full_name = st.text_input("Толық аты-жөні")
            role = st.selectbox("Рөлі", ["Директор", "Ресепшен", "Мастер"])
            commission = st.number_input("Комиссия (мастер үшін)", value=0.40, min_value=0.0, max_value=1.0)
            if st.form_submit_button("Сақтау"):
                if username and password and full_name:
                    try:
                        run_query("INSERT INTO users (username, password, full_name, role, commission) VALUES (?,?,?,?,?)", 
                                  (username, password, full_name, role, commission), is_select=False)
                        st.success("Қызметкер қосылды!")
                        st.rerun()
                    except Exception as e: st.error(f"Қате: {e}")
    with tab2:
        df_u = run_query("SELECT id, username, full_name, role, commission FROM users")
        st.dataframe(df_u, use_container_width=True)
        
        st.markdown("#### ❌ Қызметкерді өшіру")
        del_options = df_u.apply(lambda r: f"ID: {r['id']} | {r['full_name']} ({r['role']})", axis=1).tolist()
        user_to_delete = st.selectbox("Өшіру үшін таңдаңыз:", del_options)
        if st.button("❌ Таңдалған қызметкерді жүйеден өшіру", type="primary"):
            target_id = int(user_to_delete.split(" ")[2])
            run_query("DELETE FROM users WHERE id=?", (target_id,), is_select=False)
            st.success("Қызметкер сәтті өшірілді!")
            st.rerun()

# --- БЛОК 4: СКЛАД (ИНТЕГРАЦИЯ С НОВЫМ УМНЫМ ПАРСЕРОМ КАТАЛОГОВ) ---
elif "Қойма / Склад" in choice:
    st.subheader("📦 Қойма / Склад")
    
    if st.session_state['role'] == "Директор":
        with st.expander("🔍 Авто-парсер товаров (Карточки и Каталоги с CopyLine.kz)"):
            st.markdown("Сюда можно вставлять **ссылку на один товар** или **ссылку на весь каталог** (например: `https://copyline.kz/goods/rollers.html`)")
            parse_url = st.text_input("Ссылка для парсинга:", placeholder="https://copyline.kz/goods/...")
            
            if st.button("Запустить умный парсинг", type="primary"):
                if parse_url:
                    with st.spinner("Считывание структуры страницы и очистка от артикулов..."):
                        res = parse_copyline_product(parse_url)
                    
                    if res["success"]:
                        products = res["products"]
                        st.success(f"Успешно обработано позиций: {len(products)}")
                        
                        # Выводим все найденные товары в аккуратных контейнерах с индивидуальным добавлением
                        for idx, prod in enumerate(products):
                            with st.container(border=True):
                                col_p1, col_p2, col_p3 = st.columns([1, 3, 2])
                                with col_p1:
                                    if prod["image"]: st.image(prod["image"], width=90)
                                    else: st.caption("Нет фото")
                                with col_p2:
                                    st.markdown(f"**Наименование:** {prod['title']}")
                                    st.write(f"Категория: {prod['type']}")
                                with col_p3:
                                    st.markdown(f"**Цена:** {prod['price']:,.0f} ₸")
                                    
                                    # Форма индивидуального сохранения для каждой извлеченной позиции
                                    with st.form(f"save_prod_{idx}"):
                                        f_qty = st.number_input("Кол-во (шт)", value=5, min_value=1, key=f"q_{idx}")
                                        f_in = st.number_input("Закуп (₸)", value=float(prod['price'] * 0.7), key=f"i_{idx}")
                                        if st.form_submit_button("➕ Добавить на склад", use_container_width=True):
                                            run_query(
                                                "INSERT OR REPLACE INTO stock (item_name, item_type, quantity, purchase_price, retail_price) VALUES (?,?,?,?,?)",
                                                (prod['title'], prod['type'], f_qty, f_in, prod['price']), is_select=False
                                            )
                                            st.toast(f"Товар '{prod['title']}' добавлен!")
                    else:
                        st.error(f"Ошибка парсера: {res['error']}")
                else:
                    st.warning("Введите рабочую ссылку!")

    # Стандартный вывод таблицы склада
    df_stock = run_query("SELECT id, item_name, item_type, quantity, purchase_price, retail_price FROM stock")
    st.dataframe(df_stock, use_container_width=True)
    
    if st.session_state['role'] == "Директор":
        st.markdown("### 🔄 Импорт / Экспорт Excel")
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

# --- БЛОК 5: КАТАЛОГ УСЛУГ ---
elif choice == "🛠️ Қызметтер каталогы":
    st.subheader("🛠️ Қызметтер каталогы (Прайс-лист шаблон)")
    df_serv = run_query("SELECT id, service_name, price FROM services_catalog")
    st.dataframe(df_serv, use_container_width=True)
    
    if st.session_state['role'] == "Директор":
        tab_s1, tab_s2 = st.tabs(["➕ Добавить услугу", "📥 Импорт каталога из Excel"])
        with tab_s1:
            with st.form("add_service_form"):
                s_name = st.text_input("Жаңа қызмет атауы")
                s_price = st.number_input("Бағасы (₸)", min_value=0)
                if st.form_submit_button("Қосу"):
                    if s_name:
                        run_query("INSERT OR IGNORE INTO services_catalog (service_name, price) VALUES (?,?)", (s_name, s_price), is_select=False)
                        st.success("Қызмет прайсқа қосылды!")
                        st.rerun()
        with tab_s2:
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
elif choice == "💰 Касса (Admin)":
    st.subheader("💰 Сервистік орталықтың кассасы")
    df_cash = run_query("SELECT id, op_type, amount, description, created_at FROM cashbox ORDER BY id DESC")
    
    if not df_cash.empty:
        buffer_cash = io.BytesIO()
        with pd.ExcelWriter(buffer_cash, engine='xlsxwriter') as writer:
            df_cash.to_excel(writer, index=False, sheet_name='Касса')
        st.download_button(label="📥 Касса тарихын Excel-ге жүктеу", data=buffer_cash.getvalue(), file_name="cashbox.xlsx", mime="application/vnd.ms-excel")
        st.markdown("---")

    st.dataframe(df_cash, use_container_width=True)
    st.metric("Кассадағы жалпы нақты баланс", f"{df_cash[df_cash['op_type']=='Доход']['amount'].sum() - df_cash[df_cash['op_type']=='Расход']['amount'].sum():,.0f} ₸")
