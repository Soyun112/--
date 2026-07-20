const { getShare } = require("../../_lib/kid-share-store");

module.exports = async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  if (req.method !== "GET") {
    res.status(405).json({ detail: "Method Not Allowed" });
    return;
  }

  const id = req.query?.id;
  const payload = getShare(id);
  if (!payload) {
    res.status(404).json({ detail: "공유 링크를 찾을 수 없거나 만료되었습니다." });
    return;
  }

  res.status(200).json(payload);
};
