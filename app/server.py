from flask import Flask, request, render_template, redirect, url_for, session
import openai
import whisper
import tempfile
import os
import json
from flask import jsonify
from datetime import datetime
from werkzeug.utils import secure_filename
import random

CHALLENGE_TOPICS = [
    "人生最大の失敗談",
    "最近笑ったこと",
    "ちょっとした幸せ",
    "忘れられない出来事",
    "友達にしか話せない話",
    "なぜか恥ずかしかった瞬間",
    "今までで一番びっくりしたこと",
    "地味にショックだったこと",
    "絶妙なタイミングの話",
    "通勤・通学中に起きた小事件"
]

app = Flask(__name__, template_folder="templates")
app.secret_key = "your-secret-key"

# Whisper + GPT モデル
model_size = "medium"
whisper_model = whisper.load_model(model_size, device="cuda")
openai.api_key = os.environ.get('OPENAI_API_KEY', None)

@app.route("/")
def index():
    # カテゴリを読み込む
    if os.path.exists("categories.json"):
        with open("categories.json", "r", encoding="utf-8") as f:
            categories = json.load(f)
    else:
        categories = ["カフェ", "職場", "通学路・通勤路", "アウトドア"]

    return render_template("index.html", categories=categories)

@app.route("/record")
def record():
    return render_template("record.html")

@app.route("/transcribe", methods=["POST"])
@app.route("/transcribe", methods=["POST"])
def transcribe():
    if 'audio' not in request.files:
        return jsonify({"error": "音声ファイルが見つかりません"}), 400

    audio_file = request.files['audio']

    # 🔊 音声ファイルを static/audio に保存（タイムスタンプでユニークに）
    timestamp = int(datetime.now().timestamp())
    filename = f"recording_{timestamp}.webm"
    audio_save_path = os.path.join("static", "audio", secure_filename(filename))
    audio_file.save(audio_save_path)

    session['audio_path'] = audio_save_path  # セッションに保存（後で使う）

    # Whisper で文字起こし
    result = whisper_model.transcribe(audio_save_path, language='ja')
    transcribed_text = result["text"]
    session['raw_text'] = transcribed_text

    # GPTでエピソード生成
    prompt = f"""
あなたは、聞いた出来事をもとに、
人に話したくなるような「盛り上がるエピソードトーク」を作るプロです。

以下の出来事を元に、笑いや驚き、共感を引き出せるようなストーリーを、話し言葉で1つ作ってください。

・多少の脚色（登場人物の追加・誇張・展開のアレンジなど）は自由にしてOKです
・SNSや飲み会で話したくなるような面白さ、テンポのよさを意識してください
・「ですます調」ではなく、ラジオやトーク番組のような自然な語り口で
・出力はエピソード本文のみ。解説や前置きは不要です

出来事: 「{transcribed_text}」
"""
    gpt_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    episode = gpt_response.choices[0].message['content']
    session['episode'] = episode

    # トピック抽出
    topic_prompt = f"""
以下のエピソードの中から、話の中で重要な要素（場所・人・物・出来事）を3つ程度、簡潔な単語または短いフレーズで抽出してください。

【絶対に["要素1", "要素2", "要素3"]のようなJSON配列のみを出力してください】
例: ["カフェ", "友達", "注文ミス"]

エピソード:
「{episode}」
"""
    topic_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": topic_prompt}]
    )

    try:
        raw = topic_response.choices[0].message['content']
        print("GPTのトピック抽出結果:", raw)
        topics = json.loads(raw)
    except json.JSONDecodeError:
        print("⚠️ JSONとして解釈できませんでした。")
        topics = []

    session['topics'] = topics

    return jsonify({"redirect": url_for("review")})

@app.route("/category/<category_name>")
def show_category(category_name):
    filepath = "saved_data.json"
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = []
    else:
        data = []

    # 指定カテゴリでフィルタ + 新しい順にソート
    filtered = [ep for ep in data if ep["category"] == category_name]
    filtered = sorted(filtered, key=lambda x: x["date"], reverse=True)  # ←追加

    return render_template("category_list.html", category=category_name, episodes=filtered)

@app.route("/save", methods=["POST"])
def save():
    episode = session.get('episode', '')
    saved_date = datetime.now().strftime('%Y-%m-%d')
    ep_id = int(datetime.now().timestamp())
    audio_path = session.get("audio_path", None)

    # 既存カテゴリ or 新しいカテゴリ
    category = request.form.get("category")
    new_category = request.form.get("new_category")

    # 優先的に新しいカテゴリを使う
    final_category = new_category if new_category else category

    # カテゴリを追加（新しいものなら categories.json に登録）
    if final_category:
        cat_path = "categories.json"
        if os.path.exists(cat_path):
            with open(cat_path, "r", encoding="utf-8") as f:
                categories = json.load(f)
        else:
            categories = []

        if final_category not in categories:
            categories.append(final_category)
            with open(cat_path, "w", encoding="utf-8") as f:
                json.dump(categories, f, ensure_ascii=False)

    # エピソード保存
    entry = {
        "id": ep_id,
        "category": final_category,
        "episode": episode,
        "date": saved_date,
        "audio_path": audio_path
    }

    epi_path = "saved_data.json"
    if os.path.exists(epi_path):
        with open(epi_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    data.append(entry)

    with open(epi_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return redirect(url_for("episodes"))

@app.route("/episodes")
def episodes():
    filepath = "saved_data.json"
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = sorted(data, key=lambda x: x["date"], reverse=True)  # ←追加
    else:
        data = []

    return render_template("episodes.html", episodes=data)

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    filepath = "saved_data.json"

    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = []
    else:
        data = []

    # 🔍 検索ワードが含まれるエピソードだけ抽出（大文字小文字無視）
    filtered = [ep for ep in data if query.lower() in ep["episode"].lower()]
    filtered = sorted(filtered, key=lambda x: x["date"], reverse=True)  # ←追加
    return render_template("search_results.html", query=query, results=filtered)

@app.route("/delete/<int:ep_id>", methods=["POST"])
def delete_episode(ep_id):
    filepath = "saved_data.json"
    if not os.path.exists(filepath):
        return redirect(url_for("episodes"))

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        data = []

    # 指定ID以外のエピソードを残す
    updated = [ep for ep in data if ep.get("id") != ep_id]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    return redirect(url_for("episodes"))


@app.route("/edit/<int:ep_id>", methods=["GET"])
def edit_episode(ep_id):
    filepath = "saved_data.json"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # IDに一致するエピソードを探す
    episode = next((ep for ep in data if ep.get("id") == ep_id), None)

    if episode is None:
        return "エピソードが見つかりません", 404

    return render_template("edit_episode.html", episode=episode)

@app.route("/update/<int:ep_id>", methods=["POST"])
def update_episode(ep_id):
    category = request.form.get("category")
    episode_text = request.form.get("episode")

    filepath = "saved_data.json"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    for ep in data:
        if ep.get("id") == ep_id:
            ep["category"] = category
            ep["episode"] = episode_text
            break

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return redirect(url_for("episodes"))

@app.route("/retry", methods=["POST"])
def retry():
    # セッションのエピソード情報をリセット
    session.pop("raw_text", None)
    session.pop("episode", None)
    return redirect(url_for("record"))

@app.route("/regenerate", methods=["POST"])
def regenerate():
    raw_text = request.form.get("raw_text", "").strip()
    session['raw_text'] = raw_text

    # エピソード再生成
    prompt = f"""
あなたは、聞いた出来事をもとに、
人に話したくなるような「盛り上がるエピソードトーク」を作るプロです。

以下の出来事を元に、笑いや驚き、共感を引き出せるようなストーリーを、話し言葉で1つ作ってください。

・多少の脚色（登場人物の追加・誇張・展開のアレンジなど）は自由にしてOKです
・SNSや飲み会で話したくなるような面白さ、テンポのよさを意識してください
・「ですます調」ではなく、ラジオやトーク番組のような自然な語り口で
・出力はエピソード本文のみ。解説や前置きは不要です

出来事: 「{raw_text}」
"""
    gpt_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

    episode = gpt_response.choices[0].message['content']
    session['episode'] = episode

    # 🔁 トピック再抽出
    topic_prompt = f"""
以下のエピソードの中から、話の中で重要な要素（場所・人・物・出来事）を3つ程度、簡潔な単語または短いフレーズで抽出してください。

【絶対に["要素1", "要素2", "要素3"]のようなJSON配列のみを出力してください】
例: ["カフェ", "友達", "注文ミス"]

エピソード:
「{episode}」
"""

    topic_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": topic_prompt}]
    )

    try:
        raw = topic_response.choices[0].message['content']
        print("再生成後トピック抽出:", raw)
        topics = json.loads(raw)
    except json.JSONDecodeError:
        print("⚠️ JSONパース失敗（再生成）")
        topics = []

    session['topics'] = topics

    return redirect(url_for("review"))

@app.route("/manage_categories", methods=["GET", "POST"])
def manage_categories():
    filepath = "categories.json"

    # カテゴリ読み込み
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            categories = json.load(f)
    else:
        categories = ["カフェ", "職場", "通学路・通勤路", "アウトドア"]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(categories, f, ensure_ascii=False)

    # POST: カテゴリ追加
    if request.method == "POST":
        new_cat = request.form.get("new_category").strip()
        if new_cat and new_cat not in categories:
            categories.append(new_cat)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(categories, f, ensure_ascii=False)

    return render_template("manage_categories.html", categories=categories)

@app.route("/delete_category/<category_name>", methods=["POST"])
def delete_category(category_name):
    # カテゴリ一覧から削除
    cat_path = "categories.json"
    if os.path.exists(cat_path):
        with open(cat_path, "r", encoding="utf-8") as f:
            categories = json.load(f)
        categories = [c for c in categories if c != category_name]
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump(categories, f, ensure_ascii=False)

    # エピソードから該当カテゴリのものを削除
    epi_path = "saved_data.json"
    if os.path.exists(epi_path):
        with open(epi_path, "r", encoding="utf-8") as f:
            episodes = json.load(f)
        episodes = [ep for ep in episodes if ep.get("category") != category_name]
        with open(epi_path, "w", encoding="utf-8") as f:
            json.dump(episodes, f, ensure_ascii=False, indent=2)

    return redirect(url_for("manage_categories"))

def get_categories():
    if os.path.exists("categories.json"):
        with open("categories.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

@app.route("/review")
def review():
    episode = session.get('episode', '')
    raw_text = session.get('raw_text', '')
    topics = session.get('topics', [])
    if os.path.exists("categories.json"):
        with open("categories.json", "r", encoding="utf-8") as f:
            categories = json.load(f)
    else:
        categories = []
    return render_template("review.html", episode=episode, raw_text=raw_text, topics=topics, categories=categories)

@app.route("/topic_regenerate", methods=["POST"])
def topic_regenerate():
    edited_topics = request.form.getlist("topics")
    topic_summary = "、".join(edited_topics)

    # トピックに基づいたエピソード再生成
    prompt = f"""
以下のトピックを中心に、楽しく盛り上がるようなエピソードトークを話し言葉で作ってください。

トピック: {topic_summary}

・テンポよく面白く、他人に話したくなるように構成してください
・脚色はOKですが、現実にありそうな範囲で
・語り口は自然な一人語りスタイルでお願いします
・出力はエピソード本文のみ
"""
    gpt_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

    episode = gpt_response.choices[0].message['content']
    session['episode'] = episode

    # 🔁 再生成されたエピソードに対してトピック再抽出
    topic_prompt = f"""
    以下のエピソードの中から、話の中で重要な要素（場所・人・物・出来事）を3つ程度、簡潔な単語または短いフレーズで抽出してください。

    【絶対に["要素1", "要素2", "要素3"]のようなJSON配列のみを出力してください】
    例: ["カフェ", "友達", "注文ミス"]

    エピソード:
    「{episode}」
    """

    topic_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": topic_prompt}]
    )

    try:
        raw = topic_response.choices[0].message['content']
        print("再生成後トピック抽出:", raw)
        topics = json.loads(raw)
    except json.JSONDecodeError:
        print("⚠️ JSONパース失敗（トピック再生成）")
        topics = []

    session['topics'] = topics

    return redirect(url_for("review"))

@app.route("/challenge")
def challenge():
    theme = random.choice(CHALLENGE_TOPICS)
    session['challenge_theme'] = theme
    return render_template("challenge.html", theme=theme)

@app.route("/transcribe_challenge", methods=["POST"])
def transcribe_challenge():
    if 'audio' not in request.files:
        return jsonify({"error": "音声ファイルが見つかりません"}), 400

    audio_file = request.files['audio']
    timestamp = int(datetime.now().timestamp())
    filename = f"challenge_{timestamp}.webm"
    audio_path = os.path.join("static", "audio", secure_filename(filename))
    audio_file.save(audio_path)
    session['audio_path'] = audio_path

    # Whisperで文字起こし
    result = whisper_model.transcribe(audio_path, language='ja')
    transcribed_text = result["text"]
    session['raw_text'] = transcribed_text

    # 🔥 チャレンジテーマを使ってエピソード生成
    theme = session.get('challenge_theme', '自由なテーマ')

    prompt = f"""
    あなたは、聞いた出来事をもとに、
    人に話したくなるような「盛り上がるエピソードトーク」を作るプロです。

    以下のテーマ「{theme}」に沿った出来事が話されます。
    それを元に、話し言葉でテンポよく面白いエピソードトークを作成してください。

    出来事: 「{transcribed_text}」
    """

    gpt_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

    episode = gpt_response.choices[0].message['content']
    session['episode'] = episode

    # 🔁 再生成されたエピソードに対してトピック再抽出
    topic_prompt = f"""
    以下のエピソードの中から、話の中で重要な要素（場所・人・物・出来事）を3つ程度、簡潔な単語または短いフレーズで抽出してください。

    【絶対に["要素1", "要素2", "要素3"]のようなJSON配列のみを出力してください】
    例: ["カフェ", "友達", "注文ミス"]

    エピソード:
    「{episode}」
    """

    topic_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": topic_prompt}]
    )

    try:
        raw = topic_response.choices[0].message['content']
        print("再生成後トピック抽出:", raw)
        topics = json.loads(raw)
    except json.JSONDecodeError:
        print("⚠️ JSONパース失敗（トピック再生成）")
        topics = []

    session['topics'] = topics

    return jsonify({"redirect": url_for("review")})

@app.route("/record_challenge")
def record_challenge():
    return render_template("record_challenge.html", theme=session.get("challenge_theme", "未設定"))

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
