"""One policy consumed by the server and the shared verification adapter."""
import json
from pathlib import Path

POLICY = Path(__file__).resolve().parents[2] / 'verification-policy.json'

def read_policy(path=POLICY):
    data = json.loads(Path(path).read_text())
    if data.get('schema_version') != 1 or data.get('product') != '密灯' or type(data.get('model_enabled')) is not bool:
        raise ValueError('产品验证策略无效')
    if data.get('decision') != 'Q3=A' or data.get('application') != 'app.pilot:app':
        raise ValueError('产品验证策略缺少已批准依据或入口')
    return data
