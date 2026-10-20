import asyncio
import json
import ssl
import certifi
import websockets
import RPi.GPIO as GPIO

WS_URL = "wss://mempool.space/api/v1/ws"
PIN = 27

BLINK_ON = 0.03
BATCH_WINDOW = 0.9  # mempool-txids messages arrive about once per second
MAX_BLINKS = 8

# State
last_block_height = 0
blink_task = None


async def blink_batch(n):
    """One pulse per new mempool tx, spread across the batch window."""
    n = min(n, MAX_BLINKS)
    gap = BATCH_WINDOW / n
    for _ in range(n):
        GPIO.output(PIN, GPIO.HIGH)
        await asyncio.sleep(BLINK_ON)
        GPIO.output(PIN, GPIO.LOW)
        await asyncio.sleep(max(gap - BLINK_ON, BLINK_ON))


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
    global last_block_height, blink_task

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

    added = len(data.get("mempool-txids", {}).get("added", []))
    if added:
        if blink_task and not blink_task.done():
            blink_task.cancel()
        blink_task = asyncio.create_task(blink_batch(added))

async def run():
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    while True:
        try:
            async with websockets.connect(WS_URL, ssl=ssl_context) as ws:
                await ws.send(json.dumps({
                    "action": "want",
                    "data": ["blocks"]
                }))
                await ws.send(json.dumps({"track-mempool-txids": True}))
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