#!/usr/bin/env python3
"""
Личный CFO Telegram Bot
Финансовый калькулятор для расчета дневного бюджетного лимита
"""

import os
import logging
import asyncio
import threading
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

# Импорт для веб-сервера
from aiohttp import web

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

# ================== ВЕБ-СЕРВЕР ДЛЯ RENDER ==================
async def health_check(request):
    """Простой health-check endpoint для Render"""
    return web.Response(text="✅ Личный CFO Bot is running!")

async def start_web_server():
    """Запуск веб-сервера на порту 8080"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("🌐 Health check сервер запущен на порту 8080")

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
    if amount == 0:
        return "0 ₽"
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
    
    # Начало диалога
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

@dp.message(BudgetStates.waiting_for_other_income)
async def process_other_income(message: Message, state: FSMContext):
    """Обработка дополнительных доходов"""
    if message.text == "❌ Отменить":
        await cancel_calculation(message, state)
        return
    elif message.text == "⏭ Пропустить":
        other_income = 0
    else:
        try:
            other_income = int(message.text.replace(" ", "").replace(",", ""))
            if other_income < 0:
                raise ValueError
        except ValueError:
            await message.answer(
                "⚠️ <b>Пожалуйста, введите корректное число</b>\n"
                "<i>Пример: 10000 или 0</i>"
            )
            return
    
    # Сохраняем данные
    user_data[message.from_user.id]['other_income'] = other_income
    
    await message.answer(
        f"✅ <b>Дополнительный доход:</b> {format_rubles(other_income)}\n\n"
        "<b>Введите стоимость аренды жилья (или ипотека):</b>\n"
        "<i>Если нет, отправьте 0</i>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BudgetStates.waiting_for_rent)

@dp.message(BudgetStates.waiting_for_rent)
async def process_rent(message: Message, state: FSMContext):
    """Обработка ввода аренды"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    try:
        rent = int(message.text.replace(" ", "").replace(",", ""))
        if rent < 0:
            raise ValueError
        
        user_data[message.from_user.id]['rent'] = rent
        
        await message.answer(
            f"✅ <b>Аренда:</b> {format_rubles(rent)}\n\n"
            "<b>Введите расходы на транспорт в месяц:</b>\n"
            "<i>Такси, метро, бензин и т.д. Если нет, отправьте 0</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(BudgetStates.waiting_for_transport)
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Пожалуйста, введите корректное число</b>\n"
            "<i>Пример: 30000 или 0</i>"
        )

@dp.message(BudgetStates.waiting_for_transport)
async def process_transport(message: Message, state: FSMContext):
    """Обработка ввода транспортных расходов"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    try:
        transport = int(message.text.replace(" ", "").replace(",", ""))
        if transport < 0:
            raise ValueError
        
        user_data[message.from_user.id]['transport'] = transport
        
        await message.answer(
            f"✅ <b>Транспорт:</b> {format_rubles(transport)}\n\n"
            "<b>Введите другие обязательные платежи в месяц:</b>\n"
            "<i>Связь, интернет, коммунальные услуги и т.д. Если нет, отправьте 0</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(BudgetStates.waiting_for_other_bills)
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Пожалуйста, введите корректное число</b>\n"
            "<i>Пример: 5000 или 0</i>"
        )

@dp.message(BudgetStates.waiting_for_other_bills)
async def process_other_bills(message: Message, state: FSMContext):
    """Обработка ввода прочих платежей"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    try:
        other_bills = int(message.text.replace(" ", "").replace(",", ""))
        if other_bills < 0:
            raise ValueError
        
        user_data[message.from_user.id]['other_bills'] = other_bills
        
        await message.answer(
            f"✅ <b>Прочие платежи:</b> {format_rubles(other_bills)}\n\n"
            "<b>Теперь установим финансовую цель!</b>\n\n"
            "<b>На что вы хотите накопить?</b>\n"
            "<i>Пример: 'Отпуск на море', 'Новый ноутбук', 'Автомобиль'</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(BudgetStates.waiting_for_goal_name)
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Пожалуйста, введите корректное число</b>\n"
            "<i>Пример: 5000 или 0</i>"
        )

@dp.message(BudgetStates.waiting_for_goal_name)
async def process_goal_name(message: Message, state: FSMContext):
    """Обработка названия цели"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    goal_name = message.text
    user_data[message.from_user.id]['goal_name'] = goal_name
    
    await message.answer(
        f"✅ <b>Цель:</b> {goal_name}\n\n"
        f"<b>Какую сумму хотите накопить на {goal_name.lower()}?</b>\n"
        "<i>Пример: 150000</i>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BudgetStates.waiting_for_goal_amount)

@dp.message(BudgetStates.waiting_for_goal_amount)
async def process_goal_amount(message: Message, state: FSMContext):
    """Обработка суммы цели"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    try:
        goal_amount = int(message.text.replace(" ", "").replace(",", ""))
        if goal_amount <= 0:
            raise ValueError
        
        user_data[message.from_user.id]['goal_amount'] = goal_amount
        
        await message.answer(
            f"✅ <b>Сумма цели:</b> {format_rubles(goal_amount)}\n\n"
            "<b>За сколько месяцев вы хотите накопить эту сумму?</b>\n"
            "<i>Пример: 12 (год), 24 (2 года), 6 (полгода)</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(BudgetStates.waiting_for_goal_months)
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Пожалуйста, введите корректное число</b>\n"
            "<i>Пример: 150000</i>"
        )

@dp.message(BudgetStates.waiting_for_goal_months)
async def process_goal_months(message: Message, state: FSMContext):
    """Обработка срока цели и вывод результата"""
    if message.text == "❌ Отменить расчет":
        await cancel_calculation(message, state)
        return
    
    try:
        goal_months = int(message.text.replace(" ", "").replace(",", ""))
        if goal_months <= 0:
            raise ValueError
        
        user_data[message.from_user.id]['goal_months'] = goal_months
        
        # Получаем все данные
        data = user_data[message.from_user.id]
        
        # Выполняем расчет
        results = calculate_results(data)
        
        # Формируем отчет
        report = f"""
<b>📊 ВАШ ПЕРСОНАЛЬНЫЙ ФИНАНСОВЫЙ ОТЧЕТ</b>

<b>💳 ДОХОДЫ:</b>
├ Зарплата: {format_rubles(data['salary'])}
└ Дополнительный доход: {format_rubles(data.get('other_income', 0))}
<b>Итого доход: {format_rubles(results['total_income'])}</b>

<b>🏠 РАСХОДЫ:</b>
├ Аренда жилья: {format_rubles(data.get('rent', 0))}
├ Транспорт: {format_rubles(data.get('transport', 0))}
└ Прочие платежи: {format_rubles(data.get('other_bills', 0))}
<b>Итого расходы: {format_rubles(results['fixed_expenses'])}</b>

<b>🎯 ЦЕЛЬ:</b>
├ На что копим: {data['goal_name']}
├ Сумма цели: {format_rubles(data['goal_amount'])}
└ Срок накопления: {goal_months} месяцев
<b>Ежемесячный взнос: {format_rubles(results['monthly_contribution'])}</b>

<b>🧮 РАСЧЕТ:</b>
├ Доходы: {format_rubles(results['total_income'])}
├ Расходы: {format_rubles(results['fixed_expenses'])}
├ Взнос на цель: {format_rubles(results['monthly_contribution'])}
└ <b>Бюджет на траты: {format_rubles(results['monthly_budget'])}</b>

<b>📅 ДНЕВНОЙ ЛИМИТ:</b>
{format_rubles(results['monthly_budget'])} ÷ 30 дней = <b>{format_rubles(results['daily_limit'])} в день</b>

<b>✅ ИТОГ:</b> Чтобы накопить на {data['goal_name'].lower()} за {goal_months} месяцев, вы можете тратить <b>{format_rubles(results['daily_limit'])} в день</b> на еду, развлечения и прочие нужды.

<b>💎 Каждый день, укладываясь в этот лимит, вы гарантированно достигаете своей цели!</b>

Чтобы начать новый расчет, нажмите «💰 Рассчитать бюджет»
        """
        
        await message.answer(report, reply_markup=get_main_keyboard())
        
        # Очищаем состояние
        await state.clear()
        
        # Логируем успешный расчет
        logger.info(f"✅ User {message.from_user.id} completed calculation. Daily limit: {results['daily_limit']} ₽")
        
    except ValueError:
        await message.answer(
            "⚠️ <b>Пожалуйста, введите корректное число месяцев</b>\n"
            "<i>Пример: 12 (год), 24 (2 года)</i>"
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
        # Запускаем веб-сервер для health checks
        logger.info("🌐 Запуск health check сервера на порту 8080...")
        web_task = asyncio.create_task(start_web_server())
        
        # Даем время веб-серверу запуститься
        await asyncio.sleep(1)
        
        # Удаляем вебхук если есть (для чистого запуска)
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем бота
        logger.info("🤖 Запуск Telegram бота...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
