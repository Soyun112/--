// Tmap JS SDK 웹 키 (브라우저에 노출되는 클라이언트 키).
// Vercel 정적 호스팅에서도 지도가 뜨도록 포함. SK 콘솔에 kids-abcd.vercel.app 도메인 등록 권장.
window.__TMAP_APP_KEY__ = window.__TMAP_APP_KEY__ || "OnGZD9wF6s7QBFpMWyauz7h0h2cPhe0M4sE2rZUG";
const tmapAlreadyInjected = document.querySelector('script[data-tmap-sdk="1"]');
if (
  window.__TMAP_APP_KEY__ &&
  !tmapAlreadyInjected &&
  !(window.Tmapv2 && typeof window.Tmapv2.Map === "function")
) {
  document.write(
    "<script data-tmap-sdk='1' src='https://apis.openapi.sk.com/tmap/jsv2?version=1&appKey=" +
      encodeURIComponent(window.__TMAP_APP_KEY__) +
      "'><\/script>"
  );
}
