import asyncio
import json
import ssl
import time
import certifi
import websockets
import RPi.GPIO as GPIO

WS_URL = "wss://mempool.space/api/v1/ws"
PIN = 27

# State
last_block_height = 0
last_mempool_count = 0


def blink():
    """Quick on/off pulse triggered by mempool activity."""
    GPIO.output(PIN, GPIO.HIGH)
    time.sleep(0.03)
    GPIO.output(PIN, GPIO.LOW)
    time.sleep(0.03)


async def fade_in():
    """Long fade animation triggered by new block."""
    pi_pwm = GPIO.PWM(PIN, 1000)
    pi_pwm.start(0)
    try:
        fades = 60
        speed = 1
        for i in range(fades):
            for duty in range(0, 101, speed):
                pi_pwm.ChangeDutyCycle(duty)
                await asyncio.sleep(0.01)
            if i != fades - 1:
                for duty in range(100, 0, -speed):
                    pi_pwm.ChangeDutyCycle(duty)
                    await asyncio.sleep(0.01)
            speed += 1
        await asyncio.sleep(0.5)
        pi_pwm.ChangeDutyCycle(100)
        await asyncio.sleep(10)
    finally:
        pi_pwm.stop()
        GPIO.output(PIN, GPIO.LOW)


async def handle_message(msg):
    global last_block_height, last_mempool_count

    data = json.loads(msg)

    # New block notification (live) — comes as data["block"]
    new_block = None
    if "block" in data:
        new_block = data["block"]
    # Initial snapshot on connect — comes as data["blocks"] (list, newest first)
    elif "blocks" in data and isinstance(data["blocks"], list) and data["blocks"]:
        new_block = data["blocks"][0]

    if new_block:
        height = new_block.get("height", 0)
        if height > last_block_height:
            last_block_height = height
            print(f"New block: {height}")
            asyncio.create_task(fade_in())

    if "mempoolInfo" in data:
        count = data["mempoolInfo"].get("size", 0)
        if count > last_mempool_count:
            blink()
        last_mempool_count = count

async def run():
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    while True:
        try:
            async with websockets.connect(WS_URL, ssl=ssl_context) as ws:
                await ws.send(json.dumps({
                    "action": "want",
                    "data": ["blocks", "stats"]
                }))
                await ws.send(json.dumps({"action": "track-mempool"}))
                print("Connected and subscribed")

                async for message in ws:
                    await handle_message(message)

        except (websockets.ConnectionClosed, OSError) as e:
            print(f"Connection lost: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(PIN, GPIO.OUT)


def cleanup_gpio():
    GPIO.cleanup()


if __name__ == "__main__":
    setup_gpio()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        cleanup_gpio()