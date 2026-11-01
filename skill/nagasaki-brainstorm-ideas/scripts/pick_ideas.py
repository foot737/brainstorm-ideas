#!/usr/bin/env python3
"""ブレストアイデア・オープンデータセットから、発想のヒントになるアイデアを取り出す。

使い方:
  python scripts/pick_ideas.py "商店街を盛り上げたい"
  python scripts/pick_ideas.py "商店街を盛り上げたい" --related 8 --random 6 --pairs 3 --seed 42
  python scripts/pick_ideas.py --list-themes
  python scripts/pick_ideas.py "テーマ" --data ./brainstorm_ideas.json   # データの場所を指定

データの読み込み先（--data を省略した場合）:
  1. スキルに同梱された data/brainstorm_ideas.json
  2. リポジトリ直下の data/brainstorm_ideas.json
  3. GitHubで公開しているURL（DEFAULT_URL）

出力（JSON）:
  related : テーマに言葉が近いアイデア（乗っかり用。同じテーマに偏らないよう分散）
  random  : テーマとは無関係なアイデア（偶然の出会い用）
  pairs   : 掛け合わせ用に、別々のテーマから2件ずつ組にしたもの
標準ライブラリのみで動作します。
"""
import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_URL = "https://raw.githubusercontent.com/foot737/brainstorm-ideas/main/data/brainstorm_ideas.json"
ATTRIBUTION = "ながさきキャンバス ブレストアイデア・オープンデータセット（CC0）https://github.com/foot737/brainstorm-ideas"


def default_source():
    here = Path(__file__).resolve()
    cands = []
    if len(here.parents) > 1:
        cands.append(here.parents[1] / "data" / "brainstorm_ideas.json")   # スキル同梱
    if len(here.parents) > 3:
        cands.append(here.parents[3] / "data" / "brainstorm_ideas.json")   # リポジトリ直下
    for c in cands:
        if c.is_file():
            return str(c)
    return DEFAULT_URL


def load(src):
    if src.startswith("http://") or src.startswith("https://"):
        import urllib.request
        try:
            with urllib.request.urlopen(src, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            json.dump({"error": f"データを取得できませんでした: {e}", "url": src,
                       "hint": "ネットワークに接続できない環境の可能性があります。SKILL.md の「スクリプトを実行できない場合」の手順に切り替えてください。"},
                      sys.stdout, ensure_ascii=False, indent=2)
            print()
            sys.exit(1)
    return json.loads(Path(src).read_text(encoding="utf-8"))

# テーマ文言にほぼ必ず含まれるため、類似度の計算から外す語
STOP = ["アイデア", "盛り上げ", "もっと", "どうしたら"]
# ひらがな（助詞・送り仮名）と記号で区切り、漢字・カタカナ・英数字のかたまりだけを使う
SPLIT = re.compile(r"[\u3040-\u309f\s、。・：:！!？?「」『』（）()〜~／/\"“”'→\-—＝=＆&×,.]+")


def grams(text):
    text = text.lower()
    for w in STOP:
        text = text.replace(w, " ")
    out = Counter()
    for chunk in SPLIT.split(text):
        if not chunk:
            continue
        if len(chunk) == 1:
            out[chunk] += 1          # 「坂」「街」など1文字の漢字
        for i in range(len(chunk) - 1):
            out[chunk[i:i + 2]] += 1
    return out


def make_scorer(ideas):
    """よく出てくる語ほど重みを下げる（IDF）。"""
    n = len(ideas)
    df = Counter()
    for i in ideas:
        df.update(set(grams(i["idea"] + " " + i["theme"])))
    idf = lambda g: math.log((n + 1) / (df.get(g, 0) + 1)) + 0.1

    def score(q, i):
        ig, tg = grams(i["idea"]), grams(i["theme"])
        s = sum(idf(g) for g in q if g in ig)
        s += 0.3 * sum(idf(g) for g in q if g in tg and g not in ig)
        return s
    return score


def pick_spread(cands, n, per_theme):
    """同じテーマに偏らないように上位から選ぶ。"""
    out, used = [], Counter()
    for c in cands:
        if used[c["theme"]] >= per_theme:
            continue
        out.append(c)
        used[c["theme"]] += 1
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="", help="ブレストしたいテーマ")
    ap.add_argument("--related", type=int, default=8)
    ap.add_argument("--random", type=int, default=6)
    ap.add_argument("--pairs", type=int, default=3)
    ap.add_argument("--per-theme", type=int, default=3, help="related で同じテーマから選ぶ上限")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--data", default=None, help="データのファイルパスまたはURL")
    ap.add_argument("--list-themes", action="store_true")
    a = ap.parse_args()

    ideas = load(a.data or default_source())
    if a.list_themes:
        c = Counter((i["theme"], i["theme_category"]) for i in ideas)
        print(json.dumps([{"theme": t, "theme_category": k, "count": n} for (t, k), n in c.items()],
                         ensure_ascii=False, indent=2))
        return

    rng = random.Random(a.seed)
    q = grams(a.query)
    scored = []
    score = make_scorer(ideas)
    for i in ideas:
        s = score(q, i) if q else 0
        scored.append((s, rng.random(), i))
    scored.sort(key=lambda x: (-x[0], x[1]))

    hits = [i for s, _, i in scored if s > 0]
    related = pick_spread(hits, a.related, a.per_theme)
    used = {id(i) for i in related}

    # 偶然の出会い：テーマと言葉が重ならないアイデアから、なるべく別々のテーマで選ぶ
    far = [i for s, _, i in scored if s == 0 and id(i) not in used]
    if len(far) < a.random:
        far = [i for _, _, i in scored if id(i) not in used]
    rng.shuffle(far)
    rand = pick_spread(far, a.random, 1) or far[:a.random]
    used |= {id(i) for i in rand}

    # 掛け合わせ：別々のテーマから1件ずつ
    by_theme = defaultdict(list)
    for i in ideas:
        if id(i) not in used:
            by_theme[i["theme"]].append(i)
    themes = list(by_theme)
    pairs = []
    for _ in range(a.pairs):
        if len(themes) < 2:
            break
        t1, t2 = rng.sample(themes, 2)
        pairs.append([rng.choice(by_theme[t1]), rng.choice(by_theme[t2])])

    def slim(i):
        return {"idea": i["idea"], "theme": i["theme"], "theme_category": i["theme_category"]}

    out = {
        "query": a.query,
        "related": [slim(i) for i in related],
        "random": [slim(i) for i in rand],
        "pairs": [[slim(x), slim(y)] for x, y in pairs],
        "note": "related が少ない・空の場合は、テーマに近い既存アイデアがないという意味です。random と pairs を中心に発想してください。",
        "attribution": ATTRIBUTION,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
