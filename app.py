import os
import io
import random
import json
import cloudscraper
import threading
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from PIL import Image, ImageDraw, ImageFont
import logging
import socket
import httpx
from flask import Flask
# 0. ЛОГИРОВАНИЕ (чтобы видеть ошибки во вкладке Logs на Hugging Face)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# 1. СЛАБЫЙ ВЕБ-СЕРВЕР (Keep-Alive для Render)
server = Flask(__name__)
@server.route('/')
def home(): return "Katerine System is Online"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port)
# 2. ОСНОВНАЯ ЛОГИКА БОТА
load_dotenv()
NZ_LOGIN = os.getenv("NZ_LOGIN", "").strip()
NZ_PASSWORD = os.getenv("NZ_PASSWORD", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
def check_network():
    logger.info("--- СЕТЕВАЯ ДИАГНОСТИКА ---")
    hosts = ["api.telegram.org", "nz.ua", "google.com"]
    for host in hosts:
        try:
            # Попытка системного разрешения
            ip = socket.gethostbyname(host)
            logger.info(f"✅ {host} разрешен системно: {ip}")
        except Exception as e:
            logger.error(f"❌ Ошибка системного разрешения {host}: {e}")
            # Попытка через Google DNS вручную (если системный на HF тупит)
            try:
                import urllib.request
                # Упрощенная проверка через DoH не выйдет, но мы можем попробовать пингануть IP
                logger.info(f"Попытка принудительного резолва {host} через запасные пути...")
            except: pass
if not BOT_TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден в Secrets!")
else:
    logger.info(f"Токен загружен (длина: {len(BOT_TOKEN)})")
    check_network()
if not NZ_LOGIN or not NZ_PASSWORD:
    logger.error("ОШИБКА: Логин или пароль NZ_LOGIN/NZ_PASSWORD не найдены!")
BASE_URL = "https://nz.ua"
NEWS_URL = f"{BASE_URL}/dashboard/news"
GRADES_URL = f"{BASE_URL}/schedule/grades-statement?student_id=41093408&date_from=2025-08-21&date_to=2025-12-31"
INTRO_PHRASES = [
    "Отчет об успеваемости готов, сер.",
    "Данные получены, сер.",
    "Последние оценки в системе, сер.",
    "Информация обновлена, сер.",
    "Выписка сформирована, сер.",
    "Сводка по оценкам готова, сер.",
    "Данные синхронизированы, сер.",
    "Отчет по успеваемости Арсения, сер.",
    "Свежие данные по оценкам, сер.",
    "Результаты проверки системы NZ.ua, сер."
]
# Константы уведомлений
LOW_MARK_LIMIT = 8
HIGH_MARK_LIMIT = 11
def get_feedback(mark_val):
    if mark_val <= LOW_MARK_LIMIT:
        return random.choice(["Вынужден вас огорчить, сер...", "Вы огорчаете меня этим результатом, сер.", "Это плохой результат, сер."])
    elif mark_val >= HIGH_MARK_LIMIT:
        return random.choice(["Отлично, сер!", "Превосходный результат, сер!", "Вы как всегда на высоте, сер!"])
    return "Новая оценка в системе, сер."
def fetch_nz_data(url):
    scraper = cloudscraper.create_scraper()
    login_page = scraper.get(f"{BASE_URL}/login")
    soup = BeautifulSoup(login_page.text, 'html.parser')
    csrf_tag = soup.find('meta', {'name': 'csrf-token'})
    csrf_token = csrf_tag['content'] if csrf_tag else ""
    
    login_data = {
        '_csrf': csrf_token,
        'LoginForm[login]': NZ_LOGIN,
        'LoginForm[password]': NZ_PASSWORD,
        'LoginForm[rememberMe]': '0'
    }
    scraper.post(f"{BASE_URL}/login", data=login_data)
    return scraper.get(url).text
def generate_table_image(marks_data):
    row_height, header_height, padding, col_split = 42, 60, 20, 480
    font = ImageFont.load_default()
    bold_font = ImageFont.load_default()
    
    try:
        # Hugging Face usually has these fonts
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
        bold_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except: pass
    max_marks_width = 0
    for subject, marks in marks_data:
        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        m_width = temp_draw.textlength(marks, font=font)
        if m_width > max_marks_width: max_marks_width = m_width
    width = max(1150, int(col_split + max_marks_width + (padding * 2)))
    height = header_height + (len(marks_data) * row_height) + padding
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([0, 0, width, header_height], fill=(40, 40, 40)) 
    draw.text((padding, 18), "Дисциплина", fill=(255, 255, 255), font=bold_font)
    draw.text((col_split + 10, 18), "Оценки за семестр", fill=(255, 255, 255), font=bold_font)
    
    y = header_height
    for idx, (subject, marks) in enumerate(marks_data):
        if not marks.strip(): continue # Пропускаем предметы без оценок для чистоты
        
        if idx % 2 == 1: draw.rectangle([0, y, width, y + row_height], fill=(245, 245, 245))
        draw.text((padding, y + 10), subject[:45], fill=(0, 0, 0), font=bold_font)
        
        # Обрезаем очень длинные списки оценок, если они не влезают
        display_marks = marks
        if len(marks) > 150: display_marks = marks[:147] + "..."
        
        draw.text((col_split + 10, y + 10), display_marks, fill=(60, 60, 60), font=font)
        draw.line([0, y + row_height, width, y + row_height], fill=(210, 210, 210))
        y += row_height
        
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf
def get_latest_marks():
    html = fetch_nz_data(NEWS_URL)
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('.news-page__item')
    marks = []
    for item in items:
        date_el = item.select_one('.news-page__date')
        date_str = date_el.get_text(strip=True) if date_el else "???"
        desc_el = item.select_one('.news-page__desc')
        if desc_el:
            desc_text = desc_el.get_text(separator=' ', strip=True)
            if "оцінк" in desc_text.lower():
                clean_text = desc_text.replace("Учень Абаканович Арсеній Олексійович ", "").replace("Отримав оцінку ", "✅ Балл: ")
                clean_text = clean_text.replace("Підприємництво і фінансова грамотність", "Фін. грамотность").replace("Трудове навчання / Художня праця", "Худ. праця")
                marks.append(f"📅 *{date_str}*\n{clean_text}")
    return marks[:10]
def get_all_marks_raw():
    html = fetch_nz_data(GRADES_URL)
    soup = BeautifulSoup(html, 'html.parser') 
    table = soup.select_one('table')
    results = []
    subjects_dict = {}
    if table:
        for row in table.select('tr'):
            cells = row.select('td, th')
            if len(cells) > 2:
                subject = cells[1].get_text(strip=True)
                if subject in ["Дисципліна", "Назва предмету"] or not subject: continue
                
                marks_parts = []
                for i in range(2, len(cells)):
                    txt = cells[i].get_text(strip=True)
                    if txt and txt not in ["Отримані результати"]:
                        marks_parts.append(txt)
                
                if not marks_parts: continue
                
                if "Підприємництво" in subject: subject = "Фин. грамотность"
                if "Трудове" in subject: subject = "Худ. праця"
                
                if subject in subjects_dict:
                    # Избегаем дублей внутри одной строки
                    for mp in marks_parts:
                        if mp not in subjects_dict[subject]:
                            subjects_dict[subject].append(mp)
                else:
                    subjects_dict[subject] = marks_parts
    
    results = [(s, " | ".join(m)) for s, m in subjects_dict.items()]
    
    priority = ['Алгебра', 'Геометрія', 'Географія', 'Біологія', 'Хімія', 'Фізика']
    def sort_key(item):
        for idx, p in enumerate(priority):
            if p.lower() in item[0].lower(): return (0, idx)
        return (1, item[0])
    results.sort(key=sort_key)
    return results
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_active_chat(chat_id)
    
    # Регистрация команд в меню Телеграма (кнопка [ / ] слева)
    await context.bot.set_my_commands([
        ("start", "Запустить/Перезапустить интерфейс"),
        ("latest", "Показать последние 10 оценок"),
        ("table", "Показать таблицу оценок")
    ])
    
    kb = [
        [KeyboardButton("📊 Последние 10")],
        [KeyboardButton("📋 Таблица оценок")],
        [KeyboardButton("🧹 Очистить чат")],
        [KeyboardButton("📂 Документация")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        kb, 
        resize_keyboard=True, 
        one_time_keyboard=False,
        input_field_placeholder="Управление Katerine..."
    )
    
    logger.info(f"Отправка меню для chat_id {chat_id}")
    await update.message.reply_text(
        "Здраствуйте сер, интерфейс Katerine System обновлен (4 кнопки).\n\n"
        "Если они не появились — нажмите на иконку 'кнопки' в поле ввода.", 
        reply_markup=reply_markup
    )
def save_active_chat(chat_id):
    try:
        with open("active_chats.json", "w") as f:
            json.dump({"chat_id": chat_id}, f)
    except: pass
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, force_text=None):
    text = force_text if force_text else update.message.text
    chat_id = update.effective_chat.id
    kb = [
        [KeyboardButton("📊 Последние 10")],
        [KeyboardButton("📋 Таблица оценок")],
        [KeyboardButton("🧹 Очистить чат")],
        [KeyboardButton("📂 Документация")]
    ]
    reply_markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=False, input_field_placeholder="Управление Katerine...")
    if "Последние 10" in text:
        try:
            m = get_latest_marks()
            await update.message.reply_text(f"{random.choice(INTRO_PHRASES)}\n\n" + "\n\n".join(m) if m else "Новостей нет, сер.", parse_mode='Markdown', reply_markup=reply_markup)
        except Exception as e: await update.message.reply_text(f"⚠️ Ошибка, сер: {e}", reply_markup=reply_markup)
    elif "Таблица оценок" in text:
        try:
            raw = get_all_marks_raw()
            if raw:
                img_buf = generate_table_image(raw)
                await update.message.reply_photo(photo=img_buf, caption=f"📊 *{random.choice(INTRO_PHRASES)}*", parse_mode='Markdown', reply_markup=reply_markup)
            else: await update.message.reply_text("Данные не найдены, сер.", reply_markup=reply_markup)
        except Exception as e: await update.message.reply_text(f"⚠️ Ошибка, сер: {e}", reply_markup=reply_markup)
    elif "Очистить чат" in text:
        await update.message.reply_text("Чат очищен (память очищена), сер.", reply_markup=reply_markup)
    elif "Документация" in text:
        doc_text = (
            "📄 *Документация Katerine System*\n\n"
            "• *Последние 10*: Выводит последние записи об оценках из ленты новостей.\n"
            "• *Таблица оценок*: Генерирует визуальную таблицу за текущий семестр.\n"
            "• *Мониторинг*: Бот проверяет новые оценки каждый час с 05:00 до 23:00.\n"
            "• *Очистить чат*: Сброс состояния интерфейса.\n"
        )
        await update.message.reply_text(doc_text, parse_mode='Markdown', reply_markup=reply_markup)
async def monitor_marks(context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime
    now = datetime.now()
    if not (5 <= now.hour <= 23):
        return
    chat_data = {}
    try:
        with open("active_chats.json", "r") as f:
            chat_data = json.load(f)
    except: return
    chat_id = chat_data.get("chat_id")
    if not chat_id: return
    try:
        marks = get_latest_marks_for_monitor()
        seen_marks = []
        try:
            with open("seen_marks.json", "r") as f:
                seen_marks = json.load(f)
        except: pass
        new_marks = []
        for m in marks:
            m_id = m['id']
            if m_id not in seen_marks:
                new_marks.append(m)
                seen_marks.append(m_id)
        if new_marks:
            # Лимит хранения истории
            with open("seen_marks.json", "w") as f:
                json.dump(seen_marks[-50:], f)
            for nm in new_marks:
                val = nm['value']
                feedback = get_feedback(val)
                msg = f"🔔 *Уведомление о новой оценке!*\n\n{nm['text']}\n\n💬 {feedback}"
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка в мониторе: {e}")
def get_latest_marks_for_monitor():
    html = fetch_nz_data(NEWS_URL)
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('.news-page__item')
    results = []
    for item in items:
        desc_el = item.select_one('.news-page__desc')
        if desc_el:
            text = desc_el.get_text(strip=True)
            if "оцінк" in text.lower():
                import re
                mark_match = re.search(r'Отримав оцінку (\d+)', text)
                if mark_match:
                    val = int(mark_match.group(1))
                    m_id = hash(text) # Простой ID на основе текста
                    results.append({'id': m_id, 'value': val, 'text': text})
    return results
if __name__ == "__main__":
    # Запуск веб-сервера в отдельном потоке
    threading.Thread(target=run_flask).start()
    
    try:
        # Запуск бота
        logger.info("Запуск Telegram бота...")
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Настройка планировщика (мониторинг раз в час)
        job_queue = app.job_queue
        if job_queue:
            job_queue.run_repeating(monitor_marks, interval=3600, first=10)
            logger.info("Мониторинг оценок запущен (1 раз в час).")
        else:
            logger.error("КРИТИЧЕСКАЯ ОШИБКА: JobQueue не инициализирован! Проверьте наличие библиотеки apscheduler.")
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("latest", lambda u, c: handle_message(u, c, force_text="📊 Последние 10")))
        app.add_handler(CommandHandler("table", lambda u, c: handle_message(u, c, force_text="📋 Таблица оценок")))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        logger.info("Katerine System is Running on Render.com...")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"ФАТАЛЬНАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        logger.error(traceback.format_exc())
