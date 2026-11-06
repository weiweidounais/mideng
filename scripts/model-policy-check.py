"""Read only this product's approved policy; all other products keep mandatory model checks."""
import sys
from pathlib import Path


def mode(product, folder):
    if product != '密灯':
        return 'required'
    folder = Path(folder)
    policy = folder / 'verification-policy.json'
    if not policy.exists():
        return 'required'
    sys.path.insert(0, str(folder / 'backend'))
    from app.pilot_policy import read_policy
    value = read_policy(policy)
    return 'required' if value['model_enabled'] else 'disabled'


if __name__ == '__main__':
    try:
        print(mode(sys.argv[1], sys.argv[2]))
    except Exception:
        print('invalid')
        sys.exit(1)
