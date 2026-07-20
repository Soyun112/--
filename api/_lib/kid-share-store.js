const TTL_MS = 7 * 24 * 60 * 60 * 1000;

function getStore() {
  if (!global.__KID_GUIDE_SHARES__) {
    global.__KID_GUIDE_SHARES__ = new Map();
  }
  return global.__KID_GUIDE_SHARES__;
}

function createShare(payload) {
  const crypto = require("crypto");
  const id = crypto.randomBytes(6).toString("base64url");
  const expiresAt = new Date(Date.now() + TTL_MS).toISOString();
  getStore().set(id, { payload, exp: Date.now() + TTL_MS });
  return { id, expires_at: expiresAt };
}

function getShare(id) {
  if (!id) return null;
  const row = getStore().get(String(id).trim());
  if (!row) return null;
  if (Date.now() > row.exp) {
    getStore().delete(id);
    return null;
  }
  return row.payload;
}

module.exports = { createShare, getShare, TTL_MS };
