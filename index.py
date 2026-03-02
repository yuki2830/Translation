import os
import queue
import re
import sys
import threading
import time
import html
import uuid
from datetime import datetime
from google.cloud import speech
from google.cloud import translate_v2 as translate
from google.cloud import texttospeech  # ここを独立させるか、以下を確認
# 12行目あたりからの環境設定部分を以下に書き換え
# =========================
# 環境設定（ポータブル対応版）
# =========================
def get_base_path():
    if getattr(sys, 'frozen', False):
        # PyInstallerなどでexe化されている場合
        return os.path.dirname(sys.executable)
    # 通常のPythonスクリプトとして実行されている場合
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_path()
# JSONファイルの名前をここに書く（ファイル名は適宜合わせてください）
JSON_NAME = "comworks-stream1-dae0ee0dd58b.json"
JSON_PATH = os.path.join(BASE_DIR, JSON_NAME)

if not os.path.exists(JSON_PATH):
    print(f"\n[エラー] 認証ファイルが見つかりません: {JSON_NAME}")
    print(f"このプログラムと同じフォルダにJSONファイルを置いてください。")
    time.sleep(5)
    sys.exit()

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = JSON_PATH
from google.api_core.exceptions import OutOfRange, DeadlineExceeded
import pyaudio
import pygame
import requests

VMIX_URL = "http://127.0.0.1:8088/API/"
VMIX_INPUT = "CaptionTitle"
VMIX_FIELD = "Message.Text"

TRANS_LOG_FILE = f"translation_log_{datetime.now().strftime('%Y%m%d')}.txt"

RATE = 16000
CHUNK = int(RATE / 10)

# 【強化】行政・市長会見用 補正辞書
WORD_REPLACEMENTS = {
    "帝国": "定刻",
    "ダンス 完走": "脱炭素",
    "ダンス完走": "脱炭素",
    "5組目": "5期目",
    "ご機嫌": "5期目",
    "本誌": "本市",
    "避難させていただく": "担わせていただく",
    "重責を避難": "重責を担い",
    "お見積もりをいただきました": "お認めをいただきました",
    "生活保護機": "幸多き",
    "web化": "省エネ化"
}

# =========================
# 音声・翻訳・再生管理
# =========================
class EnglishSpeaker:
    def __init__(self):
        self.client = texttospeech.TextToSpeechClient()
        self.voice = texttospeech.VoiceSelectionParams(
            language_code="en-US", name="en-US-Wavenet-D"
        )
        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16, # MP3エラー回避のためWAV形式に変更
            speaking_rate=0.85 # リスニング試験にならないよう、落ち着いた速度
        )
        self.speak_queue = queue.Queue()
        self.mixer_initialized = False
        
        # オーディオ初期化の試行
        try:
            pygame.mixer.init(frequency=24000)
            self.mixer_initialized = True
        except Exception as e:
            print(f"\n[警告] スピーカーの初期化に失敗しました。読み上げはスキップされます: {e}")

        if self.mixer_initialized:
            threading.Thread(target=self._worker, daemon=True).start()

    def enqueue_text(self, text):
        if self.mixer_initialized:
            self.speak_queue.put(text)

    def _worker(self):
        while True:
            text = self.speak_queue.get()
            if text is None: break
            try:
                self._execute_speak(text)
                time.sleep(2.0) # 文章の間に2秒の「ため」を作る
            except: pass
            self.speak_queue.task_done()

    def _execute_speak(self, text):
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            response = self.client.synthesize_speech(
                input=synthesis_input, voice=self.voice, audio_config=self.audio_config
            )
            
            fname = f"tts_{uuid.uuid4()}.wav"
            with open(fname, "wb") as out:
                out.write(response.audio_content)
            
            sound = pygame.mixer.Sound(fname)
            sound.play()
            
            while pygame.mixer.get_busy():
                time.sleep(0.1)
                
            # 使用済みファイルのクリーンアップ
            threading.Timer(2.0, self._safe_remove, args=[fname]).start()
        except: pass

    def _safe_remove(self, fname):
        try:
            if os.path.exists(fname): os.remove(fname)
        except: pass

# =========================
# マイク入力（スキャン機能）
# =========================
class MicrophoneStream:
    def __init__(self, rate, chunk):
        self._rate, self._chunk = rate, chunk
        self._buff = queue.Queue()
        self.closed = True
        self._p = pyaudio.PyAudio()
        self.device_index = self._find_best_device()

    def _find_best_device(self):
        print("\n--- デバイススキャン開始 ---")
        target_idx = None
        for i in range(self._p.get_device_count()):
            try:
                info = self._p.get_device_info_by_index(i)
                name = info.get("name", "")
                if info.get("maxInputChannels") > 0:
                    print(f"ID {i}: {name}")
                    if "CABLE" in name.upper() and target_idx is None:
                        target_idx = i
            except: continue
        if target_idx is not None:
            print(f"==> 【自動選択】ID {target_idx} を使用します。\n")
        return target_idx

    def __enter__(self):
        self._stream = self._p.open(
            format=pyaudio.paInt16, channels=1, rate=self._rate,
            input=True, frames_per_buffer=self._chunk,
            input_device_index=self.device_index,
            stream_callback=self._fill_buffer,
        )
        self.closed = False
        return self

    def __exit__(self, *args):
        self._stream.stop_stream()
        self._stream.close()
        self.closed = True
        self._buff.put(None)
        self._p.terminate()

    def _fill_buffer(self, in_data, *args):
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None: return
            yield chunk

# =========================
# メイン制御
# =========================
def send_to_vmix(text):
    try: requests.get(VMIX_URL, params={"Function": "SetText", "Input": VMIX_INPUT, "SelectedName": VMIX_FIELD, "Value": text}, timeout=0.5)
    except: pass

def listen_loop(responses, translator, speaker):
    num_chars_printed = 0
    for response in responses:
        if not response.results: continue
        result = response.results[0]
        if not result.alternatives: continue
        transcript = result.alternatives[0].transcript

        # 誤認識補正の実行
        for old, new in WORD_REPLACEMENTS.items():
            transcript = transcript.replace(old, new)

        # 表示整理
        display_text = transcript[-50:] if len(transcript) > 50 else transcript
        overwrite_chars = " " * (num_chars_printed - len(display_text))

        if not result.is_final:
            sys.stdout.write(f"\rRecognizing: {display_text}{overwrite_chars}")
            sys.stdout.flush()
            num_chars_printed = len(display_text)
        else:
            print(f"\n[確定/JP] {transcript}")
            num_chars_printed = 0
            try:
                translation = translator.translate(transcript, target_language="en")
                en_text = html.unescape(translation['translatedText'])
                print(f"[翻訳/EN] {en_text}")

                with open(TRANS_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}]\nJP: {transcript}\nEN: {en_text}\n{'-'*30}\n")

                threading.Thread(target=send_to_vmix, args=(en_text,), daemon=True).start()
                speaker.enqueue_text(en_text)
            except Exception as e:
                print(f"Error: {e}")

def main():
    translator, speaker, client = translate.Client(), EnglishSpeaker(), speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE, language_code="ja-JP",
        enable_automatic_punctuation=True, model="latest_long", use_enhanced=True
    )
    streaming_config = speech.StreamingRecognitionConfig(config=config, interim_results=True)

    with MicrophoneStream(RATE, CHUNK) as stream:
        while True:
            print(f"--- ストリーム開始 ({datetime.now().strftime('%H:%M:%S')}) ---")
            reqs = (speech.StreamingRecognizeRequest(audio_content=c) for c in stream.generator())
            resps = client.streaming_recognize(config=streaming_config, requests=reqs)
            try: listen_loop(resps, translator, speaker)
            except (OutOfRange, DeadlineExceeded): continue
            except Exception as e:
                print(f"\n[再起動中...] {e}")
                time.sleep(1)

if __name__ == "__main__":
    main()