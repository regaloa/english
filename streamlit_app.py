import streamlit as st
import streamlit.components.v1 as components
import random
import time
import json
import requests
import google.generativeai as genai  # ★安定版ライブラリ
from supabase import create_client

# ==========================================
# 0. アプリ基本設定
# ==========================================
st.set_page_config(page_title="Pokémon English Battle", layout="wide")

# ==========================================
# 1. 設定 & 定数
# ==========================================
RANK_MAP = {
    "モンスターボール級 (基礎: 400点)": "TOEIC score 350-450 level (Basic)",
    "スーパーボール級 (応用: 550点)": "TOEIC score 500-600 level (Intermediate)",
    "ハイパーボール級 (実戦: 700点)": "TOEIC score 600-700 level (Upper-Intermediate)",
    "マスターボール級 (難関: 700点+)": "TOEIC score 700-750 level (Advanced)"
}

RANK_TAGS = {
    "モンスターボール級 (基礎: 400点)": "beginner",
    "スーパーボール級 (応用: 550点)": "intermediate",
    "ハイパーボール級 (実戦: 700点)": "advanced",
    "マスターボール級 (難関: 700点+)": "master"
}

# Secretsの読み込み確認
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except:
    st.error("⚠️ Secretsの設定が見つかりません。'.streamlit/secrets.toml' を確認してください。")
    st.stop()

@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        return None

supabase = init_supabase()

if not supabase:
    st.error("⚠️ データベースに接続できませんでした。")
    st.stop()

# ==========================================
# 2. 外部API & DB関数
# ==========================================

def play_pronunciation(text):
    """ブラウザ標準機能で音声再生"""
    js_code = f"""
    <script>
        function speak() {{
            const msg = new SpeechSynthesisUtterance();
            msg.text = "{text}";
            msg.lang = 'en-US';
            window.speechSynthesis.speak(msg);
        }}
        speak();
    </script>
    """
    components.html(js_code, height=0)

def get_random_pokemon_data(rank_index):
    """PokeAPIからIDと画像を取得"""
    try:
        if rank_index == 0:
            poke_id = random.randint(1, 151)
        elif rank_index == 1:
            poke_id = random.randint(152, 251)
        elif rank_index == 2:
            poke_id = random.randint(252, 386)
        else:
            poke_id = random.randint(387, 1000) 

        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            img_url = data["sprites"]["front_default"]
            return poke_id, img_url
    except:
        pass
    return None, None

def get_fallback_words_from_db(rank_name):
    """AIがない場合、DBから単語を取得する"""
    target_level = RANK_TAGS.get(rank_name, "beginner")
    
    try:
        res = supabase.table("toeic_words").select("word_en, word_jp").eq("rank_level", target_level).execute()
        data = res.data
        
        # データ不足時は全データから補充
        if len(data) < 8:
            res_all = supabase.table("toeic_words").select("word_en, word_jp").execute()
            data = res_all.data
            
        if data and len(data) >= 8:
            selected = random.sample(data, 8)
            return [{"en": item["word_en"], "jp": item["word_jp"]} for item in selected]
            
    except Exception:
        pass
    
    # 最終手段
    return [
        {"en": "Error", "jp": "エラー"},
        {"en": "Retry", "jp": "再読込"},
        {"en": "Check", "jp": "確認"},
        {"en": "Connection", "jp": "接続"},
        {"en": "Database", "jp": "DB"},
        {"en": "System", "jp": "システム"},
        {"en": "Update", "jp": "更新"},
        {"en": "Wait", "jp": "待機"}
    ]

def generate_quiz_words(api_key, rank_prompt, rank_name_for_db):
    """AIに単語リストを作らせる (google-generativeai版)"""
    if not api_key:
        return get_fallback_words_from_db(rank_name_for_db)

    try:
        genai.configure(api_key=api_key)
        
        # モデル指定 (gemini-pro)
        model = genai.GenerativeModel("gemini-pro")
        
        prompt = f"""
        Generate 8 unique English vocabulary words specifically for {rank_prompt}.
        The words should be commonly found in TOEIC tests but NOT exceeding the 750 score level.
        Output MUST be a valid JSON list of objects with 'en' (English word) and 'jp' (Japanese meaning).
        Example: [{{"en": "Profit", "jp": "利益"}}, {{"en": "Hire", "jp": "雇う"}}]
        Just the raw JSON string without markdown code blocks.
        """
        response = model.generate_content(prompt)
        
        # AIが余計な文字をつけてきた場合に掃除する処理
        text = response.text
        text = text.replace("```json", "").replace("```", "").strip()
        
        return json.loads(text)

    except Exception as e:
        # エラー時は静かにDBモードへ切り替え
        st.error(f"⚠️ AIエラー発生: {e}")
        st.warning("10秒後にオフラインモード（DB単語帳）に切り替わります...")
        time.sleep(10)
        return get_fallback_words_from_db(rank_name_for_db)

def get_english_story(api_key, words):
    """英語の物語生成"""
    if not api_key: return "Story generation skipped (Needs AI Key)."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-pro")
        
        prompt = f"""
        Write a short and **simple** Pokémon-style adventure story in English using these words: {', '.join(words)}.
        The English level should be easy to read (suitable for TOEIC 600 learners).
        Highlight the used words in **bold**.
        Keep it under 100 words.
        """
        
        response = model.generate_content(prompt)
        return response.text
    except:
        return "Failed to generate story (AI Error)."

# --- DB操作 ---

def save_pokedex(poke_id, poke_img_url):
    """【修正】IDと画像URLを保存"""
    if not poke_id: return
    try:
        chk = supabase.table("user_pokedex").select("id").eq("pokemon_id", poke_id).execute()
        if not chk.data:
            # 画像URLも一緒に保存
            supabase.table("user_pokedex").insert({
                "pokemon_id": poke_id, 
                "image_url": poke_img_url
            }).execute()
            return True 
    except: pass
    return False

def get_my_pokedex():
    """【修正】IDと画像URLを取得"""
    try:
        # image_url も取得する
        res = supabase.table("user_pokedex").select("pokemon_id, image_url").execute()
        return res.data # [{"pokemon_id": 25, "image_url": "http..."}, ...]
    except: return []

def save_mistake(en, jp):
    try:
        chk = supabase.table("mistaken_words").select("id").eq("word_en", en).execute()
        if not chk.data:
            supabase.table("mistaken_words").insert({"word_en": en, "word_jp": jp}).execute()
    except: pass

def increment_correct_count(en):
    try:
        res = supabase.table("mistaken_words").select("correct_count").eq("word_en", en).execute()
        if res.data:
            new_val = res.data[0]["correct_count"] + 1
            supabase.table("mistaken_words").update({"correct_count": new_val}).eq("word_en", en).execute()
