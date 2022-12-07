# -*- coding: UTF-8 -*-

import json
import logging
import math
from pathlib import Path
import os
from os import environ
import sys
import textwrap
import time

from font_amatic_sc import AmaticSC
from font_caladea import Caladea
from font_fredoka_one import FredokaOne
from font_hanken_grotesk import HankenGrotesk
from font_intuitive import Intuitive
from font_roboto import Roboto
from font_source_sans_pro import SourceSansPro
from font_source_serif_pro import SourceSerifPro
from PIL import Image, ImageFont, ImageDraw, ImageOps
import arrow
import geocoder
import requests

def create_mask(source):
    """Create a transparency mask to draw images in grayscale
    """
    logging.info("Creating a transparency mask for the image")
    mask_image = Image.new("1", source.size)
    w, h = source.size
    for x in range(w):
        for y in range(h):
            p = source.getpixel((x, y))
            if p in [BLACK, WHITE]:
                mask_image.putpixel((x, y), 255)
    return mask_image

# Declare non pip fonts here ** Note: ttf files need to be in the /fonts dir of application repo
Grand9KPixel = "/usr/app/fonts/Grand9KPixel.ttf"

def draw_weather(weather, img, scale):
    """Draw the weather info on screen"""
    logging.info("Prepare the weather data for drawing")
    # Draw today's date on left side below today's name
    today = arrow.utcnow().format(fmt="DD MMMM", locale=LOCALE)
    date_font = ImageFont.truetype(WEATHER_FONT, 18)
    draw.text((3, 3), today, BLACK, font=date_font)
    # Draw current temperature to right of today
    temp_font = ImageFont.truetype(WEATHER_FONT, 24)
    draw.text((3, 30), f"{temp_to_str(weather['temperature'], scale)}°", BLACK, font=temp_font)
    # Draw today's high and low temps on left side below date
    small_font = ImageFont.truetype(WEATHER_FONT, 14)
    draw.text(
        (3, 72),
        f"{temp_to_str(weather['min_temp'], scale)}° - {temp_to_str(weather['max_temp'], scale)}°",
        BLACK,
        font=small_font,
    )
    # Draw today's max humidity on left side below temperatures
    draw.text((3, 87), f"{weather['max_humidity']}%", BLACK, font=small_font)
    # Load weather icon
    icon_name = weather['symbol'].split('_')[0]
    time_of_day = ''
    # Couple of symbols have different icons for day and night. Check if this symbol is one of them.
    if len(weather['symbol'].split('_')) > 1:
        symbol_cycle = weather['symbol'].split('_')[1]
        if symbol_cycle == 'day':
            time_of_day = 'd'
        elif symbol_cycle == 'night':
            time_of_day = 'n'
    icon_filename = f"{weather['icon']}.png"
    filepath = Path(__file__).parent / 'pngs' / icon_filename
    icon_image = Image.open(filepath)
    icon_mask = create_mask(icon_image)
    # Draw the weather icon
    if WEATHER_INVERT and WAVESHARE:
        logging.info("Inverting Weather Icon")
        icon = Image.new('1', (100, 100), 255)
        icon.paste(icon_image, (0,0), icon_image)
        icon_inverted = ImageOps.invert(icon.convert('RGB'))
        img.paste(icon_inverted, (120, 3))
    else:
        img.paste(icon_image, (120, 3), icon_image)
    return img

def get_current_display():
    """Query device supervisor API to retrieve the current display"""
    url = f"{BALENA_SUPERVISOR_ADDRESS}/v2/device/tags?apikey={BALENA_SUPERVISOR_API_KEY}"
    headers = {"Accept": "application/json"}
    current_display = None
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "tags" in data:
                current_display = next((t['value'] for t in data['tags'] if t['name'] == "current_display"), None)
    except requests.exceptions.RequestException as err:
        logging.error(err)
    return current_display

def get_location():
    """Return coordinate and location info based on IP address"""
    url = "https://api.ipgeolocation.io/ipgeo?apiKey=e1b636db453240fd88fd53ed93ef91e3"
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
    except requests.exceptions.RequestException as err:
        logging.error(err)
    logging.error("Failed to retrieve the location data")
    return {}

def get_weather(lat: float, lon: float):
    """Return weather report for the next 24 hours"""
    # Truncate all geographical coordinates to max 4 decimals to respect API's policy
    url = f"https://devapi.qweather.com/v7/weather/24h?location=116.70,38.04&key=944db0245a85422abc58982bbdd3fbb7&lang=en"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.135 Safari/537.36"
    }
    logging.info("Retrieving weather forecast")
    weather = {}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            timeseries = data['hourly']
            now = arrow.utcnow()
            tomorrow = now.shift(hours=+24)
            weather_24hours = []
            for t in timeseries:
                tm = arrow.get(t['fxTime'])
                if tm < tomorrow:
                    temp = t['temp']
                    humid = t['humidity']
                    symbol = t['text']
                    icon = t['icon']
                    weather_24hours.append({
                        'time': tm,
                        'temperature': temp,
                        'humidity': humid,
                        'symbol': symbol,
                        'icon': icon,
                    })
            weather_24hours = sorted(weather_24hours, key=lambda x: x['time'])
            weather = [x for x in weather_24hours if x['time'] <= now.shift(hours=+1)][-1]
            temperatures = [x['temperature'] for x in weather_24hours if x['time'] <= now.shift(days=+1)]
            weather['max_temp'] = max(temperatures)
            weather['min_temp'] = min(temperatures)
            weather['max_humidity'] = max([x['humidity'] for x in weather_24hours if x['time'] <= now.shift(days=+1)])
    except requests.exceptions.RequestException as err:
        logging.error(err)
    return weather

def set_current_display(val):
    """Update the tag value for current display"""
    # First get device identifier for future call
    url_device = f"https://api.balena-cloud.com/v5/device?$filter=uuid eq '{BALENA_DEVICE_UUID}'&$select=id"
    url_device_tag = "https://api.balena-cloud.com/v5/device_tag"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {BALENA_API_KEY}"}
    try:
        response = requests.get(url_device, headers=headers)
        if response.status_code == 200:
            data = response.json()
            device_id = data['d'][0]['id'] if 'd' in data and len(data['d']) > 0 else None
            request_data = {
                "device": device_id,
                "tag_key": "current_display",
                "value": val
            }
            request_data = {"device": device_id, "tag_key": "current_display", "value": val }
            current_display = get_current_display()
            if current_display:
                if current_display == val:
                    # No need to modify the tag
                    return None
                # Let's modify the existing tag with the new val
                requests.patch(url_device_tag, data=request_data, headers=headers)
            else:
                # No tag exists yet, so let's create it
                requests.post(url_device_tag, data=request_data, headers=headers)
    except requests.exceptions.RequestException as err:
        logging.error(f"Failed to set current display to {val}. Error is: {err}")

def temp_to_str(temp, scale):
    """Prepare the temperature to draw based on the defined scale: Celcius or Fahrenheit"""
    if scale == 'F':
        temp = temp * 9/5 + 32
    return temp

# Read the preset environment variables and overwrite the default ones
if "DEBUG" in os.environ:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

# Assume a default font if none set
FONT_SELECTED = AmaticSC
if "FONT" in os.environ:
    FONT_SELECTED = os.environ["FONT"]

FONT_SIZE = 24
if "FONT_SIZE" in os.environ:
    FONT_SIZE = int(os.environ["FONT_SIZE"])

# Check for a quote of the day category, otherwise use inspire
CATEGORY = "inspire"
if "QOD_CATEGORY" in os.environ:
    CATEGORY = os.environ['QOD_CATEGORY']

# Check for a quote of the day language. ** Note: Only English is supported currently. **
LANGUAGE = "en"
if "QOD_LANGUAGE" in os.environ:
    LANGUAGE = os.environ['QOD_LANGUAGE']

FONT = ImageFont.truetype(FONT_SELECTED, FONT_SIZE)

WEATHER_FONT = FredokaOne
if "WEATHER_FONT" in os.environ:
    WEATHER_FONT = locals()[os.environ["WEATHER_FONT"]]

WEATHER_INVERT = True if "WEATHER_INVERT" in os.environ else False

[LAT, LONG] = [float(x) for x in os.environ["LATLONG"].split(",")] if "LATLONG" in os.environ else [None, None]

# Temperature scale
SCALE = 'F' if "SCALE" in os.environ and os.environ["SCALE"] == 'F' else 'C'

# Locale formatting of date
LOCALE = os.environ["LOCALE"] if "LOCALE" in os.environ else 'en'

# Display mode of Inkyshot
MODE = os.environ["MODE"] if "MODE" in os.environ else 'quote'

# Read balena variables for balena API calls
BALENA_API_KEY = os.environ["BALENA_API_KEY"]
BALENA_DEVICE_UUID = os.environ["BALENA_DEVICE_UUID"]
BALENA_SUPERVISOR_ADDRESS = os.environ["BALENA_SUPERVISOR_ADDRESS"]
BALENA_SUPERVISOR_API_KEY = os.environ["BALENA_SUPERVISOR_API_KEY"]

WAVESHARE = True if "WAVESHARE" in os.environ else False

# Init the display. TODO: support other colours
logging.debug("Init and Clear")
if WAVESHARE:
    logging.info("Display type: Waveshare")

    import lib.epd2in13_V2
    display = lib.epd2in13_V2.EPD()
    display.init(display.FULL_UPDATE)
    display.Clear(0xFF)
    # These are the opposite of what InkyPhat uses.
    WIDTH = display.height # yes, Height
    HEIGHT = display.width # yes, width
    BLACK = 0
    WHITE = 1
    img = Image.new('1', (WIDTH, HEIGHT), 255)
else:
    import inky
    display = inky.auto()
    logging.info("Display type: " + type(display).__name__)
    display.set_border(display.WHITE)
    WIDTH = display.WIDTH
    HEIGHT = display.HEIGHT
    BLACK = display.BLACK
    WHITE = display.WHITE
    img = Image.new("P", (WIDTH, HEIGHT))

draw = ImageDraw.Draw(img)

logging.info("Display dimensions: W %s x H %s", WIDTH, HEIGHT)

# Reason the display mode based on environment variables and the current display (logic is explained in the readme)
current_display = get_current_display()
target_display = 'quote'
if MODE == 'weather'  or (MODE == 'alternate' and current_display == 'quote'):
    target_display = 'weather'

if target_display == 'weather':
    weather_location = None
    if "WEATHER_LOCATION" in os.environ:
        weather_location = os.environ["WEATHER_LOCATION"]
    # Get the latitute and longitude of the address typed in the env variable if latitude and longitude are not set
    if weather_location and (not LAT or not LONG):
        logging.info(f"Location is set to {weather_location}")
        try:
            geo = geocoder.arcgis(weather_location)
            [LAT, LONG] = geo.latlng
        except Exception as e:
            print(f"Unexpected error: {e.message}")

    # If no address or latitute / longitude are found, retrieve location via IP address lookup
    if not LAT or not LONG:
        location = get_location()
        [LAT, LONG] = [float(location['latitude']),float(location['longitude'])]
    weather = get_weather(LAT, LONG)
    # Set latitude and longituted as environment variables for consecutive calls
    os.environ['LATLONG'] = f"{LAT},{LONG}"
    # If weather is empty dictionary, fall back to drawing quote
    if len(weather) > 0:
        img = draw_weather(weather, img, SCALE)
    else:
        target_display = 'quote'
elif target_display == 'quote':
    # Use a dashboard defined message if we have one, otherwise load a nice quote
    message = os.environ['INKY_MESSAGE'] if 'INKY_MESSAGE' in os.environ else None
    # If message was set but blank, use the device name
    if message == "":
        message = os.environ['DEVICE_NAME']
    elif message is None:
        try:
            response = requests.get(
                f"https://www.mxnzp.com/api/daily_word/recommend?count=1&app_id=q6poeljklwrih9hd&app_secret=SFhvVGh4bitiUnd1VWZkcTlldUJuZz09",
                headers={"Accept" : "application/json"}
            )
            data = response.json()
            message = data['data'][0]['content']
        except requests.exceptions.RequestException as err:
            logging.error(err)
            FONT_SIZE = 20
            message = "对不起，今天没有新消息 :("

    logging.info("Message: %s", u"message")
    # Work out what size font is required to fit this message on the display
    message_does_not_fit = True

    test_character = "永"
    if "TEST_CHARACTER" in os.environ:
        test_character = os.environ['TEST_CHARACTER']

    while message_does_not_fit == True:
        test_message = ""
        message_width = 0
        FONT_SIZE -= 1

        if FONT_SIZE <= 8:
            FONT_SIZE = 24
            FONT = ImageFont.truetype("/usr/app/fonts/DottedSongtiDiamondRegular.otf", FONT_SIZE)

        # We're using the test character here to work out how many characters
        # can fit on the display when using the chosen font
        while message_width < WIDTH:
            test_message += test_character
            message_width, message_height = draw.textsize(test_message, font=FONT)

        max_width = len(test_message)
        max_lines = math.floor(HEIGHT/message_height)

        # We wrap the message to the width we worked out earlier
        wrapper = textwrap.TextWrapper(width=max_width)
        word_list = wrapper.wrap(text=message)

        if len(word_list) <= max_lines:
            message_does_not_fit = False

        if FONT_SIZE < 9:
            message_does_not_fit = False

    logging.info("Font size: %s", FONT_SIZE)
    offset_x, offset_y = FONT.getoffset(message)

    # Rejoin the wrapped lines with newline chars
    separator = '\n'
    output_text = separator.join(word_list)

    w, h = draw.multiline_textsize(output_text, font=FONT, spacing=0)

    x = (WIDTH - w)/2
    y = (HEIGHT - h - offset_y)/2
    draw.multiline_text((x, y), output_text, BLACK, FONT, align="center", spacing=0)

# Rotate and display the image
if "ROTATE" in os.environ:
    img = img.rotate(180)

if WAVESHARE:
    # epd does not have a set_image method.
    display.display(display.getbuffer(img))
else:
    display.set_image(img)
    display.show()

logging.info("Done drawing")

# Update device with the current display for ALTERNATE mode
if MODE == 'alternate':
    set_current_display(target_display)

sys.exit(0)
