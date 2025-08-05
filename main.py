import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message
import json
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не найден в переменных окружения!")
    exit(1)
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))      # По умолчанию 300 сек
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", "50"))   # По умолчанию $50

# Глобальные переменные
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_ids = set()  # Множество ID пользователей для рассылки
last_eth_price = None
last_notification_price = None


class EthereumPriceTracker:
    def __init__(self):
        self.session = None

    async def create_session(self):
        """Создание HTTP сессии"""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close_session(self):
        """Закрытие HTTP сессии"""
        if self.session:
            await self.session.close()

    async def get_eth_price(self):
        """Получение текущего курса Ethereum"""
        try:
            await self.create_session()
            async with self.session.get(COINGECKO_API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    price = data['ethereum']['usd']
                    return float(price)
                else:
                    logger.error(f"Ошибка API: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка при получении курса: {e}")
            return None


# Инициализация трекера
price_tracker = EthereumPriceTracker()


@dp.message(CommandStart())
async def start_handler(message: Message):
    """Обработчик команды /start"""
    user_ids.add(message.from_user.id)
    await message.answer(
        "🚀 Добро пожаловать в бот отслеживания курса Ethereum!\n\n"
        "📊 Я буду уведомлять вас об изменениях курса ETH каждые $50.\n"
        "⏰ Проверка курса происходит каждые 5 минут.\n\n"
        "Доступные команды:\n"
        "/price - показать текущий курс\n"
        "/status - статус бота\n"
        "/stop - остановить уведомления"
    )


@dp.message(lambda message: message.text == "/price")
async def price_handler(message: Message):
    """Обработчик команды /price"""
    current_price = await price_tracker.get_eth_price()
    if current_price:
        await message.answer(
            f"💰 Текущий курс Ethereum: ${current_price:,.2f}\n"
            f"🕐 Время: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
        )
    else:
        await message.answer("❌ Не удалось получить текущий курс. Попробуйте позже.")


@dp.message(lambda message: message.text == "/status")
async def status_handler(message: Message):
    """Обработчик команды /status"""
    global last_eth_price, last_notification_price

    status_text = "📊 Статус бота:\n\n"

    if last_eth_price:
        status_text += f"💰 Последний курс: ${last_eth_price:,.2f}\n"

    if last_notification_price:
        status_text += f"🔔 Последнее уведомление: ${last_notification_price:,.2f}\n"

    status_text += f"👥 Подписчиков: {len(user_ids)}\n"
    status_text += f"⏱ Интервал проверки: {CHECK_INTERVAL // 60} мин\n"
    status_text += f"💵 Порог уведомлений: ${PRICE_THRESHOLD}"

    await message.answer(status_text)


@dp.message(lambda message: message.text == "/stop")
async def stop_handler(message: Message):
    """Обработчик команды /stop"""
    user_ids.discard(message.from_user.id)
    await message.answer("❌ Вы отписались от уведомлений о курсе Ethereum.")


async def send_price_notification(price, change):
    """Отправка уведомления всем пользователям"""
    if not user_ids:
        return

    change_emoji = "📈" if change > 0 else "📉"
    change_text = "выросла" if change > 0 else "упала"

    message_text = (
        f"{change_emoji} Ethereum {change_text} на ${abs(change):,.2f}!\n\n"
        f"💰 Текущий курс: ${price:,.2f}\n"
        f"📊 Изменение: {change:+,.2f} USD\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
    )

    # Отправляем уведомление всем пользователям
    for user_id in user_ids.copy():  # Копируем множество для безопасной итерации
        try:
            await bot.send_message(user_id, message_text)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            # Удаляем пользователя, если бот заблокирован
            if "bot was blocked" in str(e).lower():
                user_ids.discard(user_id)


async def price_monitoring():
    """Основной цикл мониторинга курса"""
    global last_eth_price, last_notification_price

    logger.info("Запуск мониторинга курса Ethereum...")

    while True:
        try:
            current_price = await price_tracker.get_eth_price()

            if current_price is None:
                logger.warning("Не удалось получить курс, пропускаем итерацию")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            logger.info(f"Текущий курс ETH: ${current_price:,.2f}")

            # Проверяем нужно ли отправить уведомление
            if last_notification_price is not None:
                price_change = current_price - last_notification_price

                if abs(price_change) >= PRICE_THRESHOLD:
                    await send_price_notification(current_price, price_change)
                    last_notification_price = current_price
                    logger.info(f"Отправлено уведомление об изменении на ${price_change:+,.2f}")
            else:
                # Первый запуск - запоминаем текущую цену как базовую
                last_notification_price = current_price
                logger.info("Установлена базовая цена для уведомлений")

            last_eth_price = current_price

        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    """Главная функция"""
    logger.info("Запуск Telegram бота...")
    logger.info(f"Настройки: интервал проверки = {CHECK_INTERVAL}с, порог уведомлений = ${PRICE_THRESHOLD}")

    # Запускаем мониторинг курса в фоне
    monitoring_task = asyncio.create_task(price_monitoring())

    try:
        # Запускаем бота
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        # Останавливаем мониторинг
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass

        # Закрываем сессию
        await price_tracker.close_session()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())