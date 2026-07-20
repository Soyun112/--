// 로컬 전용 (Git에 올리지 마세요). 이 파일을 tmap-key.js 로 복사하거나
// Vercel/Render 환경 변수 TMAP_APP_KEY 를 사용하세요.
// 배포: Vercel 빌드 시 scripts/build-vercel.js 가 tmap-key.js 를 생성합니다.
//        Render /api/tmap-bootstrap.js 가 키를 주입합니다.
window.__TMAP_APP_KEY__ = window.__TMAP_APP_KEY__ || "";
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
