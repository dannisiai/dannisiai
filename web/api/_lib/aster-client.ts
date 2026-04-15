import { ethers } from "ethers";

const ASTER_API_BASE =
  process.env.ASTER_API_BASE || "https://fapi.asterdex.com";
const CHAIN_ID = Number(process.env.ASTER_CHAIN_ID || "1666");

const EIP712_DOMAIN = {
  name: "AsterSignTransaction",
  version: "1",
  chainId: CHAIN_ID,
  verifyingContract: "0x0000000000000000000000000000000000000000",
};

const EIP712_TYPES = {
  Message: [{ name: "msg", type: "string" }],
};

let nonceCounter = 0;
let lastSec = 0;

function getNonce(): string {
  const nowSec = Math.floor(Date.now() / 1000);
  if (nowSec === lastSec) {
    nonceCounter++;
  } else {
    lastSec = nowSec;
    nonceCounter = 0;
  }
  return String(nowSec * 1_000_000 + nonceCounter);
}

async function signParams(params: Record<string, string>): Promise<Record<string, string>> {
  const user = process.env.ASTER_READONLY_USER;
  const signer = process.env.ASTER_READONLY_SIGNER;
  const privateKey = process.env.ASTER_READONLY_PRIVATE_KEY;

  if (!user || !signer || !privateKey) {
    throw new Error("Missing ASTER_READONLY_USER, ASTER_READONLY_SIGNER, or ASTER_READONLY_PRIVATE_KEY");
  }

  const signed: Record<string, string> = { ...params };
  signed.nonce = getNonce();
  signed.user = user;
  signed.signer = signer;

  const qs = new URLSearchParams(signed).toString();

  const wallet = new ethers.Wallet(privateKey);
  const signature = await wallet.signTypedData(EIP712_DOMAIN, EIP712_TYPES, {
    msg: qs,
  });

  signed.signature = signature;
  return signed;
}

export async function asterGet(
  path: string,
  params: Record<string, string> = {}
): Promise<unknown> {
  const signed = await signParams(params);
  const qs = new URLSearchParams(signed).toString();
  const url = `${ASTER_API_BASE}${path}?${qs}`;

  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Aster API ${res.status}: ${text}`);
  }
  return res.json();
}
