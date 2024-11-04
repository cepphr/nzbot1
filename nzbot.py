import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from quart import Quart, redirect, request, render_template
import aiohttp

# Bot and Payment configuration
BOT_TOKEN = "7851501061:AAGtJ0TH2eQQe32682ztWzwhdDEJm30J584"
GROUP_CHAT_ID = -1001234567890
MERCHANT_ID = '7f6b3f23-727c-4cfd-af88-a59be7deac33'
ZARINPAL_REQUEST_URL = 'https://api.zarinpal.com/pg/v4/payment/request.json'
ZARINPAL_VERIFY_URL = 'https://api.zarinpal.com/pg/v4/payment/verify.json'
PER_PLAYER_FEE = 1000  # Amount per player in Toman
DESCRIPTION = 'پرداخت برای ثبت نام تورنومنت گل یا پوچ'
BOT_USERNAME = "nZgol_bot"
CALLBACK_DOMAIN = "https://bot.nzclub.ir"

# Initialize bot, dispatcher, router, and Quart app
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)
router = Router()
app = Quart(__name__)

# Initialize the database asynchronously
async def initialize_database():
    async with aiosqlite.connect('reservations.db') as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            telegram_id INTEGER UNIQUE NOT NULL,
            payment_status TEXT,
            ref_id TEXT,
            player_count INTEGER
        )
        ''')
        await db.commit()

# FSM States
class ReservationStates(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_phone_number = State()
    waiting_for_player_count = State()
    waiting_for_payment = State()

# Command handlers
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_name = message.from_user.first_name
    await message.answer(f"سلام {user_name}، به بات ثبت نام تورنومنت خوش آمدید!\nاز دستور /reserve برای رزرو استفاده کنید.")

@dp.message(Command("reserve"))
async def reserve_tournament(message: types.Message, state: FSMContext):
    await state.update_data(telegram_id=message.from_user.id, full_name=message.from_user.first_name)
    await message.answer("لطفاً شماره تماس خود را به صورت دستی وارد کنید.")
    await state.set_state(ReservationStates.waiting_for_phone_number)

@dp.message(Command("info"))
async def info_command(message: types.Message):
    info_text = (
        "برگزاری دومین تورنومنت بزرگ گل یا پوچ ان زد ✅\n\n"
        "مسابقه از روز دوشنبه ۲۲ آبانماه ساعت چهار برگزار میشه (هماهنگی دقیق‌تر نحوه‌ی برگزاری در گروه تلگرامی پس از اد شدنتون انجام میشه)\n\n"
        "هزینه‌ی ورودی: ۴۵۰ تومان\n\n"
        "🏆 جایزه‌ی تیم اول: ۴۰٪ از کل ورودی + تندیس و لوح جشنواره🥇\n"
        "🥈 جایزه تیم دوم: ۱۰٪ از کل ورودی + تندیس و لوح جشنواره\n\n"
        "⭐️⭐️ آفر ویژه برای تیم برنده: بازی با تیم عمو حسن و ضبط برای یوتیوب ان زد\n\n"
        "تفاوت این مسابقه با تورنومنت قبلی قرار گرفتن رنکینگ دقیق پلیرها همراه با امتیاز هست.\n\n"
        "❌ آخرین مهلت ثبت نام جمعه ۱۸ آبانماه\n"
        "دقت کنید که تاریخ ثبت نام به هیچ وجه تمدید نمیشه ❌"
    )
    await message.answer(info_text)

dp.include_router(router)

# Process phone number
@dp.message(ReservationStates.waiting_for_phone_number)
async def process_phone_number(message: types.Message, state: FSMContext):
    phone_number = message.text
    if not phone_number.isdigit() or len(phone_number) < 10:
        await message.answer("شماره تماس نامعتبر است. لطفاً شماره‌ای معتبر وارد کنید.")
        return
    await state.update_data(phone_number=phone_number)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 نفر", callback_data="1")],
        [InlineKeyboardButton(text="2 نفر", callback_data="2")],
        [InlineKeyboardButton(text="3 نفر", callback_data="3")]
    ])
    await message.answer("چند نفر می‌خواهید ثبت نام کنید؟ لطفاً انتخاب کنید.", reply_markup=keyboard)
    await state.set_state(ReservationStates.waiting_for_player_count)

# Process player count and generate payment link
@router.callback_query(StateFilter(ReservationStates.waiting_for_player_count))
async def process_player_count(callback_query: CallbackQuery, state: FSMContext):
    player_count = int(callback_query.data)
    total_amount = player_count * PER_PLAYER_FEE
    await state.update_data(total_amount=total_amount, player_count=player_count)
    payment_link = f"{CALLBACK_DOMAIN}/request?user_id={callback_query.from_user.id}&amount={total_amount}"
    await bot.send_message(
        callback_query.from_user.id,
        f"هزینه کل برای {player_count} نفر: {total_amount} تومان\nلطفاً از طریق لینک زیر پرداخت کنید: {payment_link}"
    )
    await state.set_state(ReservationStates.waiting_for_payment)
    await callback_query.answer()

# Quart route to initiate payment request
@app.route('/request/')
async def send_request():
    user_id = request.args.get('user_id')
    amount = int(request.args.get('amount', PER_PLAYER_FEE))
    callback_url = f'{CALLBACK_DOMAIN}/verify?user_id={user_id}'
    
    data = {
        "merchant_id": MERCHANT_ID,
        "amount": amount * 10,
        "description": DESCRIPTION,
        "callback_url": callback_url
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(ZARINPAL_REQUEST_URL, json=data) as response:
            result = await response.json()
            if result['data']['code'] == 100:
                return redirect(f'https://www.zarinpal.com/pg/StartPay/{result["data"]["authority"]}')
            return 'Error in creating payment request'

# Quart route to verify payment
@app.route('/verify/')
async def verify():
    authority = request.args.get('Authority')
    user_id = request.args.get('user_id')
    amount = int(request.args.get('amount', PER_PLAYER_FEE))

    data = {
        "merchant_id": MERCHANT_ID,
        "amount": amount * 10,
        "authority": authority
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(ZARINPAL_VERIFY_URL, json=data) as response:
            result = await response.json()
            if result['data']['code'] == 100:
                ref_id = result['data']['ref_id']
                await store_successful_payment(user_id, ref_id)
                await send_invite_link(user_id)
                return await render_template("payment_success.html", ref_id=ref_id, bot_username=BOT_USERNAME)
            elif result['data']['code'] == 101:
                return 'تراکنش قبلاً به ثبت رسیده است.'
            else:
                return 'تراکنش ناموفق بود. کد وضعیت: {}'.format(result['data']['code'])

# Store successful payment in the database
async def store_successful_payment(user_id, ref_id):
    async with aiosqlite.connect('reservations.db') as db:
        await db.execute('''
            INSERT INTO users (telegram_id, payment_status, ref_id)
            VALUES (?, 'Success', ?)
            ON CONFLICT(telegram_id) DO UPDATE SET payment_status='Success', ref_id=?
        ''', (user_id, ref_id, ref_id))
        await db.commit()

# Send a limited invite link based on player count
async def send_invite_link(user_id):
    async with aiosqlite.connect('reservations.db') as db:
        async with db.execute('SELECT player_count FROM users WHERE telegram_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            player_count = row[0] if row else 1

    try:
        invite_link = await bot.create_chat_invite_link(
            GROUP_CHAT_ID,
            member_limit=player_count
        )
        await bot.send_message(user_id, f"پرداخت شما با موفقیت انجام شد. "
                                        f"برای پیوستن به گروه تورنمنت از لینک زیر استفاده کنید. "
                                        f"این لینک برای {player_count} نفر معتبر است:\n{invite_link.invite_link}")
    except Exception as e:
        logging.error(f"Failed to create or send invite link: {e}")

# Main function to run both Quart and Aiogram in the same event loop
async def main():
    await initialize_database()
    await asyncio.gather(
        app.run_task(host='0.0.0.0', port=5000),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
