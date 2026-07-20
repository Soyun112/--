const { createShare } = require("../_lib/kid-share-store");

module.exports = async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  if (req.method !== "POST") {
    res.status(405).json({ detail: "Method Not Allowed" });
    return;
  }

  try {
    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
    if (!body?.steps?.length) {
      res.status(422).json({ detail: "steps가 필요합니다." });
      return;
    }
    res.status(200).json(createShare(body));
  } catch (err) {
    res.status(400).json({ detail: err.message || "잘못된 요청입니다." });
  }
};
