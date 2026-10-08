import streamlit as st
import streamlit.components.v1 as components
import random
import time
import json
import requests
import sqlite3
import google.generativeai as genai

# ==========================================
# 0. アプリ基本設定
# ==========================================
st.set_page_config(page_title="Pokémon English Battle", layout="wide")

# ==========================================
# 1. 設定 & 定数 & DB初期化
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

# SQLite3 データベース設定
DB_FILE = "pokemon_english.db"

def init_db():
    """必要なテーブルが存在しない場合は作成する"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # フォールバック用の単語帳テーブル
        c.execute('''
            CREATE TABLE IF NOT EXISTS toeic_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_en TEXT,
                word_jp TEXT,
                rank_level TEXT
            )
        ''')
        # 図鑑テーブル
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_pokedex (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pokemon_id INTEGER UNIQUE,
                image_url TEXT
            )
        ''')
        # 間違えた単語テーブル
        c.execute('''
            CREATE TABLE IF NOT EXISTS mistaken_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_en TEXT UNIQUE,
                word_jp TEXT,
                correct_count INTEGER DEFAULT 0
            )
        ''')
        conn.commit()

# アプリ起動時にDBを初期化
init_db()

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
    """AIがない場合、SQLiteから単語を取得する"""
    target_level = RANK_TAGS.get(rank_name, "beginner")
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            c.execute("SELECT word_en, word_jp FROM toeic_words WHERE rank_level = ?", (target_level,))
            data = c.fetchall()
            
            # データ不足時は全データから補充
            if len(data) < 8:
                c.execute("SELECT word_en, word_jp FROM toeic_words")
                data = c.fetchall()
                
            if data and len(data) >= 8:
                selected = random.sample(data, 8)
                return [{"en": item["word_en"], "jp": item["word_jp"]} for item in selected]
            
    except Exception:
        pass
    
    # 最終手段（DBにもデータがない場合）
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
        
        # モデル指定
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

# --- DB操作 (SQLite3版) ---

def save_pokedex(poke_id, poke_img_url):
    """IDと画像URLを保存"""
    if not poke_id: return False
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM user_pokedex WHERE pokemon_id = ?", (poke_id,))
            if not c.fetchone():
                c.execute("INSERT INTO user_pokedex (pokemon_id, image_url) VALUES (?, ?)", (poke_id, poke_img_url))
                conn.commit()
                return True 
    except: pass
    return False

def get_my_pokedex():
    """IDと画像URLを取得"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT pokemon_id, image_url FROM user_pokedex")
            return [{"pokemon_id": row["pokemon_id"], "image_url": row["image_url"]} for row in c.fetchall()]
    except: return []

def save_mistake(en, jp):
    """間違えた単語を保存"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM mistaken_words WHERE word_en = ?", (en,))
            if not c.fetchone():
                c.execute("INSERT INTO mistaken_words (word_en, word_jp) VALUES (?, ?)", (en, jp))
                conn.commit()
    except: pass

def increment_correct_count(en):
    """正解回数をカウントアップ"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT correct_count FROM mistaken_words WHERE word_en = ?", (en,))
            row = c.fetchone()
            if row:
                new_val = row[0] + 1
                c.execute("UPDATE mistaken_words SET correct_count = ? WHERE word_en = ?", (new_val, en))
                conn.commit()
                return new_val
    except: pass
    return 0

def delete_mistake(en):
    """単語を削除"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM mistaken_words WHERE word_en = ?", (en,))
            conn.commit()
    except: pass

def get_mistakes_count():
    """間違えた単語の数を取得"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(id) FROM mistaken_words")
            return c.fetchone()[0]
    except: return 0

def fetch_revenge_words(limit=8):
    """復習用の単語を取得"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT word_en, word_jp, correct_count FROM mistaken_words")
            data = c.fetchall()
            
            if not data: return []
            
            word_list = [{"en": row["word_en"], "jp": row["word_jp"], "count": row["correct_count"]} for row in data]
            random.shuffle(word_list)
            return word_list[:limit]
    except: return []

# ==========================================
# 3. ゲームロジック
# ==========================================
def init_game(word_list, time_limit, mode="NORMAL", poke_id=None, poke_img=None):
    cards = []
    for item in word_list:
        cnt = item.get("count", 0)
        cards.append({"id": item["en"], "text": item["en"], "pair": item["jp"], "is_jp": False, "count": cnt})
        cards.append({"id": item["en"], "text": item["jp"], "pair": item["en"], "is_jp": True, "count": cnt})
    
    random.shuffle(cards)
    
    st.session_state.cards = cards
    st.session_state.flipped = []
    st.session_state.matched = set()
    st.session_state.collected_now = [] 
    st.session_state.mistakes_now = []
    st.session_state.mastered_pending = []
    st.session_state.current_mode = mode
    
    st.session_state.current_poke_id = poke_id
    st.session_state.current_poke_img = poke_img
    
    st.session_state.start_time = time.time()
    st.session_state.time_limit = time_limit
    st.session_state.game_state = "PLAYING"
    st.session_state.last_matched_word = None
    
    st.session_state.is_cleared = False
    st.session_state.is_new_discovery = False

# ==========================================
# 4. アプリ本体
# ==========================================
def main():
    # サイドバー
    st.sidebar.title("⚙️ メニュー")
    api_key = st.sidebar.text_input("Gemini API Key", type="password")
    
    rank_keys = list(RANK_MAP.keys())
    rank_options = rank_keys + ["🔥 復習モード (Revenge)"]
    selected_rank_name = st.sidebar.selectbox("挑戦するランク", rank_options)
    
    st.sidebar.divider()
    m_count = get_mistakes_count()
    st.sidebar.error(f"💀 苦手な単語: {m_count} 語")
    
    # 図鑑 (画像URL対応版)
    st.sidebar.divider()
    with st.sidebar.expander("📖 ポケモン図鑑 (Pokedex)"):
        my_pokedex = get_my_pokedex()
        if my_pokedex:
            st.write(f"現在の発見数: **{len(my_pokedex)}**
