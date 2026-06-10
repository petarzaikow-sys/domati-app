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
# НАСТРОЙКИ В КОДА — само редките (цена, кутии)
# Наличността и етикетът на беритбата се управляват
# от листа „Настройки" в Google Sheet — виж най-долу.
# ─────────────────────────────────────────────
DEFAULT_STOCK_KG = 50       # резервна стойност, ако листът липсва
PRICE_PER_KG = 3            # евро на килограм
BOX_OPTIONS = [3, 5]        # размери на кутиите в кг
PICKUP_INFO = "Лично предаване в Пловдив. Ще се свържа с теб по телефона за ден и място."
DEFAULT_HARVEST_LABEL = "Беритба юни 2026"

# Квартали на Пловдив + околни села за падащото меню
LOCATIONS = [
    "— Пловдив — квартали —",
    "Център",
    "Капана",
    "Старият град",
    "Мараша",
    "Съдийски квартал",
    "Каменица 1",
    "Каменица 2",
    "Изгрев",
    "Столипиново",
    "Гладно поле",
    "Тракия",
    "Скобелева майка",
    "Кючук Париж",
    "Въстанически",
    "Христо Смирненски",
    "Христо Ботев",
    "Беломорски",
    "Остромила",
    "Коматево",
    "Прослав",
    "Кършияка",
    "Гагарин",
    "Захарна фабрика",
    "Филипово",
    "Тодор Каблешков",
    "— Околни села и градове —",
    "Марково",
    "Браниполе",
    "Белащица",
    "Брестник",
    "Куклен",
    "Първенец",
    "Брестовица",
    "Кадиево",
    "Златитрап",
    "Оризари",
    "Ягодово",
    "Крумово",
    "Катуница",
    "Садово",
    "Асеновград",
    "Труд",
    "Войводиново",
    "Строево",
    "Граф Игнатиево",
    "Калековец",
    "Скутаре",
    "Рогош",
    "Маноле",
    "Царацово",
    "Костиево",
    "Радиново",
    "Бенковски",
    "Стамболийски",
    "Перущица",
    "Кричим",
    "Раковски",
    "Друго (напиши по-долу)",
]
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
def get_sheets():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    book = client.open_by_key(st.secrets["sheet_id"])

    orders_ws = book.sheet1
    first_row = orders_ws.row_values(1)
    if [_norm(h) for h in first_row[: len(SHEET_HEADERS)]] != SHEET_HEADERS:
        # Заглавният ред липсва или е пипнат — възстановяваме го на ред 1
        if any(_norm(c) for c in first_row):
            orders_ws.insert_row(SHEET_HEADERS, 1)
        else:
            orders_ws.update("A1", [SHEET_HEADERS])

    # Лист „Настройки" — наличност и етикет, редактирани от телефона
    try:
        settings_ws = book.worksheet("Настройки")
    except gspread.exceptions.WorksheetNotFound:
        settings_ws = book.add_worksheet(title="Настройки", rows=10, cols=2)
        settings_ws.update(
            "A1:B3",
            [
                ["Настройка", "Стойност"],
                ["Наличност (кг)", str(DEFAULT_STOCK_KG)],
                ["Беритба", DEFAULT_HARVEST_LABEL],
            ],
        )
    return orders_ws, settings_ws


def load_settings(settings_ws):
    """Чете наличност (B2) и етикет на беритбата (B3) от листа Настройки."""
    try:
        raw_stock = settings_ws.acell("B2").value
        raw_label = settings_ws.acell("B3").value
        stock = int(str(raw_stock).strip())
        label = str(raw_label).strip() or DEFAULT_HARVEST_LABEL
        return stock, label
    except (ValueError, TypeError, AttributeError):
        return DEFAULT_STOCK_KG, DEFAULT_HARVEST_LABEL


def _norm(value) -> str:
    """Чисти интервали и невидими знаци за сигурно сравняване."""
    return str(value or "").strip()


def load_orders(sheet):
    """Връща всички поръчки като списък от речници."""
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return []
    headers = [_norm(h) for h in rows[0]]
    return [dict(zip(headers, r)) for r in rows[1:]]


def _row_kg(order) -> int:
    try:
        return int(float(_norm(order.get("Кутия (кг)")) or 0))
    except ValueError:
        return 0


def confirmed_kg(orders, harvest_label):
    """Сума на килограмите с потвърдени поръчки за текущата беритба."""
    hl = _norm(harvest_label)
    return sum(
        _row_kg(o)
        for o in orders
        if _norm(o.get("Статус")) == "Потвърдена" and _norm(o.get("Беритба")) == hl
    )


def waitlist_stats(orders, harvest_label):
    """Брой хора и килограми в чакащия списък за текущата беритба."""
    hl = _norm(harvest_label)
    matching = [
        o
        for o in orders
        if _norm(o.get("Статус")) == "Чакащ списък" and _norm(o.get("Беритба")) == hl
    ]
    return len(matching), sum(_row_kg(o) for o in matching)


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
        color: #2e2a24;
        border-left: 4px solid #c1442e;
        padding: 0.8rem 1rem;
        border-radius: 6px;
        margin-bottom: 1rem;
        font-size: 1.05rem;
    }
    .stock-banner b {
        color: #c1442e;
    }
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
    ws, settings_ws = get_sheets()
    STOCK_KG, HARVEST_LABEL = load_settings(settings_ws)
    orders = load_orders(ws)
except Exception:
    st.error(
        "Връзката с базата не успя. Опитай да презаредиш страницата след минута."
    )
    st.stop()

taken = confirmed_kg(orders, HARVEST_LABEL)
remaining = max(STOCK_KG - taken, 0)
sold_out = remaining < min(BOX_OPTIONS)

# Скрита диагностика: отвори приложението с ?admin=1 накрая на адреса
if st.query_params.get("admin") == "1":
    with st.expander("🔧 Диагностика (вижда се само с ?admin=1)", expanded=True):
        st.write(f"Наличност от Настройки (B2): **{STOCK_KG} кг**")
        st.write(f"Етикет от Настройки (B3): **«{HARVEST_LABEL}»**")
        st.write(f"Общо редове с поръчки: **{len(orders)}**")
        st.write(f"Потвърдени кг за този етикет: **{taken}**")
        st.write(f"Оставащи: **{remaining} кг**")
        labels_seen = sorted({_norm(o.get("Беритба")) for o in orders})
        statuses_seen = sorted({_norm(o.get("Статус")) for o in orders})
        st.write(f"Етикети в колоната «Беритба»: {labels_seen}")
        st.write(f"Стойности в колоната «Статус»: {statuses_seen}")

if sold_out:
    wl_people, wl_kg = waitlist_stats(orders, HARVEST_LABEL)
    if wl_people > 0:
        wl_text = (
            f" В чакащия списък вече има <b>{wl_people} "
            f"{'човек' if wl_people == 1 else 'души'} ({wl_kg} кг)</b>."
        )
    else:
        wl_text = ""
    st.markdown(
        f'<div class="stock-banner sold-out">Текущата беритба е <b>изчерпана</b>.{wl_text} '
        "Запиши се — бера 2–3 пъти седмично и пиша на хората по реда на списъка.</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f'<div class="stock-banner">Останали от тази беритба: <b>{remaining} кг</b><br>'
        '<span style="font-size: 0.88rem;">Бера 2–3 пъти седмично през целия сезон.</span></div>',
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
    area = st.selectbox(
        "Квартал / населено място *",
        options=LOCATIONS,
        index=None,
        placeholder="Избери от списъка",
    )
    other_area = st.text_input(
        "Ако избра «Друго» — напиши къде", placeholder="напр. с. Цалапица"
    )
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
    if area is None or area.startswith("—"):
        errors.append("Избери квартал или населено място от списъка.")
    elif area.startswith("Друго") and not other_area.strip():
        errors.append("Избра «Друго» — напиши населеното място в полето под менюто.")

    if errors:
        for e in errors:
            st.warning(e)
    else:
        final_area = other_area.strip() if area.startswith("Друго") else area

        # Препрочитаме наличността точно преди запис (срещу едновременни поръчки)
        orders = load_orders(ws)
        taken = confirmed_kg(orders, HARVEST_LABEL)
        remaining = max(STOCK_KG - taken, 0)

        status = "Потвърдена" if box <= remaining else "Чакащ списък"
        number = len(orders) + 1
        now = datetime.now(ZoneInfo("Europe/Sofia")).strftime("%d.%m.%Y %H:%M")
        price = box * PRICE_PER_KG

        # Записваме на точно определен ред (заглавен ред + брой поръчки + 1),
        # винаги от колона A — append_row понякога "пръска" редовете.
        target_row = len(orders) + 2
        ws.update(
            f"A{target_row}",
            [[
                number,
                status,
                now,
                name.strip(),
                phone.strip(),
                box,
                price,
                final_area,
                note.strip(),
                HARVEST_LABEL,
            ]],
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
