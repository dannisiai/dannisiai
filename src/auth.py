import copy
import time
import threading
import urllib.parse

from eth_account import Account
from eth_account.messages import encode_typed_data


EIP712_TYPED_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "Message": [{"name": "msg", "type": "string"}],
    },
    "primaryType": "Message",
    "domain": {
        "name": "AsterSignTransaction",
        "version": "1",
        "chainId": 1666,
        "verifyingContract": "0x0000000000000000000000000000000000000000",
    },
    "message": {"msg": ""},
}


class NonceGenerator:
    """Thread-safe microsecond nonce generator with server time offset correction."""

    def __init__(self):
        self._last_sec = 0
        self._counter = 0
        self._lock = threading.Lock()
        self._offset_sec: int = 0

    def set_server_offset(self, server_time_ms: int):
        """Calibrate local clock against server time."""
        local_ms = int(time.time() * 1000)
        self._offset_sec = (server_time_ms - local_ms) // 1000

    def __call__(self) -> int:
        with self._lock:
            now_sec = int(time.time()) + self._offset_sec
            if now_sec == self._last_sec:
                self._counter += 1
            else:
                self._last_sec = now_sec
                self._counter = 0
            return now_sec * 1_000_000 + self._counter


get_nonce = NonceGenerator()


class AsterAuth:
    """Handles EIP-712 request signing for Aster v3 API."""

    def __init__(self, user: str, signer: str, private_key: str, chain_id: int = 1666):
        self.user = user
        self.signer = signer
        self._private_key = private_key
        self._typed_data = _build_typed_data(chain_id)
        self._sign_lock = threading.Lock()

    def sign_params(self, params: dict) -> dict:
        """Add auth fields + signature to a parameter dict. Returns a new dict."""
        with self._sign_lock:
            signed = dict(params)
            signed["nonce"] = str(get_nonce())
            signed["user"] = self.user
            signed["signer"] = self.signer

            msg = urllib.parse.urlencode(signed)
            td = copy.deepcopy(self._typed_data)
            td["message"]["msg"] = msg
            encoded = encode_typed_data(full_message=td)
            sig = Account.sign_message(encoded, private_key=self._private_key)
            signed["signature"] = sig.signature.hex()
            return signed

    def build_signed_url(self, base_url: str, params: dict) -> str:
        signed = self.sign_params(params)
        qs = urllib.parse.urlencode(signed)
        return f"{base_url}?{qs}"


def _build_typed_data(chain_id: int) -> dict:
    data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Message": [{"name": "msg", "type": "string"}],
        },
        "primaryType": "Message",
        "domain": {
            "name": "AsterSignTransaction",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        "message": {"msg": ""},
    }
    return data
