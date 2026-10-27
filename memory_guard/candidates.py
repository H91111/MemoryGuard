"""Character TF-IDF and real, optional BGE CLS embedding (no silent fallback)."""
from __future__ import annotations

import math
import os
from collections import Counter
from pathlib import Path
import json

MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"


def grams(text):
    text = "".join(text.lower().split())
    return Counter(text[i:i+n] for n in (1, 2, 3) for i in range(max(0, len(text)-n+1)))


def tfidf_scores(query, texts):
    if not texts:
        return []
    counts = [grams(t) for t in texts]
    df = Counter(t for c in counts for t in c)
    idf = {t: math.log((1+len(texts))/(1+f))+1 for t, f in df.items()}

    def vector(c):
        v = {t: (1+math.log(n))*idf[t] for t, n in c.items() if t in idf}
        norm = math.sqrt(sum(x*x for x in v.values())) or 1
        return {t: x/norm for t, x in v.items()}
    q = vector(grams(query))
    return [sum(q.get(t, 0)*x for t, x in vector(c).items()) for c in counts]


class BGEEncoder:
    def __init__(self, model_path=None):
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("语义依赖未安装，请先安装 .[semantic]；不会以字符检索冒充向量模型") from exc
        self.torch = torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        path = model_path or os.environ.get("MEMORY_GUARD_BGE_PATH")
        local = Path.cwd() / "models/bge-small-zh-v1.5"
        if not local.exists():
            local = Path(__file__).resolve().parent.parent / "models/bge-small-zh-v1.5"
        if not path and (local / "manifest.json").exists():
            manifest = json.loads((local / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("revision") != MODEL_REVISION:
                raise RuntimeError("本地 BGE manifest revision 与冻结配置不匹配")
            path = str(local)
        kwargs = {"local_files_only": True} if path else {"revision": MODEL_REVISION}
        self.tokenizer = AutoTokenizer.from_pretrained(path or MODEL_ID, **kwargs)
        self.model = AutoModel.from_pretrained(path or MODEL_ID, **kwargs).eval()
        self.cache = {}
        self.forward_batches = 0

    def encode(self, texts):
        import numpy as np
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        for start in range(0, len(missing), 32):
            batch = missing[start:start+32]
            encoded = self.tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            with self.torch.inference_mode():
                output = self.model(**encoded).last_hidden_state[:, 0]
                output = self.torch.nn.functional.normalize(output, p=2, dim=1).cpu().numpy()
            self.forward_batches += 1
            self.cache.update(zip(batch, output))
        return np.array([self.cache[t] for t in texts])

    def scores(self, query, texts):
        if not texts:
            return []
        q = self.encode(["为这个句子生成表示以用于检索相关文章：" + query])[0]
        return (self.encode(texts) @ q).tolist()


def rank(query, facts, mode="character", encoder=None):
    texts = [f"{f['project']} {f['version_scope']} {f['subject']} {f['attribute']} {f['value']} {f.get('text', '')}" for f in facts]
    char = tfidf_scores(query, texts)
    if mode in {"semantic", "hybrid"}:
        if encoder is None:
            raise RuntimeError("此检索模式需要真实 BGEEncoder")
        semantic = encoder.scores(query, texts)
    else:
        semantic = [0.0] * len(texts)
    for fact, a, b in zip(facts, char, semantic):
        fact["scores"] = {"character": round(a, 6), "semantic": round(b, 6)}
        fact["score"] = b if mode == "semantic" else (a+b)/2 if mode == "hybrid" else a
    return sorted(facts, key=lambda f: (-f["score"], f["fact_id"]))
