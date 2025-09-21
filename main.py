import os
import tempfile
import logging
import requests
from flask import Flask, request, jsonify
from pydub import AudioSegment
import speech_recognition as sr
from rapidfuzz import process, fuzz
 
# ------------------ Logging Configuration ------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
 
app = Flask(__name__)
 
# List of possible keywords to match
KEYWORDS = ["בני ברק", "ירושלים", "תל אביב", "חיפה", "אשדוד"]
 
# ------------------ Helper Functions ------------------
 
def add_silence(input_path: str) -> AudioSegment:
    """
    Add one second of silence at the beginning and end of the audio file.
    This improves speech recognition accuracy, especially for short recordings.
    """
    logging.info("Adding one second of silence to audio file...")
    audio = AudioSegment.from_file(input_path, format="wav")
    silence = AudioSegment.silent(duration=1000)  # 1000ms = 1 second
    return silence + audio + silence
 
def recognize_speech(audio_segment: AudioSegment) -> str:
    """
    Perform speech recognition using Google SpeechRecognition API.
    """
    recognizer = sr.Recognizer()
    try:
        # Use a temporary file for SpeechRecognition to read
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as temp_wav:
            audio_segment.export(temp_wav.name, format="wav")
            with sr.AudioFile(temp_wav.name) as source:
                data = recognizer.record(source)
 
            text = recognizer.recognize_google(data, language="he-IL")
            logging.info(f"Recognized text: {text}")
            return text
    except sr.UnknownValueError:
        logging.warning("Speech not detected or unclear.")
        return ""
    except Exception as e:
        logging.error(f"Error during speech recognition: {e}")
        return ""
 
def find_best_match(text: str) -> str | None:
    """
    Find the closest matching word from the predefined KEYWORDS list.
    """
    if not text:
        return None
 
    result = process.extractOne(text, KEYWORDS, scorer=fuzz.ratio)
    if result and result[1] >= 80:
        logging.info(f"Best match found: {result[0]} (confidence: {result[1]}%)")
        return result[0]
 
    logging.info("No sufficient match found.")
    return None
 
# ------------------ API Endpoint ------------------
 
@app.route("/upload_audio", methods=["GET"])
def upload_audio():
    """
    Endpoint to receive an audio file via GET parameter,
    download it, process it, and return the recognized text with the best match.
    Example usage:
    /upload_audio?file_url=https://example.com/audio.wav
    """
    file_url = request.args.get("file_url")
    if not file_url:
        logging.error("Missing 'file_url' parameter.")
        return jsonify({"error": "Missing 'file_url' parameter"}), 400
 
    logging.info(f"Received file URL: {file_url}")
 
    try:
        # Step 1: Download the audio file
        response = requests.get(file_url, timeout=15)
        if response.status_code != 200:
            logging.error(f"Failed to download audio file. Status code: {response.status_code}")
            return jsonify({"error": "Failed to download audio file"}), 400
 
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as temp_input:
            temp_input.write(response.content)
            temp_input.flush()
            logging.info(f"Audio downloaded and saved temporarily: {temp_input.name}")
 
            # Step 2: Add silence
            processed_audio = add_silence(temp_input.name)
 
            # Step 3: Speech recognition
            recognized_text = recognize_speech(processed_audio)
 
            # Step 4: Matching against predefined keywords
            matched_word = find_best_match(recognized_text)
 
            if matched_word:
                logging.info(f"Final matched keyword: {matched_word}")
            else:
                logging.info("No keyword match found.")
 
    except Exception as e:
        logging.error(f"Processing error: {e}")
        return jsonify({"error": "Error processing the audio file"}), 500
 
    return jsonify({
        "recognized_text": recognized_text,
        "matched_word": matched_word if matched_word else "No match found"
    })
 
# ------------------ Run Server ------------------
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Server running on port {port}")
    app.run(host="0.0.0.0", port=port)
