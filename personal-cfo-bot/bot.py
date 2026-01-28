#!/usr/bin/env python3
"""
Личный CFO Telegram Bot
Финансовый калькулятор для расчета дневного бюджетного лимита
"""

import os
import logging
import asyncio
from typing import Dict
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, 
    KeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# ================== КОНФИГУРАЦИЯ ==================
load_dotenv()

# Токен бота (из переменных окружения или .env файла)
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    print("=" * 60)
    print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не найден!")
    print("=" * 60)
    print("Добавьте переменную окружения TELEGRAM_BOT_TOKEN")
    print("или создайте файл .env с содержанием:")
    print('TELEGRAM_BOT_TOKEN="ваш_токен_здесь"')
    print("=" * 60)
    exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота (исправлено для aiogram 3.7.0+)
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ================== МАШИНА СОСТОЯНИЙ ==================
class BudgetStates(StatesGroup):
    """Состояния для пошагового ввода данных"""
    waiting_for_salary = State()
    waiting_for_other_income = State()
    waiting_for_rent = State()
    waiting_for_transport = State()
    waiting_for_other_bills = State()
    waiting_for_goal_name = State()
    waiting_for_goal_amount = State()
    waiting_for_goal_months = State()

# Хранилище данных пользователя (временное, в памяти)
user_data: Dict[int, Dict] = {}

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
def format_rubles(amount: int) -> str:
    """Форматирует число в рубли с пробелами-разделителями"""
    return f"{amount:,} ₽".replace(",", " ")

def calculate_results(data: Dict) -> Dict:
    """
    Выполняет все финансовые расчеты на основе введенных данных
    """
    # Доходы
    salary = int(data.get('salary', 0))
    other_income = int(data.get('other_income', 0))
    total_income = salary + other_income
    
    # Расходы
    rent = int(data.get('rent', 0))
    transport = int(data.get('transport', 0))
    other_bills = int(data.get('other_bills', 0))
    fixed_expenses = rent + transport + other_bills
    
    # Цель
    goal_amount = int(data.get('goal_amount', 0))
    goal_months = max(1, int(data.get('goal_months', 1)))
    monthly_contribution = (goal_amount + goal_months - 1) // goal_months
    
    # Бюджет
    monthly_budget = total_income - fixed_expenses - monthly_contribution
    days_in_month = 30
    daily_limit = monthly_budget // days_in_month if monthly_budget > 0 else 0
    
    return {
        'total_income': total_income,
        'fixed_expenses': fixed_expenses,
        'monthly_contribution': monthly_contribution,
        'monthly_budget': monthly_budget,
        'daily_limit': daily_limit,
        'goal_name': data.get('goal_name', 'финансовую цель'),
        'goal_months': goal_months
    }

# ================== КЛАВИАТУРЫ ==================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура главного меню"""
    builder = ReplyKeyboardBuilder()
    
    builder.add(KeyboardButton(text="💰 Рассчитать бюджет"))
    builder.add(KeyboardButton(text="📊 Пример расчета"))
    builder.add(KeyboardButton(text="❓ Помощь"))
    
    builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Отменить расчет"))
    return builder.as_markup(resize_keyboard=True)

def get_skip_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой пропуска"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="⏭ Пропустить"))
    builder.add(KeyboardButton(text="❌ Отменить"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# ================== ОБРАБОТЧИКИ КОМАНД ==================
@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    """
    Обработчик команд /start и /help
    """
    welcome_text = """
👋 <b>Добро пожаловать в Личный CFO!</b>

Я помогу рассчитать ваш <b>дневной бюджетный лимит</b> — сумму, которую можно тратить каждый день после всех обязательных платежей и отчислений на цель.

<b>📈 Как это работает:</b>
1. Вы вводите доходы, расходы и финансовую цель
2. Я рассчитываю, сколько нужно откладывать в месяц
3. Вы получаете <b>дневной лимит</b> — ваш "паёк" на каждый день

<b>🎯 Основные возможности:</b>
• <b>💰 Рассчитать бюджет</b> — начать новый расчет
• <b>📊 Пример расчета</b> — посмотреть, как это работает
• <b>❓ Помощь</b> — показать это сообщение

<b>💡 Просто нажмите «💰 Рассчитать бюджет» чтобы начать!</b>
    """
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    """Показать справку"""
    await cmd_start(message)

@dp.message(F.text == "📊 Пример расчета")
async def show_example(message: Message):
    """Показать пример расчета"""
    example_text = """
<b>📊 ПРИМЕР РАСЧЕТА ДНЕВНОГО ЛИМИТА</b>

<b>💳 Доходы:</b>
├ Зарплата: 70 000 ₽
└ Дополнительный доход: 20 000 ₽
<b>Итого доход: 90 000 ₽</b>

<b>🏠 Расходы:</b>
├ Аренда жилья: 30 000 ₽
├ Транспорт: 6 000 ₽
└ Прочие платежи: 0 ₽
<b>Итого расходы: 36 000 ₽</b>

<b>🎯 Цель:</b>
├ На что копим: Отпуск на море
├ Сумма цели: 150 000 ₽
└ Срок накопления: 10 месяцев
<b>Ежемесячный взнос: 15 000 ₽</b>

<b>🧮 Расчет:</b>
├ Доходы: 90 000 ₽
├ Расходы: 36 000 ₽
├ Взнос на цель: 15 000 ₽
└ <b>Бюджет на траты: 39 000 ₽</b>

<b>📅 Дневной лимит:</b>
39 000 ₽ ÷ 30 дней = <b>1 300 ₽ в день</b>

<b>✅ Итог:</b> Чтобы накопить на отпуск за 10 месяцев, можно тратить <b>1 300 ₽ в день</b> на еду, развлечения и прочие нужды.

<b>💎 Каждый день, укладываясь в этот лимит, вы гарантированно достигаете своей цели!</b>
    """
    await message.answer(example_text, reply_markup=get_main_keyboard())

# ================== НАЧАЛО РАСЧЕТА ==================
@dp.message(F.text == "💰 Рассчитать бюджет")
async def start_calculation(message: Message, state: FSMContext):
    """
    Начало процесса расчета бюджета
    """
    # Сброс предыдущих данных
    user_data[message.from_user.id] = {}
    
    # Начало диалог
    await message.answer(
        "🎯 <b>Отлично! Давайте рассчитаем ваш персональный бюджет.</b>\n\n"
        "<b>Введите вашу зарплату (основной доход):</b>\n"
        "<i>Просто отправьте число, например: 70000</i>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BudgetStates.waiting_for_salary)

# ================== ОБРАБОТЧИКИ ВВОДА ДАННЫХ ==================
@dp.message(BudgetStates.waiting_for_salary)
async def process_salary(message: Message, state: FSMContext):
    """Обработка ввода зарплаты"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    try:
        salary = int(message.text.replace(" ", "").replace(",", ""))
        if salary <= 0:
            raise ValueError
        
        # Сохраняем данные
        user_data[message.from_user.id]['salary'] = salary
        
        await message.answer(
            f"✅ <b>Зарплата:</b> {format_rubles(salary)}\n\n"
            "<b>Введите другие источники дохода в месяц:</b>\n"
            "<i>Если нет других доходов, отправьте 0 или нажмите 'Пропустить'</i>",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(BudgetStates.waiting_for_other_income)
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Пожалуйста, введите корректное число</b>\n"
            "<i>Пример: 70000 или 85 000</i>"
        )

async def cancel_calculation(message: Message, state: FSMContext):
    """Отмена текущего расчета"""
    await state.clear()
    await message.answer(
        "❌ <b>Расчет отменен.</b>\n\n"
        "Чтобы начать заново, нажмите «💰 Рассчитать бюджет»",
        reply_markup=get_main_keyboard()
    )

# ================== ЗАПУСК БОТА ==================
async def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("🤖 Бот 'Личный CFO' запускается...")
    logger.info(f"✅ Токен загружен. Длина: {len(API_TOKEN)} символов")
    logger.info("=" * 50)
    
    try:
        # Удаляем вебхук если есть (для чистого запуска)
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем бота
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
async def health_check(request):
    return web.Response(text="Bot is alive")

# Запускаем веб-сервер в фоновом режиме
async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("🌐 Health check сервер запущен на порту 8080")

# Добавьте в функцию main():
async def main():
    logger.info("🤖 Бот 'Личный CFO' запускается...")
    
    # Запускаем health check сервер
    await start_web_server()
    
    # Запускаем бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
