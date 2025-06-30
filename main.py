import requests
import asyncio
import edge_tts
import os
import subprocess
import speech_recognition as sr
import pandas as pd
import yfinance as yf
from difflib import get_close_matches
from requests_toolbelt.multipart.encoder import MultipartEncoder
import re
import shutil

# --- הגדרות מערכת ימות המשיח ---
USERNAME = "0733181201"
PASSWORD = "6714453"
TOKEN = f"{USERNAME}:{PASSWORD}"
DOWNLOAD_PATH = "10"
UPLOAD_FOLDER_FOR_OUTPUT = "11"

# --- הגדרות קבצים ---
CSV_FILE_PATH = "stock_data.csv"
OUTPUT_AUDIO_FILE_NAME = "000.wav"
OUTPUT_INI_FILE_NAME = "ext.ini"
TEMP_MP3_FILE = "output.mp3"
TEMP_INPUT_WAV = "input.wav"

# --- נתיב להרצת ffmpeg ---
FFMPEG_EXECUTABLE = "ffmpeg"

def ensure_ffmpeg():
    global FFMPEG_EXECUTABLE
    if not shutil.which("ffmpeg"):
        print("⬇️ מתקין ffmpeg...")
        ffmpeg_bin_dir = "ffmpeg_bin"
        os.makedirs(ffmpeg_bin_dir, exist_ok=True)
        zip_path = "ffmpeg.zip"
        try:
            r = requests.get("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", stream=True)
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("✅ הורדת ffmpeg הושלמה.")
            import zipfile
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(ffmpeg_bin_dir)
            os.remove(zip_path)
            for root, _, files in os.walk(ffmpeg_bin_dir):
                if "ffmpeg" in files or "ffmpeg.exe" in files:
                    FFMPEG_EXECUTABLE = os.path.join(root, "ffmpeg")
                    os.environ["PATH"] += os.pathsep + root
                    print(f"✅ ffmpeg הותקן והוסף ל-PATH מנתיב: {FFMPEG_EXECUTABLE}")
                    return
            print("❌ שגיאה: לא נמצא קובץ הפעלה של ffmpeg.")
        except Exception as e:
            print(f"❌ שגיאה בהתקנת ffmpeg: {e}")
    else:
        print("⏩ ffmpeg כבר קיים.")

def download_yemot_file():
    url = "https://www.call2all.co.il/ym/api/GetIVR2Dir"
    params = {"token": TOKEN, "path": DOWNLOAD_PATH}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        files = response.json().get("files", [])
        valid_files = [(int(f["name"].replace(".wav", "")), f["name"])
                       for f in files if f.get("exists") and f["name"].endswith(".wav") and not f["name"].startswith("M")]
        if not valid_files:
            return None, None
        _, name = max(valid_files)
        dl_url = "https://www.call2all.co.il/ym/api/DownloadFile"
        dl_params = {"token": TOKEN, "path": f"ivr2:/{DOWNLOAD_PATH}/{name}"}
        r = requests.get(dl_url, params=dl_params)
        r.raise_for_status()
        with open(TEMP_INPUT_WAV, "wb") as f:
            f.write(r.content)
        print(f"📅 הקלטה חדשה הורדה: {name}")
        return TEMP_INPUT_WAV, name
    except Exception as e:
        print(f"❌ שגיאה בהורדה: {e}")
        return None, None

def transcribe_audio(filename):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(filename) as source:
            audio = r.record(source)
        return r.recognize_google(audio, language="he-IL")
    except Exception:
        return ""

def normalize_text(text):
    if not isinstance(text, str):
        if pd.isna(text):
            text = ""
        else:
            text = str(text)
    return re.sub(r'[^א-תa-zA-Z0-9 ]', '', text).lower().strip()

def load_stock_data(path):
    df = pd.read_csv(path)
    stock_data = {}
    for _, row in df.iterrows():
        has_dedicated_folder = str(row["has_dedicated_folder"]).lower() == 'true'
        stock_data[normalize_text(row["name"])] = {
            "symbol": row["symbol"],
            "display_name": row["display_name"],
            "type": row["type"],
            "has_dedicated_folder": has_dedicated_folder,
            "target_path": row["target_path"] if has_dedicated_folder and pd.notna(row["target_path"]) else ""
        }
    print(f"✅ נתוני מניות נטענו בהצלחה: {path}")
    return stock_data

def get_best_match(query, stock_dict):
    matches = get_close_matches(normalize_text(query), stock_dict.keys(), n=1, cutoff=0.6)
    return matches[0] if matches else None

def get_stock_price_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty or len(hist) < 2:
            return None
        current_price = hist["Close"].iloc[-1]
        day_before_price = hist["Close"].iloc[-2]
        day_change_percent = (current_price - day_before_price) / day_before_price * 100 if day_before_price else 0
        return {"current": round(current_price, 2), "day_change_percent": round(day_change_percent, 2)}
    except Exception:
        return None

def create_ext_ini_file(action_type, value):
    try:
        with open(OUTPUT_INI_FILE_NAME, 'w', encoding='windows-1255') as f:
            if action_type == "go_to_folder":
                f.write(f"type=go_to_folder\n")
                f.write(f"go_to_folder={value}\n")
            elif action_type == "play_file":
                f.write(f"type=playfile\n")
                f.write(f"file_name={value}\n")
        return True
    except Exception:
        return False

def upload_file_to_yemot(file_path, yemot_path):
    full_upload_path = f"ivr2:/{UPLOAD_FOLDER_FOR_OUTPUT}/{yemot_path}"
    m = MultipartEncoder(fields={
        "token": TOKEN,
        "path": full_upload_path,
        "upload": (os.path.basename(file_path), open(file_path, 'rb'), 'audio/wav' if file_path.endswith('.wav') else 'text/plain')
    })
    try:
        requests.post("https://www.call2all.co.il/ym/api/UploadFile", data=m, headers={'Content-Type': m.content_type})
        return True
    except Exception:
        return False

def convert_mp3_to_wav(mp3_file, wav_file):
    try:
        subprocess.run([FFMPEG_EXECUTABLE, "-loglevel", "error", "-y", "-i", mp3_file, "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_file], check=True)
        return True
    except Exception:
        return False

async def create_audio_file_from_text(text, filename):
    try:
        await edge_tts.Communicate(text, voice="he-IL-AvriNeural").save(filename)
        return True
    except Exception:
        return False

async def main_loop():
    stock_data = load_stock_data(CSV_FILE_PATH)
    ensure_ffmpeg()
    last_processed_file = None
    while True:
        filename, yemot_filename = download_yemot_file()
        if not yemot_filename or yemot_filename == last_processed_file:
            await asyncio.sleep(1)
            continue
        last_processed_file = yemot_filename
        print(f"\U0001f4e5 זוהה קובץ חדש: {yemot_filename}")
        recognized_text = transcribe_audio(TEMP_INPUT_WAV)
        if recognized_text:
            best_match_key = get_best_match(recognized_text, stock_data)
            if best_match_key:
                stock_info = stock_data[best_match_key]
                if stock_info["has_dedicated_folder"] and stock_info["target_path"]:
                    if create_ext_ini_file("go_to_folder", stock_info["target_path"]):
                        upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
                else:
                    data = get_stock_price_data(stock_info["symbol"])
                    if data:
                        direction = "עלייה" if data["day_change_percent"] > 0 else "ירידה"
                        text = f"מחיר מניית {stock_info['display_name']} עומד כעת על {data['current']} דולר. מתחילת היום נרשמה {direction} של {abs(data['day_change_percent'])} אחוז."
                    else:
                        text = f"מצטערים, לא הצלחנו למצוא נתונים עבור מניית {stock_info['display_name']}."
                    if await create_audio_file_from_text(text, TEMP_MP3_FILE):
                        if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                            upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME)
                            if create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME):
                                upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
            else:
                error_text = "לא הצלחנו לזהות את נייר הערך שביקשת. אנא נסה שנית."
                if await create_audio_file_from_text(error_text, TEMP_MP3_FILE):
                    if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                        upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME)
                        if create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME):
                            upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
        else:
            error_text = "לא זוהה דיבור ברור בהקלטה."
            if await create_audio_file_from_text(error_text, TEMP_MP3_FILE):
                if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                    upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME)
                    if create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME):
                        upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
        for f in [TEMP_INPUT_WAV, TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME, OUTPUT_INI_FILE_NAME]:
            if os.path.exists(f):
                os.remove(f)
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main_loop())
