"""Shared transport/header infrastructure; no sentence-interpretation rules."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request
try:
    import truststore
except ImportError:
    truststore = None
if truststore is not None:
    truststore.inject_into_ssl()
ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT.parent

def load_env() -> dict[str, str]:
    """Read .env without printing or exporting its contents."""
    result = dict(os.environ)
    for path in (PACKAGE / ".env", ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result.setdefault(key, value)
    return result

def parse_header(text: str) -> dict[str, Any]:
    header = text.splitlines()[0]
    staff_match = re.search(r"\d+ staff on the rota:\s*(.*?)\. Blocks run", header)
    blocks_match = re.search(r"Blocks run\s*(.*?), one person per block", header)
    station_match = re.search(r"people on a station are\s*(.*?); the rest", header)
    labels_match = re.search(r"stations, one person on each:\s*(.*?)\.\s*The people on a station", header)
    if not (staff_match and blocks_match and station_match and labels_match):
        raise ValueError("Could not parse roster, blocks, or station holders from item header")
    staff = [x.strip() for x in staff_match.group(1).split(",")]
    blocks = re.findall(r"\d{2}:\d{2}", blocks_match.group(1))
    holders = [x.strip() for x in station_match.group(1).split(",")]
    stations = [x.strip() for x in labels_match.group(1).split(",")]
    if len(staff) != 5 or len(blocks) != 5 or len(holders) != 3 or len(stations) != 3:
        raise ValueError("Unexpected puzzle dimensions in item header")
    return {"staff": staff, "blocks": blocks, "stations": stations,
            "station_holders": holders}

def line_records(text: str) -> list[dict[str, Any]]:
    # Keep exact source text and physical line numbers. The header is line 1.
    return [{"line": i, "text": s} for i, s in enumerate(text.splitlines(), start=1)
            if i > 1 and s.strip()]

class GraniteClient:
    def __init__(self, env: dict[str, str], item_id: str):
        self.base_url = env.get("OPENROUTER_BASE_URL", "").rstrip("/")
        self.api_key = env.get("OPENROUTER_API_KEY", "")
        self.model = env.get("MODEL", "ibm-granite/granite-4.2-8b")
        if self.model != "ibm-granite/granite-4.2-8b":
            raise ValueError("This challenge permits only ibm-granite/granite-4.2-8b")
        self.item_id = item_id
        self.calls = 0
        self.raw_outputs = []
        self.call_metadata = []
        self.wire_mode = 'json_schema'
        if not self.base_url or not self.api_key:
            raise RuntimeError("Set OPENROUTER_BASE_URL and OPENROUTER_API_KEY in .env")

    def request_payload(self, prompt: str, response_format: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You extract literal constraints from shift notes. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 1.0,
            "top_p": 0.95,
            "max_tokens": 5000,
            "reasoning": {"enabled": False},
            "response_format": response_format,
            "provider": {"require_parameters": True},
        }
        if self.wire_mode in ('json_object_deepinfra','json_object_deepinfra_short'):
            payload['response_format'] = {'type':'json_object'}
            payload['provider'] = {'require_parameters':True,'only':['deepinfra'],'allow_fallbacks':False}
            if self.wire_mode=='json_object_deepinfra_short':
                from .format_hint import named_format_hint
                payload['messages'][-1]['content'] += named_format_hint(response_format)
            else:
                payload['messages'][-1]['content'] += '\nOutput ONLY JSON satisfying this schema (enforced by local validation):\n' + json.dumps(response_format['json_schema']['schema'],ensure_ascii=False,separators=(',',':'))
        elif self.wire_mode != 'json_schema':
            raise ValueError('Unknown Granite wire mode')
        return payload

    def call(self, prompt: str, response_format: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        request_body = self.request_payload(prompt,response_format)
        body = json.dumps(request_body).encode('utf-8')
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Item-Id": self.item_id,
        })
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Model endpoint returned HTTP {e.code}: {detail}") from e
        message = payload['choices'][0]['message']
        content = message.get("content", "")
        self.raw_outputs.append(content)
        self.call_metadata.append({"prompt_chars": len(request_body['messages'][-1]['content']), "output_chars": len(content) if isinstance(content, str) else 0, "finish_reason": payload["choices"][0].get("finish_reason"), "usage": payload.get("usage", {}), 'wire_mode':self.wire_mode,'provider':payload.get('provider'),'response_model':payload.get('model'),'response_id':payload.get('id')})
        if not isinstance(content, str):
            raise ValueError("Model response contained no text JSON")
        return parse_model_json(content)

def parse_model_json(content: str) -> dict[str, Any]:
    try:
        obj = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"Model response did not match the JSON contract: {error.msg} at character {error.pos}") from error
    if not isinstance(obj, dict) or not isinstance(obj.get("lines"), list):
        raise ValueError("Model response must be an object containing a lines array")
    return obj
