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
DOWNLOAD_PATH = "1/2/2/10"  # שלוחת ההקלטות בימות המשיח
UPLOAD_FOLDER_FOR_OUTPUT = "1/2/2/11" # התיקייה אליה יעלו קבצי הפלט (000.wav ו-ext.ini)

# --- הגדרות קבצים ---
CSV_FILE_PATH = "stock_data.csv"  # שם קובץ ה-CSV עם נתוני המניות
OUTPUT_AUDIO_FILE_NAME = "000.wav" # שם קובץ השמע שייווצר (000.wav)
OUTPUT_INI_FILE_NAME = "ext.ini"   # שם קובץ ה-INI שייווצר (ext.ini)
TEMP_MP3_FILE = "output.mp3"      # קובץ זמני ליצירת שמע לפני המרה ל-WAV
TEMP_INPUT_WAV = "input.wav"      # קובץ זמני להורדת הקלטה מימות המשיח

# --- פונקציות עזר ---

def ensure_ffmpeg():
    """
    בודק אם ffmpeg מותקן וזמין ב-PATH. אם לא, מנסה להוריד ולהתקין.
    """
    if not shutil.which("ffmpeg"):
        print("⬇️ מתקין ffmpeg...")
        # יצירת תיקייה זמנית ל-ffmpeg אם אינה קיימת
        ffmpeg_bin_dir = "ffmpeg_bin"
        os.makedirs(ffmpeg_bin_dir, exist_ok=True)
        zip_path = "ffmpeg.zip"
        
        try:
            # הורדת קובץ ה-zip של ffmpeg
            r = requests.get("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", stream=True)
            r.raise_for_status() # Raise an exception for bad status codes
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("✅ הורדת ffmpeg הושלמה.")

            # פתיחת קובץ ה-zip
            import zipfile
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(ffmpeg_bin_dir)
            os.remove(zip_path) # מחיקת קובץ ה-zip לאחר החילוץ
            
            # הוספת הנתיב של ffmpeg ל-PATH של המערכת
            for root, _, files in os.walk(ffmpeg_bin_dir):
                if "ffmpeg.exe" in files: # For Windows
                    os.environ["PATH"] += os.pathsep + os.path.join(root)
                    print(f"✅ ffmpeg הותקן והוסף ל-PATH מנתיב: {os.path.join(root)}")
                    return
                elif "ffmpeg" in files: # For Linux/macOS
                    os.environ["PATH"] += os.pathsep + os.path.join(root)
                    print(f"✅ ffmpeg הותקן והוסף ל-PATH מנתיב: {os.path.join(root)}")
                    return
            print("❌ שגיאה: לא נמצא קובץ הפעלה של ffmpeg לאחר החילוץ.")
        except Exception as e:
            print(f"❌ שגיאה בהתקנת ffmpeg: {e}")
            print("אנא וודא ש-ffmpeg מותקן וזמין ב-PATH שלך באופן ידני.")
    else:
        print("⏩ ffmpeg כבר קיים.")

def download_yemot_file():
    """
    מוריד את קובץ ההקלטה החדש ביותר משלוחת ההקלטות בימות המשיח.
    מחזיר את נתיב הקובץ המקומי ואת שם הקובץ המקורי בימות המשיח.
    """
    url = "https://www.call2all.co.il/ym/api/GetIVR2Dir"
    params = {"token": TOKEN, "path": DOWNLOAD_PATH}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # יזרוק שגיאה עבור קודי סטטוס שאינם 200
        files = response.json().get("files", [])
        
        # סינון קבצי WAV תקינים שאינם מתחילים ב-M (קבצי מערכת/הודעות)
        valid_files = [(int(f["name"].replace(".wav", "")), f["name"]) 
                       for f in files if f.get("exists") and f["name"].endswith(".wav") and not f["name"].startswith("M")]
        
        if not valid_files:
            return None, None
        
        # מציאת הקובץ החדש ביותר (מספר גבוה ביותר)
        _, name = max(valid_files)
        
        dl_url = "https://www.call2all.co.il/ym/api/DownloadFile"
        dl_params = {"token": TOKEN, "path": f"ivr2:/{DOWNLOAD_PATH}/{name}"}
        
        r = requests.get(dl_url, params=dl_params)
        r.raise_for_status() # יזרוק שגיאה עבור קודי סטטוס שאינם 200
        
        with open(TEMP_INPUT_WAV, "wb") as f:
            f.write(r.content)
        
        print(f"📥 הקלטה חדשה הורדה: {name}")
        return TEMP_INPUT_WAV, name
    except requests.exceptions.RequestException as e:
        print(f"❌ שגיאת הורדה מימות המשיח: {e}")
        return None, None
    except Exception as e:
        print(f"❌ שגיאה בתהליך הורדת קובץ: {e}")
        return None, None

def transcribe_audio(filename):
    """
    ממיר קובץ שמע לטקסט באמצעות Google Web Speech API.
    """
    r = sr.Recognizer()
    try:
        with sr.AudioFile(filename) as source:
            audio = r.record(source)
        return r.recognize_google(audio, language="he-IL")
    except sr.UnknownValueError:
        print("❌ דיבור לא זוהה.")
        return ""
    except sr.RequestError as e:
        print(f"❌ שגיאה בשירות זיהוי הדיבור; {e}")
        return ""
    except Exception as e:
        print(f"❌ שגיאה בתמלול אודיו: {e}")
        return ""

def normalize_text(text):
    """
    מנרמל טקסט עבור התאמה (מסיר תווים מיוחדים וממיר לאותיות קטנות).
    """
    # ודא שהקלט הוא מחרוזת. אם הוא לא (לדוגמה, float NaN), המר אותו למחרוזת ריקה.
    if not isinstance(text, str):
        if pd.isna(text): # אם זה NaN (שמופיע כ-float), התייחס אליו כריק
            text = ""
        else: # אם זה סוג אחר של לא-מחרוזת, המר למחרוזת
            text = str(text) 
    
    return re.sub(r'[^א-תa-zA-Z0-9 ]', '', text).lower().strip()

def load_stock_data(path):
    """
    טוען את נתוני המניות מקובץ ה-CSV.
    הערה: המפתח למילון הוא 'name' (השם לזיהוי דיבור),
    'display_name' הוא השם המנוקד לתצוגה/השמעה.
    """
    df = pd.read_csv(path)
    stock_data = {}
    for _, row in df.iterrows():
        # ודא שהערכים הבוליאניים מומרים כראוי
        has_dedicated_folder = str(row["has_dedicated_folder"]).lower() == 'true'
        # הערה: הסרתי את str() כאן מכיוון ש-normalize_text מטפלת בזה עכשיו
        stock_data[normalize_text(row["name"])] = { 
            "symbol": row["symbol"],
            "display_name": row["display_name"],
            "type": row["type"],
            "has_dedicated_folder": has_dedicated_folder,
            "target_path": row["target_path"] if has_dedicated_folder and pd.notna(row["target_path"]) else ""
        }
    print(f"✅ נתוני מניות נטענו בהצלחה מ- {path}")
    return stock_data

def get_best_match(query, stock_dict):
    """
    מוצא את ההתאמה הטובה ביותר עבור השאילתה מול שמות המניות.
    """
    matches = get_close_matches(normalize_text(query), stock_dict.keys(), n=1, cutoff=0.6)
    return matches[0] if matches else None

def get_stock_price_data(ticker):
    """
    מקבל טיקר מניה ומחזיר את מחירה הנוכחי ואחוז שינוי יומי.
    """
    try:
        stock = yf.Ticker(ticker)
        # Fetching data for a period that includes at least two trading days
        hist = stock.history(period="5d") 
        
        if hist.empty or len(hist) < 2:
            print(f"⚠️ לא נמצאו מספיק נתוני היסטוריה עבור {ticker}.")
            return None
        
        current_price = hist["Close"].iloc[-1]
        day_before_price = hist["Close"].iloc[-2] # Price of the previous trading day
        
        if day_before_price == 0: # Avoid division by zero
            day_change_percent = 0
        else:
            day_change_percent = (current_price - day_before_price) / day_before_price * 100
        
        return {
            "current": round(current_price, 2),
            "day_change_percent": round(day_change_percent, 2)
        }
    except Exception as e:
        print(f"❌ שגיאה בקבלת נתוני מניה עבור {ticker}: {e}")
        return None

async def create_audio_file_from_text(text, filename):
    """
    יוצר קובץ שמע (MP3) מטקסט נתון באמצעות Edge TTS.
    """
    try:
        # קובץ השמע מוכן עם שם הקובץ הזמני (output.mp3)
        await edge_tts.Communicate(text, voice="he-IL-AvriNeural").save(filename)
        print(f"✅ קובץ שמע נוצר בהצלחה: {filename}")
        return True
    except Exception as e:
        print(f"❌ שגיאה ביצירת קובץ שמע: {e}")
        return False

def convert_mp3_to_wav(mp3_file, wav_file):
    """
    ממיר קובץ MP3 לקובץ WAV בפורמט הנדרש לימות המשיח.
    """
    try:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", mp3_file, 
                        "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_file], 
                       check=True) # check=True will raise an error if ffmpeg fails
        print(f"✅ המרת {mp3_file} ל- {wav_file} הושלמה.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ שגיאת המרה עם ffmpeg: {e}")
        print(f"ודא ש-ffmpeg מותקן ונגיש ב-PATH.")
        return False
    except Exception as e:
        print(f"❌ שגיאה כללית בהמרה: {e}")
        return False

def upload_file_to_yemot(file_path, yemot_path):
    """
    מעלה קובץ לימות המשיח.
    """
    # יצירת נתיב ההעלאה המלא עבור הקובץ הספציפי
    full_upload_path = f"ivr2:/{UPLOAD_FOLDER_FOR_OUTPUT}/{yemot_path}"
    
    m = MultipartEncoder(fields={
        "token": TOKEN,
        "path": full_upload_path,
        "upload": (os.path.basename(file_path), open(file_path, 'rb'), 'audio/wav' if file_path.endswith('.wav') else 'text/plain')
    })
    
    try:
        r = requests.post("https://www.call2all.co.il/ym/api/UploadFile", data=m, 
                          headers={'Content-Type': m.content_type})
        r.raise_for_status() # יזרוק שגיאה עבור קודי סטטוס שאינם 200
        print(f"⬆️ הקובץ {os.path.basename(file_path)} הועלה בהצלחה לנתיב: {full_upload_path}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ שגיאה בהעלאת קובץ לימות המשיח: {e}")
        return False
    except Exception as e:
        print(f"❌ שגיאה כללית בהעלאת קובץ: {e}")
        return False

def create_ext_ini_file(action_type, value):
    """
    יוצר קובץ ext.ini בהתאם לפעולה הנדרשת (הפניה לשלוחה או השמעת קובץ).
    """
    file_path = OUTPUT_INI_FILE_NAME # קובץ ext.ini תמיד באותה תיקייה
    try:
        # קידוד 1255 עבור ימות המשיח - חובה!
        with open(file_path, 'w', encoding='windows-1255') as f: 
            if action_type == "go_to_folder":
                f.write(f"type=go_to_folder\n")
                f.write(f"go_to_folder={value}\n")
                print(f"✅ קובץ {OUTPUT_INI_FILE_NAME} נוצר בהצלחה עם הפנייה לשלוחה: {value}")
            elif action_type == "play_file":
                f.write(f"type=playfile\n")
                f.write(f"file_name={value}\n")
                print(f"✅ קובץ {OUTPUT_INI_FILE_NAME} נוצר בהצלחה עם הפנייה לקובץ שמע: {value}")
            else:
                print(f"❌ סוג פעולה לא נתמך עבור {OUTPUT_INI_FILE_NAME}: {action_type}")
                return False
        return True
    except Exception as e:
        print(f"❌ שגיאה בכתיבת קובץ {OUTPUT_INI_FILE_NAME}: {e}")
        return False

async def main_loop():
    """
    הלולאה הראשית של הסקריפט: מזהה קבצי הקלטה, מעבד אותם ומגיב.
    """
    stock_data = load_stock_data(CSV_FILE_PATH)
    if stock_data is None:
        print("❌ הסקריפט לא יכול להמשיך ללא נתוני מניות.")
        return

    print("🔁 התחילה לולאה שמזהה קבצים כל שנייה...")

    ensure_ffmpeg() # וודא ש-ffmpeg קיים

    last_processed_file = None

    while True:
        filename, file_name_only = download_yemot_file()

        if not file_name_only:
            await asyncio.sleep(1) # אין קבצים חדשים, המתן שניה
            continue

        if file_name_only == last_processed_file:
            await asyncio.sleep(1) # אותו קובץ כמו בפעם הקודמת, המתן שניה
            continue

        last_processed_file = file_name_only
        print(f"📥 זוהה קובץ חדש: {file_name_only}")

        recognized_text = transcribe_audio(TEMP_INPUT_WAV) # תמלול הקובץ המקומי

        if recognized_text:
            print(f"👂 זוהה דיבור: '{recognized_text}'")
            best_match_key = get_best_match(recognized_text, stock_data)

            if best_match_key:
                stock_info = stock_data[best_match_key]
                symbol = stock_info['symbol']
                display_name = stock_info['display_name']
                has_dedicated_folder = stock_info['has_dedicated_folder']
                target_path = stock_info['target_path']

                print(f"🎯 התאמה הטובה ביותר: {display_name} ({symbol})")

                if has_dedicated_folder and target_path:
                    # אם יש שלוחה ייעודית מוגדרת וקיימת
                    print(f"➡️ למניה יש שלוחה ייעודית: {target_path}. מפנה לשם.")
                    if create_ext_ini_file("go_to_folder", target_path):
                        upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
                    else:
                        print("❌ שגיאה ביצירת קובץ INI להפניה לשלוחה.")
                else:
                    # אין שלוחה ייעודית, או שהשדות לא מולאו כראוי - משיכת נתונים והשמעה
                    print(f"ℹ️ למניה אין שלוחה ייעודית או שהנתיב לא הוגדר. משיכת נתונים והשמעת מחיר.")
                    stock_price_data = get_stock_price_data(symbol)
                    
                    if stock_price_data:
                        change_direction = 'עלייה' if stock_price_data['day_change_percent'] > 0 else 'ירידה'
                        # קובץ השמע מוכן עם שם הקובץ הזמני (output.mp3)
                        audio_text = (
                            f"מחיר מניית {display_name} עומד כעת על {stock_price_data['current']} דולר. "
                            f"מתחילת היום נרשמה {change_direction} של {abs(stock_price_data['day_change_percent'])} אחוז."
                        )
                        
                        if await create_audio_file_from_text(audio_text, TEMP_MP3_FILE):
                            if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                                # העלאת קובץ השמע
                                if upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME):
                                    # יצירת והעלאת ext.ini להפניה לקובץ השמע שנוצר
                                    if create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME):
                                        upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
                    else:
                        print(f"❌ לא ניתן להשיג נתוני מחיר עבור {display_name}. מכין הודעת שגיאה קולית.")
                        error_text = f"מצטערים, לא הצלחנו למצוא נתונים עבור מניית {display_name}."
                        if await create_audio_file_from_text(error_text, TEMP_MP3_FILE):
                            if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                                if upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME):
                                    create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME)
                                    upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
            else:
                print("❌ לא זוהה נייר ערך תואם ברשימה.")
                error_text = "לא הצלחנו לזהות את נייר הערך שביקשת. אנא נסה שנית."
                if await create_audio_file_from_text(error_text, TEMP_MP3_FILE):
                    if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                        if upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME):
                            create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME)
                            upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
        else:
            print("❌ לא זוהה דיבור ברור מהקלטה.")
            error_text = "לא זוהה דיבור ברור בהקלטה. אנא נסה שנית."
            if await create_audio_file_from_text(error_text, TEMP_MP3_FILE):
                if convert_mp3_to_wav(TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME):
                    if upload_file_to_yemot(OUTPUT_AUDIO_FILE_NAME, OUTPUT_AUDIO_FILE_NAME):
                        create_ext_ini_file("play_file", OUTPUT_AUDIO_FILE_NAME)
                        upload_file_to_yemot(OUTPUT_INI_FILE_NAME, OUTPUT_INI_FILE_NAME)
        
        # ניקוי קבצים זמניים
        for f in [TEMP_INPUT_WAV, TEMP_MP3_FILE, OUTPUT_AUDIO_FILE_NAME, OUTPUT_INI_FILE_NAME]:
            if os.path.exists(f):
                os.remove(f)
        
        print("✅ סבב עיבוד הסתיים. ממתין לקובץ חדש...\n")
        await asyncio.sleep(1) # המתן שניה לפני הבדיקה הבאה

# --- הפעלת הלולאה הראשית ---
if __name__ == "__main__":
    asyncio.run(main_loop())
