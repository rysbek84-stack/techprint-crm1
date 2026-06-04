import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
import json

DB_NAME = "service_center_crm.db"
KASPI_PAY_ID = "orgtechnika_shymkent" 

# --- ОБЯЗАТЕЛЬНО ЗАПОЛНИТЕ ДЛЯ АВТО-СОГЛАСОВАНИЯ ЧЕРЕЗ ТГ ---
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА" 
YOUR_CHAT_ID = "ВАШ_ЧАТ_ID" 

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
            pickup_deadline TEXT DEFAULT NULL 
        )
    ''')
    
    try: cursor.execute("ALTER TABLE orders ADD COLUMN rejected_at TEXT DEFAULT NULL")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE orders ADD COLUMN pickup_deadline TEXT DEFAULT NULL")
    except sqlite3.OperationalError: pass

    cursor.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, full_name TEXT, role TEXT, commission REAL DEFAULT 0.40)')
    cursor.execute('CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT UNIQUE, item_type TEXT, quantity REAL DEFAULT 0, price REAL DEFAULT 0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS cashbox (id INTEGER PRIMARY KEY AUTOINCREMENT, op_type TEXT, amount REAL, description TEXT, created_at TEXT)')
    
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('admin', 'admin', 'Администратор (Директор)', 'Директор', 0.0)")
        cursor.execute("INSERT INTO users (username, password, full_name, role, commission) VALUES ('reception', '123', 'Алия (Ресепшен)', 'Ресепшен', 0.0)")
    
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

# --- ОБРАБОТЧИК АВТОМАТИЧЕСКИХ ССЫЛОК ИЗ WHATSAPP ---
if "action" in st.query_params and "order_id" in st.query_params:
    action = st.query_params["action"]
    o_id = int(st.query_params["order_id"])
    
    if action == "approve":
        run_query("UPDATE orders SET status='В работе' WHERE id=?", (o_id,), is_select=False)
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
        run_query("UPDATE orders SET status='Согласование', rejected_at=?, pickup_deadline=? WHERE id=?", (now_str, deadline_str, o_id), is_select=False)
        
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
    </style>
""", unsafe_allow_html=True)

@st.dialog("🖨️ Квитанция / Акт приема", width="large")
def show_print_receipt(order):
    total = order['parts_cost'] + order['work_cost']
    debt = total - order['paid_amount']
    st.html(f"""
    <div style="padding: 20px; font-family: 'Inter', sans-serif; color: black; background: white; border: 1px solid #ccc;">
        <h2 style="text-align: center; margin-bottom: 2px;">🔧 СЕРВИС ОРТАЛЫК TechPrint.kz</h2>
        <p style="text-align: center; margin-top: 0; font-size: 13px; color: #555555;">Уақыты: {order['created_at']}</p>
        <hr style="border-top: 2px dashed black;">
        <h3 style="text-align: center;">ТАПСЫРЫС № {order['id']}</h3>
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
    menu = ["📊 Басты бет & Аналитика", "📝 Тапсырыстар", "👥 Персонал (Админ)", "📦 Қойма / Склад (Админ)", "💰 Касса (Админ)"]
elif st.session_state['role'] == "Ресепшен":
    menu = ["📝 Тапсырыстар", "📦 Қойма / Склад (Просмотр)"]
elif st.session_state['role'] == "Мастер":
    menu = ["🛠️ Менің тапсырыстарым", "💵 Менің жалақым"]

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
        with c2: st.markdown(f'<div class="metric-card"><div class="metric-title">Барлық Төленген</div><div class="metric-value">{total_paid:,.0f} ₸</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="metric-card"><div class="metric-title" style="color:#16a34a;">Таза пайда СЦ</div><div class="metric-value" style="color:#16a34a;">{net_profit:,.0f} ₸</div></div>', unsafe_allow_html=True)

# --- БЛОК 2: ТАПСЫРЫСТАР (ГЛАВНЫЙ МОДУЛЬ) ---
elif choice == "📝 Тапсырыстар":
    st.subheader("📝 Тапсырыстарды басқару жүйесі")
    
    with st.expander("➕ Жаңа тапсырыс қосу"):
        with st.form("add_order_form", clear_on_submit=True):
            c_name = st.text_input("Клиент аты*")
            c_phone = st.text_input("Телефон*")
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
                    run_query('''INSERT INTO orders (client_name, phone, device_model, serial_number, is_cartridge, description, status, master_id, created_at)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (c_name, c_phone, d_model, s_num, is_cart, desc, "Принят", m_options[selected_m_name], now_str), is_select=False)
                    st.success("Тапсырыс қосылды!")
                    st.rerun()

    res_orders = run_query("SELECT o.*, u.full_name as master_name FROM orders o LEFT JOIN users u ON o.master_id = u.id ORDER BY o.id DESC")
    if not res_orders.empty:
        list_options = res_orders.apply(lambda r: f"№{r['id']} | {r['client_name']} — {r['device_model']} [{r['status']}]", axis=1).tolist()
        sel_order_text = st.selectbox("Өңдеу үшін тапсырысты таңдаңыз:", list_options)
        sel_id = int(sel_order_text.split(" ")[0].replace("№", ""))
        order_data = res_orders[res_orders['id'] == sel_id].iloc[0]
        
        if st.button("🖨️ Квитанцияны басып шығару"):
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

        with st.form("edit_order_form"):
            col1, col2, col3 = st.columns(3)
            u_name = col1.text_input("Клиент аты", value=str(order_data['client_name']))
            u_phone = col2.text_input("Телефон", value=str(order_data['phone']))
            u_paid = col3.number_input("💵 ТӨЛЕНДІ (₸)", value=float(order_data['paid_amount']))
            
            col4, col5, col6 = st.columns(3)
            u_status = col4.selectbox("Статус", ["Принят", "Согласование", "В работе", "Готов", "Выдан"], index=["Принят", "Согласование", "В работе", "Готов", "Выдан"].index(order_data['status']))
            u_parts = col5.number_input("Қосалқы бөлшек құны (₸)", value=float(order_data['parts_cost']))
            u_work = col6.number_input("Жұмыс құны (₸)", value=float(order_data['work_cost']))
            
            masters_df = run_query("SELECT id, full_name FROM users WHERE role='Мастер'")
            m_options = {row['full_name']: row['id'] for _, row in masters_df.iterrows()}
            m_options["Не назначен"] = None
            current_master_name = order_data['master_name'] if order_data['master_name'] else "Не назначен"
            u_master = st.selectbox("Шеберді өзгерту", list(m_options.keys()), index=list(m_options.keys()).index(current_master_name))

            total_bill = u_parts + u_work + penalty_amount
            remaining_debt = total_bill - u_paid
            st.write(f"**💰 Баланс: Чек: {total_bill:,.0f} ₸ | Қалдық қарыз: {remaining_debt:,.0f} ₸**")
            
            # --- ИНТЕГРАЦИЯ КЛИКАБЕЛЬНЫХ ССЫЛОК WHATSAPP С КРАСИВЫМ ФОРМАТИРОВАНИЕМ ---
            if u_status == "Согласование":
                st.markdown("<div class='kaspi-box'>", unsafe_allow_html=True)
                st.markdown("#### 📱 Клиентпен бағаны келісу және Төлем сілтемелері:")
                
                # Замените этот URL на адрес вашей развернутой CRM (например, https://mycrm.streamlit.app)
                base_url = "https://crm-techprint.streamlit.app"
                
                link_approve_crm = f"{base_url}/?action=approve&order_id={sel_id}"
                link_reject_crm = f"{base_url}/?action=reject&order_id={sel_id}"

                # Формируем ОДНО общее сообщение, где ссылки оформлены в виде понятного и удобного меню
                msg_full = (
                    f"⚙️ *Сервисный Центр TechPrint.kz*\n"
                    f"Тапсырыс №{sel_id} ({order_data['device_model']})\n"
                    f"Жалпы жөндеу құны: *{total_bill:,.0f} ₸.*\n\n"
                    f"Пожалуйста, выберите один из вариантов ответа (нажмите на нужную ссылку):\n\n"
                    f"🟢 *ЖӨНДЕУГЕ КЕЛІСЕМІН (СОГЛАСЕН):*\n"
                    f"{link_approve_crm}\n\n"
                    f"-----------------------------\n\n"
                    f"🔴 *БАС ТАРТАМЫН (ОТКАЗЫВАЮСЬ):*\n"
                    f"{link_reject_crm}\n\n"
                    f"⚠️ _Ескерту: Бас тартқан жағдайда құрылғыны 3 жұмыс күні ішінде алып кетуіңіз керек. Одан асса, сақтау ақысы күніне 500 ₸ құрайды._"
                )
                
                wa_url_combined = send_whatsapp_link(u_phone, msg_full)
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    st.markdown(f'<a href="{wa_url_combined}" target="_blank" class="whatsapp-btn">💬 Отправить меню согласования в WhatsApp</a>', unsafe_allow_html=True)
                with col_btn2:
                    if st.form_submit_button("🤖 ТГ Авто-Келісу батырмаларын жолдау"):
                        send_telegram_with_buttons(sel_id, order_data['device_model'], total_bill)
                        st.success("Интерактивті батырмалар ТГ-ға жіберілді!")

                if remaining_debt > 0:
                    kaspi_url = f"https://pay.kaspi.kz/pay/{KASPI_PAY_ID}?amount={int(remaining_debt)}"
                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=130x130&data={urllib.parse.quote(kaspi_url)}"
                    st.image(qr_url, caption=f"Внутренний Kaspi QR для мастера: {remaining_debt:,.0f} ₸")
                st.markdown("</div>", unsafe_allow_html=True)

            if st.form_submit_button("💾 Измененияны сақтау"):
                if u_paid != order_data['paid_amount']:
                    diff = u_paid - order_data['paid_amount']
                    run_query("INSERT INTO cashbox (op_type, amount, description, created_at) VALUES ('Доход', ?, ?, ?)", 
                              (diff, f"Оплата заказа №{sel_id}", datetime.now().strftime("%Y-%m-%d %H:%M")), is_select=False)
                
                if u_status == "Готов" and order_data['status'] != "Готов":
                    send_telegram_notification(u_phone, u_name, order_data['device_model'], sel_id)
                    
                run_query("UPDATE orders SET client_name=?, phone=?, paid_amount=?, status=?, parts_cost=?, work_cost=?, master_id=? WHERE id=?", 
                          (u_name, u_phone, u_paid, u_status, u_parts, u_work, m_options[u_master], sel_id), is_select=False)
                st.success("Сақталды!")
                st.rerun()
                
        if st.session_state['role'] == "Директор":
            if st.button("❌ Тапсырысты базадан мүлдем өшіру (Удалить заказ)"):
                run_query("DELETE FROM orders WHERE id=?", (sel_id,), is_select=False)
                st.error("Тапсырыс өшірілді!")
                st.rerun()
    else: st.info("Тапсырыстар әлі жоқ.")

# --- БЛОК 3: МЕНІҢ ТАПСЫРЫСТАРЫМ (МАСТЕР) ---
elif choice == "🛠️ Менің тапсырыстарым":
    st.subheader("🛠️ Сізге бекітілген тапсырыстар")
    my_id = st.session_state['user_id']
    res_my = run_query("SELECT * FROM orders WHERE master_id=? ORDER BY id DESC", (my_id,))
    if not res_my.empty:
        list_my = res_my.apply(lambda r: f"№{r['id']} | {r['client_name']} — {r['device_model']} [{r['status']}]", axis=1).tolist()
        sel_my = st.selectbox("Тапсырысты таңдаңыз:", list_my)
        sel_my_id = int(sel_my.split(" ")[0].replace("№", ""))
        my_order_data = res_my[res_my['id'] == sel_my_id].iloc[0]
        
        st.info(f"📋 **Сипаттамасы:** {my_order_data['description']}")
        with st.form("master_edit_form"):
            u_status = st.selectbox("Статус", ["В работе", "Готов"], index=["В работе", "Готов"].index(my_order_data['status']) if my_order_data['status'] in ["В работе", "Готов"] else 0)
            u_parts = st.number_input("Жұмсалған бөлшектер құны, ₸", value=float(my_order_data['parts_cost']))
            u_work = st.number_input("Жөндеу жұмысының құны, ₸", value=float(my_order_data['work_cost']))
            
            if st.form_submit_button("💾 Сақтау"):
                if u_status == "Готов" and my_order_data['status'] != "Готов":
                    send_telegram_notification(my_order_data['phone'], my_order_data['client_name'], my_order_data['device_model'], sel_my_id)
                run_query("UPDATE orders SET status=?, parts_cost=?, work_cost=? WHERE id=?", (u_status, u_parts, u_work, sel_my_id), is_select=False)
                st.success("Сақталды!")
                st.rerun()
    else: st.info("Сізде белсенді тапсырыстар жоқ.")

# --- БЛОК 4: МЕНІҢ ЖАЛАҚЫМ (МАСТЕР) ---
elif choice == "💵 Менің жалақым":
    my_id = st.session_state['user_id']
    master_info = run_query("SELECT commission FROM users WHERE id=?", (my_id,)).iloc[0]
    comm = master_info['commission']
    st.subheader(f"💵 Сіздің жеке жалақыңыз (Ваша ставка: {comm*100}%)")
    df_salary = run_query("SELECT id, device_model, work_cost, status FROM orders WHERE master_id=? AND status='Выдан'", (my_id,))
    if not df_salary.empty:
        df_salary['Мастер үлесі (₸)'] = df_salary['work_cost'] * comm
        st.dataframe(df_salary, use_container_width=True, hide_index=True)
        st.metric("Итого к выдаче:", f"{df_salary['Мастер үлесі (₸)'].sum():,.0f} ₸")
    else: st.info("Төленетін жалақы табылмады ('Выдан' күйінде болуы керек).")

# --- БЛОК 5: ПЕРСОНАЛМЕН ЖҰМЫС ---
elif choice == "👥 Персонал (Админ)":
    st.subheader("👥 Қызметкерлерді басқару")
    with st.expander("➕ Жаңа қызметкерді қосу"):
        with st.form("add_user_form"):
            new_user = st.text_input("Логин*")
            new_pass = st.text_input("Пароль*")
            new_name = st.text_input("Толық аты (ФИО)*")
            new_role = st.selectbox("Профессия / Роль", ["Директор", "Ресепшен", "Мастер"])
            new_comm = st.slider("Мастер комиссиясы, %", 0, 100, 40) / 100.0
            if st.form_submit_button("💾 Қызметкерді қосу"):
                if new_user and new_pass and new_name:
                    try:
                        run_query("INSERT INTO users (username, password, full_name, role, commission) VALUES (?, ?, ?, ?, ?)",
                                  (new_user, new_pass, new_name, new_role, new_comm), is_select=False)
                        st.success("Қызметкер қосылды!")
                        st.rerun()
                    except Exception: st.error("Бұл логин бос емес!")

    st.markdown("---")
    users_df = run_query("SELECT id, username, password, full_name, role, commission FROM users")
    if not users_df.empty:
        st.markdown("### ⚙️ Қызметкердің деректерін өзгерту немесе өшіру:")
        user_options = users_df.apply(lambda r: f"{r['role']} | {r['full_name']} (@{r['username']})", axis=1).tolist()
        selected_user_text = st.selectbox("Өзгерту үшін қызметкерді таңдаңыз:", user_options)
        sel_user_idx = user_options.index(selected_user_text)
        user_data = users_df.iloc[sel_user_idx]
        sel_user_id = int(user_data['id'])
        
        with st.form(f"edit_user_form_{sel_user_id}"):
            col_u1, col_u2 = st.columns(2)
            edit_name = col_u1.text_input("Толық аты (ФИО)", value=str(user_data['full_name']))
            edit_pass = col_u2.text_input("Пароль", value=str(user_data['password']))
            col_u3, col_u4 = st.columns(2)
            edit_role = col_u3.selectbox("Роль", ["Директор", "Ресепшен", "Мастер"], index=["Директор", "Ресепшен", "Мастер"].index(user_data['role']))
            current_comm_percent = int(user_data['commission'] * 100) if user_data['commission'] else 40
            edit_comm = st.slider("Шебер пайызы, %", 0, 100, current_comm_percent) / 100.0
            
            c_btn1, c_btn2 = st.columns([3, 1])
            if c_btn1.form_submit_button("💾 Өзгерістерді сақтау", type="primary"):
                run_query("UPDATE users SET full_name=?, password=?, role=?, commission=? WHERE id=?", (edit_name, edit_pass, edit_role, edit_comm, sel_user_id), is_select=False)
                st.success("Жаңартылды!")
                st.rerun()
            if c_btn2.form_submit_button("❌ Өшіру (Удалить)", type="secondary"):
                if user_data['username'] == 'admin': st.error("Бас админды өшіруге болмайды!")
                else:
                    run_query("DELETE FROM users WHERE id=?", (sel_user_id,), is_select=False)
                    st.warning("Өшірілді.")
                    st.rerun()

# --- БЛОК 6: ҚОЙМА / СКЛАД ---
elif choice in ["📦 Қойма / Склад (Админ)", "📦 Қойма / Склад (Просмотр)"]:
    st.subheader("📦 Қойма мен тауарларды есепке алу")
    if st.session_state['role'] == "Директор":
        with st.expander("➕ Жаңа тауар/материал қосу"):
            with st.form("add_stock_form"):
                i_name = st.text_input("Тауар атауы")
                i_type = st.selectbox("Түрі", ["тонер", "запчасть", "материал"])
                i_qty = st.number_input("Саны", min_value=0.0, step=1.0)
                i_price = st.number_input("Бағасы, ₸", min_value=0.0)
                if st.form_submit_button("Қоймаға қосу"):
                    if i_name:
                        run_query("INSERT INTO stock (item_name, item_type, quantity, price) VALUES (?, ?, ?, ?)", (i_name, i_type, i_qty, i_price), is_select=False)
                        st.success("Тауар қосылды!")
                        st.rerun()
                        
    df_stock_view = run_query("SELECT id, item_name as 'Атауы', item_type as 'Түрі', quantity as 'Қалдық саны', price as 'Бағасы (₸)' FROM stock")
    st.dataframe(df_stock_view, use_container_width=True, hide_index=True)
    
    if st.session_state['role'] == "Директор" and not df_stock_view.empty:
        st.markdown("### ⚙️ Тауар санын өзгерту:")
        sel_stock_id = st.selectbox("Тауарды таңдаңыз:", df_stock_view['id'].tolist())
        new_qty = st.number_input("Жаңа қалдық саны:", min_value=0.0, step=1.0)
        if st.button("Қалдықты жаңарту"):
            run_query("UPDATE stock SET quantity=? WHERE id=?", (new_qty, sel_stock_id), is_select=False)
            st.success("Жаңартылды!")
            st.rerun()

# --- БЛОК 7: КАССА ---
elif choice == "💰 Касса (Админ)":
    st.subheader("💰 Сервистік орталықтың кассасы")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        with st.form("cash_out_form"):
            st.markdown("### ➖ Расход жазу (Шығыс)")
            out_amount = st.number_input("Сумма (₸)", min_value=0.0)
            out_desc = st.text_input("Не үшін")
            if st.form_submit_button("Кассадан ақша шығару"):
                if out_amount > 0:
                    run_query("INSERT INTO cashbox (op_type, amount, description, created_at) VALUES ('Расход', ?, ?, ?)",
                              (out_amount, out_desc, datetime.now().strftime("%Y-%m-%d %H:%M")), is_select=False)
                    st.success("Шығыс жазылды!")
                    st.rerun()
                    
    with col_c2:
        df_cash = run_query("SELECT op_type, amount, description, created_at FROM cashbox ORDER BY id DESC")
        if not df_cash.empty:
            total_in = df_cash[df_cash['op_type']=='Доход']['amount'].sum()
            total_out = df_cash[df_cash['op_type']=='Расход']['amount'].sum()
            st.metric("💸 Кассадағы таза қалдық:", f"{total_in - total_out:,.0f} ₸")
            st.markdown("**Соңғы транзакциялар:**")
            st.dataframe(df_cash, use_container_width=True)
