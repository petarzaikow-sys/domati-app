# -*- coding: utf-8 -*-
"""
Поръчки на домати — Streamlit приложение
Записва поръчките в Google Sheet и раздава поредни номера.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

# ─────────────────────────────────────────────
# НАСТРОЙКИ — променяй само тук
# ─────────────────────────────────────────────
STOCK_KG = 50               # налични килограми за текущата беритба
PRICE_PER_KG = 3            # евро на килограм
BOX_OPTIONS = [3, 5]        # размери на кутиите в кг
PICKUP_INFO = "Лично предаване в Пловдив. Ще се свържа с теб по телефона за ден и място."
HARVEST_LABEL = "Беритба юни 2026"   # смени при всяка нова беритба
SHEET_HEADERS = [
    "Номер", "Статус", "Дата", "Име", "Телефон",
    "Кутия (кг)", "Цена (евро)", "Район", "Бележка", "Беритба",
]

# ─────────────────────────────────────────────
# ВРЪЗКА С GOOGLE SHEETS
# ─────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource
def get_worksheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(st.secrets["sheet_id"]).sheet1
    # Ако таблицата е празна — слагаме заглавния ред
    if not sheet.get_all_values():
        sheet.append_row(SHEET_HEADERS)
    return sheet


def load_orders(sheet):
    """Връща всички поръчки като списък от речници."""
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return []
    headers = rows[0]
    return [dict(zip(headers, r)) for r in rows[1:]]


def confirmed_kg(orders):
    """Сума на килограмите с потвърдени поръчки за текущата беритба."""
    total = 0
    for o in orders:
        if o.get("Статус") == "Потвърдена" and o.get("Беритба") == HARVEST_LABEL:
            try:
                total += int(o.get("Кутия (кг)", 0))
            except ValueError:
                pass
    return total


def valid_phone(phone: str) -> bool:
    digits = re.sub(r"[^\d]", "", phone)
    return 9 <= len(digits) <= 13


# ─────────────────────────────────────────────
# ВЪНШЕН ВИД
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Домати от оранжерията",
    page_icon="🍅",
    layout="centered",
)

st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    .subtitle {
        color: #6b5d4f;
        margin-top: 0.2rem;
        margin-bottom: 1.2rem;
    }
    .stock-banner {
        background: #f3ede3;
        border-left: 4px solid #c1442e;
        padding: 0.8rem 1rem;
        border-radius: 6px;
        margin-bottom: 1rem;
        font-size: 1.05rem;
    }
    .sold-out {
        background: #f3ede3;
        border-left: 4px solid #7a6f5d;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<p class="main-title">🍅 Домати от оранжерията</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">Зрели на растението. Брани сутринта, в деня на предаването. '
    "Без системни препарати.</p>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# СЪСТОЯНИЕ НА НАЛИЧНОСТТА
# ─────────────────────────────────────────────
try:
    ws = get_worksheet()
    orders = load_orders(ws)
except Exception:
    st.error(
        "Връзката с базата не успя. Опитай да презаредиш страницата след минута."
    )
    st.stop()

taken = confirmed_kg(orders)
remaining = max(STOCK_KG - taken, 0)
sold_out = remaining < min(BOX_OPTIONS)

if sold_out:
    st.markdown(
        '<div class="stock-banner sold-out">Текущата беритба е <b>изчерпана</b>. '
        "Можеш да се запишеш в чакащия списък — за следващата беритба редът е по списъка.</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f'<div class="stock-banner">Останали от тази беритба: <b>{remaining} кг</b></div>',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
# ПОТВЪРЖДЕНИЕ СЛЕД УСПЕШНА ПОРЪЧКА
# ─────────────────────────────────────────────
if "done" in st.session_state:
    d = st.session_state["done"]
    if d["status"] == "Потвърдена":
        st.success(
            f"Готово, {d['name']}! Поръчката ти е приета.\n\n"
            f"**Твоят номер: {d['number']}**\n\n"
            f"Кутия {d['kg']} кг — {d['price']} евро.\n\n"
            f"{PICKUP_INFO}"
        )
    else:
        st.info(
            f"{d['name']}, тази беритба се изчерпа, но си в **чакащия списък под номер {d['number']}**.\n\n"
            "При следващата беритба ще ти пиша по реда на списъка."
        )
    if st.button("Нова поръчка"):
        del st.session_state["done"]
        st.rerun()
    st.stop()

# ─────────────────────────────────────────────
# ФОРМАТА
# ─────────────────────────────────────────────
with st.form("order_form"):
    st.subheader("Запиши се" if sold_out else "Поръчай")

    box_labels = {
        kg: f"Кутия {kg} кг — {kg * PRICE_PER_KG} евро" for kg in BOX_OPTIONS
    }
    box = st.radio(
        "Избери кутия",
        options=BOX_OPTIONS,
        format_func=lambda kg: box_labels[kg],
        horizontal=True,
    )

    name = st.text_input("Име и фамилия *")
    phone = st.text_input("Телефон *", placeholder="088 123 4567")
    area = st.text_input("Квартал / район в Пловдив", placeholder="напр. Кючук Париж")
    note = st.text_area("Бележка (по желание)", height=68)

    st.caption(
        "Данните ти се използват само за тази поръчка и не се споделят с никого."
    )

    submitted = st.form_submit_button(
        "Запиши ме в чакащия списък" if sold_out else "Поръчай", use_container_width=True
    )

if submitted:
    errors = []
    if not name.strip():
        errors.append("Въведи име.")
    if not valid_phone(phone):
        errors.append("Въведи валиден телефон (поне 9 цифри).")

    if errors:
        for e in errors:
            st.warning(e)
    else:
        # Препрочитаме наличността точно преди запис (срещу едновременни поръчки)
        orders = load_orders(ws)
        taken = confirmed_kg(orders)
        remaining = max(STOCK_KG - taken, 0)

        status = "Потвърдена" if box <= remaining else "Чакащ списък"
        number = len(orders) + 1
        now = datetime.now(ZoneInfo("Europe/Sofia")).strftime("%d.%m.%Y %H:%M")
        price = box * PRICE_PER_KG

        ws.append_row(
            [
                number,
                status,
                now,
                name.strip(),
                phone.strip(),
                box,
                price,
                area.strip(),
                note.strip(),
                HARVEST_LABEL,
            ]
        )

        st.session_state["done"] = {
            "status": status,
            "number": number,
            "name": name.strip().split()[0],
            "kg": box,
            "price": price,
        }
        st.rerun()

# ─────────────────────────────────────────────
# ДОЛЕН КОЛОНТИТУЛ
# ─────────────────────────────────────────────
st.divider()
st.caption("Оранжерия край Пловдив · Истински домати, на нормална цена.")
